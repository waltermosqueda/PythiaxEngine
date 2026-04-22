from __future__ import annotations

import sqlite3
from pathlib import Path

from infra.db.config import get_sqlite_fallback_path


def get_sqlite_db_path() -> Path:
    return get_sqlite_fallback_path()


def connect_sqlite(
    db_path: str | Path | None = None,
    *,
    row_factory: bool = False,
) -> sqlite3.Connection:
    resolved_path = Path(db_path) if db_path is not None else get_sqlite_db_path()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(resolved_path))
    if row_factory:
        connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection
