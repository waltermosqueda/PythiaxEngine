from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from uuid import uuid4

import herramientas.auto_actualizar as auto_actualizar
from titan_system.core.database import TitanDB


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-auto-actualizar" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_ejecutar_paso_opcional_accepts_explicit_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResult:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def fake_run(*args, **kwargs):
        captured["timeout"] = kwargs["timeout"]
        return FakeResult()

    monkeypatch.setattr(auto_actualizar.subprocess, "run", fake_run)
    monkeypatch.setattr(
        auto_actualizar,
        "guardar_salida",
        lambda step_name, fecha_base, text: Path(".cache") / "pytest-auto-actualizar.txt",
    )

    ok = auto_actualizar.ejecutar_paso_opcional(
        "auditoria_centinela",
        ["python", "fake.py"],
        date(2026, 4, 24),
        timeout_seconds=1800,
    )

    assert ok is True
    assert captured["timeout"] == 1800


def test_get_ultima_fecha_db_reads_active_runtime_backend(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "runtime-cloud.db"
    try:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.resolve().as_posix()}")
        monkeypatch.setenv("TITANDB_FORCE_SQLALCHEMY_COMPAT", "1")

        with TitanDB() as db:
            db.conn.execute(
                """
                INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("SPY", "2026-04-23", 500.0, 505.0, 499.0, 504.0, 1000000, 504.0),
            )
            db.conn.commit()

        latest = auto_actualizar.get_ultima_fecha_db()

        assert latest == date(2026, 4, 23)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_require_cloud_database_runtime_rejects_sqlite_when_flag_enabled(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/runner.db")
    monkeypatch.setenv("PYTHIAX_REQUIRE_CLOUD_DB", "1")

    try:
        auto_actualizar.require_cloud_database_runtime()
    except RuntimeError as exc:
        assert "Neon/Postgres" in str(exc)
    else:
        raise AssertionError("Se esperaba RuntimeError al exigir cloud DB sobre SQLite.")


def test_build_model_snapshot_freshness_report_detects_missing_models(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "freshness.db"
    try:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.resolve().as_posix()}")
        monkeypatch.setenv("TITANDB_FORCE_SQLALCHEMY_COMPAT", "1")
        monkeypatch.setattr(
            auto_actualizar,
            "monitored_entries",
            lambda: [
                {"label": "V13", "role": "activo"},
                {"label": "ML_V97", "role": "legacy_ml"},
            ],
        )

        with TitanDB() as db:
            db.conn.execute(
                """
                INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("SPY", "2026-04-24", 500.0, 505.0, 499.0, 504.0, 1000000, 504.0),
            )
            db.save_model_run_snapshot(
                model_key="V13",
                model_name="INVERTIR_V13",
                analyzed_date="2026-04-24",
                prediction_for="2026-04-25",
                freshness="AL DIA",
                signal_count=2,
                role="activo",
                snapshot_payload={"picks": [{"ticker": "AAPL"}]},
            )

        report = auto_actualizar.build_model_snapshot_freshness_report(date(2026, 4, 24))

        assert report["expected_models"] == 2
        assert report["fresh_models"] == 1
        assert report["missing_models"] == ["ML_V97"]
        assert report["latest_prices_date"] == "2026-04-24"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_monitored_snapshots_already_current_requires_full_coverage_and_matching_date(monkeypatch) -> None:
    monkeypatch.setattr(
        auto_actualizar,
        "build_model_snapshot_freshness_report",
        lambda fecha_base: {
            "missing_models": [],
            "latest_prices_date": "2026-04-24",
            "latest_prediction_date": "2026-04-24",
        },
    )

    assert auto_actualizar.monitored_snapshots_already_current(date(2026, 4, 24)) is True

    monkeypatch.setattr(
        auto_actualizar,
        "build_model_snapshot_freshness_report",
        lambda fecha_base: {
            "missing_models": ["ML_V97"],
            "latest_prices_date": "2026-04-24",
            "latest_prediction_date": "2026-04-24",
        },
    )

    assert auto_actualizar.monitored_snapshots_already_current(date(2026, 4, 24)) is False
