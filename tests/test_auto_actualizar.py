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
        "sync_target_incremental_core",
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


def test_cloud_target_database_url_prefers_explicit_target_env(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/runner.db")
    monkeypatch.setenv("PYTHIAX_TARGET_DATABASE_URL", "postgresql://user:pass@host/dbname")

    assert auto_actualizar.cloud_target_database_url() == "postgresql+psycopg://user:pass@host/dbname"


def test_sync_target_incremental_uses_explicit_cloud_target_when_runtime_is_sqlite(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/runner.db")
    monkeypatch.setenv("PYTHIAX_TARGET_DATABASE_URL", "postgresql://user:pass@host/dbname")

    def fake_optional(step_name, command, fecha_base, timeout_seconds=None):
        captured["step_name"] = step_name
        captured["command"] = command
        captured["fecha_base"] = fecha_base
        captured["timeout_seconds"] = timeout_seconds
        return True

    monkeypatch.setattr(auto_actualizar, "ejecutar_paso_opcional", fake_optional)

    observed_failures: list[str] = []
    auto_actualizar.sync_target_incremental(
        "sync_target_incremental_core",
        date(2026, 4, 24),
        observed_failures,
    )

    assert observed_failures == []
    assert captured["step_name"] == "sync_target_incremental_core"
    assert "--target-url" in captured["command"]
    assert "postgresql+psycopg://user:pass@host/dbname" in captured["command"]
    assert "--report-path" in captured["command"]
    assert captured["timeout_seconds"] == 30 * 60
