"""
AUDITORIA ML_TRADING_V102 - PURGED CV / EMBARGO
===============================================

Objetivo:
  Someter `Machine Winners/ml_trading_v102.py` a una validacion temporal mas dura
  antes de considerar que su ML merece volver a tener peso en el proyecto Claude.

Enfoque:
  1. Reutilizar la logica real de features y scoring de `v102`
  2. Construir el dataset desde `titan.db`
  3. Auditar con:
     - recent check original del script
     - recent check seguro (sin reference leakage)
     - purged k-fold con embargo
     - purged expanding walk-forward
  4. Comparar contra baselines simples nacidos del mismo stack de features

Fecha:
  2026-04-08
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "titan_system" / "data" / "titan.db"
SOURCE_PATH = ROOT.parent / "Machine Winners" / "ml_trading_v102.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.purged_cv_utils import build_purged_expanding_splits, build_purged_kfold_splits

TOP_K = 18
FAST_MODE = False
KFOLD_SPLITS = 5
EXPANDING_SPLITS = 5
TEST_DAYS = 20
PURGE_DAYS = 1
EMBARGO_DAYS = 1
MIN_TRAIN_DAYS = 220


def load_v102_module():
    spec = importlib.util.spec_from_file_location("ml_trading_v102_audit", SOURCE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SafeEventAwarePopPredictor:
    """
    Wrapper de auditoria:
    - reutiliza la arquitectura real de V102
    - hace visible cualquier error de fit en workers
    - evita dejar modelos sin entrenar por excepciones silenciosas
    """

    def __init__(self, module, fast_mode: bool = False) -> None:
        self.module = module
        self.inner = module.EventAwarePopPredictor(fast_mode=fast_mode)
        for attr in ("close_model", "high_reg", "close_reg"):
            model = getattr(self.inner, attr, None)
            if model is not None and hasattr(model, "set_params"):
                model.set_params(n_jobs=1)

    def fit(self, train_frame: pd.DataFrame, feature_cols: list[str], reference_rows: pd.DataFrame):
        self.inner.feature_cols = feature_cols
        base = train_frame.dropna(subset=["target_pop", "target_close", "target_gap"]).copy()
        if base.empty:
            raise RuntimeError("Training frame is empty after target filtering.")

        x_base = base[self.inner.feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        self.inner.scaler.fit(x_base.values)

        fm = self.inner.fast_mode
        pop_train = self.inner._sample_binary(base, "target_pop", max_rows=90_000 if not fm else 50_000, random_state=42)
        close_train = self.inner._sample_binary(base, "target_close", max_rows=70_000 if not fm else 45_000, random_state=43)
        gap_train = self.inner._sample_binary(base, "target_gap", max_rows=70_000 if not fm else 45_000, random_state=44)
        mom_mask = base["setup_momentum"] >= 0.42
        rev_mask = base["setup_reversal"] >= 0.38
        mom_train = self.inner._sample_binary(base, "target_pop", subset_mask=mom_mask, max_rows=60_000 if not fm else 35_000, random_state=45)
        rev_train = self.inner._sample_binary(base, "target_pop", subset_mask=rev_mask, max_rows=60_000 if not fm else 35_000, random_state=46)

        if len(mom_train) < 2_000:
            mom_train = pop_train.copy()
        if len(rev_train) < 2_000:
            rev_train = pop_train.copy()
        if close_train.empty:
            close_train = base.dropna(subset=["target_close"]).copy()
        if gap_train.empty:
            gap_train = base.dropna(subset=["target_gap"]).copy()

        high_rt = self.inner._sample_regression(base, "fwd_high1", max_rows=70_000 if not fm else 45_000, random_state=47)
        close_rt = self.inner._sample_regression(base, "fwd_close_ret1", max_rows=70_000 if not fm else 45_000, random_state=48)
        if high_rt.empty:
            high_rt = base.dropna(subset=["fwd_high1"]).copy()
        if close_rt.empty:
            close_rt = base.dropna(subset=["fwd_close_ret1"]).copy()

        def _x(df: pd.DataFrame):
            num = df[self.inner.feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
            return self.inner.scaler.transform(num.values)

        def _fit_cls(model, df: pd.DataFrame, target_col: str):
            model.fit(_x(df), df[target_col].astype(int).values)

        def _fit_reg(model, df: pd.DataFrame, target_col: str, lo: float, hi: float):
            model.fit(_x(df), df[target_col].clip(lo, hi).values)

        tasks = []
        with ThreadPoolExecutor(max_workers=7) as pool:
            tasks.append(pool.submit(_fit_cls, self.inner.pop_model, pop_train, "target_pop"))
            tasks.append(pool.submit(_fit_cls, self.inner.close_model, close_train, "target_close"))
            tasks.append(pool.submit(_fit_cls, self.inner.gap_model, gap_train, "target_gap"))
            tasks.append(pool.submit(_fit_cls, self.inner.momentum_model, mom_train, "target_pop"))
            tasks.append(pool.submit(_fit_cls, self.inner.reversal_model, rev_train, "target_pop"))
            tasks.append(pool.submit(_fit_reg, self.inner.high_reg, high_rt, "fwd_high1", -0.30, 0.60))
            tasks.append(pool.submit(_fit_reg, self.inner.close_reg, close_rt, "fwd_close_ret1", -0.30, 0.40))
            for task in tasks:
                task.result()

        self.inner.template_library.fit(reference_rows)
        self.inner.is_fitted = True
        return self

    def score(self, frame: pd.DataFrame, regime: str) -> pd.DataFrame:
        return self.inner.score(frame, regime)


def load_price_dict(required_tickers: list[str]) -> dict[str, pd.DataFrame]:
    tickers = sorted(set(required_tickers))
    placeholders = ",".join("?" for _ in tickers)
    query = f"""
        SELECT
            ticker,
            date,
            open,
            high,
            low,
            close,
            COALESCE(adj_close, close) AS adj_close,
            volume
        FROM prices
        WHERE ticker IN ({placeholders})
        ORDER BY ticker, date
    """

    with sqlite3.connect(DB_PATH) as conn:
        raw = pd.read_sql_query(query, conn, params=tickers, parse_dates=["date"])

    data: dict[str, pd.DataFrame] = {}
    for ticker, frame in raw.groupby("ticker"):
        frame = frame.sort_values("date").copy()
        factor = np.where(frame["close"].abs() > 1e-12, frame["adj_close"] / frame["close"], 1.0)
        out = pd.DataFrame(
            {
                "Open": frame["open"].values * factor,
                "High": frame["high"].values * factor,
                "Low": frame["low"].values * factor,
                "Close": frame["adj_close"].values,
                "Volume": frame["volume"].astype(float).values,
            },
            index=pd.to_datetime(frame["date"]),
        ).sort_index()
        data[ticker] = out

    if "VIX" in data and "^VIX" not in data:
        data["^VIX"] = data["VIX"].copy()
    return data


def build_dataset(module) -> tuple[pd.DataFrame, list[str], pd.DataFrame, dict[str, Any]]:
    tickers = sorted(set(module.TRADABLE_UNIVERSE + module.CONTEXT_TICKERS + ["VIX"]))
    data = load_price_dict(tickers)

    tradable_loaded = [
        ticker for ticker in module.TRADABLE_UNIVERSE
        if ticker in data and len(data[ticker]) >= module.MIN_HISTORY
    ]
    missing_tradable = sorted(set(module.TRADABLE_UNIVERSE) - set(tradable_loaded))

    context_close = {}
    for ticker in module.CONTEXT_TICKERS:
        if ticker in data:
            context_close[ticker] = data[ticker]["Close"]
    if "^VIX" not in context_close and "VIX" in data:
        context_close["^VIX"] = data["VIX"]["Close"]

    regime_frame = module.build_regime_frame(data, tradable_loaded)
    features_by_ticker: dict[str, pd.DataFrame] = {}

    def _build_one(ticker: str):
        return ticker, module.build_ticker_features(ticker, data[ticker], context_close, regime_frame)

    with ThreadPoolExecutor(max_workers=min(os.cpu_count() or 4, 8)) as pool:
        futures = {pool.submit(_build_one, ticker): ticker for ticker in tradable_loaded}
        for future in as_completed(futures):
            ticker, feat = future.result()
            features_by_ticker[ticker] = feat

    module.apply_cross_sectional_features(data, features_by_ticker, tradable_loaded)
    dataset = module.flatten_features(features_by_ticker, tradable_loaded)
    dataset = module.create_targets(dataset)
    feat_cols = module.feature_columns(dataset)
    reference_rows = module.extract_reference_rows(dataset, data)

    meta = {
        "tradable_loaded": tradable_loaded,
        "missing_tradable": missing_tradable,
        "context_loaded": sorted(context_close),
        "reference_rows": len(reference_rows),
    }
    return dataset, feat_cols, reference_rows, meta


def recent_check_safe(module, dataset, feat_cols, reference_rows, top_k: int, fast_mode: bool, n_days: int = 20) -> pd.DataFrame:
    all_dates = sorted(dataset["date"].unique())
    if len(all_dates) <= n_days + 40:
        return pd.DataFrame()

    split_date = all_dates[-n_days]
    train = dataset[dataset["date"] < split_date].copy()
    test_dates = all_dates[-n_days:]
    ref_train = reference_rows[reference_rows["date"] < split_date].copy()
    if train.empty:
        return pd.DataFrame()

    predictor = SafeEventAwarePopPredictor(module, fast_mode=fast_mode)
    predictor.fit(train, feat_cols, ref_train)

    rows = []
    for current_date in test_dates[:-1]:
        frame = dataset[dataset["date"] == current_date].copy()
        if frame.empty:
            continue
        regime_val = float(frame["regime_code"].iloc[0]) if "regime_code" in frame else 0.0
        regime = module.regime_label_from_value(regime_val)
        scored = predictor.score(frame, regime).nlargest(top_k, "final_score")
        picked = set(scored["ticker"])
        base = frame[frame["ticker"].isin(picked)]
        rows.append(
            {
                "date": str(pd.Timestamp(current_date).date()),
                "avg_pop_pct": float(base["fwd_pop1"].mean() * 100.0),
                "avg_close_pct": float(base["fwd_close_ret1"].mean() * 100.0),
                "hit_rate": float((base["target_pop"] == 1).mean()),
            }
        )
    return pd.DataFrame(rows)


def recent_check_legacy_like(module, dataset, feat_cols, reference_rows, top_k: int, fast_mode: bool, n_days: int = 20) -> pd.DataFrame:
    all_dates = sorted(dataset["date"].unique())
    if len(all_dates) <= n_days + 40:
        return pd.DataFrame()

    split_date = all_dates[-n_days]
    train = dataset[dataset["date"] < split_date].copy()
    test_dates = all_dates[-n_days:]
    if train.empty:
        return pd.DataFrame()

    predictor = SafeEventAwarePopPredictor(module, fast_mode=fast_mode)
    predictor.fit(train, feat_cols, reference_rows)

    rows = []
    for current_date in test_dates[:-1]:
        frame = dataset[dataset["date"] == current_date].copy()
        if frame.empty:
            continue
        regime_val = float(frame["regime_code"].iloc[0]) if "regime_code" in frame else 0.0
        regime = module.regime_label_from_value(regime_val)
        scored = predictor.score(frame, regime).nlargest(top_k, "final_score")
        picked = set(scored["ticker"])
        base = frame[frame["ticker"].isin(picked)]
        rows.append(
            {
                "date": str(pd.Timestamp(current_date).date()),
                "avg_pop_pct": float(base["fwd_pop1"].mean() * 100.0),
                "avg_close_pct": float(base["fwd_close_ret1"].mean() * 100.0),
                "hit_rate": float((base["target_pop"] == 1).mean()),
            }
        )
    return pd.DataFrame(rows)


def score_baselines(frame: pd.DataFrame) -> dict[str, pd.Series]:
    baseline: dict[str, pd.Series] = {}
    setup_combo = (
        0.35 * frame["setup_momentum"]
        + 0.25 * frame["setup_reversal"]
        + 0.20 * frame["setup_squeeze"]
        + 0.20 * frame["setup_gap"]
    )
    baseline["setup_combo"] = setup_combo
    baseline["event_combo"] = (
        0.45 * setup_combo
        + 0.20 * frame["cs_ret_5d_rank"]
        + 0.20 * frame["cs_vol_ratio_rank"]
        + 0.15 * frame["close_strength"]
    )
    baseline["momentum_combo"] = (
        0.60 * frame["setup_momentum"]
        + 0.20 * frame["setup_squeeze"]
        + 0.20 * frame["setup_gap"]
    )
    baseline["reversal_combo"] = (
        0.55 * frame["setup_reversal"]
        + 0.25 * frame["cs_vol_ratio_rank"]
        + 0.20 * frame["close_strength"]
    )
    baseline["rev_vol_combo"] = (
        (1.0 - frame["cs_ret_5d_rank"])
        + frame["cs_vol_ratio_rank"]
        + 0.75 * frame["setup_reversal"]
    )
    return baseline


def evaluate_selection(frame: pd.DataFrame, picked: list[str], label: str, fold_name: str, current_date: pd.Timestamp, regime: str) -> dict[str, Any]:
    chosen = frame[frame["ticker"].isin(set(picked))].copy()
    if chosen.empty:
        return {
            "scheme": fold_name,
            "model": label,
            "date": current_date,
            "regime": regime,
            "top_k": 0,
            "hit_rate": np.nan,
            "avg_pop_pct": np.nan,
            "avg_close_pct": np.nan,
            "avg_excess_close_pct": np.nan,
        }

    return {
        "scheme": fold_name,
        "model": label,
        "date": current_date,
        "regime": regime,
        "top_k": len(chosen),
        "hit_rate": float((chosen["target_pop"] == 1).mean()),
        "avg_pop_pct": float(chosen["fwd_pop1"].mean() * 100.0),
        "avg_close_pct": float(chosen["fwd_close_ret1"].mean() * 100.0),
        "avg_excess_close_pct": float((chosen["fwd_close_ret1"].mean() - frame["fwd_close_ret1"].mean()) * 100.0),
    }


def run_fold_scheme(module, dataset, feat_cols, reference_rows, folds, top_k: int, fast_mode: bool, scheme_name: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for fold in folds:
        train = dataset[dataset["date"].isin(fold.train_dates)].copy()
        test = dataset[dataset["date"].isin(fold.test_dates)].copy()
        if train.empty or test.empty:
            continue

        ref_train = reference_rows[reference_rows["date"].isin(fold.train_dates)].copy()
        predictor = SafeEventAwarePopPredictor(module, fast_mode=fast_mode)
        predictor.fit(train, feat_cols, ref_train)

        for current_date in fold.test_dates:
            frame = test[test["date"] == current_date].copy()
            if len(frame) < top_k:
                continue
            regime_val = float(frame["regime_code"].iloc[0]) if "regime_code" in frame else 0.0
            regime = module.regime_label_from_value(regime_val)
            scored = predictor.score(frame, regime)
            picked_ml = scored.nlargest(top_k, "final_score")["ticker"].tolist()
            rows.append(evaluate_selection(frame, picked_ml, "ml_v102", scheme_name, current_date, regime))

            for baseline_name, baseline_score in score_baselines(frame).items():
                picked = (
                    pd.DataFrame({"ticker": frame["ticker"].values, "score": baseline_score.values})
                    .nlargest(top_k, "score")["ticker"]
                    .tolist()
                )
                rows.append(evaluate_selection(frame, picked, baseline_name, scheme_name, current_date, regime))

    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (scheme, model), frame in results.groupby(["scheme", "model"]):
        rows.append(
            {
                "scheme": scheme,
                "model": model,
                "days": len(frame),
                "hit_rate": frame["hit_rate"].mean(),
                "avg_pop_pct": frame["avg_pop_pct"].mean(),
                "avg_close_pct": frame["avg_close_pct"].mean(),
                "avg_excess_close_pct": frame["avg_excess_close_pct"].mean(),
            }
        )
    out = pd.DataFrame(rows)
    return out.sort_values(["scheme", "avg_close_pct", "hit_rate"], ascending=[True, False, False]).reset_index(drop=True)


def print_summary_table(summary: pd.DataFrame, scheme_name: str) -> None:
    subset = summary[summary["scheme"] == scheme_name].copy()
    if subset.empty:
        print(f"\n{scheme_name}: sin resultados")
        return
    print(f"\n{scheme_name}")
    display = subset[["model", "days", "hit_rate", "avg_pop_pct", "avg_close_pct", "avg_excess_close_pct"]].copy()
    display["hit_rate"] = (display["hit_rate"] * 100.0).round(1)
    for col in ["avg_pop_pct", "avg_close_pct", "avg_excess_close_pct"]:
        display[col] = display[col].round(3)
    print(display.to_string(index=False))


def main() -> None:
    module = load_v102_module()
    dataset, feat_cols, reference_rows, meta = build_dataset(module)

    print("AUDITORIA ML_TRADING_V102 - PURGED CV / EMBARGO")
    print(f"Dataset rows={len(dataset):,} | features={len(feat_cols)} | reference_rows={len(reference_rows)}")
    print(
        f"Tradable loaded={len(meta['tradable_loaded'])}/{len(module.TRADABLE_UNIVERSE)} | "
        f"context loaded={len(meta['context_loaded'])}/{len(module.CONTEXT_TICKERS)}"
    )
    if meta["missing_tradable"]:
        print(f"Missing tradable sample: {meta['missing_tradable'][:12]}")

    recent_legacy = recent_check_legacy_like(
        module, dataset, feat_cols, reference_rows, top_k=TOP_K, fast_mode=FAST_MODE, n_days=20
    )
    recent_safe = recent_check_safe(
        module, dataset, feat_cols, reference_rows, top_k=TOP_K, fast_mode=FAST_MODE, n_days=20
    )

    all_dates = sorted(dataset["date"].unique())
    kfolds = build_purged_kfold_splits(
        all_dates,
        n_splits=KFOLD_SPLITS,
        purge_days=PURGE_DAYS,
        embargo_days=EMBARGO_DAYS,
        min_train_days=MIN_TRAIN_DAYS,
    )
    expanding = build_purged_expanding_splits(
        all_dates,
        n_splits=EXPANDING_SPLITS,
        test_days=TEST_DAYS,
        purge_days=PURGE_DAYS,
        min_train_days=MIN_TRAIN_DAYS,
    )

    kfold_results = run_fold_scheme(
        module, dataset, feat_cols, reference_rows, kfolds, TOP_K, FAST_MODE, "purged_kfold"
    )
    expanding_results = run_fold_scheme(
        module, dataset, feat_cols, reference_rows, expanding, TOP_K, FAST_MODE, "purged_expanding"
    )
    results = pd.concat([kfold_results, expanding_results], ignore_index=True)
    summary = summarize(results)

    print("\nRecent check legado del script")
    if recent_legacy.empty:
        print("Sin datos")
    else:
        print(
            f"Days={len(recent_legacy)} | "
            f"Avg_pop={recent_legacy['avg_pop_pct'].mean():+.2f}% | "
            f"Avg_close={recent_legacy['avg_close_pct'].mean():+.2f}% | "
            f"Avg_hit={recent_legacy['hit_rate'].mean():.1%}"
        )

    print("\nRecent check seguro (refs filtradas al train)")
    if recent_safe.empty:
        print("Sin datos")
    else:
        print(
            f"Days={len(recent_safe)} | "
            f"Avg_pop={recent_safe['avg_pop_pct'].mean():+.2f}% | "
            f"Avg_close={recent_safe['avg_close_pct'].mean():+.2f}% | "
            f"Avg_hit={recent_safe['hit_rate'].mean():.1%}"
        )

    if not recent_legacy.empty and not recent_safe.empty:
        delta_close = recent_safe["avg_close_pct"].mean() - recent_legacy["avg_close_pct"].mean()
        print(f"Delta seguro vs legado Avg_close = {delta_close:+.3f} pp")

    print_summary_table(summary, "purged_kfold")
    print_summary_table(summary, "purged_expanding")

    print("\nLectura final")
    print("  - Si ML pierde contra baselines simples bajo purged CV y expanding purged, no merece promotion al core.")
    print("  - Si el recent check legado supera claramente al seguro, hay leakage por reference templates.")
    print("  - Si sobrevive solo algun baseline simple, rescatar la hipotesis y no el stack ML entero.")


if __name__ == "__main__":
    main()
