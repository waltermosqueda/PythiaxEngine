from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from infra.db.config import DEFAULT_SQLITE_PATH, get_sqlite_fallback_path
from infra.db.runtime import RuntimeDB, adapt_qmark_sql, aggregate_distinct_sql
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


def test_adapt_qmark_sql_converts_tuple_params() -> None:
    sql, params = adapt_qmark_sql(
        "SELECT * FROM predictions WHERE model_name = ? AND target_date >= ?",
        ("INVERTIR_V13_D_D10", "2026-04-01"),
    )

    assert sql == "SELECT * FROM predictions WHERE model_name = :p0 AND target_date >= :p1"
    assert params == {"p0": "INVERTIR_V13_D_D10", "p1": "2026-04-01"}


def test_aggregate_distinct_sql_switches_by_backend() -> None:
    assert (
        aggregate_distinct_sql("p.ticker", "tickers_csv", "sqlite")
        == "GROUP_CONCAT(DISTINCT p.ticker) AS tickers_csv"
    )
    assert (
        aggregate_distinct_sql("p.ticker", "tickers_csv", "postgresql")
        == "STRING_AGG(DISTINCT p.ticker, ',') AS tickers_csv"
    )


def test_runtime_db_reads_sqlite_via_database_url(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "db" / "runtime_reader.db"
    try:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.resolve().as_posix()}")

        with TitanDB(db_path=str(db_path)) as db:
            db.conn.execute(
                """
                INSERT INTO predictions
                    (id, model_name, ticker, prediction_date, target_date, direction, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (1, "INVERTIR_V13_D_D10", "AAPL", "2026-04-21", "2026-04-22", "UP", 0.8),
            )
            db.conn.execute(
                """
                INSERT INTO outcomes
                    (id, prediction_id, actual_direction, actual_return, hit)
                VALUES (?, ?, ?, ?, ?)
                """,
                (1, 1, "UP", 0.03, 1),
            )
            db.conn.commit()

        with RuntimeDB() as runtime_db:
            rows = runtime_db.fetchall(
                "SELECT ticker FROM predictions WHERE model_name = ?",
                ("INVERTIR_V13_D_D10",),
            )
            accuracy = runtime_db.get_model_accuracy("INVERTIR_V13_D_D10")
            stats = runtime_db.db_stats()

        assert rows[0][0] == "AAPL"
        assert accuracy["total"] == 1
        assert accuracy["aciertos"] == 1
        assert stats["predictions_count"] == 1
        assert stats["outcomes_count"] == 1
        assert stats["db_size_mb"] is not None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
