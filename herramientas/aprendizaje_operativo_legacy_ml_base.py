#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import contextlib
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import sys
from types import ModuleType
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import herramientas.aprendizaje_operativo_v11 as base_v11
from herramientas.legacy_ml_cloud_specs import (
    REPO_STRATEGIES_SOURCE_PATH,
    cloud_universe_for_model,
)
from titan_system.core.data_loader import get_sector
from titan_system.core.database import TitanDB
from titan_system.models.strategies import (
    StrategyBrainV11,
    StrategyBrainV11Opt,
    StrategyV22,
    StrategyV37,
    StrategyV39Full,
    StrategyV94,
    StrategyV97,
    StrategyV102,
)


os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 1))
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

try:
    from joblib.externals.loky.backend import context as loky_context

    def _safe_count_physical_cores() -> tuple[int, None]:
        return (os.cpu_count() or 1, None)

    loky_context._count_physical_cores = _safe_count_physical_cores
except Exception:
    pass


HORIZON_RE = re.compile(r"_D(\d+)$")
CLOUD_BRIDGE_ADAPTERS = {
    "brain_v11",
    "brain_v11_optimized",
    "v22",
    "v37",
    "v39",
    "v39full",
    "v94",
    "v97",
    "v102",
}


@dataclass(frozen=True)
class LegacyMLConfig:
    model_id: str
    label: str
    model_prefix: str
    source_path: str
    learning_file: str
    adapter_kind: str
    signal_code: str
    native_horizon: int
    evaluation_mode: str = "close_on_target"
    max_picks: int = 10
    min_rows: int = 120
    notes: str = ""


@dataclass
class LegacyMLPick:
    ticker: str
    sector: str
    price: float
    score: float
    confidence: float
    signal: str
    rank: int
    meta: dict[str, object]


@dataclass
class LegacyMLSnapshot:
    run_started: datetime
    run_finished: datetime
    analyzed_date: str
    db_last_write: datetime | None
    freshness: str
    regime_label: str
    breadth_pct: float
    picks: list[LegacyMLPick]
    quality_alerts: list[dict[str, object]]
    memory_context: list[str]
    notes: list[str]


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    work = df.copy().rename(
        columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}
    )
    keep = [column for column in ["Open", "High", "Low", "Close", "Volume"] if column in work.columns]
    work = work[keep].copy()
    work.index = pd.to_datetime(work.index)
    work = work.sort_index()
    work["SMA50"] = work["Close"].rolling(50).mean()
    work["RET1"] = work["Close"].pct_change()
    work["INTRADAY"] = work["Close"] / work["Open"] - 1.0
    work["RANGE_PCT"] = work["High"] / work["Low"].replace(0, pd.NA) - 1.0
    work["CORP_ACTION_DAY"] = (
        work["RET1"].abs().fillna(0) >= 0.15
    ) | (
        work["RANGE_PCT"].abs().fillna(0) >= 0.25
    )
    return work


def load_module_from_path(model_id: str, source_path: str) -> ModuleType:
    path = Path(source_path)
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo legacy: {path}")

    module_name = f"_legacy_ml_{model_id}"
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se pudo crear spec para {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def parse_source_assignments(source_path: str) -> dict[str, Any]:
    path = Path(source_path)
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    if not path.exists():
        return {}

    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return {}

    assignments: dict[str, Any] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            assignments[target.id] = ast.literal_eval(node.value)
        except Exception:
            continue
    return assignments


def _source_value(source: Any, attr_name: str) -> Any:
    if isinstance(source, dict):
        return source.get(attr_name)
    return getattr(source, attr_name, None)


def build_runtime_context(config: LegacyMLConfig, learning_path: Path, latest_db_date: str | None) -> dict[str, object]:
    source_path = Path(config.source_path) if config.source_path else None
    if source_path is not None and not source_path.is_absolute():
        source_path = (ROOT / source_path).resolve()
    critical_files = {
        "learning": learning_path.resolve(),
        "auto_actualizar": ROOT / "herramientas" / "auto_actualizar.py",
    }
    if source_path is not None and source_path.exists():
        critical_files["source"] = source_path.resolve()
    file_hashes = {
        name: base_v11.file_sha256(path)
        for name, path in critical_files.items()
        if path.exists()
    }
    fingerprint = hashlib.sha256(
        "|".join(f"{name}:{value}" for name, value in sorted(file_hashes.items())).encode("utf-8")
    ).hexdigest()
    return {
        "source_path": config.source_path,
        "learning_path": str(learning_path.resolve().relative_to(ROOT)),
        "latest_db_date": latest_db_date,
        "cloud_bridge": config.adapter_kind in CLOUD_BRIDGE_ADAPTERS,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "critical_file_hashes": file_hashes,
        "runtime_fingerprint": fingerprint,
    }


def extract_sector_map_from_module(module: Any) -> dict[str, str]:
    sector_map: dict[str, str] = {}
    for attr_name in ["ACTIVOS_MERCADO", "ACTIVOS", "activos"]:
        value = _source_value(module, attr_name)
        if isinstance(value, dict):
            sector_map.update({str(key): str(val) for key, val in value.items()})
    return sector_map


def extract_universe_from_module(module: Any) -> list[str]:
    tickers: list[str] = []
    for attr_name in [
        "ACTIVOS_MERCADO",
        "ACTIVOS",
        "TICKERS",
        "activos",
        "REQUESTED_UNIVERSE",
        "TRADABLE_UNIVERSE",
        "ALL_TICKERS",
        "CONTEXT_TICKERS",
    ]:
        value = _source_value(module, attr_name)
        if isinstance(value, dict):
            tickers.extend(str(key) for key in value.keys())
        elif isinstance(value, (list, tuple, set)):
            tickers.extend(str(item) for item in value)

    requested_universe = _source_value(module, "REQUESTED_UNIVERSE")
    required_event_tickers = _source_value(module, "REQUIRED_EVENT_TICKERS")
    if isinstance(requested_universe, (list, tuple, set)):
        tickers.extend(str(item) for item in requested_universe)
    if isinstance(required_event_tickers, (list, tuple, set)):
        tickers.extend(str(item) for item in required_event_tickers)

    deduped = list(dict.fromkeys(tickers))
    if "SPY" not in deduped:
        deduped.insert(0, "SPY")
    return deduped


class OperationalLearningLegacyML:
    def __init__(self, db: TitanDB, config: LegacyMLConfig):
        self.db = db
        self.config = config
        self.model_prefix = config.model_prefix
        self.model_name = f"{config.model_prefix}_{config.signal_code}_D{config.native_horizon}"
        self.model_version = config.model_id
        self.run_dir = ROOT / "aprendizaje_operativo" / f"{config.model_id}_runs"
        self.report_dir = ROOT / "aprendizaje_operativo" / f"{config.model_id}_reports"
        self.learning_path = ROOT / config.learning_file
        self.source_metadata = parse_source_assignments(config.source_path)
        self.module = None if config.adapter_kind in CLOUD_BRIDGE_ADAPTERS else load_module_from_path(config.model_id, config.source_path)

        self.sector_map = self._discover_sector_map()
        self.requested_universe = self._discover_universe()
        self.histories = self._load_histories(self.requested_universe)
        if "SPY" not in self.histories:
            raise RuntimeError("SPY no esta disponible en titan.db para legacy ML")

        self.spy_dates = self.histories["SPY"].index
        self.date_to_idx = {ts.date().isoformat(): idx for idx, ts in enumerate(self.spy_dates)}
        self.latest_db_date = self.spy_dates[-1].date().isoformat()

        market_status = db.get_market_data_status()
        self.db_last_write = None
        updated_at_text = market_status.get("market_data_updated_at")
        latest_prices_date = market_status.get("latest_prices_date")
        if updated_at_text and latest_prices_date == self.latest_db_date:
            self.db_last_write = datetime.strptime(updated_at_text, "%Y-%m-%d %H:%M:%S")

        # Cache strategy instances across backfill dates — avoids retraining per date.
        # Each strategy trains once on first call; subsequent dates reuse the instance.
        self._strategy_instance_cache: dict[type, Any] = {}

    def _discover_sector_map(self) -> dict[str, str]:
        source = self.module if self.module is not None else self.source_metadata
        return extract_sector_map_from_module(source)

    def _discover_universe(self) -> list[str]:
        bridge_universe = cloud_universe_for_model(self.config.model_id)
        if bridge_universe:
            deduped = list(dict.fromkeys(str(ticker) for ticker in bridge_universe))
            if "SPY" not in deduped:
                deduped.insert(0, "SPY")
            return deduped
        source = self.module if self.module is not None else self.source_metadata
        return extract_universe_from_module(source)

    def _load_histories(self, requested_universe: list[str]) -> dict[str, pd.DataFrame]:
        from datetime import date as _date, timedelta as _timedelta
        # Limit to 500 calendar days (~355 trading days) to reduce Supabase egress in CI.
        # 355 bars >> max lookback of any strategy (StrategyV22: min_rows=252).
        _cutoff = (_date.today() - _timedelta(days=500)).isoformat()
        histories: dict[str, pd.DataFrame] = {}
        for ticker in requested_universe:
            df = self.db.get_prices(ticker, start_date=_cutoff)
            if df.empty:
                continue
            normalized = normalize_ohlcv(df)
            if len(normalized) < max(30, self.config.min_rows // 2):
                continue
            histories[ticker] = normalized
        return histories

    def resolve_as_of(self, requested_date: str | None) -> pd.Timestamp:
        if requested_date is None:
            return self.spy_dates[-1]
        ts = pd.Timestamp(requested_date)
        candidates = self.spy_dates[self.spy_dates <= ts]
        if len(candidates) == 0:
            raise ValueError(f"No hay fechas en DB <= {requested_date}")
        return candidates[-1]

    def trading_day_offset(self, date_text: str, days_forward: int) -> str | None:
        idx = self.date_to_idx.get(date_text)
        if idx is None:
            return None
        target_idx = idx + days_forward
        if target_idx >= len(self.spy_dates):
            return None
        return self.spy_dates[target_idx].date().isoformat()

    def projected_business_day_offset(self, date_text: str, days_forward: int) -> str:
        cursor = pd.Timestamp(date_text).date()
        remaining = days_forward
        while remaining > 0:
            cursor += pd.Timedelta(days=1)
            if cursor.weekday() < 5:
                remaining -= 1
        return cursor.isoformat()

    def resolve_target_date(self, prediction_date: str, days_forward: int) -> str:
        actual = self.trading_day_offset(prediction_date, days_forward)
        if actual is not None:
            return actual
        return self.projected_business_day_offset(prediction_date, days_forward)

    def _sector_for_ticker(self, ticker: str) -> str:
        sector = self.sector_map.get(ticker)
        if sector:
            return sector
        fallback = get_sector(ticker)
        return fallback if fallback else "other"

    def extract_horizon(self, model_name: str) -> int | None:
        match = HORIZON_RE.search(model_name)
        return int(match.group(1)) if match else None

    def _historical_freshness(self, analyzed_date: str) -> str:
        if analyzed_date != self.latest_db_date:
            return "HISTORICA"
        today = datetime.now().date()
        latest_dt = datetime.strptime(analyzed_date, "%Y-%m-%d").date()
        staleness = base_v11.v11.business_days_between(latest_dt, today)
        if staleness <= 1:
            return "AL DIA"
        return f"STALE ({staleness} dias habiles)"

    def _compute_regime(self, as_of_ts: pd.Timestamp) -> dict[str, object]:
        spy = self.histories["SPY"].loc[:as_of_ts]
        close = float(spy["Close"].iloc[-1])
        sma50 = float(spy["SMA50"].iloc[-1]) if pd.notna(spy["SMA50"].iloc[-1]) else None
        vol20 = float(spy["RET1"].rolling(20).std().iloc[-1]) if len(spy) >= 20 else None
        above_sma = sma50 is not None and close > sma50
        low_vol = vol20 is not None and vol20 < 0.022
        return {
            "safe": bool(above_sma and low_vol),
            "above_sma": bool(above_sma),
            "low_vol": bool(low_vol),
            "spy_close": round(close, 4),
            "spy_sma50": round(sma50, 4) if sma50 is not None else None,
            "spy_vol20": round(vol20 * 100.0, 3) if vol20 is not None else None,
        }

    def _compute_breadth_asof(self, as_of_ts: pd.Timestamp) -> float:
        eligible: list[bool] = []
        for ticker, df in self.histories.items():
            if ticker == "SPY":
                continue
            work = df.loc[:as_of_ts]
            if len(work) < 55:
                continue
            price = work["Close"].iloc[-1]
            sma50 = work["SMA50"].iloc[-1]
            if pd.isna(price) or pd.isna(sma50):
                continue
            eligible.append(bool(price > sma50))
        if not eligible:
            return 0.0
        return round(sum(eligible) / len(eligible) * 100, 1)

    def _recent_quality_alerts_asof(self, as_of_ts: pd.Timestamp) -> list[dict[str, object]]:
        alerts: list[dict[str, object]] = []
        for ticker, df in self.histories.items():
            if ticker == "SPY":
                continue
            work = df.loc[:as_of_ts]
            flagged = work[work["CORP_ACTION_DAY"]]
            if flagged.empty:
                continue
            last_idx = flagged.index[-1]
            if (work.index[-1] - last_idx).days > 10:
                continue
            last = flagged.iloc[-1]
            alerts.append(
                {
                    "ticker": ticker,
                    "date": last_idx.date().isoformat(),
                    "ret1": round(float(last["RET1"] * 100.0), 1),
                    "intraday": round(float(last["INTRADAY"] * 100.0), 1),
                    "range_pct": round(float(last["RANGE_PCT"] * 100.0), 1),
                }
            )
        alerts.sort(key=lambda item: item["date"], reverse=True)
        return alerts

    def context_memory_rows(self, regime_label: str, limit: int = 4) -> list[dict[str, object]]:
        df = self.db.execute_raw(
            """
            SELECT
                p.model_name,
                p.regime,
                COUNT(*) AS total,
                AVG(o.hit) * 100.0 AS accuracy_pct,
                AVG(o.actual_return) * 100.0 AS avg_return_pct
            FROM predictions p
            JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ?
            GROUP BY p.model_name, p.regime
            ORDER BY total DESC, accuracy_pct DESC
            """,
            (self.model_name,),
        )
        if df.empty:
            return []
        filtered = df[df["regime"] == regime_label].copy()
        if filtered.empty:
            filtered = df.copy()
        filtered = filtered.head(limit)
        rows: list[dict[str, object]] = []
        for _, row in filtered.iterrows():
            rows.append(
                {
                    "label": str(row["model_name"]).replace(f"{self.model_prefix}_", ""),
                    "regime": str(row["regime"] or "-"),
                    "total": int(row["total"] or 0),
                    "accuracy_pct": round(float(row["accuracy_pct"]), 2) if pd.notna(row["accuracy_pct"]) else 0.0,
                    "avg_return_pct": round(float(row["avg_return_pct"]), 3) if pd.notna(row["avg_return_pct"]) else 0.0,
                }
            )
        return rows

    def _histories_asof(self, as_of_ts: pd.Timestamp, min_rows: int | None = None) -> dict[str, pd.DataFrame]:
        resolved_min_rows = self.config.min_rows if min_rows is None else min_rows
        sliced: dict[str, pd.DataFrame] = {}
        for ticker, df in self.histories.items():
            work = df.loc[:as_of_ts].copy()
            if len(work) < resolved_min_rows:
                continue
            sliced[ticker] = work
        if "SPY" in self.histories and "SPY" not in sliced:
            spy = self.histories["SPY"].loc[:as_of_ts].copy()
            if not spy.empty:
                sliced["SPY"] = spy
        return sliced

    def _build_multiindex_ohlcv(self, histories: dict[str, pd.DataFrame], tickers: list[str]) -> pd.DataFrame:
        frames = {
            ticker: histories[ticker][["Open", "High", "Low", "Close", "Volume"]].copy()
            for ticker in tickers
            if ticker in histories and len(histories[ticker]) >= self.config.min_rows
        }
        return pd.concat(frames, axis=1) if frames else pd.DataFrame()

    def _build_price_volume_panel(
        self,
        histories: dict[str, pd.DataFrame],
        tickers: list[str],
        min_history: int,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        price_frames = {
            ticker: histories[ticker]["Close"].rename(ticker)
            for ticker in tickers
            if ticker in histories and len(histories[ticker]) >= min_history
        }
        volume_frames = {
            ticker: histories[ticker]["Volume"].rename(ticker)
            for ticker in tickers
            if ticker in histories and len(histories[ticker]) >= min_history
        }
        if not price_frames or "SPY" not in histories:
            return pd.DataFrame(), pd.DataFrame(), pd.Series(dtype=float), pd.Series(dtype=float)
        price_df = pd.concat(price_frames.values(), axis=1)
        volume_df = pd.concat(volume_frames.values(), axis=1)
        common = price_df.columns.intersection(volume_df.columns)
        price_df = price_df[common]
        volume_df = volume_df[common]
        valid = price_df.isna().mean() < 0.05
        price_df = price_df.loc[:, valid].ffill()
        volume_df = volume_df.loc[:, valid].ffill().fillna(0)
        market_s = histories["SPY"]["Close"].copy()
        common_dates = price_df.index.intersection(market_s.index)
        price_df = price_df.loc[common_dates]
        volume_df = volume_df.loc[common_dates]
        market_s = market_s.loc[common_dates]
        return price_df, volume_df, market_s, market_s.pct_change()

    def build_snapshot(self, requested_date: str | None = None) -> tuple[LegacyMLSnapshot, dict[str, object]]:
        run_started = datetime.now()
        as_of_ts = self.resolve_as_of(requested_date)
        analyzed_date = as_of_ts.date().isoformat()
        regime_info = self._compute_regime(as_of_ts)
        regime_label = "SEGURO" if regime_info["safe"] else "PELIGRO"
        picks, notes = self.generate_picks(as_of_ts)
        snapshot = LegacyMLSnapshot(
            run_started=run_started,
            run_finished=datetime.now(),
            analyzed_date=analyzed_date,
            db_last_write=self.db_last_write,
            freshness=self._historical_freshness(analyzed_date),
            regime_label=regime_label,
            breadth_pct=float(self._compute_breadth_asof(as_of_ts)),
            picks=picks,
            quality_alerts=self._recent_quality_alerts_asof(as_of_ts),
            memory_context=[
                f"{row['label']} en {row['regime']}: hit {row['accuracy_pct']:.1f}% | avg {row['avg_return_pct']:+.3f}% | n={row['total']}"
                for row in self.context_memory_rows(regime_label)
            ],
            notes=notes,
        )
        return snapshot, regime_info

    def generate_picks(self, as_of_ts: pd.Timestamp) -> tuple[list[LegacyMLPick], list[str]]:
        try:
            if self.config.adapter_kind == "brain_v11":
                return self._run_repo_strategy(
                    as_of_ts,
                    StrategyBrainV11,
                    min_rows=max(self.config.min_rows, 215),
                    signal="BUY",
                    min_confidence=0.60,
                )
            if self.config.adapter_kind == "brain_v11_optimized":
                return self._run_repo_strategy(
                    as_of_ts,
                    StrategyBrainV11Opt,
                    min_rows=max(self.config.min_rows, 215),
                    signal="BUY",
                    min_confidence=0.60,
                )
            if self.config.adapter_kind == "v37":
                return self._run_repo_strategy(
                    as_of_ts,
                    StrategyV37,
                    min_rows=max(self.config.min_rows, 100),
                    signal="SURGE",
                    min_confidence=0.60,
                )
            if self.config.adapter_kind == "v39":
                return self._run_repo_strategy(
                    as_of_ts,
                    StrategyV39Full,
                    min_rows=max(self.config.min_rows, 120),
                    signal="TOP",
                )
            if self.config.adapter_kind == "v39full":
                return self._run_repo_strategy(
                    as_of_ts,
                    StrategyV39Full,
                    min_rows=max(self.config.min_rows, 120),
                    signal="TOP",
                )
            if self.config.adapter_kind == "v97":
                return self._run_repo_strategy(
                    as_of_ts,
                    StrategyV97,
                    min_rows=max(self.config.min_rows, 200),
                    signal="SURGE_WINDOW",
                    min_confidence=0.65,
                )
            if self.config.adapter_kind == "v22":
                return self._run_repo_strategy(
                    as_of_ts,
                    StrategyV22,
                    min_rows=max(self.config.min_rows, 252),
                    signal="BUY",
                )
            if self.config.adapter_kind == "v94":
                return self._run_repo_strategy(
                    as_of_ts,
                    StrategyV94,
                    min_rows=max(self.config.min_rows, 120),
                    signal="BUY",
                )
            if self.config.adapter_kind == "v102":
                return self._run_repo_strategy(
                    as_of_ts,
                    StrategyV102,
                    min_rows=max(self.config.min_rows, 220),
                    signal="EVENT",
                )
            if self.config.adapter_kind == "brain_v9":
                return self._run_v22(as_of_ts)
        except Exception as exc:
            return [], [f"ERROR adapter {self.config.adapter_kind}: {type(exc).__name__}: {exc}"]
        return [], [f"Adapter no soportado: {self.config.adapter_kind}"]

    @staticmethod
    def _force_kwargs(factory: Any, **forced_kwargs: Any) -> Any:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            kwargs.update(forced_kwargs)
            return factory(*args, **kwargs)

        return wrapped

    @staticmethod
    def _pick_field(row: dict[str, Any], *aliases: str, default: Any = None) -> Any:
        for alias in aliases:
            if alias in row:
                return row[alias]
        return default

    def _run_brain_multiclass(self, as_of_ts: pd.Timestamp) -> tuple[list[LegacyMLPick], list[str]]:
        histories = self._histories_asof(as_of_ts, min_rows=210)
        tickers = [ticker for ticker in self.requested_universe if ticker != "SPY"]
        df_raw = self._build_multiindex_ohlcv(histories, tickers)
        if df_raw.empty:
            return [], ["Sin historia suficiente para construir df_raw multiclase."]

        patches: dict[str, object] = {}
        try:
            if self.config.adapter_kind == "brain_v11_optimized":
                def safe_delayed(func: Any) -> Any:
                    def wrapped(*args: Any, **kwargs: Any) -> Any:
                        return lambda: func(*args, **kwargs)

                    return wrapped

                class SafeSequentialParallel:
                    def __init__(self, *args: Any, **kwargs: Any) -> None:
                        self.args = args
                        self.kwargs = kwargs

                    def __call__(self, jobs: Any) -> list[Any]:
                        return [job() for job in jobs]

                for name in ["Parallel", "delayed", "RandomForestClassifier", "ExtraTreesClassifier", "LogisticRegression"]:
                    patches[name] = getattr(self.module, name)
                self.module.Parallel = SafeSequentialParallel
                self.module.delayed = safe_delayed
                self.module.RandomForestClassifier = self._force_kwargs(patches["RandomForestClassifier"], n_jobs=1)
                self.module.ExtraTreesClassifier = self._force_kwargs(patches["ExtraTreesClassifier"], n_jobs=1)
                self.module.LogisticRegression = self._force_kwargs(patches["LogisticRegression"], n_jobs=1)
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    brain = self.module.TradingBrain()
                    brain.entrenar_modelos(df_raw)
                    live = brain.predecir_hoy(df_raw)
            else:
                brain = self.module.TradingBrain()
                brain.entrenar_modelos(df_raw)
                live = brain.predecir_hoy(df_raw)
        finally:
            for name, original in patches.items():
                setattr(self.module, name, original)
        if live is None or live.empty:
            return [], []

        picks_df = live[(live["signal"] == 2) & (live["ai_confidence"] >= 60.0)].copy()
        if picks_df.empty:
            return [], []

        sort_cols = [column for column in ["ai_confidence", "momento", "adx"] if column in picks_df.columns]
        picks_df = picks_df.sort_values(by=sort_cols, ascending=[False] * len(sort_cols)).head(self.config.max_picks)

        picks: list[LegacyMLPick] = []
        for rank, (_, row) in enumerate(picks_df.iterrows(), start=1):
            ticker = str(row["ticker"])
            meta = {
                key: round(float(row[key]), 4)
                for key in ["rsi", "bb_pos", "macd_hist", "adx", "stoch_k", "sl_pct", "tp1_pct"]
                if key in row and pd.notna(row[key])
            }
            picks.append(
                LegacyMLPick(
                    ticker=ticker,
                    sector=self.sector_map.get(ticker, "N/A"),
                    price=round(float(row["precio"]), 4),
                    score=round(float(row["ai_confidence"]), 4),
                    confidence=max(0.05, min(0.99, float(row["ai_confidence"]) / 100.0)),
                    signal="BUY",
                    rank=rank,
                    meta=meta,
                )
            )
        return picks, []

    def _run_v37(self, as_of_ts: pd.Timestamp) -> tuple[list[LegacyMLPick], list[str]]:
        histories = self._histories_asof(as_of_ts, min_rows=100)
        data_dict = {
            ticker: df[["Open", "High", "Low", "Close", "Volume"]].copy()
            for ticker, df in histories.items()
            if ticker != "SPY"
        }
        if not data_dict:
            return [], ["Sin data_dict suficiente para NOVA."]

        brain = self.module.NovaBrain()
        brain.train_model(data_dict)

        results: list[dict[str, object]] = []
        for ticker, df in data_dict.items():
            prob, last_feat = brain.predict_tomorrow(df)
            if prob < 60.0:
                continue
            results.append(
                {
                    "ticker": ticker,
                    "prob": float(prob),
                    "precio": float(df["Close"].iloc[-1]),
                    "vol_z": float(last_feat.vol_zscore),
                    "bb_rank": float(last_feat.bb_squeeze_rank),
                    "close_str": float(last_feat.close_strength),
                }
            )

        results.sort(key=lambda item: float(item["prob"]), reverse=True)
        picks: list[LegacyMLPick] = []
        for rank, row in enumerate(results[: self.config.max_picks], start=1):
            ticker = str(row["ticker"])
            picks.append(
                LegacyMLPick(
                    ticker=ticker,
                    sector=self.sector_map.get(ticker, "N/A"),
                    price=round(float(row["precio"]), 4),
                    score=round(float(row["prob"]), 4),
                    confidence=max(0.05, min(0.99, float(row["prob"]) / 100.0)),
                    signal="SURGE",
                    rank=rank,
                    meta={
                        "vol_z": round(float(row["vol_z"]), 4),
                        "bb_rank": round(float(row["bb_rank"]), 4),
                        "close_strength": round(float(row["close_str"]), 4),
                    },
                )
            )
        return picks, []

    def _run_v39_like(self, as_of_ts: pd.Timestamp) -> tuple[list[LegacyMLPick], list[str]]:
        histories = self._histories_asof(as_of_ts, min_rows=120)
        tickers = list(getattr(self.module, "TICKERS"))
        price_df, volume_df, market_s, market_ret = self._build_price_volume_panel(histories, tickers, min_history=90)
        if price_df.empty or market_s.empty:
            return [], ["Panel price/volume insuficiente para v39."]

        patches = {
            "RandomForestClassifier": getattr(self.module, "RandomForestClassifier"),
            "ExtraTreesClassifier": getattr(self.module, "ExtraTreesClassifier"),
        }
        self.module.RandomForestClassifier = self._force_kwargs(patches["RandomForestClassifier"], n_jobs=1)
        self.module.ExtraTreesClassifier = self._force_kwargs(patches["ExtraTreesClassifier"], n_jobs=1)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                df, feat_cols = self.module.build_features(price_df, volume_df, market_s, market_ret)
                models, scaler, _ = self.module.train_model(df, feat_cols)
        finally:
            for name, original in patches.items():
                setattr(self.module, name, original)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = self.module.predict_today(
                df,
                feat_cols,
                models,
                scaler,
                market_s,
                market_ret,
                top_k=self.config.max_picks,
            )
        if result is None:
            return [], []

        top, today, _, current_regime = result
        today_prices = price_df.loc[today]
        picks: list[LegacyMLPick] = []
        for _, row in top.iterrows():
            ticker = str(row["ticker"])
            picks.append(
                LegacyMLPick(
                    ticker=ticker,
                    sector=self.sector_map.get(ticker, "N/A"),
                    price=round(float(today_prices.get(ticker, 0.0)), 4),
                    score=round(float(row["score"]) * 100.0, 4),
                    confidence=max(0.05, min(0.99, float(row["score"]))),
                    signal="TOP",
                    rank=int(row["rank"]),
                    meta={
                        "score_pct": round(float(row["score_pct"]), 4),
                        "market_regime": str(current_regime),
                    },
                )
            )
        return picks, []

    def _run_v97(self, as_of_ts: pd.Timestamp) -> tuple[list[LegacyMLPick], list[str]]:
        histories = self._histories_asof(as_of_ts, min_rows=200)
        data_dict = {
            ticker: df[["Open", "High", "Low", "Close", "Volume"]].copy()
            for ticker, df in histories.items()
            if ticker != "SPY"
        }
        if not data_dict:
            return [], ["Sin data_dict suficiente para Titan Omega."]

        feat_dict: dict[str, pd.DataFrame] = {}
        for ticker, df in data_dict.items():
            resolved_ticker, feat = self.module.calcular_metricas(ticker, df)
            if feat is not None:
                feat_dict[str(resolved_ticker)] = feat
        if not feat_dict:
            return [], ["No se pudieron calcular metricas Titan Omega."]

        brain = self.module.TitanOmegaBrain()
        if not brain.train(data_dict, feat_dict):
            return [], ["Titan Omega no logro entrenar."]

        results = brain.scan_market(feat_dict, data_dict)
        picks: list[LegacyMLPick] = []
        for rank, row in enumerate(results[: self.config.max_picks], start=1):
            ticker = str(row["ticker"])
            picks.append(
                LegacyMLPick(
                    ticker=ticker,
                    sector=self.sector_map.get(ticker, "N/A"),
                    price=round(float(row["precio"]), 4),
                    score=round(float(row["prob"]), 4),
                    confidence=max(0.05, min(0.99, float(row["prob"]) / 100.0)),
                    signal="SURGE_WINDOW",
                    rank=rank,
                    meta={
                        "vol_z": round(float(row["vol_z"]), 4),
                        "squeeze": round(float(row["squeeze"]), 4),
                        "c2h": round(float(row["c2h"]), 4),
                    },
                )
            )
        return picks, []

    def _run_v22(self, as_of_ts: pd.Timestamp) -> tuple[list[LegacyMLPick], list[str]]:
        histories = self._histories_asof(as_of_ts, min_rows=252)
        if "SPY" not in histories:
            return [], ["SPY faltante para v22."]

        # Weekly brain cache: ISO-week key so we retrain once per week, not every day.
        # This makes backfill ~5x faster while preserving per-day signal generation.
        week_key = as_of_ts.strftime("%G-W%V")  # e.g. "2025-W23"
        cached_brain = getattr(self, "_v22_brain_cache", None)
        use_cached = cached_brain is not None and cached_brain[0] == week_key

        # Save/restore only HAS_XGB/HAS_LGBM flags; do NOT patch n_jobs so the
        # module runs with its native n_jobs=-1 (RF/ET/LR parallelism unchanged).
        # Brain-v9 always runs alone (serial backfill), so n_jobs=-1 is safe.
        patches = {
            "HAS_XGB": getattr(self.module, "HAS_XGB", False),
            "HAS_LGBM": getattr(self.module, "HAS_LGBM", False),
        }
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                engine = self.module.TradingEngine()
                engine.data = {
                    ticker: df[["Open", "High", "Low", "Close", "Volume"]].copy()
                    for ticker, df in histories.items()
                }
                engine.spy_ret = engine.data["SPY"]["Close"].pct_change().fillna(0)
                engine.calcular_features()
                if use_cached:
                    # Reuse last week's trained brain — skip full retraining
                    engine.brain = cached_brain[1]
                else:
                    engine.entrenar_global(verbose=False)
                    self._v22_brain_cache = (week_key, engine.brain)
                signals = engine.generar_senales()
        finally:
            self.module.HAS_XGB = patches["HAS_XGB"]
            self.module.HAS_LGBM = patches["HAS_LGBM"]

        buys = [
            signal for signal in signals
            if signal.get("ticker") != "SPY"
            and self._pick_field(signal, "señal", "seÃ±al") == "BUY"
        ]

        picks: list[LegacyMLPick] = []
        for rank, row in enumerate(buys[: self.config.max_picks], start=1):
            ticker = str(row["ticker"])
            meta = {
                key: row[key]
                for key in ["score", "consenso", "rr", "kelly_pct", "adx", "rsi14", "rsi7", "vol_rel", "bt_sharpe", "bt_wr"]
                if key in row
            }
            picks.append(
                LegacyMLPick(
                    ticker=ticker,
                    sector=self.sector_map.get(ticker, "N/A"),
                    price=round(float(row["precio"]), 4),
                    score=round(float(row.get("score", row.get("confianza", 0.0))), 4),
                    confidence=max(0.05, min(0.99, float(row.get("confianza", 0.0)) / 100.0)),
                    signal="BUY",
                    rank=rank,
                    meta=meta,
                )
            )
        return picks, []

    def _run_repo_strategy(
        self,
        as_of_ts: pd.Timestamp,
        strategy_cls: type[StrategyBrainV11] | type[StrategyBrainV11Opt] | type[StrategyV22] | type[StrategyV37] | type[StrategyV39Full] | type[StrategyV94] | type[StrategyV97] | type[StrategyV102],
        *,
        min_rows: int,
        signal: str,
        min_confidence: float = 0.0,
    ) -> tuple[list[LegacyMLPick], list[str]]:
        histories = self._histories_asof(as_of_ts, min_rows=min_rows)
        if "SPY" not in histories:
            return [], ["SPY faltante para strategy bridge."]

        prices_dict = {
            ticker: df[["Open", "High", "Low", "Close", "Volume"]].copy()
            for ticker, df in histories.items()
        }
        tickers = list(prices_dict.keys())
        # Reuse cached strategy instance to avoid full ML retraining on every backfill date.
        # The model trains on first call; subsequent dates skip training (retrain_every=999).
        if strategy_cls not in self._strategy_instance_cache:
            self._strategy_instance_cache[strategy_cls] = strategy_cls(retrain_every=999)
        strategy = self._strategy_instance_cache[strategy_cls]
        raw_picks = strategy(prices_dict, tickers, as_of_ts.date().isoformat())
        if not raw_picks:
            return [], []

        ranked = sorted(
            raw_picks,
            key=lambda item: (
                float(item.get("score", 0.0)),
                float(item.get("confidence", 0.0)),
                str(item.get("ticker") or ""),
            ),
            reverse=True,
        )

        picks: list[LegacyMLPick] = []
        seen: set[str] = set()
        for row in ranked:
            ticker = str(row.get("ticker") or "").upper()
            if not ticker or ticker == "SPY" or ticker in seen or ticker not in histories:
                continue
            if str(row.get("direction", "UP")).upper() != "UP":
                continue

            confidence = max(0.05, min(0.99, float(row.get("confidence", 0.0))))
            if confidence < min_confidence:
                continue
            seen.add(ticker)
            score = round(float(row.get("score", confidence * 100.0)), 4)
            picks.append(
                LegacyMLPick(
                    ticker=ticker,
                    sector=self._sector_for_ticker(ticker),
                    price=round(float(histories[ticker]["Close"].iloc[-1]), 4),
                    score=score,
                    confidence=confidence,
                    signal=signal,
                    rank=len(picks) + 1,
                    meta={
                        "adapter_kind": self.config.adapter_kind,
                        "strategy_bridge": strategy_cls.__name__,
                    },
                )
            )
            if len(picks) >= self.config.max_picks:
                break
        return picks, []

    def _prediction_rows_from_pick(self, pick: LegacyMLPick, prediction_date: str) -> list[dict[str, Any]]:
        horizon = self.config.native_horizon
        return [
            {
                "model_name": self.model_name,
                "model_version": self.model_version,
                "ticker": pick.ticker,
                "prediction_date": prediction_date,
                "target_date": self.resolve_target_date(prediction_date, horizon),
                "direction": "UP",
                "confidence": max(0.05, min(0.99, float(pick.confidence))),
                "score": round(float(pick.score), 4),
                "regime": None,
                "sector": pick.sector,
            }
        ]

    def _existing_prediction_keys(self, prediction_date: str) -> set[tuple[str, str, str]]:
        rows = self.db.conn.execute(
            """
            SELECT model_name, ticker, target_date
            FROM predictions
            WHERE prediction_date = ? AND model_name = ?
            """,
            (prediction_date, self.model_name),
        ).fetchall()
        return {(str(row[0]), str(row[1]), str(row[2])) for row in rows}

    def prediction_date_exists(self, prediction_date: str) -> bool:
        row = self.db.conn.execute(
            """
            SELECT COUNT(*)
            FROM predictions
            WHERE prediction_date = ? AND model_name = ?
            """,
            (prediction_date, self.model_name),
        ).fetchone()
        return bool(row and int(row[0]) > 0)

    def record_snapshot(self, snapshot: LegacyMLSnapshot, regime_info: dict[str, object]) -> dict[str, int]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._save_snapshot_artifact(snapshot, regime_info)
        existing_keys = self._existing_prediction_keys(snapshot.analyzed_date)
        rows: list[dict[str, Any]] = []
        for pick in snapshot.picks:
            for row in self._prediction_rows_from_pick(pick, snapshot.analyzed_date):
                row["regime"] = snapshot.regime_label
                key = (str(row["model_name"]), str(row["ticker"]), str(row["target_date"]))
                if key in existing_keys:
                    continue
                rows.append(row)
        saved = self.db.save_predictions_bulk(rows) if rows else 0
        return {"saved_predictions": saved, "signals": len(snapshot.picks)}

    def _save_snapshot_artifact(self, snapshot: LegacyMLSnapshot, regime_info: dict[str, object]) -> None:
        artifact = {
            "model_name": self.model_prefix,
            "model_version": self.model_version,
            "label": self.config.label,
            "config_notes": self.config.notes,
            "analyzed_date": snapshot.analyzed_date,
            "prediction_for": self.resolve_target_date(snapshot.analyzed_date, self.config.native_horizon),
            "native_horizon": self.config.native_horizon,
            "evaluation_mode": self.config.evaluation_mode,
            "run_started": snapshot.run_started.isoformat(timespec="seconds"),
            "run_finished": snapshot.run_finished.isoformat(timespec="seconds"),
            "db_last_write": snapshot.db_last_write.isoformat(timespec="seconds") if snapshot.db_last_write else None,
            "freshness": snapshot.freshness,
            "regime_label": snapshot.regime_label,
            "regime_info": regime_info,
            "breadth_pct": snapshot.breadth_pct,
            "quality_alerts": snapshot.quality_alerts,
            "memory_context": snapshot.memory_context,
            "notes": snapshot.notes,
            "picks": [asdict(pick) for pick in snapshot.picks],
            "runtime_context": build_runtime_context(self.config, self.learning_path, self.latest_db_date),
        }
        path = self.run_dir / f"{snapshot.analyzed_date}.json"
        path.write_text(json.dumps(artifact, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        self.db.save_model_run_snapshot(
            model_key=self.config.label,
            model_name=self.model_name,
            model_version=self.model_version,
            role="legacy_ml",
            analyzed_date=snapshot.analyzed_date,
            prediction_for=str(artifact["prediction_for"]),
            freshness=snapshot.freshness,
            regime_label=snapshot.regime_label,
            breadth_pct=snapshot.breadth_pct,
            signal_count=len(snapshot.picks),
            snapshot_payload=artifact,
        )

    # Corporate action guard — mirrors SCANNER/invertir_v13.py RET1 logic.
    # Detects overnight price gaps caused by stock splits/reverse splits by
    # checking close-to-close returns between consecutive days.
    CORP_RETURN_ABS_THRESHOLD = 0.50  # 50%

    def _is_suspect_corporate_action(
        self,
        ticker: str,
        entry_date: str,
        target_date: str,
        raw_return: float,
    ) -> bool:
        if abs(raw_return) <= self.CORP_RETURN_ABS_THRESHOLD:
            return False
        rows = self.db.conn.execute(
            """
            SELECT close
            FROM prices
            WHERE ticker = ? AND date BETWEEN ? AND ?
            ORDER BY date
            """,
            (ticker, entry_date, target_date),
        ).fetchall()
        if not rows:
            return False
        prev_c = None
        for (c,) in rows:
            if c is not None and prev_c is not None and float(prev_c) != 0:
                if abs(float(c) - float(prev_c)) / float(prev_c) > self.CORP_RETURN_ABS_THRESHOLD:
                    return True
            prev_c = c
        return False

    def _window_max_close_return(self, ticker: str, entry_date: str, target_date: str) -> float | None:
        window_df = normalize_ohlcv(self.db.get_prices(ticker, start_date=entry_date, end_date=target_date))
        if window_df.empty or "Close" not in window_df.columns:
            return None

        entry_row = self.db.conn.execute(
            """
            SELECT open, close
            FROM prices
            WHERE ticker = ? AND date = ?
            """,
            (ticker, entry_date),
        ).fetchone()
        if entry_row is None or entry_row[0] in (None, 0):
            return None

        entry_open = float(entry_row[0])
        entry_close_val = entry_row[1]
        # Guard: open == close sugiere barra incompleta (datos pre-cierre o intraday).
        if entry_close_val is not None and abs(entry_open - float(entry_close_val)) < 1e-6:
            return None

        max_close = float(window_df["Close"].max())
        raw_return = (max_close - entry_open) / entry_open
        if self._is_suspect_corporate_action(ticker, entry_date, target_date, raw_return):
            return None
        return raw_return

    def evaluate_due_predictions(
        self,
        max_target_date: str | None = None,
        recompute_existing: bool = False,
    ) -> dict[str, Any]:
        if max_target_date is None:
            max_target_date = self.latest_db_date

        if recompute_existing:
            pending = self.db.conn.execute(
                """
                SELECT p.id, p.model_name, p.ticker, p.direction, p.prediction_date, p.target_date
                FROM predictions p
                WHERE p.model_name = ? AND p.target_date <= ?
                ORDER BY p.target_date, p.id
                """,
                (self.model_name, max_target_date),
            ).fetchall()
            if pending:
                pred_ids = [int(row[0]) for row in pending]
                for i in range(0, len(pred_ids), 500):
                    batch = pred_ids[i : i + 500]
                    placeholders = ",".join("?" * len(batch))
                    self.db.conn.execute(
                        f"DELETE FROM outcomes WHERE prediction_id IN ({placeholders})",
                        batch,
                    )
        else:
            pending = self.db.conn.execute(
                """
                SELECT p.id, p.model_name, p.ticker, p.direction, p.prediction_date, p.target_date
                FROM predictions p
                LEFT JOIN outcomes o ON p.id = o.prediction_id
                WHERE p.model_name = ? AND o.id IS NULL AND p.target_date <= ?
                ORDER BY p.target_date, p.id
                """,
                (self.model_name, max_target_date),
            ).fetchall()

        summary = {
            "evaluated": 0,
            "hits": 0,
            "misses": 0,
            "errors": 0,
            "dates": len({str(row[5]) for row in pending}),
        }
        target_updates: list[tuple[str, int]] = []
        outcome_rows: list[tuple[int, str, float, int]] = []

        if self.config.evaluation_mode == "window_max_close":
            for pred_id, model_name, ticker, predicted_dir, pred_date, stored_target_date in pending:
                pred_date = str(pred_date)
                stored_target_date = str(stored_target_date)
                horizon = self.extract_horizon(str(model_name))
                if horizon is None:
                    summary["errors"] += 1
                    continue

                entry_date = self.trading_day_offset(pred_date, 1)
                actual_target_date = self.trading_day_offset(pred_date, horizon)
                if entry_date is None or actual_target_date is None or actual_target_date > max_target_date:
                    continue

                if stored_target_date != actual_target_date:
                    target_updates.append((actual_target_date, int(pred_id)))

                actual_return = self._window_max_close_return(str(ticker), entry_date, actual_target_date)
                if actual_return is None:
                    summary["errors"] += 1
                    continue

                actual_direction = "UP" if actual_return >= 0 else "DOWN"
                hit = 1 if str(predicted_dir).upper() == actual_direction else 0
                outcome_rows.append((int(pred_id), actual_direction, float(actual_return), hit))
                summary["evaluated"] += 1
                if hit:
                    summary["hits"] += 1
                else:
                    summary["misses"] += 1
        else:
            prepared_rows: list[tuple[int, str, str, str, str]] = []
            tickers_needed: set[str] = set()
            dates_needed: set[str] = set()

            for pred_id, model_name, ticker, predicted_dir, pred_date, stored_target_date in pending:
                pred_date = str(pred_date)
                stored_target_date = str(stored_target_date)
                ticker = str(ticker)
                horizon = self.extract_horizon(str(model_name))
                if horizon is None:
                    summary["errors"] += 1
                    continue

                entry_date = self.trading_day_offset(pred_date, 1)
                actual_target_date = self.trading_day_offset(pred_date, horizon)
                if entry_date is None or actual_target_date is None or actual_target_date > max_target_date:
                    continue

                if stored_target_date != actual_target_date:
                    target_updates.append((actual_target_date, int(pred_id)))

                prepared_rows.append((int(pred_id), str(predicted_dir), ticker, entry_date, actual_target_date))
                tickers_needed.add(ticker)
                dates_needed.add(entry_date)
                dates_needed.add(actual_target_date)

            price_map: dict[tuple[str, str], tuple[object, object]] = {}
            sorted_dates = sorted(dates_needed)
            sorted_tickers = sorted(tickers_needed)
            if sorted_dates and sorted_tickers:
                max_tickers_per_chunk = max(1, 900 - len(sorted_dates))
                date_placeholders = ",".join(["?"] * len(sorted_dates))
                for start in range(0, len(sorted_tickers), max_tickers_per_chunk):
                    ticker_chunk = sorted_tickers[start : start + max_tickers_per_chunk]
                    ticker_placeholders = ",".join(["?"] * len(ticker_chunk))
                    rows = self.db.conn.execute(
                        f"""
                        SELECT ticker, date, open, close
                        FROM prices
                        WHERE ticker IN ({ticker_placeholders}) AND date IN ({date_placeholders})
                        """,
                        (*ticker_chunk, *sorted_dates),
                    ).fetchall()
                    for row_ticker, row_date, row_open, row_close in rows:
                        price_map[(str(row_ticker), str(row_date))] = (row_open, row_close)

            for pred_id, predicted_dir, ticker, entry_date, actual_target_date in prepared_rows:
                entry_row = price_map.get((ticker, entry_date))
                target_row = price_map.get((ticker, actual_target_date))
                entry_open = entry_row[0] if entry_row is not None else None
                entry_close = entry_row[1] if entry_row is not None else None
                target_close = target_row[1] if target_row is not None else None
                if entry_open in (None, 0) or target_close is None:
                    summary["errors"] += 1
                    continue
                # Guard: open == close sugiere barra incompleta (datos pre-cierre o intraday).
                # Dejar la predicción pendiente en lugar de registrar un retorno de 0.0 falso.
                if entry_close is not None and abs(float(entry_open) - float(entry_close)) < 1e-6:
                    summary["errors"] += 1
                    continue

                actual_return = (float(target_close) - float(entry_open)) / float(entry_open)
                if self._is_suspect_corporate_action(ticker, entry_date, actual_target_date, actual_return):
                    summary["errors"] += 1
                    continue
                actual_direction = "UP" if actual_return >= 0 else "DOWN"
                hit = 1 if predicted_dir.upper() == actual_direction else 0
                outcome_rows.append((pred_id, actual_direction, actual_return, hit))
                summary["evaluated"] += 1
                if hit:
                    summary["hits"] += 1
                else:
                    summary["misses"] += 1

        if target_updates:
            self.db.conn.executemany(
                "UPDATE predictions SET target_date = ? WHERE id = ?",
                target_updates,
            )
        if outcome_rows:
            self.db.conn.executemany(
                """
                INSERT OR REPLACE INTO outcomes
                    (prediction_id, actual_direction, actual_return, hit)
                VALUES (?, ?, ?, ?)
                """,
                outcome_rows,
            )

        self.db.conn.commit()
        return summary

    def report(self) -> pd.DataFrame:
        df = self.db.execute_raw(
            """
            SELECT
                p.model_name,
                COUNT(*) AS total_predictions,
                SUM(CASE WHEN o.id IS NOT NULL THEN 1 ELSE 0 END) AS evaluated,
                AVG(o.hit) * 100 AS accuracy_pct,
                AVG(o.actual_return) * 100 AS avg_return_pct,
                AVG(p.confidence) * 100 AS avg_confidence_pct
            FROM predictions p
            LEFT JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ?
            GROUP BY p.model_name
            ORDER BY p.model_name
            """,
            (self.model_name,),
        )
        for column, digits in {
            "accuracy_pct": 2,
            "avg_return_pct": 3,
            "avg_confidence_pct": 2,
        }.items():
            if column in df.columns:
                df[column] = df[column].apply(
                    lambda value, d=digits: round(float(value), d) if pd.notna(value) else None
                )
        return df

    def report_status(self) -> dict[str, Any]:
        row = self.db.conn.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT prediction_date), MIN(prediction_date), MAX(prediction_date)
            FROM predictions
            WHERE model_name = ?
            """,
            (self.model_name,),
        ).fetchone()
        first_prediction_date = row[2]
        last_prediction_date = row[3]
        if hasattr(first_prediction_date, "isoformat"):
            first_prediction_date = first_prediction_date.isoformat()
        if hasattr(last_prediction_date, "isoformat"):
            last_prediction_date = last_prediction_date.isoformat()
        return {
            "predictions_count": int(row[0] or 0),
            "prediction_days": int(row[1] or 0),
            "first_prediction_date": first_prediction_date,
            "last_prediction_date": last_prediction_date,
        }

    def daily_summary_text(self, snapshot: LegacyMLSnapshot) -> str:
        lines = [
            f"{self.config.label} | {snapshot.analyzed_date} | {snapshot.freshness}",
            f"Regimen: {snapshot.regime_label} | breadth {snapshot.breadth_pct:.1f}% | picks {len(snapshot.picks)}",
            f"Target nativo: D{self.config.native_horizon} | evaluacion: {self.config.evaluation_mode}",
        ]
        if snapshot.notes:
            lines.append("Notas:")
            lines.extend([f"  - {note}" for note in snapshot.notes])
        if snapshot.memory_context:
            lines.append("Memoria:")
            lines.extend([f"  - {item}" for item in snapshot.memory_context])
        if snapshot.picks:
            lines.append("Picks:")
            lines.extend(
                [f"  - #{pick.rank:02d} {pick.ticker} | score {pick.score:.2f} | conf {pick.confidence * 100:.1f}%" for pick in snapshot.picks[: self.config.max_picks]]
            )
        else:
            lines.append("Picks: sin senales.")
        return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aprendizaje operativo para legacy ML observado")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Correr el modelo observado en una fecha")
    run_parser.add_argument("--date", help="Fecha a analizar (YYYY-MM-DD)")

    backfill_parser = sub.add_parser("backfill", help="Backfill historico de predicciones")
    backfill_parser.add_argument("--from-date", required=True, help="Fecha inicial (YYYY-MM-DD)")
    backfill_parser.add_argument("--to-date", help="Fecha final (YYYY-MM-DD)")

    report_parser = sub.add_parser("report", help="Reporte acumulado del modelo observado")
    report_parser.add_argument("--status-only", action="store_true", help="Solo mostrar status general")

    summary_parser = sub.add_parser("daily-summary", help="Resumen textual de una fecha")
    summary_parser.add_argument("--date", help="Fecha a analizar (YYYY-MM-DD)")

    recompute_parser = sub.add_parser("recompute-outcomes", help="Recalcular outcomes")
    recompute_parser.add_argument("--to-date", help="Fecha maxima target (YYYY-MM-DD)")

    return parser.parse_args()


def run_single(engine: OperationalLearningLegacyML, requested_date: str | None) -> None:
    snapshot, regime_info = engine.build_snapshot(requested_date)
    counters = engine.record_snapshot(snapshot, regime_info)
    evaluated = engine.evaluate_due_predictions()
    print(f"[{engine.config.label}] {snapshot.analyzed_date} | picks={len(snapshot.picks)} | saved={counters['saved_predictions']}")
    print(json.dumps(evaluated, indent=2))


def run_backfill(engine: OperationalLearningLegacyML, from_date: str, to_date: str | None) -> None:
    start_ts = engine.resolve_as_of(from_date)
    end_ts = engine.resolve_as_of(to_date) if to_date else engine.spy_dates[-1]
    days = [ts for ts in engine.spy_dates if start_ts <= ts <= end_ts]

    saved = 0
    skipped = 0
    for ts in days:
        date_text = ts.date().isoformat()
        if engine.prediction_date_exists(date_text):
            skipped += 1
            continue
        snapshot, regime_info = engine.build_snapshot(date_text)
        counters = engine.record_snapshot(snapshot, regime_info)
        saved += counters["saved_predictions"]
        print(f"[{engine.config.label}] backfill {date_text} | picks={len(snapshot.picks)} | saved={counters['saved_predictions']}")

    evaluated = engine.evaluate_due_predictions(max_target_date=end_ts.date().isoformat())
    print(
        json.dumps(
            {
                "model": engine.config.label,
                "days_processed": len(days),
                "days_skipped_existing": skipped,
                "predictions_saved": saved,
                "evaluation": evaluated,
            },
            indent=2,
        )
    )


def run_report(engine: OperationalLearningLegacyML, status_only: bool) -> None:
    print(json.dumps({"model": engine.config.label, **engine.report_status()}, indent=2, default=str))
    if status_only:
        return
    df = engine.report()
    if df.empty:
        print("Sin predicciones todavia.")
        return
    print(df.to_string(index=False))


def run_daily_summary(engine: OperationalLearningLegacyML, requested_date: str | None) -> None:
    snapshot, _ = engine.build_snapshot(requested_date)
    print(engine.daily_summary_text(snapshot))


def run_recompute_outcomes(engine: OperationalLearningLegacyML, to_date: str | None) -> None:
    evaluated = engine.evaluate_due_predictions(
        max_target_date=to_date or engine.latest_db_date,
        recompute_existing=True,
    )
    print(json.dumps(evaluated, indent=2))


def main_for_config(config: LegacyMLConfig) -> int:
    args = parse_args()
    with TitanDB() as db:
        engine = OperationalLearningLegacyML(db, config)
        if args.command == "run":
            run_single(engine, args.date)
            return 0
        if args.command == "backfill":
            run_backfill(engine, args.from_date, args.to_date)
            return 0
        if args.command == "report":
            run_report(engine, args.status_only)
            return 0
        if args.command == "daily-summary":
            run_daily_summary(engine, args.date)
            return 0
        if args.command == "recompute-outcomes":
            run_recompute_outcomes(engine, args.to_date)
            return 0
    return 1
