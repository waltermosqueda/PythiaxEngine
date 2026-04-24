from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from infra.db.base import Base
from infra.db.models import PipelineRun
from infra.db.pipeline_runs import start_pipeline_run


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-pipeline-runs" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_pipeline_run_recorder_persists_successful_dashboard_build() -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "pipeline_runs.db"
    database_url = f"sqlite:///{db_path.resolve().as_posix()}"
    engine = create_engine(database_url, future=True)
    try:
        Base.metadata.create_all(engine)

        recorder = start_pipeline_run(
            "dashboard_build",
            database_url=database_url,
            run_id="dashboard-build-001",
            run_source="github_actions",
            commit_sha="abc123def456",
            run_date="2026-04-23",
            active_scanner_version="13",
            db_backend="sqlite",
        )
        recorder.finish(
            status="SUCCESS",
            run_date="2026-04-23",
            active_scanner_version="13",
            db_backend="sqlite",
            latest_prices_date="2026-04-22",
            warnings_count=0,
            artifact_manifest={"artifact_count": 5},
            metadata_json={"variant": "all"},
        )

        with Session(engine) as session:
            row = session.scalar(select(PipelineRun).where(PipelineRun.run_id == "dashboard-build-001"))

        assert recorder.persisted is True
        assert row is not None
        assert row.status == "SUCCESS"
        assert row.pipeline_name == "dashboard_build"
        assert row.run_source == "github_actions"
        assert row.commit_sha == "abc123def456"
        assert row.active_scanner_version == "13"
        assert row.latest_prices_date.isoformat() == "2026-04-22"
        assert row.artifact_manifest["artifact_count"] == 5
        assert row.metadata_json["variant"] == "all"
        assert row.finished_at is not None
    finally:
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_resolve_run_id_namespaces_ci_run_with_attempt(monkeypatch) -> None:
    from infra.db.pipeline_runs import resolve_run_id

    monkeypatch.setenv("GITHUB_RUN_ID", "777")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "3")
    monkeypatch.delenv("PYTHIAX_RUN_ID", raising=False)
    monkeypatch.delenv("PYTHIAX_RUN_ATTEMPT", raising=False)

    assert resolve_run_id("dashboard_build") == "dashboard_build-777-attempt-3"


def test_pipeline_run_recorder_skips_when_table_is_missing() -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "missing_table.db"
    database_url = f"sqlite:///{db_path.resolve().as_posix()}"
    try:
        recorder = start_pipeline_run(
            "dashboard_build",
            database_url=database_url,
            run_id="dashboard-build-missing",
        )

        assert recorder.persisted is False
        assert recorder.skipped_reason == "pipeline_runs_table_missing"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
