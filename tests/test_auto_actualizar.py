from __future__ import annotations

import shutil
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
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
        assert "cloud Postgres" in str(exc)
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
                {"label": "V13", "role": "activo", "prefix": "INVERTIR_V13"},
                {
                    "label": "ML_V97",
                    "role": "legacy_ml",
                    "prefix": "LEGACY_ML_V97_SURGE_D3",
                    "exact_model_name": True,
                },
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
        by_label = {row["label"]: row for row in report["models"]}
        assert by_label["V13"]["prediction_days"] == 0
        assert by_label["V13"]["latest_prediction_date"] is None
        assert by_label["ML_V97"]["status"] == "missing_snapshot"
        assert by_label["ML_V97"]["total_prediction_rows"] == 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_build_model_snapshot_freshness_report_exposes_prediction_coverage_for_missing_snapshot(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "freshness-predictions.db"
    try:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.resolve().as_posix()}")
        monkeypatch.setenv("TITANDB_FORCE_SQLALCHEMY_COMPAT", "1")
        monkeypatch.setattr(
            auto_actualizar,
            "monitored_entries",
            lambda: [
                {"label": "V13", "role": "activo", "prefix": "INVERTIR_V13"},
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
            db.save_prediction(
                model_name="INVERTIR_V13_D_D10",
                model_version="v13",
                ticker="AAPL",
                prediction_date="2026-04-24",
                target_date="2026-04-25",
                direction="UP",
                confidence=0.91,
                score=82.5,
                regime="SEGURO",
                sector="Tech",
            )

        report = auto_actualizar.build_model_snapshot_freshness_report(date(2026, 4, 24))

        assert report["missing_models"] == ["V13"]
        model = report["models"][0]
        assert model["label"] == "V13"
        assert model["status"] == "missing_snapshot"
        assert model["latest_prediction_date"] == "2026-04-24"
        assert model["latest_prediction_rows"] == 1
        assert model["total_prediction_rows"] == 1
        assert model["prediction_days"] == 1
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


def test_auditar_integridad_dashboard_runs_required_step(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_ejecutar_paso(step_name, command, fecha_base):
        captured["step_name"] = step_name
        captured["command"] = command
        captured["fecha_base"] = fecha_base
        return True

    monkeypatch.setattr(auto_actualizar, "ejecutar_paso", fake_ejecutar_paso)

    ok = auto_actualizar.auditar_integridad_dashboard(date(2026, 4, 24))

    assert ok is True
    assert captured["step_name"] == "dashboard_integrity"
    assert captured["command"] == [
        auto_actualizar.sys.executable,
        str(auto_actualizar.DASHBOARD_INTEGRITY_SCRIPT),
    ]
    assert captured["fecha_base"] == date(2026, 4, 24)


def test_ejecutar_publicacion_liviana_blocks_when_dashboard_integrity_fails(monkeypatch) -> None:
    optional_called = {"value": False}

    monkeypatch.setattr(auto_actualizar, "validate_model_snapshot_freshness", lambda fecha_base: True)
    monkeypatch.setattr(auto_actualizar, "refrescar_dashboard", lambda fecha_base: True)
    monkeypatch.setattr(auto_actualizar, "auditar_integridad_dashboard", lambda fecha_base: False)
    monkeypatch.setattr(
        auto_actualizar,
        "ejecutar_paso_opcional",
        lambda *args, **kwargs: optional_called.__setitem__("value", True) or True,
    )

    ok = auto_actualizar.ejecutar_publicacion_liviana(date(2026, 4, 24))

    assert ok is False
    assert optional_called["value"] is False


def test_ejecutar_pipeline_diario_can_skip_dashboard_refresh_tail(monkeypatch) -> None:
    operational = SimpleNamespace(
        active_scanner=Path("scanner_activo.py"),
        active_learning=Path("aprendizaje_v13.py"),
        active_version="V13",
        observed_versions=[],
        observed_learning_chain=[],
    )
    dashboard_calls = {
        "validate": False,
        "refresh": False,
        "audit": False,
        "optional": False,
    }

    monkeypatch.setattr(auto_actualizar, "resolve_operational_scanner_context", lambda: operational)
    monkeypatch.setattr(auto_actualizar, "build_learning_steps", lambda command_name: [])
    monkeypatch.setattr(auto_actualizar, "build_observed_steps", lambda command_name: [])
    monkeypatch.setattr(auto_actualizar, "build_legacy_ml_steps", lambda command_name: [])
    monkeypatch.setattr(auto_actualizar, "ejecutar_paso", lambda step_name, command, fecha_base: True)
    monkeypatch.setattr(
        auto_actualizar,
        "validate_model_snapshot_freshness",
        lambda fecha_base: dashboard_calls.__setitem__("validate", True) or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "refrescar_dashboard",
        lambda fecha_base: dashboard_calls.__setitem__("refresh", True) or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "auditar_integridad_dashboard",
        lambda fecha_base: dashboard_calls.__setitem__("audit", True) or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "ejecutar_paso_opcional",
        lambda *args, **kwargs: dashboard_calls.__setitem__("optional", True) or True,
    )

    ok = auto_actualizar.ejecutar_pipeline_diario(
        date(2026, 4, 24),
        datetime(2026, 4, 24, 22, 0),
        skip_dashboard_refresh=True,
    )

    assert ok is True
    assert dashboard_calls == {
        "validate": True,
        "refresh": False,
        "audit": False,
        "optional": False,
    }


def test_ejecutar_pipeline_diario_skip_dashboard_refresh_still_blocks_on_missing_snapshots(monkeypatch) -> None:
    operational = SimpleNamespace(
        active_scanner=Path("scanner_activo.py"),
        active_learning=Path("aprendizaje_v13.py"),
        active_version="V13",
        observed_versions=[],
        observed_learning_chain=[],
    )
    dashboard_calls = {
        "validate": 0,
        "refresh": 0,
        "audit": 0,
        "optional": 0,
    }

    monkeypatch.setattr(auto_actualizar, "resolve_operational_scanner_context", lambda: operational)
    monkeypatch.setattr(auto_actualizar, "build_learning_steps", lambda command_name: [])
    monkeypatch.setattr(auto_actualizar, "build_observed_steps", lambda command_name: [])
    monkeypatch.setattr(auto_actualizar, "build_legacy_ml_steps", lambda command_name: [])
    monkeypatch.setattr(auto_actualizar, "ejecutar_paso", lambda step_name, command, fecha_base: True)
    monkeypatch.setattr(
        auto_actualizar,
        "validate_model_snapshot_freshness",
        lambda fecha_base: dashboard_calls.__setitem__("validate", dashboard_calls["validate"] + 1) or False,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "refrescar_dashboard",
        lambda fecha_base: dashboard_calls.__setitem__("refresh", dashboard_calls["refresh"] + 1) or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "auditar_integridad_dashboard",
        lambda fecha_base: dashboard_calls.__setitem__("audit", dashboard_calls["audit"] + 1) or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "ejecutar_paso_opcional",
        lambda *args, **kwargs: dashboard_calls.__setitem__("optional", dashboard_calls["optional"] + 1) or True,
    )

    ok = auto_actualizar.ejecutar_pipeline_diario(
        date(2026, 4, 24),
        datetime(2026, 4, 24, 22, 0),
        skip_dashboard_refresh=True,
    )

    assert ok is False
    assert dashboard_calls == {
        "validate": 1,
        "refresh": 0,
        "audit": 0,
        "optional": 0,
    }
