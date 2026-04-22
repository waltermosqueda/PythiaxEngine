"""Database scaffolding for the Postgres migration path."""

from infra.db.config import get_database_url, get_sqlite_fallback_path
from infra.db.sqlite_compat import connect_sqlite, get_sqlite_db_path

__all__ = [
    "connect_sqlite",
    "get_database_url",
    "get_sqlite_db_path",
    "get_sqlite_fallback_path",
]
