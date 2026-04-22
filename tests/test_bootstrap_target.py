from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from uuid import uuid4

from infra.db.bootstrap_target import bootstrap_target_from_sqlite
from infra.db.migrate_sqlite_to_postgres import sqlite_path_to_url
from titan_system.core.database import TitanDB


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-bootstrap" / uuid4().hex
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
            ("SPY", "2026-04-21", 500.0, 505.0, 497.0, 503.0, 1900000, 503.0),
        )
        con.execute(
            """
            INSERT INTO predictions
                (id, model_name, ticker, prediction_date, target_date, direction, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, "INVERTIR_V13_D_D10", "SPY", "2026-04-21", "2026-04-22", "UP", 0.81),
        )
        con.execute(
            """
            INSERT INTO outcomes
                (id, prediction_id, actual_direction, actual_return, hit)
            VALUES (?, ?, ?, ?, ?)
            """,
            (1, 1, "UP", 0.018, 1),
        )
        con.execute(
            """
            INSERT INTO data_status (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            ("latest_prices_date", "2026-04-21", "2026-04-21 20:00:00"),
        )
        con.commit()


def test_bootstrap_target_from_sqlite_runs_alembic_then_loads_data() -> None:
    tmp_dir = make_workspace_tmp_dir()
    source_path = tmp_dir / "source.db"
    target_path = tmp_dir / "target.db"
    report_path = tmp_dir / "report.json"
    try:
        seed_source_sqlite(source_path)

        report = bootstrap_target_from_sqlite(
            source_sqlite_path=source_path,
            target_url=sqlite_path_to_url(target_path),
            reset_target=True,
            allow_sqlite_target=True,
            report_path=report_path,
        )

        counts = {result.table_name: result.target_rows for result in report.results}
        assert counts["prices"] == 1
        assert counts["predictions"] == 1
        assert counts["outcomes"] == 1
        assert counts["data_status"] == 1
        assert report_path.exists()

        with sqlite3.connect(str(target_path)) as con:
            prediction_count = con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
            data_status_count = con.execute("SELECT COUNT(*) FROM data_status").fetchone()[0]

        assert prediction_count == 1
        assert data_status_count == 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
