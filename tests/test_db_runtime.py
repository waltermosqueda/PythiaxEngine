from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from infra.db.config import DEFAULT_SQLITE_PATH, get_sqlite_fallback_path
from infra.db.sqlite_compat import connect_sqlite, get_sqlite_db_path
from titan_system.core.database import TitanDB


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-runtime" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_sqlite_fallback_path_defaults_to_repo_db(monkeypatch) -> None:
    monkeypatch.delenv("SQLITE_FALLBACK_PATH", raising=False)

    assert get_sqlite_fallback_path() == DEFAULT_SQLITE_PATH
    assert get_sqlite_db_path() == DEFAULT_SQLITE_PATH


def test_sqlite_fallback_path_respects_env(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    custom_path = tmp_dir / "runtime" / "custom.db"
    try:
        monkeypatch.setenv("SQLITE_FALLBACK_PATH", str(custom_path))

        assert get_sqlite_fallback_path() == custom_path
        assert get_sqlite_db_path() == custom_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_connect_sqlite_creates_parent_and_supports_row_factory(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    custom_path = tmp_dir / "db" / "runtime.db"
    try:
        monkeypatch.setenv("SQLITE_FALLBACK_PATH", str(custom_path))

        with connect_sqlite(row_factory=True) as con:
            con.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
            con.execute("INSERT INTO sample (value) VALUES (?)", ("ok",))
            row = con.execute("SELECT value FROM sample").fetchone()

        assert custom_path.exists()
        assert row["value"] == "ok"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_titandb_uses_configured_sqlite_fallback(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    custom_path = tmp_dir / "db" / "titandb.db"
    try:
        monkeypatch.setenv("SQLITE_FALLBACK_PATH", str(custom_path))

        with TitanDB() as db:
            resolved_path = Path(db.db_path)
            tables = {
                row[0]
                for row in db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

        assert resolved_path == custom_path
        assert custom_path.exists()
        assert {"prices", "predictions", "outcomes"}.issubset(tables)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
