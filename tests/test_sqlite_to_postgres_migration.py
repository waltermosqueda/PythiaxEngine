from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

import pandas as pd
from sqlalchemy import create_engine, text

from infra.db.migrate_sqlite_to_postgres import (
    adapt_chunk_for_target_backend,
    migrate_sqlite_to_target,
    sqlite_path_to_url,
)
from titan_system.core.database import TitanDB


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-migration" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def seed_source_sqlite(db_path: Path) -> None:
    with TitanDB(db_path=str(db_path)) as db:
        con = db.conn
        con.execute(
            """
            INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("AAPL", "2026-04-21", 100.0, 105.0, 99.0, 103.0, 1200000, 103.0),
        )
        con.execute(
            """
            INSERT INTO predictions
                (id, model_name, model_version, ticker, prediction_date, target_date,
                 direction, confidence, score, regime, sector)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "INVERTIR_V13_MAIN",
                "v13",
                "AAPL",
                "2026-04-21",
                "2026-04-22",
                "UP",
                0.77,
                1.25,
                "bull",
                "technology",
            ),
        )
        con.execute(
            """
            INSERT INTO outcomes
                (id, prediction_id, actual_direction, actual_return, hit)
            VALUES (?, ?, ?, ?, ?)
            """,
            (1, 1, "UP", 0.024, 1),
        )
        con.execute(
            """
            INSERT INTO model_metrics
                (id, model_name, period_start, period_end, total_predictions,
                 correct_predictions, accuracy, avg_confidence, avg_return_when_right,
                 avg_return_when_wrong, profit_factor, sharpe_ratio, max_drawdown)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "INVERTIR_V13_MAIN",
                "2026-04-01",
                "2026-04-22",
                10,
                7,
                0.70,
                0.66,
                0.018,
                -0.011,
                1.9,
                1.2,
                -0.05,
            ),
        )
        con.execute(
            """
            INSERT INTO regimes
                (date, trend_regime, vol_regime, credit_regime, composite,
                 vix_level, spy_return_20d, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-04-21", "bull", "normal", "loose", "bull_normal", 19.5, 0.032, "seed"),
        )
        con.execute(
            """
            INSERT INTO data_status (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            ("latest_prices_date", "2026-04-21", "2026-04-21 20:00:00"),
        )
        con.commit()


def test_sqlite_migration_copies_expected_tables() -> None:
    tmp_dir = make_workspace_tmp_dir()
    source_path = tmp_dir / "source.db"
    target_path = tmp_dir / "target.db"
    try:
        seed_source_sqlite(source_path)

        report = migrate_sqlite_to_target(
            source_url=sqlite_path_to_url(source_path),
            target_url=sqlite_path_to_url(target_path),
            reset_target=True,
            ensure_schema=True,
            chunk_size=2,
        )

        counts = {result.table_name: result.target_rows for result in report.results}
        assert counts["prices"] == 1
        assert counts["predictions"] == 1
        assert counts["outcomes"] == 1
        assert counts["model_metrics"] == 1
        assert counts["regimes"] == 1
        assert counts["data_status"] == 1
        assert counts["pipeline_runs"] == 0

        skipped = {result.table_name: result.skipped for result in report.results}
        assert skipped["pipeline_runs"] is True

        target_engine = create_engine(sqlite_path_to_url(target_path), future=True)
        try:
            with target_engine.connect() as connection:
                row = connection.execute(
                    text(
                        """
                        SELECT ticker, direction, confidence
                        FROM predictions
                        WHERE id = 1
                        """
                    )
                ).mappings().one()
                assert row["ticker"] == "AAPL"
                assert row["direction"] == "UP"
                assert float(row["confidence"]) == 0.77
        finally:
            target_engine.dispose()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_sqlite_migration_with_reset_is_repeatable() -> None:
    tmp_dir = make_workspace_tmp_dir()
    source_path = tmp_dir / "source.db"
    target_path = tmp_dir / "target.db"
    try:
        seed_source_sqlite(source_path)
        source_url = sqlite_path_to_url(source_path)
        target_url = sqlite_path_to_url(target_path)

        first_report = migrate_sqlite_to_target(
            source_url=source_url,
            target_url=target_url,
            reset_target=True,
            ensure_schema=True,
            chunk_size=10,
        )
        second_report = migrate_sqlite_to_target(
            source_url=source_url,
            target_url=target_url,
            reset_target=True,
            ensure_schema=True,
            chunk_size=10,
        )

        first_counts = {result.table_name: result.target_rows for result in first_report.results}
        second_counts = {result.table_name: result.target_rows for result in second_report.results}

        assert first_counts == second_counts

        with sqlite3.connect(str(target_path)) as con:
            prediction_count = con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
            outcome_count = con.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]

        assert prediction_count == 1
        assert outcome_count == 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_adapt_chunk_for_sqlite_serializes_json_columns() -> None:
    chunk = pd.DataFrame(
        [
            {
                "id": 1,
                "run_id": "dashboard_build-1",
                "pipeline_name": "dashboard_build",
                "status": "SUCCESS",
                "artifact_manifest": {"files": ["index.html"]},
                "metadata_json": {"variant": "all", "count": 1},
            }
        ]
    )

    adapted = adapt_chunk_for_target_backend(
        "pipeline_runs",
        chunk,
        target_backend="sqlite",
    )

    assert adapted.loc[0, "artifact_manifest"] == '{"files": ["index.html"]}'
    assert adapted.loc[0, "metadata_json"] == '{"variant": "all", "count": 1}'
