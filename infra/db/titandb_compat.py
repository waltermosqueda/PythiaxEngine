from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection, CursorResult, Engine
from sqlalchemy.engine.url import make_url

from infra.db.base import Base
from infra.db.runtime import adapt_qmark_sql
from infra.db.session import create_db_engine

import infra.db.models  # noqa: F401


UPSERT_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "prices": {
        "conflict_columns": ("ticker", "date"),
        "update_columns": ("open", "high", "low", "close", "volume", "adj_close"),
    },
    "predictions": {
        "conflict_columns": ("model_name", "ticker", "prediction_date", "target_date"),
        "update_columns": ("model_version", "direction", "confidence", "score", "regime", "sector"),
    },
    "outcomes": {
        "conflict_columns": ("prediction_id",),
        "update_columns": ("actual_direction", "actual_return", "hit"),
    },
    "regimes": {
        "conflict_columns": ("date",),
        "update_columns": (
            "trend_regime",
            "vol_regime",
            "credit_regime",
            "composite",
            "vix_level",
            "spy_return_20d",
            "details",
        ),
    },
    "data_status": {
        "conflict_columns": ("key",),
        "update_columns": ("value", "updated_at"),
    },
    "model_metrics": {
        "conflict_columns": ("model_name", "period_start", "period_end"),
        "update_columns": (
            "total_predictions",
            "correct_predictions",
            "accuracy",
            "avg_confidence",
            "avg_return_when_right",
            "avg_return_when_wrong",
            "profit_factor",
            "sharpe_ratio",
            "max_drawdown",
        ),
    },
    "model_run_snapshots": {
        "conflict_columns": ("model_key", "analyzed_date"),
        "update_columns": (
            "model_name",
            "model_version",
            "role",
            "prediction_for",
            "freshness",
            "regime_label",
            "breadth_pct",
            "signal_count",
            "snapshot_json",
        ),
    },
}

INSERT_OR_REPLACE_RE = re.compile(
    r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+(?P<table>[A-Za-z_][A-Za-z0-9_]*)\s*"
    r"\((?P<columns>.*?)\)\s*VALUES\s*\((?P<values>.*?)\)\s*$",
    re.IGNORECASE | re.DOTALL,
)


def rewrite_insert_or_replace(sql: str) -> str:
    normalized = sql.strip().rstrip(";")
    match = INSERT_OR_REPLACE_RE.match(normalized)
    if not match:
        return sql

    table = match.group("table").lower()
    rule = UPSERT_RULES.get(table)
    if rule is None:
        raise ValueError(f"No hay regla de UPSERT definida para la tabla {table!r}.")

    columns = tuple(part.strip() for part in match.group("columns").split(",") if part.strip())
    values = match.group("values").strip()
    conflict_columns = rule["conflict_columns"]

    missing = [column for column in conflict_columns if column not in columns]
    if missing:
        raise ValueError(
            f"La query de {table!r} no incluye las columnas de conflicto requeridas: {missing!r}."
        )

    update_columns = tuple(
        column
        for column in rule["update_columns"]
        if column in columns and column not in conflict_columns
    )

    if update_columns:
        update_clause = ", ".join(f"{column} = EXCLUDED.{column}" for column in update_columns)
        conflict_action = f"DO UPDATE SET {update_clause}"
    else:
        conflict_action = "DO NOTHING"

    columns_sql = ", ".join(columns)
    conflict_sql = ", ".join(conflict_columns)
    return (
        f"INSERT INTO {table} ({columns_sql}) VALUES ({values}) "
        f"ON CONFLICT ({conflict_sql}) {conflict_action}"
    )


class TitanCompatCursor:
    def __init__(self, connection: "TitanCompatConnection"):
        self._connection = connection
        self._result: CursorResult[Any] | None = None
        self._rows: list[tuple[Any, ...]] | None = None
        self._offset = 0
        self.description: list[tuple[Any, ...]] | None = None
        self.rowcount = -1
        self.lastrowid: int | None = None

    def _bind_result(self, result: CursorResult[Any] | None) -> "TitanCompatCursor":
        self._result = result
        self._rows = None
        self._offset = 0
        if result is None:
            self.description = None
            self.rowcount = 0
            self.lastrowid = None
            return self

        keys = list(result.keys()) if result.returns_rows else []
        self.description = [(key, None, None, None, None, None, None) for key in keys] if keys else None
        self.rowcount = int(result.rowcount or 0) if result.rowcount is not None else -1
        self.lastrowid = getattr(result, "lastrowid", None) if not result.returns_rows else None
        self._rows = [tuple(row) for row in result.all()] if result.returns_rows else []
        return self

    def execute(self, sql: str, params: Any = ()) -> "TitanCompatCursor":
        return self._bind_result(self._connection._execute(sql, params))

    def executemany(self, sql: str, seq_of_params: Iterable[Any]) -> "TitanCompatCursor":
        return self._bind_result(self._connection._executemany(sql, seq_of_params))

    def _materialize_rows(self) -> list[tuple[Any, ...]]:
        if self._rows is None:
            self._rows = []
        return self._rows

    def fetchone(self) -> tuple[Any, ...] | None:
        rows = self._materialize_rows()
        if self._offset >= len(rows):
            return None
        row = rows[self._offset]
        self._offset += 1
        return row

    def fetchmany(self, size: int | None = None) -> list[tuple[Any, ...]]:
        rows = self._materialize_rows()
        if size is None or size <= 0:
            size = len(rows) - self._offset
        chunk = rows[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows = self._materialize_rows()
        if self._offset == 0:
            self._offset = len(rows)
            return list(rows)
        chunk = rows[self._offset :]
        self._offset = len(rows)
        return chunk

    def close(self) -> None:
        if self._result is not None:
            self._result.close()
        self._result = None
        self._rows = []
        self._offset = 0

    def __iter__(self):
        return iter(self.fetchall())


class TitanCompatConnection:
    def __init__(self, connection: Connection):
        self._connection = connection

    def _normalize_sql(self, sql: str) -> str:
        return rewrite_insert_or_replace(sql)

    def _execute(self, sql: str, params: Any = ()) -> CursorResult[Any]:
        normalized_sql = self._normalize_sql(sql)
        adapted_sql, adapted_params = adapt_qmark_sql(normalized_sql, params)
        return self._connection.execute(text(adapted_sql), adapted_params)

    def _executemany(self, sql: str, seq_of_params: Iterable[Any]) -> CursorResult[Any] | None:
        rows = list(seq_of_params)
        if not rows:
            return None

        normalized_sql = self._normalize_sql(sql)
        adapted_sql, _ = adapt_qmark_sql(normalized_sql, rows[0])
        payload = [adapt_qmark_sql(normalized_sql, params)[1] for params in rows]
        return self._connection.execute(text(adapted_sql), payload)

    def cursor(self) -> TitanCompatCursor:
        return TitanCompatCursor(self)

    def execute(self, sql: str, params: Any = ()) -> TitanCompatCursor:
        return self.cursor().execute(sql, params)

    def executemany(self, sql: str, seq_of_params: Sequence[Any]) -> TitanCompatCursor:
        return self.cursor().executemany(sql, seq_of_params)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def create_titandb_compat_connection(database_url: str) -> tuple[Engine, TitanCompatConnection]:
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite" and url.database:
        Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)

    engine = create_db_engine(database_url=database_url)
    Base.metadata.create_all(engine)
    return engine, TitanCompatConnection(engine.connect())
