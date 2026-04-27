from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from infra.db.bootstrap_sqlite_from_target import bootstrap_sqlite_from_target
from infra.db.migrate_sqlite_to_postgres import sqlite_path_to_url
from titan_system.core.database import TitanDB


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-bootstrap-sqlite-from-target" / uuid4().hex
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
            ("SPY", "2026-04-23", 500.0, 505.0, 498.0, 504.0, 1200000, 504.0),
        )
        con.execute(
            """
            INSERT INTO predictions
                (id, model_name, model_version, ticker, prediction_date, target_date, direction, confidence, score, regime, sector)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "INVERTIR_V13_D_D10", "v13", "AAPL", "2026-04-23", "2026-04-24", "UP", 0.91, 2.4, "SEGURO", "Tech"),
        )
        con.execute(
            """
            INSERT INTO outcomes
                (id, prediction_id, actual_direction, actual_return, hit)
            VALUES (?, ?, ?, ?, ?)
            """,
            (1, 1, "UP", 0.021, 1),
        )
        con.execute(
            """
            INSERT INTO model_metrics
                (model_name, period_start, period_end, total_predictions, correct_predictions, accuracy)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("INVERTIR_V13_D_D10", "2026-04-01", "2026-04-24", 1, 1, 1.0),
        )
        con.execute(
            """
            INSERT INTO regimes
                (date, trend_regime, vol_regime, credit_regime, composite, vix_level, spy_return_20d, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-04-24", "BULL", "LOW", "OK", "SEGURO", 18.5, 0.034, "{}"),
        )
        con.execute(
            """
            INSERT INTO data_status (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            ("latest_prices_date", "2026-04-24", "2026-04-24 20:00:00"),
        )
        con.commit()


def test_bootstrap_sqlite_from_target_materializes_runner_sqlite() -> None:
    tmp_dir = make_workspace_tmp_dir()
    source_path = tmp_dir / "source.db"
    target_path = tmp_dir / "runner.db"
    try:
        seed_source_sqlite(source_path)

        report = bootstrap_sqlite_from_target(
            source_url=sqlite_path_to_url(source_path),
            target_sqlite_path=target_path,
            reset_target=True,
        )

        assert report.ensure_schema is True
        assert target_path.exists()

        with TitanDB(db_path=str(target_path)) as db:
            assert db.conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0] == 1
            assert db.conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 1
            assert db.conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0] == 1
            assert db.conn.execute("SELECT COUNT(*) FROM model_metrics").fetchone()[0] == 1
            assert db.conn.execute("SELECT COUNT(*) FROM regimes").fetchone()[0] == 1
            assert db.conn.execute("SELECT COUNT(*) FROM data_status").fetchone()[0] == 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
