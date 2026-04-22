from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine

from infra.db.migrate_sqlite_to_postgres import sqlite_path_to_url
from infra.db.runtime import RuntimeDB
from titan_system.core.database import TitanDB
import herramientas.competencia_topn_estandar as competition_topn


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-competition-fallback" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def seed_competition_db(db_path: Path) -> None:
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
            INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("SPY", "2026-04-22", 503.0, 507.0, 501.0, 506.0, 2100000, 506.0),
        )

        rows = [
            (1, "INVERTIR_V13_D_D10", "AAPL", "2026-04-21", "2026-04-22", "UP", 0.93, 2.1),
            (2, "INVERTIR_V13_D_D10", "MSFT", "2026-04-21", "2026-04-22", "UP", 0.81, 1.8),
            (3, "INVERTIR_V13_D_D10", "GOOG", "2026-04-21", "2026-04-22", "UP", 0.42, 1.1),
        ]
        for row in rows:
            con.execute(
                """
                INSERT INTO predictions
                    (id, model_name, ticker, prediction_date, target_date, direction, confidence, score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )

        outcomes = [
            (1, 1, "UP", 0.025, 1),
            (2, 2, "UP", 0.019, 1),
            (3, 3, "DOWN", -0.011, 0),
        ]
        for row in outcomes:
            con.execute(
                """
                INSERT INTO outcomes
                    (id, prediction_id, actual_direction, actual_return, hit)
                VALUES (?, ?, ?, ?, ?)
                """,
                row,
            )
        con.commit()


def test_competition_snapshot_uses_db_fallback_when_snapshots_are_missing(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "competition.db"
    try:
        seed_competition_db(db_path)

        custom_entry = {
            "key": "V13",
            "label": "V13",
            "role": "activo",
            "prefix": "INVERTIR_V13",
        }
        monkeypatch.setattr(competition_topn, "monitored_entries", lambda: [custom_entry])
        monkeypatch.setattr(competition_topn, "load_entry_snapshots", lambda entry: {})

        engine = create_engine(sqlite_path_to_url(db_path), future=True)
        try:
            with RuntimeDB(engine) as db:
                snapshot = competition_topn.build_standardized_competition_snapshot(
                    db,
                    market_dates=["2026-04-21", "2026-04-22"],
                    active_version=13,
                    reference_version=None,
                    top_n=2,
                )
        finally:
            engine.dispose()

        row = snapshot["rows"][0]
        recent_row = snapshot["recent"]["league_equalized"][0]

        assert row["selection_source"] == "db_fallback"
        assert row["db_fallback_days"] == 1
        assert row["pred_days"] == 1
        assert row["latest_picks"] == 2
        assert row["latest_tickers"] == ["AAPL", "MSFT"]
        assert recent_row["version"] == "V13"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
