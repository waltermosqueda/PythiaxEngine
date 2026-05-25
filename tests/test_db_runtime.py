from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

import infra.db.config as db_config
from herramientas import aprendizaje_operativo_legacy_ml_base as legacy_ml_base
from infra.db.config import DEFAULT_SQLITE_PATH, get_sqlite_fallback_path
from infra.db.runtime import RuntimeDB, adapt_qmark_sql, aggregate_distinct_sql
from infra.db.sqlite_compat import connect_sqlite, get_sqlite_db_path
from titan_system.core.data_loader import DataLoader
from titan_system.core.database import TitanDB


def make_workspace_tmp_dir() -> Path:
    path = Path(".cache") / "pytest-runtime" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_sqlite_fallback_path_defaults_to_repo_db(monkeypatch) -> None:
    monkeypatch.delenv("SQLITE_FALLBACK_PATH", raising=False)

    assert get_sqlite_fallback_path() == DEFAULT_SQLITE_PATH
    assert get_sqlite_db_path() == DEFAULT_SQLITE_PATH


def test_database_url_requires_explicit_configuration_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PYTHIAX_ENABLE_SQLITE_FALLBACK", raising=False)
    monkeypatch.delenv("SQLITE_FALLBACK_PATH", raising=False)
    monkeypatch.setattr(db_config, "read_env_file", lambda path=db_config.ENV_FILE_PATH: {})

    with pytest.raises(RuntimeError, match="DATABASE_URL no configurada"):
        db_config.get_database_url()


def test_database_url_can_opt_in_to_sqlite_fallback(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    custom_path = tmp_dir / "runtime" / "fallback.db"
    try:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("PYTHIAX_ENABLE_SQLITE_FALLBACK", "1")
        monkeypatch.setenv("SQLITE_FALLBACK_PATH", str(custom_path))
        monkeypatch.setattr(db_config, "read_env_file", lambda path=db_config.ENV_FILE_PATH: {})

        assert db_config.get_database_url() == f"sqlite:///{custom_path.resolve().as_posix()}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_sqlite_fallback_path_respects_env(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    custom_path = tmp_dir / "runtime" / "custom.db"
    try:
        monkeypatch.setenv("SQLITE_FALLBACK_PATH", str(custom_path))

        assert get_sqlite_fallback_path() == custom_path.resolve()
        assert get_sqlite_db_path() == custom_path.resolve()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_sqlite_db_path_prefers_runtime_database_url(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    runtime_path = tmp_dir / "runtime" / "active.db"
    fallback_path = tmp_dir / "fallback" / "fallback.db"
    try:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{runtime_path.resolve().as_posix()}")
        monkeypatch.setenv("SQLITE_FALLBACK_PATH", str(fallback_path))

        assert get_sqlite_fallback_path() == fallback_path.resolve()
        assert get_sqlite_db_path() == runtime_path.resolve()
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


def test_titandb_always_uses_default_sqlite_path(monkeypatch) -> None:
    """TitanDB() sin db_path siempre usa DEFAULT_DB_PATH (local SQLite).
    Ignora DATABASE_URL y SQLITE_FALLBACK_PATH — los precios son siempre locales.
    """
    tmp_dir = make_workspace_tmp_dir()
    custom_path = tmp_dir / "db" / "titandb.db"
    try:
        # Aunque DATABASE_URL y SQLITE_FALLBACK_PATH apunten a otro lugar,
        # TitanDB() debe usar DEFAULT_DB_PATH (titan_system/data/titan.db)
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{custom_path.resolve().as_posix()}")
        monkeypatch.delenv("TITANDB_FORCE_SQLALCHEMY_COMPAT", raising=False)
        monkeypatch.setenv("SQLITE_FALLBACK_PATH", str(custom_path))

        with TitanDB() as db:
            resolved_path = Path(db.db_path)
            tables = {
                row[0]
                for row in db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

        expected_path = Path(TitanDB.DEFAULT_DB_PATH).resolve()
        assert resolved_path == expected_path
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


def test_legacy_ml_recompute_outcomes_updates_targets_and_reuses_prefetched_prices(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "db" / "legacy-ml-recompute.db"
    model_prefix = f"LEGACY_ML_TEST_{uuid4().hex[:8].upper()}"
    model_name = f"{model_prefix}_BUY_D2"
    ticker_up = f"TST_{uuid4().hex[:6].upper()}_UP"
    ticker_down = f"TST_{uuid4().hex[:6].upper()}_DOWN"

    class DummyLegacyMLEngine(legacy_ml_base.OperationalLearningLegacyML):
        def __init__(self, db: TitanDB):
            self.db = db
            self.config = legacy_ml_base.LegacyMLConfig(
                model_id="legacy_ml_test",
                label="ML_TEST",
                model_prefix=model_prefix,
                source_path="titan_system/models/strategies.py",
                learning_file="herramientas/aprendizaje_operativo_legacy_ml_v22.py",
                adapter_kind="v22",
                signal_code="BUY",
                native_horizon=2,
                evaluation_mode="close_on_target",
            )
            self.model_prefix = self.config.model_prefix
            self.model_name = f"{self.config.model_prefix}_{self.config.signal_code}_D{self.config.native_horizon}"
            self.model_version = self.config.model_id
            self.spy_dates = pd.to_datetime(["2026-04-21", "2026-04-22", "2026-04-23", "2026-04-24"])
            self.date_to_idx = {ts.date().isoformat(): idx for idx, ts in enumerate(self.spy_dates)}
            self.latest_db_date = "2026-04-24"

    try:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.resolve().as_posix()}")

        with TitanDB() as db:
            db.conn.executemany(
                """
                INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (ticker_up, "2026-04-22", 100.0, 101.0, 99.0, 101.0, 1000, 101.0),
                    (ticker_up, "2026-04-23", 101.0, 106.0, 100.0, 105.0, 1000, 105.0),
                    (ticker_down, "2026-04-22", 200.0, 201.0, 199.0, 199.0, 1000, 199.0),
                    (ticker_down, "2026-04-23", 199.0, 200.0, 190.0, 190.0, 1000, 190.0),
                ],
            )
            db.conn.executemany(
                """
                INSERT INTO predictions
                    (model_name, ticker, prediction_date, target_date, direction, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (model_name, ticker_up, "2026-04-21", "2026-04-22", "UP", 0.8),
                    (model_name, ticker_down, "2026-04-21", "2026-04-23", "UP", 0.7),
                ],
            )
            db.conn.commit()

            prediction_ids = {
                row[1]: int(row[0])
                for row in db.conn.execute(
                    "SELECT id, ticker FROM predictions WHERE model_name = ? AND ticker IN (?, ?)",
                    (model_name, ticker_up, ticker_down),
                ).fetchall()
            }

            engine = DummyLegacyMLEngine(db)
            summary = engine.evaluate_due_predictions(max_target_date="2026-04-24", recompute_existing=True)

            prediction_rows = db.conn.execute(
                "SELECT id, target_date FROM predictions WHERE id IN (?, ?) ORDER BY id",
                (prediction_ids[ticker_down], prediction_ids[ticker_up]),
            ).fetchall()
            outcome_rows = db.conn.execute(
                "SELECT prediction_id, actual_direction, ROUND(actual_return, 3), hit FROM outcomes WHERE prediction_id IN (?, ?) ORDER BY prediction_id",
                (prediction_ids[ticker_down], prediction_ids[ticker_up]),
            ).fetchall()

        assert summary == {"evaluated": 2, "hits": 1, "misses": 1, "errors": 0, "dates": 2}
        assert [tuple(row) for row in prediction_rows] == [
            (prediction_ids[ticker_up], "2026-04-23"),
            (prediction_ids[ticker_down], "2026-04-23"),
        ]
        assert [tuple(row) for row in outcome_rows] == [
            (prediction_ids[ticker_up], "UP", 0.05, 1),
            (prediction_ids[ticker_down], "DOWN", -0.05, 0),
        ]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_titandb_sqlalchemy_compat_supports_legacy_queries_and_pandas(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "db" / "compat-runtime.db"
    try:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.resolve().as_posix()}")
        monkeypatch.setenv("TITANDB_FORCE_SQLALCHEMY_COMPAT", "1")

        with TitanDB(db_path=str(db_path)) as db:
            assert db.using_sqlalchemy_compat is True

            raw_prices = pd.DataFrame(
                [
                    {
                        "Open": 100.0,
                        "High": 99.0,
                        "Low": 101.0,
                        "Close": 102.0,
                        "Volume": 1000,
                        "Adj Close": 102.0,
                    }
                ],
                index=[pd.Timestamp("2026-04-21")],
            )
            saved_prices = db.save_prices(raw_prices, "AAPL")
            db.conn.execute(
                """
                INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("MSFT", "2026-04-21", 100.0, 99.0, 101.0, 102.0, 1000, 102.0),
            )
            db.conn.commit()
            repaired = db.repair_ohlcv_bounds(start_date="2026-04-21", end_date="2026-04-21")

            prediction_id = db.save_prediction(
                model_name="INVERTIR_V13_D_D10",
                ticker="AAPL",
                prediction_date="2026-04-21",
                target_date="2026-04-22",
                direction="UP",
                confidence=0.81,
                score=1.7,
                regime="SEGURO",
                sector="Tech",
            )
            db.conn.execute(
                """
                INSERT OR REPLACE INTO outcomes
                    (prediction_id, actual_direction, actual_return, hit)
                VALUES (?, ?, ?, ?)
                """,
                (prediction_id, "UP", 0.031, 1),
            )
            db.conn.execute(
                """
                INSERT OR REPLACE INTO data_status (key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                ("latest_prices_date", "2026-04-21", "2026-04-21 20:00:00"),
            )
            db.conn.commit()

            row = db.conn.execute(
                "SELECT high, low FROM prices WHERE ticker = ? AND date = ?",
                ("MSFT", "2026-04-21"),
            ).fetchone()
            status = db.get_market_data_status()
            predictions = db.get_predictions(model_name="INVERTIR_V13_D_D10")
            raw_df = db.execute_raw(
                "SELECT ticker, confidence FROM predictions WHERE model_name = ?",
                ("INVERTIR_V13_D_D10",),
            )

        assert saved_prices == 1
        assert repaired == 1
        assert prediction_id > 0
        assert round(float(row[0]), 2) == 102.0
        assert round(float(row[1]), 2) == 100.0
        assert status["latest_prices_date"] == "2026-04-21"
        assert predictions.iloc[0]["ticker"] == "AAPL"
        assert round(float(raw_df.iloc[0]["confidence"]), 2) == 0.81
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_data_loader_refresh_recent_invalid_rows_redownloads_bad_latest_bar(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "db" / "invalid-refresh.db"
    try:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.resolve().as_posix()}")
        monkeypatch.setenv("TITANDB_FORCE_SQLALCHEMY_COMPAT", "1")

        with TitanDB(db_path=str(db_path)) as db:
            db.conn.execute(
                """
                INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                ("VIX", "2026-04-28", 0.0, 17.83, 0.0, 17.83, 0, 17.83),
            )
            db.conn.commit()

            loader = DataLoader(db, years_history=2, max_workers=1)
            captured: dict[str, str] = {}

            def fake_download_one(ticker, force_full=False, latest_date=None, end_date=None):
                captured["ticker"] = ticker
                captured["latest_date"] = latest_date
                captured["end_date"] = end_date
                refreshed = pd.DataFrame(
                    [
                        {
                            "Open": 18.30,
                            "High": 19.43,
                            "Low": 17.78,
                            "Close": 17.83,
                            "Volume": 0,
                            "Adj Close": 17.83,
                        }
                    ],
                    index=[pd.Timestamp("2026-04-28")],
                )
                return ticker, refreshed, "ok", None

            monkeypatch.setattr(loader, "_download_one", fake_download_one)

            refresh_stats = loader.refresh_recent_invalid_rows(end_date="2026-04-28")
            row = db.conn.execute(
                "SELECT open, high, low, close, volume FROM prices WHERE ticker = ? AND date = ?",
                ("VIX", "2026-04-28"),
            ).fetchone()

        assert captured == {
            "ticker": "VIX",
            "latest_date": "2026-04-27",
            "end_date": "2026-04-28",
        }
        assert refresh_stats["invalid_rows"] == 1
        assert refresh_stats["refetched_rows"] == 1
        assert refresh_stats["refreshed_tickers"] == ["VIX"]
        assert refresh_stats["remaining_rows"] == 0
        assert refresh_stats["remaining_tickers"] == []
        assert round(float(row[0]), 2) == 18.30
        assert round(float(row[1]), 2) == 19.43
        assert round(float(row[2]), 2) == 17.78
        assert round(float(row[3]), 2) == 17.83
        assert int(row[4]) == 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_data_loader_refresh_recent_invalid_rows_parallelizes_refetch_across_tickers(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "db" / "invalid-refresh-parallel.db"
    try:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.resolve().as_posix()}")
        monkeypatch.setenv("TITANDB_FORCE_SQLALCHEMY_COMPAT", "1")

        with TitanDB(db_path=str(db_path)) as db:
            db.conn.executemany(
                """
                INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("AAPL", "2026-04-28", 0.0, 101.0, 0.0, 100.0, 1000, 100.0),
                    ("MSFT", "2026-04-28", 0.0, 201.0, 0.0, 200.0, 2000, 200.0),
                ],
            )
            db.conn.commit()

            loader = DataLoader(db, years_history=2, max_workers=2)
            barrier = threading.Barrier(2, timeout=1)
            started: list[str] = []

            def fake_download_one(ticker, force_full=False, latest_date=None, end_date=None):
                started.append(ticker)
                barrier.wait()
                base_price = 110.0 if ticker == "AAPL" else 210.0
                refreshed = pd.DataFrame(
                    [
                        {
                            "Open": base_price,
                            "High": base_price + 1.0,
                            "Low": base_price - 1.0,
                            "Close": base_price + 0.5,
                            "Volume": 1000,
                            "Adj Close": base_price + 0.5,
                        }
                    ],
                    index=[pd.Timestamp("2026-04-28")],
                )
                return ticker, refreshed, "ok", None

            monkeypatch.setattr(loader, "_download_one", fake_download_one)

            refresh_stats = loader.refresh_recent_invalid_rows(end_date="2026-04-28")
            rows = db.conn.execute(
                "SELECT ticker, open, close FROM prices WHERE date = ? ORDER BY ticker",
                ("2026-04-28",),
            ).fetchall()

        assert sorted(started) == ["AAPL", "MSFT"]
        assert refresh_stats["invalid_rows"] == 2
        assert refresh_stats["refetched_rows"] == 2
        assert refresh_stats["refreshed_tickers"] == ["AAPL", "MSFT"]
        assert refresh_stats["remaining_rows"] == 0
        assert refresh_stats["remaining_tickers"] == []
        assert refresh_stats["errors"] == []
        assert refresh_stats["workers_used"] == 2
        assert refresh_stats["elapsed_seconds"] >= 0
        assert [row[0] for row in rows] == ["AAPL", "MSFT"]
        assert round(float(rows[0][1]), 2) == 110.0
        assert round(float(rows[1][1]), 2) == 210.0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_data_loader_download_one_fails_fast_when_history_call_hangs(monkeypatch) -> None:
    tmp_dir = make_workspace_tmp_dir()
    db_path = tmp_dir / "db" / "download-timeout.db"
    try:
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.resolve().as_posix()}")
        monkeypatch.setenv("TITANDB_FORCE_SQLALCHEMY_COMPAT", "1")

        with TitanDB(db_path=str(db_path)) as db:
            loader = DataLoader(db, years_history=2, max_workers=1, max_retries=2, retry_sleep=0)
            timeout_values: list[float] = []

            def fake_run(*args, **kwargs):
                timeout_values.append(kwargs["timeout"])
                raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

            monkeypatch.setattr("titan_system.core.data_loader.subprocess.run", fake_run)

            ticker, df, status, detail = loader._download_one(
                "XLE",
                force_full=False,
                latest_date=None,
                end_date="2026-04-29",
            )

        assert ticker == "XLE"
        assert df is None
        assert status == "error"
        assert "timeout duro" in (detail or "")
        assert timeout_values == [45, 45]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
