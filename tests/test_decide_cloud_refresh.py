from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from infra.cloud.decide_cloud_refresh import decide_cloud_refresh
from infra.db.base import Base
from infra.db.session import create_db_engine


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-decide-cloud-refresh" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_sqlite_db() -> tuple[Path, str]:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "runtime.db"
    database_url = f"sqlite:///{db_path.resolve().as_posix()}"
    engine = create_db_engine(database_url=database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    return tmp_dir, database_url


def test_decide_cloud_refresh_requests_publish_when_snapshots_are_newer_than_last_publish() -> None:
    tmp_dir, database_url = create_sqlite_db()
    engine = create_db_engine(database_url=database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO data_status (key, value) VALUES ('latest_prices_date', '2026-04-24')")
            )
            connection.execute(
                text(
                    """
                    INSERT INTO pipeline_runs (
                        run_id,
                        pipeline_name,
                        status,
                        latest_prices_date,
                        finished_at
                    ) VALUES (
                        'github_pages_publish-1',
                        'github_pages_publish',
                        'SUCCESS',
                        '2026-04-24',
                        '2026-04-24 12:00:00'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO model_run_snapshots (
                        model_key,
                        model_name,
                        analyzed_date,
                        signal_count,
                        snapshot_json,
                        created_at
                    ) VALUES (
                        'V13',
                        'INVERTIR_V13',
                        '2026-04-24',
                        1,
                        '{}',
                        '2026-04-24 13:00:00'
                    )
                    """
                )
            )

        payload = decide_cloud_refresh(database_url=database_url)

        assert payload["snapshot_newer_than_publish"] is True
        assert payload["should_refresh"] is True
    finally:
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_decide_cloud_refresh_skips_when_last_publish_already_covers_current_snapshot() -> None:
    tmp_dir, database_url = create_sqlite_db()
    engine = create_db_engine(database_url=database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO data_status (key, value) VALUES ('latest_prices_date', '2026-04-24')")
            )
            connection.execute(
                text(
                    """
                    INSERT INTO pipeline_runs (
                        run_id,
                        pipeline_name,
                        status,
                        latest_prices_date,
                        finished_at
                    ) VALUES (
                        'github_pages_publish-2',
                        'github_pages_publish',
                        'SUCCESS',
                        '2026-04-24',
                        '2026-04-24 14:00:00'
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO model_run_snapshots (
                        model_key,
                        model_name,
                        analyzed_date,
                        signal_count,
                        snapshot_json,
                        created_at
                    ) VALUES (
                        'V13',
                        'INVERTIR_V13',
                        '2026-04-24',
                        1,
                        '{}',
                        '2026-04-24 13:00:00'
                    )
                    """
                )
            )

        payload = decide_cloud_refresh(database_url=database_url)
        forced = decide_cloud_refresh(database_url=database_url, force=True)

        assert payload["snapshot_newer_than_publish"] is False
        assert payload["should_refresh"] is False
        assert forced["should_refresh"] is True
    finally:
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)
