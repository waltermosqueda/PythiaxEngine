"""Database scaffolding for the Postgres migration path."""

from infra.db.bootstrap_target import bootstrap_target_from_sqlite
from infra.db.config import get_database_url, get_sqlite_fallback_path
from infra.db.pipeline_runs import PipelineRunRecorder, start_pipeline_run
from infra.db.runtime import (
    RuntimeDB,
    adapt_qmark_sql,
    aggregate_distinct_sql,
    connect_runtime_db,
    get_runtime_database_url,
    resolve_runtime_backend,
)
from infra.db.sqlite_compat import connect_sqlite, get_sqlite_db_path

__all__ = [
    "adapt_qmark_sql",
    "aggregate_distinct_sql",
    "bootstrap_target_from_sqlite",
    "connect_sqlite",
    "connect_runtime_db",
    "get_database_url",
    "get_runtime_database_url",
    "get_sqlite_db_path",
    "get_sqlite_fallback_path",
    "PipelineRunRecorder",
    "resolve_runtime_backend",
    "RuntimeDB",
    "start_pipeline_run",
]
