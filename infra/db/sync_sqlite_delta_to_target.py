from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from infra.db.config import get_database_url, get_sqlite_fallback_path
from infra.db.migrate_sqlite_to_postgres import normalize_chunk, redact_url
from infra.db.models import DataStatus, ModelMetric, Outcome, Prediction, Price, Regime


@dataclass
class TableSyncResult:
    table_name: str
    source_rows: int
    upserted_rows: int
    source_cursor: str | None
    target_cursor_before: str | None
    target_cursor_after: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "table_name": self.table_name,
            "source_rows": self.source_rows,
            "upserted_rows": self.upserted_rows,
            "source_cursor": self.source_cursor,
            "target_cursor_before": self.target_cursor_before,
            "target_cursor_after": self.target_cursor_after,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sincroniza en forma incremental el delta reciente desde SQLite hacia Postgres.",
    )
    parser.add_argument(
        "--source-sqlite-path",
        type=Path,
        default=get_sqlite_fallback_path(),
        help="Ruta de la SQLite fuente. Default: fallback configurado.",
    )
    parser.add_argument(
        "--target-url",
        default=get_database_url(),
        help="URL SQLAlchemy del target. Default: DATABASE_URL actual.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1000,
        help="Filas por chunk para cada upsert.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Ruta opcional para escribir un reporte JSON.",
    )
    return parser.parse_args()


def _read_scalar_sqlite(source_path: Path, sql: str, params: tuple[Any, ...] = ()) -> Any:
    with sqlite3.connect(source_path) as con:
        row = con.execute(sql, params).fetchone()
        return row[0] if row else None


def _read_scalar_target(session: Session, sql: str) -> Any:
    return session.execute(text(sql)).scalar()


def _iter_source_chunks(
    *,
    source_path: Path,
    table_name: str,
    sql: str,
    params: tuple[Any, ...],
    chunk_size: int,
):
    with sqlite3.connect(source_path) as con:
        for chunk in pd.read_sql_query(sql, con, params=params, chunksize=chunk_size):
            normalized = normalize_chunk(table_name, chunk)
            rows = normalized.where(pd.notna(normalized), None).to_dict(orient="records")
            if rows:
                yield rows


def _set_serial_sequence(session: Session, table_name: str) -> None:
    session.execute(
        text(
            f"""
            SELECT setval(
                pg_get_serial_sequence('{table_name}', 'id'),
                COALESCE((SELECT MAX(id) FROM {table_name}), 1),
                true
            )
            """
        )
    )


def sync_prices(*, source_path: Path, session: Session, chunk_size: int) -> TableSyncResult:
    target_before = session.scalar(select(func.max(Price.date)))
    source_after = _read_scalar_sqlite(source_path, "SELECT MAX(date) FROM prices")
    params: tuple[Any, ...] = ()
    sql = "SELECT ticker, date, open, high, low, close, volume, adj_close FROM prices"
    if target_before is not None:
        sql += " WHERE date >= ?"
        params = (str(target_before),)
    sql += " ORDER BY date, ticker"

    source_rows = 0
    upserted_rows = 0
    for rows in _iter_source_chunks(
        source_path=source_path,
        table_name="prices",
        sql=sql,
        params=params,
        chunk_size=chunk_size,
    ):
        source_rows += len(rows)
        stmt = pg_insert(Price).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Price.ticker.key, Price.date.key],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "adj_close": stmt.excluded.adj_close,
            },
        )
        session.execute(stmt)
        session.commit()
        upserted_rows += len(rows)

    target_after = session.scalar(select(func.max(Price.date)))
    return TableSyncResult(
        table_name="prices",
        source_rows=source_rows,
        upserted_rows=upserted_rows,
        source_cursor=str(source_after) if source_after else None,
        target_cursor_before=str(target_before) if target_before else None,
        target_cursor_after=str(target_after) if target_after else None,
    )


def sync_predictions(*, source_path: Path, session: Session, chunk_size: int) -> TableSyncResult:
    target_before = session.scalar(select(func.max(Prediction.prediction_date)))
    source_after = _read_scalar_sqlite(source_path, "SELECT MAX(prediction_date) FROM predictions")
    params: tuple[Any, ...] = ()
    sql = """
        SELECT
            id,
            model_name,
            model_version,
            ticker,
            prediction_date,
            target_date,
            direction,
            confidence,
            score,
            regime,
            sector,
            created_at
        FROM predictions
    """
    if target_before is not None:
        sql += " WHERE prediction_date >= ?"
        params = (str(target_before),)
    sql += " ORDER BY id"

    source_rows = 0
    upserted_rows = 0
    for rows in _iter_source_chunks(
        source_path=source_path,
        table_name="predictions",
        sql=sql,
        params=params,
        chunk_size=chunk_size,
    ):
        source_rows += len(rows)
        stmt = pg_insert(Prediction).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Prediction.id.key],
            set_={
                "model_name": stmt.excluded.model_name,
                "model_version": stmt.excluded.model_version,
                "ticker": stmt.excluded.ticker,
                "prediction_date": stmt.excluded.prediction_date,
                "target_date": stmt.excluded.target_date,
                "direction": stmt.excluded.direction,
                "confidence": stmt.excluded.confidence,
                "score": stmt.excluded.score,
                "regime": stmt.excluded.regime,
                "sector": stmt.excluded.sector,
                "created_at": stmt.excluded.created_at,
            },
        )
        session.execute(stmt)
        session.commit()
        upserted_rows += len(rows)

    _set_serial_sequence(session, "predictions")
    session.commit()
    target_after = session.scalar(select(func.max(Prediction.prediction_date)))
    return TableSyncResult(
        table_name="predictions",
        source_rows=source_rows,
        upserted_rows=upserted_rows,
        source_cursor=str(source_after) if source_after else None,
        target_cursor_before=str(target_before) if target_before else None,
        target_cursor_after=str(target_after) if target_after else None,
    )


def sync_outcomes(*, source_path: Path, session: Session, chunk_size: int) -> TableSyncResult:
    target_before = session.execute(
        select(func.max(Prediction.target_date)).select_from(Outcome).join(Prediction, Prediction.id == Outcome.prediction_id)
    ).scalar()
    source_after = _read_scalar_sqlite(
        source_path,
        """
        SELECT MAX(p.target_date)
        FROM outcomes o
        JOIN predictions p ON p.id = o.prediction_id
        """,
    )
    params: tuple[Any, ...] = ()
    sql = """
        SELECT
            o.id,
            o.prediction_id,
            o.actual_direction,
            o.actual_return,
            o.hit,
            o.evaluated_at
        FROM outcomes o
        JOIN predictions p ON p.id = o.prediction_id
    """
    if target_before is not None:
        sql += " WHERE p.target_date >= ?"
        params = (str(target_before),)
    sql += " ORDER BY o.id"

    source_rows = 0
    upserted_rows = 0
    for rows in _iter_source_chunks(
        source_path=source_path,
        table_name="outcomes",
        sql=sql,
        params=params,
        chunk_size=chunk_size,
    ):
        source_rows += len(rows)
        stmt = pg_insert(Outcome).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Outcome.id.key],
            set_={
                "prediction_id": stmt.excluded.prediction_id,
                "actual_direction": stmt.excluded.actual_direction,
                "actual_return": stmt.excluded.actual_return,
                "hit": stmt.excluded.hit,
                "evaluated_at": stmt.excluded.evaluated_at,
            },
        )
        session.execute(stmt)
        session.commit()
        upserted_rows += len(rows)

    _set_serial_sequence(session, "outcomes")
    session.commit()
    target_after = session.execute(
        select(func.max(Prediction.target_date)).select_from(Outcome).join(Prediction, Prediction.id == Outcome.prediction_id)
    ).scalar()
    return TableSyncResult(
        table_name="outcomes",
        source_rows=source_rows,
        upserted_rows=upserted_rows,
        source_cursor=str(source_after) if source_after else None,
        target_cursor_before=str(target_before) if target_before else None,
        target_cursor_after=str(target_after) if target_after else None,
    )


def sync_model_metrics(*, source_path: Path, session: Session, chunk_size: int) -> TableSyncResult:
    target_before = session.scalar(select(func.max(ModelMetric.period_end)))
    source_after = _read_scalar_sqlite(source_path, "SELECT MAX(period_end) FROM model_metrics")
    sql = """
        SELECT
            id,
            model_name,
            period_start,
            period_end,
            total_predictions,
            correct_predictions,
            accuracy,
            avg_confidence,
            avg_return_when_right,
            avg_return_when_wrong,
            profit_factor,
            sharpe_ratio,
            max_drawdown,
            calculated_at
        FROM model_metrics
        ORDER BY id
    """

    source_rows = 0
    upserted_rows = 0
    for rows in _iter_source_chunks(
        source_path=source_path,
        table_name="model_metrics",
        sql=sql,
        params=(),
        chunk_size=chunk_size,
    ):
        rows = [{key: value for key, value in row.items() if key != "id"} for row in rows]
        source_rows += len(rows)
        stmt = pg_insert(ModelMetric).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_model_metrics_model_period",
            set_={
                "total_predictions": stmt.excluded.total_predictions,
                "correct_predictions": stmt.excluded.correct_predictions,
                "accuracy": stmt.excluded.accuracy,
                "avg_confidence": stmt.excluded.avg_confidence,
                "avg_return_when_right": stmt.excluded.avg_return_when_right,
                "avg_return_when_wrong": stmt.excluded.avg_return_when_wrong,
                "profit_factor": stmt.excluded.profit_factor,
                "sharpe_ratio": stmt.excluded.sharpe_ratio,
                "max_drawdown": stmt.excluded.max_drawdown,
                "calculated_at": stmt.excluded.calculated_at,
            },
        )
        session.execute(stmt)
        session.commit()
        upserted_rows += len(rows)

    target_after = session.scalar(select(func.max(ModelMetric.period_end)))
    return TableSyncResult(
        table_name="model_metrics",
        source_rows=source_rows,
        upserted_rows=upserted_rows,
        source_cursor=str(source_after) if source_after else None,
        target_cursor_before=str(target_before) if target_before else None,
        target_cursor_after=str(target_after) if target_after else None,
    )


def sync_regimes(*, source_path: Path, session: Session, chunk_size: int) -> TableSyncResult:
    target_before = session.scalar(select(func.max(Regime.date)))
    source_after = _read_scalar_sqlite(source_path, "SELECT MAX(date) FROM regimes")
    params: tuple[Any, ...] = ()
    sql = """
        SELECT
            date,
            trend_regime,
            vol_regime,
            credit_regime,
            composite,
            vix_level,
            spy_return_20d,
            details
        FROM regimes
    """
    if target_before is not None:
        sql += " WHERE date >= ?"
        params = (str(target_before),)
    sql += " ORDER BY date"

    source_rows = 0
    upserted_rows = 0
    for rows in _iter_source_chunks(
        source_path=source_path,
        table_name="regimes",
        sql=sql,
        params=params,
        chunk_size=chunk_size,
    ):
        source_rows += len(rows)
        stmt = pg_insert(Regime).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Regime.date.key],
            set_={
                "trend_regime": stmt.excluded.trend_regime,
                "vol_regime": stmt.excluded.vol_regime,
                "credit_regime": stmt.excluded.credit_regime,
                "composite": stmt.excluded.composite,
                "vix_level": stmt.excluded.vix_level,
                "spy_return_20d": stmt.excluded.spy_return_20d,
                "details": stmt.excluded.details,
            },
        )
        session.execute(stmt)
        session.commit()
        upserted_rows += len(rows)

    target_after = session.scalar(select(func.max(Regime.date)))
    return TableSyncResult(
        table_name="regimes",
        source_rows=source_rows,
        upserted_rows=upserted_rows,
        source_cursor=str(source_after) if source_after else None,
        target_cursor_before=str(target_before) if target_before else None,
        target_cursor_after=str(target_after) if target_after else None,
    )


def sync_data_status(*, source_path: Path, session: Session) -> TableSyncResult:
    sql = "SELECT key, value, updated_at FROM data_status ORDER BY key"
    rows = next(
        _iter_source_chunks(
            source_path=source_path,
            table_name="data_status",
            sql=sql,
            params=(),
            chunk_size=100,
        ),
        [],
    )
    target_before = _read_scalar_target(session, "SELECT MAX(updated_at) FROM data_status")
    source_after = _read_scalar_sqlite(source_path, "SELECT MAX(updated_at) FROM data_status")
    if rows:
        stmt = pg_insert(DataStatus).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[DataStatus.key.key],
            set_={
                "value": stmt.excluded.value,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        session.execute(stmt)
        session.commit()
    target_after = _read_scalar_target(session, "SELECT MAX(updated_at) FROM data_status")
    return TableSyncResult(
        table_name="data_status",
        source_rows=len(rows),
        upserted_rows=len(rows),
        source_cursor=str(source_after) if source_after else None,
        target_cursor_before=str(target_before) if target_before else None,
        target_cursor_after=str(target_after) if target_after else None,
    )


def build_report(
    *,
    source_path: Path,
    target_url: str,
    chunk_size: int,
    results: list[TableSyncResult],
) -> dict[str, Any]:
    return {
        "source_sqlite_path": str(source_path.resolve()),
        "target_url": redact_url(target_url),
        "chunk_size": chunk_size,
        "results": [result.as_dict() for result in results],
    }


def write_report(report_path: Path, payload: dict[str, Any]) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def sync_sqlite_delta_to_target(
    *,
    source_sqlite_path: Path,
    target_url: str,
    chunk_size: int = 1000,
    report_path: Path | None = None,
) -> dict[str, Any]:
    source_path = source_sqlite_path.resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"No existe la SQLite fuente: {source_path}")

    engine = create_engine(target_url)
    if not engine.dialect.name.startswith("postgres"):
        raise ValueError("El target incremental debe ser Postgres para usar UPSERT nativo.")

    try:
        with Session(engine) as session:
            results = [
                sync_prices(source_path=source_path, session=session, chunk_size=chunk_size),
                sync_predictions(source_path=source_path, session=session, chunk_size=chunk_size),
                sync_outcomes(source_path=source_path, session=session, chunk_size=chunk_size),
                sync_model_metrics(source_path=source_path, session=session, chunk_size=chunk_size),
                sync_regimes(source_path=source_path, session=session, chunk_size=chunk_size),
                sync_data_status(source_path=source_path, session=session),
            ]
        payload = build_report(
            source_path=source_path,
            target_url=target_url,
            chunk_size=chunk_size,
            results=results,
        )
        if report_path is not None:
            write_report(report_path, payload)
        return payload
    finally:
        engine.dispose()


def main() -> int:
    args = parse_args()
    payload = sync_sqlite_delta_to_target(
        source_sqlite_path=args.source_sqlite_path,
        target_url=args.target_url,
        chunk_size=args.chunk_size,
        report_path=args.report_path,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
