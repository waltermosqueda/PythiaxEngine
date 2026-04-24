from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from herramientas.dashboard_paths import SNAPSHOT_PATH
from infra.db.base import Base
from infra.db.models import PipelineRun
from infra.publish.dashboard_site import SITE_MANIFEST_NAME
from infra.publish.record_pages_publish import record_github_pages_publish


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-pages-publish-ledger" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_record_github_pages_publish_persists_success() -> None:
    tmp_dir = make_workspace_tmp_dir()
    site_dir = tmp_dir / "site"
    site_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_dir / "publish.db"
    database_url = f"sqlite:///{db_path.resolve().as_posix()}"
    engine = create_engine(database_url, future=True)
    try:
        Base.metadata.create_all(engine)
        (site_dir / SITE_MANIFEST_NAME).write_text(
            json.dumps(
                {
                    "generated_at": "2026-04-23T04:24:30+00:00",
                    "entrypoint": "index.html",
                    "entrypoint_source": "preview_c1_pro.html",
                    "source_manifest_name": "tablero_maquina_pensante_artifact_manifest.json",
                    "source_artifact_count": 5,
                    "build": {
                        "build_source": "github_actions",
                        "db_backend": "postgresql",
                        "run_id": "5555",
                        "pipeline_run_id": "dashboard_build-5555-attempt-1",
                        "run_attempt": "1",
                    },
                    "published_files": ["index.html", SNAPSHOT_PATH.name],
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (site_dir / SNAPSHOT_PATH.name).write_text(
            json.dumps(
                {
                    "operational_context": {"active_version": 13, "reference_version": 12},
                    "integrity": {"latest_market_date": "2026-04-22"},
                }
            )
            + "\n",
            encoding="utf-8",
        )

        payload = record_github_pages_publish(
            site_dir=site_dir,
            page_url="https://waltermosqueda.github.io/PythiaxEngine/",
            database_url=database_url,
        )

        with Session(engine) as session:
            row = session.scalar(select(PipelineRun).where(PipelineRun.run_id == payload["run_id"]))

        assert payload["persisted"] is True
        assert row is not None
        assert row.pipeline_name == "github_pages_publish"
        assert row.status == "SUCCESS"
        assert row.db_backend == "postgresql"
        assert row.active_scanner_version == "13"
        assert row.latest_prices_date.isoformat() == "2026-04-22"
        assert row.metadata_json["page_url"] == "https://waltermosqueda.github.io/PythiaxEngine/"
        assert row.metadata_json["dashboard_pipeline_run_id"] == "dashboard_build-5555-attempt-1"
        assert SNAPSHOT_PATH.name in row.artifact_manifest["published_files"]
    finally:
        engine.dispose()
        shutil.rmtree(tmp_dir, ignore_errors=True)
