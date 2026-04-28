from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine

import analisis.generar_tablero_maquina_pensante as dashboard
from infra.db.migrate_sqlite_to_postgres import sqlite_path_to_url
from infra.db.runtime import RuntimeDB
from titan_system.core.database import TitanDB


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-dashboard-active" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def seed_dashboard_db(db_path: Path) -> None:
    with TitanDB(db_path=str(db_path)) as db:
        con = db.conn

        for idx, market_date in enumerate(["2026-04-18", "2026-04-21", "2026-04-22", "2026-04-23", "2026-04-24"], start=1):
            con.execute(
                """
                INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("SPY", market_date, 500.0 + idx, 505.0 + idx, 499.0 + idx, 504.0 + idx, 1000000, 504.0 + idx),
            )

        prediction_rows = [
            (1, "INVERTIR_V13_D_D10", "AAPL", "2026-04-21", "2026-04-22", "UP", 0.94, 84.2, "SEGURO", "Tecnologia"),
            (2, "INVERTIR_V13_D_D10", "MSFT", "2026-04-21", "2026-04-22", "UP", 0.83, 77.5, "SEGURO", "Tecnologia"),
            (3, "INVERTIR_V13_E_D15", "NVDA", "2026-04-21", "2026-04-24", "UP", 0.88, 81.0, "SEGURO", "Tecnologia"),
            (4, "INVERTIR_V13_D_D10", "OLD", "2026-04-18", "2026-04-21", "DOWN", 0.31, 22.0, "PELIGRO", "Industriales"),
        ]
        for row in prediction_rows:
            con.execute(
                """
                INSERT INTO predictions
                    (id, model_name, ticker, prediction_date, target_date, direction, confidence, score, regime, sector)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )

        outcome_rows = [
            (1, 1, "UP", 0.028, 1),
            (2, 2, "UP", 0.017, 1),
            (3, 3, "UP", 0.034, 1),
            (4, 4, "DOWN", -0.013, 1),
        ]
        for row in outcome_rows:
            con.execute(
                """
                INSERT INTO outcomes
                    (id, prediction_id, actual_direction, actual_return, hit)
                VALUES (?, ?, ?, ?, ?)
                """,
                row,
            )

        con.execute(
            """
            INSERT INTO regimes
                (date, trend_regime, vol_regime, credit_regime, composite, vix_level, spy_return_20d, details)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("2026-04-21", "bull", "low_vol", "open", "SEGURO", 18.4, 0.061, "seed"),
        )
        con.commit()


def test_active_snapshot_uses_prediction_db_fallback_when_postgres_snapshot_is_missing(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "dashboard.db"
    try:
        seed_dashboard_db(db_path)
        monkeypatch.setattr(
            dashboard,
            "resolve_operational_scanner_context",
            lambda: SimpleNamespace(active_version=13, reference_version=None),
        )

        engine = create_engine(sqlite_path_to_url(db_path), future=True)
        try:
            with RuntimeDB(engine) as db:
                payload = dashboard.build_active_snapshot(db, db)
        finally:
            engine.dispose()

        active_run = payload["active_run"]

        assert active_run is not None
        assert active_run["source"] == "prediction_db_fallback"
        assert active_run["fallback_reason"] == "missing_postgres_run_snapshot"
        assert active_run["regime_label"] == "SEGURO"
        assert active_run["prediction_for"] == "2026-04-22"
        assert active_run["analyzed_date"] == "2026-04-21"
        assert active_run["memory_context"] == []
        assert [row["ticker"] for row in active_run["results_d"]] == ["AAPL", "MSFT"]
        assert [row["ticker"] for row in active_run["results_e"]] == ["NVDA"]
        assert all(row["note"] == "db fallback" for row in active_run["results_d"] + active_run["results_e"])
        assert payload["reference_run"] is None
        assert payload["active_d"]["total"] == 3
        assert payload["active_e"]["total"] == 1
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_active_snapshot_uses_snapshot_db_and_overlays_live_results(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "dashboard.db"
    try:
        seed_dashboard_db(db_path)
        with TitanDB(db_path=str(db_path)) as db:
            db.save_model_run_snapshot(
                model_key="V13",
                model_name="INVERTIR_V13",
                analyzed_date="2026-04-21",
                prediction_for="2026-04-22",
                freshness="AL DIA",
                regime_label="SEGURO",
                breadth_pct=61.5,
                signal_count=1,
                snapshot_payload={
                    "version": 13,
                    "analyzed_date": "2026-04-21",
                    "prediction_for": "2026-04-22",
                    "regime_label": "SEGURO",
                    "breadth_pct": 61.5,
                    "memory_context": ["contexto"],
                    "freshness": "AL DIA",
                    "results_d": [
                        {
                            "ticker": "AAPL",
                            "signal": "D (Leadership)",
                            "sector": "Tecnologia",
                            "score": 84.2,
                            "priority_score": 84.2,
                            "note": "snapshot",
                        }
                    ],
                    "results_e": [],
                },
            )

        monkeypatch.setattr(
            dashboard,
            "resolve_operational_scanner_context",
            lambda: SimpleNamespace(active_version=13, reference_version=None),
        )

        engine = create_engine(sqlite_path_to_url(db_path), future=True)
        try:
            with RuntimeDB(engine) as db:
                payload = dashboard.build_active_snapshot(db, db)
        finally:
            engine.dispose()

        active_run = payload["active_run"]

        assert active_run is not None
        assert active_run["source"] == "snapshot_db"
        assert active_run["breadth_pct"] == 61.5
        assert active_run["memory_context"] == ["contexto"]
        assert [row["ticker"] for row in active_run["results_d"]] == ["AAPL", "MSFT"]
        assert [row["ticker"] for row in active_run["results_e"]] == ["NVDA"]
        assert active_run["results_d"][0]["signal"] == "D (Leadership)"
        assert active_run["results_d"][0]["confidence"] == 0.94
        assert active_run["results_d"][0]["target_date"] == "2026-04-22"
        assert active_run["results_e"][0]["target_date"] == "2026-04-24"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_active_snapshot_uses_latest_prediction_date_when_db_moves_forward(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "dashboard.db"
    try:
        seed_dashboard_db(db_path)
        with TitanDB(db_path=str(db_path)) as db:
            db.conn.execute(
                """
                INSERT INTO predictions
                    (id, model_name, ticker, prediction_date, target_date, direction, confidence, score, regime, sector)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (5, "INVERTIR_V13_D_D10", "AVGO", "2026-04-22", "2026-04-23", "UP", 0.91, 79.1, "SEGURO", "Tecnologia"),
            )
            db.conn.execute(
                """
                INSERT INTO regimes
                    (date, trend_regime, vol_regime, credit_regime, composite, vix_level, spy_return_20d, details)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("2026-04-22", "bull", "low_vol", "open", "SEGURO", 18.0, 0.05, "seed"),
            )
            db.conn.commit()

        monkeypatch.setattr(
            dashboard,
            "resolve_operational_scanner_context",
            lambda: SimpleNamespace(active_version=13, reference_version=None),
        )

        engine = create_engine(sqlite_path_to_url(db_path), future=True)
        try:
            with RuntimeDB(engine) as db:
                payload = dashboard.build_active_snapshot(db, db)
        finally:
            engine.dispose()

        active_run = payload["active_run"]

        assert active_run is not None
        assert active_run["source"] == "prediction_db_fallback"
        assert active_run["analyzed_date"] == "2026-04-22"
        assert active_run["prediction_for"] == "2026-04-23"
        assert [row["ticker"] for row in active_run["results_d"]] == ["AVGO"]
        assert active_run["results_e"] == []
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
