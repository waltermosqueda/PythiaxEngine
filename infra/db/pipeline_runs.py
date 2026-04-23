from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import os
from typing import Any

from sqlalchemy import inspect, select
from sqlalchemy.engine import make_url

from infra.db.models import PipelineRun
from infra.db.session import create_session_factory


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def resolve_run_source() -> str:
    return "github_actions" if os.getenv("GITHUB_ACTIONS") == "true" else "local"


def resolve_run_id(pipeline_name: str) -> str:
    value = os.getenv("PYTHIAX_RUN_ID") or os.getenv("GITHUB_RUN_ID")
    if value:
        return str(value)
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{pipeline_name}-{resolve_run_source()}-{stamp}"


def resolve_commit_sha() -> str | None:
    return os.getenv("PYTHIAX_COMMIT_SHA") or os.getenv("GITHUB_SHA")


def resolve_db_backend_name(database_url: str) -> str:
    return make_url(database_url).get_backend_name()


def coerce_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text[:10]).date()


@dataclass
class PipelineRunRecorder:
    pipeline_name: str
    database_url: str
    run_id: str
    run_source: str
    commit_sha: str | None
    persisted: bool = False
    skipped_reason: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        self._session_factory = create_session_factory(database_url=self.database_url)

    def start(
        self,
        *,
        run_date: date | datetime | str | None = None,
        active_scanner_version: str | None = None,
        db_backend: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> "PipelineRunRecorder":
        try:
            with self._session_factory() as session:
                if not inspect(session.bind).has_table(PipelineRun.__tablename__):
                    self.skipped_reason = "pipeline_runs_table_missing"
                    return self
                row = PipelineRun(
                    run_id=self.run_id,
                    pipeline_name=self.pipeline_name,
                    run_date=coerce_date(run_date),
                    status="RUNNING",
                    run_source=self.run_source,
                    commit_sha=self.commit_sha,
                    active_scanner_version=active_scanner_version,
                    db_backend=db_backend,
                    metadata_json=metadata_json,
                )
                session.add(row)
                session.commit()
                self.persisted = True
        except Exception as exc:
            self.skipped_reason = "pipeline_runs_write_error"
            self.error_message = f"{type(exc).__name__}: {exc}"
        return self

    def finish(
        self,
        *,
        status: str,
        run_date: date | datetime | str | None = None,
        active_scanner_version: str | None = None,
        db_backend: str | None = None,
        expected_market_date: date | datetime | str | None = None,
        latest_prices_date: date | datetime | str | None = None,
        rows_inserted: int | None = None,
        warnings_count: int | None = None,
        error_message: str | None = None,
        artifact_manifest: dict[str, Any] | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> "PipelineRunRecorder":
        if not self.persisted:
            return self
        try:
            with self._session_factory() as session:
                row = session.scalar(
                    select(PipelineRun).where(PipelineRun.run_id == self.run_id)
                )
                if row is None:
                    self.persisted = False
                    self.skipped_reason = "pipeline_run_row_missing"
                    return self
                row.status = status
                row.run_date = coerce_date(run_date) or row.run_date
                row.active_scanner_version = active_scanner_version or row.active_scanner_version
                row.db_backend = db_backend or row.db_backend
                row.expected_market_date = coerce_date(expected_market_date) or row.expected_market_date
                row.latest_prices_date = coerce_date(latest_prices_date) or row.latest_prices_date
                row.rows_inserted = rows_inserted
                row.warnings_count = warnings_count
                row.error_message = error_message
                row.artifact_manifest = artifact_manifest
                row.metadata_json = metadata_json
                row.finished_at = utc_now()
                session.commit()
        except Exception as exc:
            self.error_message = f"{type(exc).__name__}: {exc}"
        return self


def start_pipeline_run(
    pipeline_name: str,
    *,
    database_url: str,
    run_id: str | None = None,
    run_source: str | None = None,
    commit_sha: str | None = None,
    run_date: date | datetime | str | None = None,
    active_scanner_version: str | None = None,
    db_backend: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> PipelineRunRecorder:
    recorder = PipelineRunRecorder(
        pipeline_name=pipeline_name,
        database_url=database_url,
        run_id=run_id or resolve_run_id(pipeline_name),
        run_source=run_source or resolve_run_source(),
        commit_sha=commit_sha or resolve_commit_sha(),
    )
    return recorder.start(
        run_date=run_date,
        active_scanner_version=active_scanner_version,
        db_backend=db_backend or resolve_db_backend_name(database_url),
        metadata_json=metadata_json,
    )
