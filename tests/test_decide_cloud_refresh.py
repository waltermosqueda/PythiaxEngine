from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from infra.db.base import Base
from infra.cloud.decide_cloud_refresh import decide_cloud_refresh
from infra.db.pipeline_runs import start_pipeline_run
from infra.db.session import create_db_engine
from titan_system.core.database import TitanDB

import infra.db.models  # noqa: F401


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-decide-cloud-refresh" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def ensure_pipeline_runs_schema(database_url: str) -> None:
    engine = create_db_engine(database_url=database_url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def test_decide_cloud_refresh_is_true_when_market_date_exceeds_last_publish() -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "cloud-refresh.db"
    database_url = sqlite_url(db_path)
    try:
        with TitanDB(db_path=str(db_path)) as db:
            db.save_market_data_update("2026-04-24", updated_at="2026-04-24 20:00:00")

        ensure_pipeline_runs_schema(database_url)
        recorder = start_pipeline_run(
            "github_pages_publish",
            database_url=database_url,
            run_date="2026-04-23",
            active_scanner_version="13",
        )
        recorder.finish(
            status="SUCCESS",
            run_date="2026-04-23",
            latest_prices_date="2026-04-23",
            warnings_count=0,
        )

        payload = decide_cloud_refresh(database_url=database_url)

        assert payload["latest_prices_date"] == "2026-04-24"
        assert payload["last_publish_market_date"] == "2026-04-23"
        assert payload["should_refresh"] is True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_decide_cloud_refresh_can_skip_when_publish_is_current() -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "cloud-refresh-skip.db"
    database_url = sqlite_url(db_path)
    try:
        with TitanDB(db_path=str(db_path)) as db:
            db.save_market_data_update("2026-04-24", updated_at="2026-04-24 20:00:00")

        ensure_pipeline_runs_schema(database_url)
        recorder = start_pipeline_run(
            "github_pages_publish",
            database_url=database_url,
            run_date="2026-04-24",
            active_scanner_version="13",
        )
        recorder.finish(
            status="SUCCESS",
            run_date="2026-04-24",
            latest_prices_date="2026-04-24",
            warnings_count=0,
        )

        payload = decide_cloud_refresh(database_url=database_url)
        forced = decide_cloud_refresh(database_url=database_url, force=True)

        assert payload["should_refresh"] is False
        assert forced["should_refresh"] is True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
