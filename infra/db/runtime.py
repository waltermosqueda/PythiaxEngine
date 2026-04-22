from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection, CursorResult, Engine

from infra.db.config import get_database_url
from infra.db.session import create_db_engine


def _normalize_params(params: Any) -> tuple[Any, ...] | Mapping[str, Any]:
    if params is None:
        return ()
    if isinstance(params, dict):
        return params
    if isinstance(params, tuple):
        return params
    if isinstance(params, list):
        return tuple(params)
    return (params,)


def adapt_qmark_sql(sql: str, params: Any = ()) -> tuple[str, Mapping[str, Any]]:
    normalized = _normalize_params(params)
    if isinstance(normalized, Mapping):
        return sql, dict(normalized)

    if not normalized:
        return sql, {}

    placeholders = sql.count("?")
    if placeholders != len(normalized):
        raise ValueError(
            f"La query espera {placeholders} placeholders y recibio {len(normalized)} parametros."
        )

    parts = sql.split("?")
    rebuilt: list[str] = []
    bound: dict[str, Any] = {}
    for index, part in enumerate(parts[:-1]):
        key = f"p{index}"
        rebuilt.append(part)
        rebuilt.append(f":{key}")
        bound[key] = normalized[index]
    rebuilt.append(parts[-1])
    return "".join(rebuilt), bound


@dataclass(frozen=True)
class RuntimeBackend:
    name: str
    database_url: str

    @property
    def is_sqlite(self) -> bool:
        return self.name == "sqlite"

    @property
    def is_postgres(self) -> bool:
        return self.name.startswith("postgres")


def resolve_runtime_backend(engine: Engine | None = None) -> RuntimeBackend:
    if engine is None:
        engine = create_db_engine()
    return RuntimeBackend(
        name=engine.dialect.name,
        database_url=str(engine.url),
    )


def aggregate_distinct_sql(column_expression: str, alias: str, backend_name: str) -> str:
    if backend_name.startswith("postgres"):
        return f"STRING_AGG(DISTINCT {column_expression}, ',') AS {alias}"
    return f"GROUP_CONCAT(DISTINCT {column_expression}) AS {alias}"


class RuntimeDB:
    def __init__(self, engine: Engine | None = None):
        self.engine = engine or create_db_engine()
        self.connection: Connection = self.engine.connect()
        self.backend = resolve_runtime_backend(self.engine)

    def __enter__(self) -> "RuntimeDB":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()
        self.engine.dispose()

    def execute(self, sql: str, params: Any = ()) -> CursorResult[Any]:
        adapted_sql, adapted_params = adapt_qmark_sql(sql, params)
        return self.connection.execute(text(adapted_sql), adapted_params)

    def read_df(self, sql: str, params: Any = ()) -> pd.DataFrame:
        adapted_sql, adapted_params = adapt_qmark_sql(sql, params)
        return pd.read_sql_query(text(adapted_sql), self.connection, params=adapted_params)

    def scalar(self, sql: str, params: Any = ()) -> Any:
        row = self.execute(sql, params).fetchone()
        if row is None:
            return None
        return row[0]

    def fetchall(self, sql: str, params: Any = ()) -> list[Any]:
        return list(self.execute(sql, params).fetchall())

    def db_stats(self) -> dict[str, Any]:
        stats: dict[str, Any] = {}

        for table in ["prices", "predictions", "outcomes", "regimes"]:
            stats[f"{table}_count"] = int(self.scalar(f"SELECT COUNT(*) FROM {table}") or 0)

        row = self.execute("SELECT MIN(date), MAX(date) FROM prices").fetchone()
        stats["price_date_range"] = f"{row[0]} -> {row[1]}" if row and row[0] else "Sin datos"

        models = self.fetchall("SELECT DISTINCT model_name FROM predictions")
        stats["models"] = [row[0] for row in models]

        if self.backend.is_sqlite:
            sqlite_database = self.engine.url.database
            if sqlite_database and Path(sqlite_database).exists():
                size_mb = Path(sqlite_database).stat().st_size / (1024 * 1024)
                stats["db_size_mb"] = round(size_mb, 2)

        return stats

    def get_model_accuracy(
        self,
        model_name: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        query = """
            SELECT
                COUNT(*) as total,
                SUM(o.hit) as aciertos,
                ROUND(AVG(o.hit) * 100, 2) as accuracy_pct,
                ROUND(AVG(o.actual_return) * 100, 4) as avg_return_pct,
                ROUND(AVG(CASE WHEN o.hit = 1 THEN o.actual_return END) * 100, 4) as avg_return_right,
                ROUND(AVG(CASE WHEN o.hit = 0 THEN o.actual_return END) * 100, 4) as avg_return_wrong,
                ROUND(AVG(p.confidence) * 100, 2) as avg_confidence
            FROM predictions p
            INNER JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ?
        """
        params: list[Any] = [model_name]

        if start_date:
            query += " AND p.target_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND p.target_date <= ?"
            params.append(end_date)

        row = self.execute(query, tuple(params)).fetchone()
        if not row or row[0] == 0:
            return {"total": 0, "accuracy": 0, "message": "Sin datos evaluados"}

        return {
            "total": row[0],
            "aciertos": row[1],
            "accuracy_pct": row[2],
            "avg_return_pct": row[3],
            "avg_return_when_right": row[4],
            "avg_return_when_wrong": row[5],
            "avg_confidence": row[6],
        }

    def get_accuracy_by_sector(self, model_name: str) -> pd.DataFrame:
        query = """
            SELECT
                p.sector,
                COUNT(*) as total,
                SUM(o.hit) as aciertos,
                ROUND(AVG(o.hit) * 100, 2) as accuracy_pct,
                ROUND(AVG(o.actual_return) * 100, 4) as avg_return_pct
            FROM predictions p
            INNER JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ? AND p.sector IS NOT NULL
            GROUP BY p.sector
            ORDER BY accuracy_pct DESC
        """
        return self.read_df(query, (model_name,))

    def get_streak(self, model_name: str) -> dict[str, int | str]:
        query = """
            SELECT o.hit
            FROM predictions p
            INNER JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ?
            ORDER BY p.target_date DESC
            LIMIT 50
        """
        rows = self.fetchall(query, (model_name,))
        if not rows:
            return {"current_streak": 0, "streak_type": "none"}

        first = rows[0][0]
        streak = 0
        for row in rows:
            if row[0] == first:
                streak += 1
            else:
                break

        return {
            "current_streak": streak,
            "streak_type": "wins" if first == 1 else "losses",
        }


def connect_runtime_db() -> RuntimeDB:
    return RuntimeDB()


def get_runtime_database_url() -> str:
    return get_database_url()
