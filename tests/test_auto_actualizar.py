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
    monkeypatch.setattr(
        auto_actualizar,
        "build_dashboard_history_report",
        lambda fecha_base, min_market_days=90: {
            "history_complete": True,
            "window_days": 90,
        },
    )
    monkeypatch.setattr(auto_actualizar, "guardar_reporte_json", lambda path, payload: path)

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


def test_monitored_snapshots_already_current_rejects_incomplete_dashboard_history(monkeypatch) -> None:
    monkeypatch.setattr(
        auto_actualizar,
        "build_model_snapshot_freshness_report",
        lambda fecha_base: {
            "missing_models": [],
            "latest_prices_date": "2026-04-24",
            "latest_prediction_date": "2026-04-24",
        },
    )
    monkeypatch.setattr(
        auto_actualizar,
        "build_dashboard_history_report",
        lambda fecha_base, min_market_days=90: {
            "history_complete": False,
            "window_days": 90,
        },
    )
    monkeypatch.setattr(auto_actualizar, "guardar_reporte_json", lambda path, payload: path)

    assert auto_actualizar.monitored_snapshots_already_current(date(2026, 4, 24)) is False


def test_model_snapshot_coverage_is_current_ignores_optional_missing_models() -> None:
    report = {
        "missing_models": ["ML_V39FULL"],
        "required_missing_models": [],
        "optional_missing_models": ["ML_V39FULL"],
        "latest_prices_date": "2026-04-24",
        "latest_prediction_date": "2026-04-24",
    }

    assert auto_actualizar.model_snapshot_coverage_is_current(report, date(2026, 4, 24)) is True


def test_validate_model_snapshot_freshness_allows_optional_missing_models(monkeypatch) -> None:
    alerts = {"count": 0}

    monkeypatch.setattr(
        auto_actualizar,
        "build_model_snapshot_freshness_report",
        lambda fecha_base: {
            "missing_models": ["ML_V39FULL"],
            "required_missing_models": [],
            "optional_missing_models": ["ML_V39FULL"],
            "latest_prices_date": fecha_base.isoformat(),
            "latest_prediction_date": fecha_base.isoformat(),
            "models": [],
        },
    )
    monkeypatch.setattr(
        auto_actualizar,
        "guardar_reporte_json",
        lambda path, payload: Path(".cache") / "pytest-model-freshness.json",
    )
    monkeypatch.setattr(
        auto_actualizar,
        "emit_critical_alert",
        lambda *args, **kwargs: alerts.__setitem__("count", alerts["count"] + 1),
    )

    ok = auto_actualizar.validate_model_snapshot_freshness(date(2026, 4, 24))

    assert ok is True
    assert alerts["count"] == 0


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

    monkeypatch.setattr(auto_actualizar, "ensure_minimum_dashboard_history", lambda fecha_base: True)
    monkeypatch.setattr(auto_actualizar, "validate_model_snapshot_freshness", lambda fecha_base: True)
    monkeypatch.setattr(auto_actualizar, "recompute_required_outcomes", lambda fecha_base: True)
    monkeypatch.setattr(auto_actualizar, "recompute_optional_outcomes", lambda fecha_base: None)
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


def test_ejecutar_publicacion_liviana_reconciles_outcomes_before_refresh(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        auto_actualizar,
        "ensure_minimum_dashboard_history",
        lambda fecha_base: calls.append("ensure_history") or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "validate_model_snapshot_freshness",
        lambda fecha_base: calls.append("validate") or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "recompute_required_outcomes",
        lambda fecha_base: calls.append("required_outcomes") or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "recompute_optional_outcomes",
        lambda fecha_base: calls.append("optional_outcomes"),
    )
    monkeypatch.setattr(
        auto_actualizar,
        "refrescar_dashboard",
        lambda fecha_base: calls.append("refresh") or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "auditar_integridad_dashboard",
        lambda fecha_base: calls.append("audit") or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "ejecutar_paso_opcional",
        lambda *args, **kwargs: calls.append("auditoria_centinela") or True,
    )

    ok = auto_actualizar.ejecutar_publicacion_liviana(date(2026, 4, 24))

    assert ok is True
    assert calls == [
        "ensure_history",
        "validate",
        "required_outcomes",
        "optional_outcomes",
        "refresh",
        "audit",
        "auditoria_centinela",
    ]


def test_ensure_minimum_dashboard_history_bootstraps_sparse_cloud_history(monkeypatch) -> None:
    calls: list[str] = []
    reports = iter(
        [
            {
                "history_complete": False,
                "window_days": 90,
                "start_date": "2026-01-01",
                "missing_snapshot_history": ["V13", "V12"],
                "predictions_recent": 46,
                "outcomes_recent": 0,
                "regimes_recent": 1,
            },
            {
                "history_complete": True,
                "window_days": 90,
                "start_date": "2026-01-01",
                "missing_snapshot_history": [],
                "predictions_recent": 900,
                "outcomes_recent": 700,
                "regimes_recent": 90,
            },
        ]
    )

    monkeypatch.setattr(
        auto_actualizar,
        "build_dashboard_history_report",
        lambda fecha_base, min_market_days=90: next(reports),
    )
    monkeypatch.setattr(auto_actualizar, "guardar_reporte_json", lambda path, payload: path)
    monkeypatch.setattr(
        auto_actualizar,
        "backfill_required_history",
        lambda from_date, fecha_base: calls.append(f"required:{from_date}") or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "backfill_optional_history",
        lambda from_date, fecha_base: calls.append(f"optional:{from_date}"),
    )
    monkeypatch.setattr(
        auto_actualizar,
        "recompute_required_outcomes",
        lambda fecha_base: calls.append("required_outcomes") or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "recompute_optional_outcomes",
        lambda fecha_base: calls.append("optional_outcomes"),
    )

    ok = auto_actualizar.ensure_minimum_dashboard_history(date(2026, 4, 24))

    assert ok is True
    assert calls == [
        "required:2026-01-01",
        "optional:2026-01-01",
        "required_outcomes",
        "optional_outcomes",
    ]


def test_ejecutar_pipeline_diario_can_skip_dashboard_refresh_tail(monkeypatch) -> None:
    operational = SimpleNamespace(
        active_scanner=Path("scanner_activo.py"),
        active_learning=Path("aprendizaje_v13.py"),
        active_version="V13",
        observed_versions=[],
        observed_learning_chain=[],
    )
    required_steps: list[str] = []
    dashboard_calls = {
        "validate": False,
        "refresh": False,
        "audit": False,
        "optional": False,
    }

    monkeypatch.setattr(auto_actualizar, "resolve_operational_scanner_context", lambda: operational)
    monkeypatch.setattr(
        auto_actualizar,
        "build_learning_steps",
        lambda command_name: [
            ("outcomes_v13", Path("aprendizaje_v13.py"))
        ]
        if command_name == "recompute-outcomes"
        else [],
    )
    monkeypatch.setattr(
        auto_actualizar,
        "build_observed_steps",
        lambda command_name: [
            (
                "outcomes_observado_v12" if command_name == "recompute-outcomes" else "observado_v12",
                Path("observado_v12.py"),
            )
        ],
    )
    monkeypatch.setattr(
        auto_actualizar,
        "build_legacy_ml_steps",
        lambda command_name: [
            (
                "outcomes_legacy_ml_v39full"
                if command_name == "recompute-outcomes"
                else "legacy_ml_v39full",
                Path("legacy_ml_v39full.py"),
            )
        ],
    )
    monkeypatch.setattr(
        auto_actualizar,
        "ejecutar_paso",
        lambda step_name, command, fecha_base: required_steps.append(step_name) or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "validate_model_snapshot_freshness",
        lambda fecha_base: dashboard_calls.__setitem__("validate", True) or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "ensure_minimum_dashboard_history",
        lambda fecha_base: required_steps.append("ensure_history") or True,
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
    assert required_steps == ["validacion", "scanner", "ensure_history", "outcomes_v13"]
    assert dashboard_calls == {
        "validate": True,
        "refresh": False,
        "audit": False,
        "optional": True,
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
    monkeypatch.setattr(
        auto_actualizar,
        "build_learning_steps",
        lambda command_name: [
            ("outcomes_v13", Path("aprendizaje_v13.py"))
        ]
        if command_name == "recompute-outcomes"
        else [],
    )
    monkeypatch.setattr(auto_actualizar, "build_observed_steps", lambda command_name: [])
    monkeypatch.setattr(auto_actualizar, "build_legacy_ml_steps", lambda command_name: [])
    monkeypatch.setattr(auto_actualizar, "ejecutar_paso", lambda step_name, command, fecha_base: True)
    monkeypatch.setattr(auto_actualizar, "ensure_minimum_dashboard_history", lambda fecha_base: True)
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


def test_ejecutar_pipeline_diario_treats_observed_and_legacy_steps_as_optional(monkeypatch) -> None:
    operational = SimpleNamespace(
        active_scanner=Path("scanner_activo.py"),
        active_learning=Path("aprendizaje_v13.py"),
        active_version="V13",
        observed_versions=[12],
        observed_learning_chain=[Path("observado_v12.py")],
    )
    calls: dict[str, list[str] | int] = {
        "required": [],
        "optional": [],
        "validate": 0,
    }

    monkeypatch.setattr(auto_actualizar, "resolve_operational_scanner_context", lambda: operational)
    monkeypatch.setattr(
        auto_actualizar,
        "build_learning_steps",
        lambda command_name: [
            ("outcomes_v13", Path("aprendizaje_v13.py"))
        ]
        if command_name == "recompute-outcomes"
        else [],
    )
    monkeypatch.setattr(
        auto_actualizar,
        "build_observed_steps",
        lambda command_name: [
            (
                "observado_v12"
                if command_name == "run"
                else "resumen_observado_v12"
                if command_name == "daily-summary"
                else "outcomes_observado_v12",
                Path("observado_v12.py"),
            )
        ],
    )
    monkeypatch.setattr(
        auto_actualizar,
        "build_legacy_ml_steps",
        lambda command_name: [
            (
                "legacy_ml_v39full"
                if command_name == "run"
                else "resumen_legacy_ml_v39full"
                if command_name == "daily-summary"
                else "outcomes_legacy_ml_v39full",
                Path("legacy_ml_v39full.py"),
            )
        ],
    )
    monkeypatch.setattr(
        auto_actualizar,
        "ejecutar_paso",
        lambda step_name, command, fecha_base: calls["required"].append(step_name) or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "ejecutar_paso_opcional",
        lambda step_name, command, fecha_base, timeout_seconds=None: calls["optional"].append(step_name) or False,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "ensure_minimum_dashboard_history",
        lambda fecha_base: calls["required"].append("ensure_history") or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "validate_model_snapshot_freshness",
        lambda fecha_base: calls.__setitem__("validate", int(calls["validate"]) + 1) or True,
    )

    ok = auto_actualizar.ejecutar_pipeline_diario(
        date(2026, 4, 24),
        datetime(2026, 4, 24, 22, 0),
        skip_dashboard_refresh=False,
    )

    assert ok is True
    assert calls["required"] == [
        "validacion",
        "scanner",
        "ensure_history",
        "outcomes_v13",
        "gestor",
        "dashboard_maquina",
        "dashboard_integrity",
    ]
    assert calls["optional"] == [
        "observado_v12",
        "resumen_observado_v12",
        "legacy_ml_v39full",
        "resumen_legacy_ml_v39full",
        "outcomes_observado_v12",
        "outcomes_legacy_ml_v39full",
        "auditoria_centinela",
    ]
    assert calls["validate"] == 1


def test_main_skip_dashboard_refresh_short_circuits_pipeline_when_snapshots_look_current(monkeypatch) -> None:
    latest_after = date(2026, 4, 24)
    pipeline_call: dict[str, object] = {}
    publication_called = {"value": False}
    repaired_invalid_call: dict[str, date] = {}
    repaired_bounds_call: dict[str, str] = {}

    class FakeTitanDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_market_data_status(self):
            return {
                "latest_prices_date": latest_after.isoformat(),
                "market_data_updated_at": "2026-04-24T22:00:00",
            }

        def save_market_data_update(self, _value):
            raise AssertionError("No deberia reconciliar metadata cuando ya esta al dia.")

        def repair_ohlcv_bounds(self, *, start_date, end_date):
            repaired_bounds_call["start_date"] = start_date
            repaired_bounds_call["end_date"] = end_date
            return 1

    monkeypatch.setattr(auto_actualizar, "require_cloud_database_runtime", lambda: None)
    monkeypatch.setattr(auto_actualizar, "runtime_backend_name", lambda: "postgres")
    monkeypatch.setattr(auto_actualizar, "runtime_sqlite_path", lambda: None)
    monkeypatch.setattr(auto_actualizar, "fecha_objetivo_mercado", lambda now: latest_after)
    monkeypatch.setattr(auto_actualizar, "get_ultima_fecha_db", lambda: latest_after)
    monkeypatch.setattr(auto_actualizar, "dias_bursatiles_faltantes", lambda ultima, objetivo: 0)
    monkeypatch.setattr(
        auto_actualizar,
        "debe_correr_pipeline",
        lambda now, faltantes, force_pipeline=False: True,
    )
    monkeypatch.setattr(auto_actualizar, "TitanDB", FakeTitanDB)
    monkeypatch.setattr(
        auto_actualizar,
        "repair_recent_invalid_ohlcv_rows",
        lambda fecha_base: repaired_invalid_call.__setitem__("fecha_base", fecha_base) or 1,
    )
    monkeypatch.setattr(auto_actualizar, "monitored_snapshots_already_current", lambda fecha_base: True)
    monkeypatch.setattr(
        auto_actualizar,
        "ejecutar_pipeline_diario",
        lambda fecha_base, now, skip_dashboard_refresh=False: pipeline_call.update(
            {
                "fecha_base": fecha_base,
                "now": now,
                "skip_dashboard_refresh": skip_dashboard_refresh,
            }
        ) or True,
    )
    monkeypatch.setattr(
        auto_actualizar,
        "ejecutar_publicacion_liviana",
        lambda fecha_base: publication_called.__setitem__("value", True) or True,
    )
    monkeypatch.setattr(auto_actualizar.sys, "argv", ["auto_actualizar.py", "--skip-dashboard-refresh"])

    rc = auto_actualizar.main()

    assert rc == 0
    assert publication_called["value"] is False
    assert pipeline_call == {}
    assert repaired_invalid_call == {}
    assert repaired_bounds_call == {}
