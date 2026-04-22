"""
AUDITORIA ML_TRADING_V22 - STACKED PURGE VS TEMPORAL PURGE
==========================================================

Objetivo:
  Auditar `Machine Winners/ml_trading_v22.py` uno por uno, separando:
  - valor real de su feature set / labels
  - calidad metodologica de su "purged walk-forward"

Enfoque:
  - reconstruccion exacta del universo y features desde `titan.db`
  - labels exactas `triple_barrier_labels(...)`
  - comparacion entre:
      * original_stacked_purge: misma geometria de panel apilado del script
      * purged_kfold_date: purge correcto por fecha
      * purged_expanding_date: past-only realista por fecha
  - proxy fiel del ensemble para medir el edge del stack sin ejecutar la
    maquinaria completa nested del script original en cada fold
"""

from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import RobustScaler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.purged_cv_utils import build_purged_expanding_splits, build_purged_kfold_splits


os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")


DB_PATH = ROOT / "titan_system" / "data" / "titan.db"
SOURCE_PATH = ROOT.parent / "Machine Winners" / "ml_trading_v22.py"

TOP_K = 10
MIN_HISTORY = 252
HORIZON = 5
KFOLD_SPLITS = 5
EXPANDING_SPLITS = 5
TEST_DAYS = 20
PURGE_DAYS = 5
EMBARGO_DAYS = 5


@dataclass(frozen=True)
class RowFold:
    fold_id: int
    train_idx: np.ndarray
    test_idx: np.ndarray


def load_v22_module():
    spec = importlib.util.spec_from_file_location("ml_trading_v22_audit", SOURCE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_adjusted_ohlcv(universe: list[str]) -> dict[str, pd.DataFrame]:
    placeholders = ",".join("?" for _ in universe)
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
        raw = pd.read_sql_query(query, conn, params=universe, parse_dates=["date"])

    data: dict[str, pd.DataFrame] = {}
    for ticker in universe:
        frame = raw[raw["ticker"] == ticker].copy()
        if frame.empty:
            continue
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
    return data


def build_dataset(module) -> tuple[pd.DataFrame, list[str], dict[str, object]]:
    universe = list(module.ACTIVOS.keys())
    data = load_adjusted_ohlcv(universe)

    engine = module.TradingEngine()
    for ticker in universe:
        frame = data.get(ticker)
        if frame is None or len(frame) < MIN_HISTORY:
            continue
        engine.data[ticker] = frame

    if "SPY" in engine.data:
        engine.spy_ret = engine.data["SPY"]["Close"].pct_change().fillna(0)

    engine.calcular_features()
    feat_cols = list(module.StackedEnsemble.FEAT_COLS)

    frames: list[pd.DataFrame] = []
    loaded = list(engine.features.keys())
    missing = sorted(set(universe) - set(loaded))

    for ticker in loaded:
        feat_df = engine.features[ticker].copy()
        close = engine.data[ticker]["Close"].astype(float)
        labels = module.triple_barrier_labels(
            close.values,
            horizon=HORIZON,
            threshold=0.018,
            vol_scale=True,
        ).astype(float)

        n = min(len(feat_df), len(labels), len(close))
        feat_df = feat_df.iloc[:n].copy()
        close = close.iloc[:n].copy()
        labels = labels[:n]
        labels[-HORIZON:] = np.nan

        frame = feat_df[feat_cols].copy()
        frame["date"] = pd.to_datetime(feat_df.index)
        frame["ticker"] = ticker
        frame["label"] = labels
        frame["target_buy"] = (frame["label"] == 2).astype(float)
        frame["fwd_close1"] = close.shift(-1).values / close.values - 1.0
        frame["fwd_close5"] = close.shift(-HORIZON).values / close.values - 1.0
        frames.append(frame.reset_index(drop=True))

    dataset = pd.concat(frames, ignore_index=True)
    dataset = dataset.replace([np.inf, -np.inf], np.nan)
    dataset = dataset.dropna(subset=feat_cols + ["label", "fwd_close1", "fwd_close5"]).copy()
    dataset["label"] = dataset["label"].astype(int)
    dataset["target_buy"] = (dataset["label"] == 2).astype(int)

    meta = {
        "loaded": loaded,
        "missing": missing,
    }
    return dataset, feat_cols, meta


def build_original_stacked_splits(n_rows: int, n_folds: int = 4, horizon: int = HORIZON, embargo: int = EMBARGO_DAYS) -> list[RowFold]:
    min_train = max(200, n_rows // (n_folds + 2))
    fold_size = max(80, (n_rows - min_train) // n_folds)
    folds: list[RowFold] = []
    for fold_id in range(1, n_folds + 1):
        val_start = min_train + (fold_id - 1) * fold_size
        val_end = min(val_start + fold_size, n_rows - embargo)
        if val_end <= val_start + 20:
            continue
        train_end = val_start - horizon
        if train_end < min_train // 2:
            continue
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(val_start, val_end)
        folds.append(RowFold(fold_id=fold_id, train_idx=train_idx, test_idx=test_idx))
    return folds


class V22ProxyModel:
    """
    Proxy fiel y manejable del stack v22.

    No replica el nested walk-forward interno, pero si conserva:
      - mismas 62 features
      - mismo label triple-barrier
      - ensemble multi-modelo con weighting fijo
      - score de clase BUY como objetivo de ranking
    """

    def __init__(self) -> None:
        self.scaler = RobustScaler()
        self.models = {
            "et": ExtraTreesClassifier(
                n_estimators=180,
                max_depth=8,
                min_samples_leaf=3,
                class_weight="balanced",
                random_state=42,
                n_jobs=1,
            ),
            "gb": GradientBoostingClassifier(
                n_estimators=180,
                max_depth=4,
                learning_rate=0.04,
                subsample=0.8,
                min_samples_leaf=5,
                random_state=42,
            ),
            "lr": LogisticRegression(
                max_iter=400,
                C=0.3,
                class_weight="balanced",
                random_state=42,
                solver="saga",
                n_jobs=1,
            ),
        }
        self.weights = {"et": 0.45, "gb": 0.35, "lr": 0.20}

    def fit(self, frame: pd.DataFrame, feat_cols: list[str]) -> "V22ProxyModel":
        train = frame.dropna(subset=feat_cols + ["label"]).copy()
        x = self.scaler.fit_transform(train[feat_cols].values)
        y = train["label"].astype(int).values
        for model in self.models.values():
            model.fit(x, y)
        return self

    def buy_score(self, frame: pd.DataFrame, feat_cols: list[str]) -> pd.Series:
        x = self.scaler.transform(frame[feat_cols].fillna(0.0).values)
        scores = np.zeros(len(frame), dtype=float)
        total_w = sum(self.weights.values()) + 1e-10
        for name, model in self.models.items():
            proba = model.predict_proba(x)
            full = np.zeros((len(frame), 3), dtype=float)
            for j, cls in enumerate(model.classes_):
                full[:, int(cls)] = proba[:, j]
            scores += full[:, 2] * (self.weights[name] / total_w)
        return pd.Series(scores, index=frame.index)


def baseline_scores(frame: pd.DataFrame) -> dict[str, pd.Series]:
    trend_cs_combo = (
        0.30 * frame["cs_mom_rank"].rank(pct=True)
        + 0.20 * frame["mom_score"].rank(pct=True)
        + 0.15 * frame["mom21"].rank(pct=True)
        + 0.15 * frame["price_accel"].rank(pct=True)
        + 0.10 * frame["hurst"].rank(pct=True)
        + 0.10 * (1.0 - frame["cs_vol_rank"].rank(pct=True))
    )
    quality_trend_combo = (
        0.25 * frame["cs_mom_rank"].rank(pct=True)
        + 0.20 * frame["mom21"].rank(pct=True)
        + 0.15 * frame["mer"].rank(pct=True)
        + 0.15 * frame["hurst"].rank(pct=True)
        + 0.15 * (-frame["amihud"]).rank(pct=True)
        + 0.10 * (-frame["gk_vol"]).rank(pct=True)
    )
    meanrev_quant_combo = (
        0.25 * frame["mean_reversion"].rank(pct=True)
        + 0.20 * (-frame["zscore20"]).rank(pct=True)
        + 0.20 * (-frame["dist_20"]).rank(pct=True)
        + 0.15 * (-frame["rsi14"]).rank(pct=True)
        + 0.10 * frame["rsi_div"].rank(pct=True)
        + 0.10 * (-frame["williams_r"]).rank(pct=True)
    )
    return {
        "trend_cs_combo": trend_cs_combo,
        "quality_trend_combo": quality_trend_combo,
        "meanrev_quant_combo": meanrev_quant_combo,
        "cs_mom_rank": frame["cs_mom_rank"],
        "mom_score": frame["mom_score"],
    }


def evaluate_pickset(frame: pd.DataFrame, picked: list[str], label: str, scheme: str, current_date: pd.Timestamp) -> dict[str, object]:
    subset = frame[frame["ticker"].isin(set(picked))].copy()
    return {
        "scheme": scheme,
        "model": label,
        "date": current_date,
        "top_k": len(subset),
        "buy_hit_rate": float((subset["label"] == 2).mean()) if len(subset) else np.nan,
        "avg_close1_pct": float(subset["fwd_close1"].mean() * 100.0) if len(subset) else np.nan,
        "avg_close5_pct": float(subset["fwd_close5"].mean() * 100.0) if len(subset) else np.nan,
        "avg_excess5_pct": float((subset["fwd_close5"].mean() - frame["fwd_close5"].mean()) * 100.0) if len(subset) else np.nan,
    }


def run_row_scheme(dataset: pd.DataFrame, feat_cols: list[str], folds: list[RowFold], scheme_name: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    contamination: list[dict[str, object]] = []

    for fold in folds:
        train = dataset.iloc[fold.train_idx].copy()
        test = dataset.iloc[fold.test_idx].copy()
        if train.empty or test.empty:
            continue

        contamination.append(
            {
                "fold": fold.fold_id,
                "train_min_date": pd.Timestamp(train["date"].min()),
                "train_max_date": pd.Timestamp(train["date"].max()),
                "test_min_date": pd.Timestamp(test["date"].min()),
                "test_max_date": pd.Timestamp(test["date"].max()),
                "overlap": bool(pd.Timestamp(train["date"].max()) >= pd.Timestamp(test["date"].min())),
            }
        )

        model = V22ProxyModel().fit(train, feat_cols)
        for current_date, frame in test.groupby("date"):
            frame = frame.dropna(subset=feat_cols).copy()
            if len(frame) < TOP_K:
                continue
            frame["ml_score"] = model.buy_score(frame, feat_cols)
            ml_picks = frame.nlargest(TOP_K, "ml_score")["ticker"].tolist()
            rows.append(evaluate_pickset(frame, ml_picks, "ml_v22_proxy", scheme_name, pd.Timestamp(current_date)))

            for name, score in baseline_scores(frame).items():
                picked = pd.DataFrame({"ticker": frame["ticker"].values, "score": score.values}).nlargest(TOP_K, "score")["ticker"].tolist()
                rows.append(evaluate_pickset(frame, picked, name, scheme_name, pd.Timestamp(current_date)))

    return pd.DataFrame(rows), pd.DataFrame(contamination)


def run_date_scheme(dataset: pd.DataFrame, feat_cols: list[str], folds, scheme_name: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for fold in folds:
        train = dataset[dataset["date"].isin(fold.train_dates)].copy()
        test = dataset[dataset["date"].isin(fold.test_dates)].copy()
        if train.empty or test.empty:
            continue

        model = V22ProxyModel().fit(train, feat_cols)
        for current_date in fold.test_dates:
            frame = test[test["date"] == current_date].dropna(subset=feat_cols).copy()
            if len(frame) < TOP_K:
                continue
            frame["ml_score"] = model.buy_score(frame, feat_cols)
            ml_picks = frame.nlargest(TOP_K, "ml_score")["ticker"].tolist()
            rows.append(evaluate_pickset(frame, ml_picks, "ml_v22_proxy", scheme_name, pd.Timestamp(current_date)))

            for name, score in baseline_scores(frame).items():
                picked = pd.DataFrame({"ticker": frame["ticker"].values, "score": score.values}).nlargest(TOP_K, "score")["ticker"].tolist()
                rows.append(evaluate_pickset(frame, picked, name, scheme_name, pd.Timestamp(current_date)))
    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (scheme, model), frame in results.groupby(["scheme", "model"]):
        rows.append(
            {
                "scheme": scheme,
                "model": model,
                "days": len(frame),
                "buy_hit_rate": frame["buy_hit_rate"].mean(),
                "avg_close1_pct": frame["avg_close1_pct"].mean(),
                "avg_close5_pct": frame["avg_close5_pct"].mean(),
                "avg_excess5_pct": frame["avg_excess5_pct"].mean(),
            }
        )
    out = pd.DataFrame(rows)
    return out.sort_values(["scheme", "avg_close5_pct", "buy_hit_rate"], ascending=[True, False, False]).reset_index(drop=True)


def print_table(summary: pd.DataFrame, scheme_name: str) -> None:
    subset = summary[summary["scheme"] == scheme_name].copy()
    if subset.empty:
        print(f"\n{scheme_name}: sin resultados")
        return
    print(f"\n{scheme_name}")
    display = subset[["model", "days", "buy_hit_rate", "avg_close1_pct", "avg_close5_pct", "avg_excess5_pct"]].copy()
    display["buy_hit_rate"] = (display["buy_hit_rate"] * 100.0).round(1)
    for col in ["avg_close1_pct", "avg_close5_pct", "avg_excess5_pct"]:
        display[col] = display[col].round(3)
    print(display.to_string(index=False))


def main() -> None:
    module = load_v22_module()
    dataset, feat_cols, meta = build_dataset(module)

    print("AUDITORIA ML_TRADING_V22 - STACKED PURGE VS TEMPORAL PURGE")
    print(f"Dataset rows={len(dataset):,} | features={len(feat_cols)} | horizon={HORIZON}d")
    print(f"Tradable loaded={len(meta['loaded'])}/{len(module.ACTIVOS)}")
    if meta["missing"]:
        print(f"Missing sample={meta['missing'][:12]}")

    original_folds = build_original_stacked_splits(len(dataset), n_folds=4, horizon=HORIZON, embargo=EMBARGO_DAYS)
    original_results, contamination = run_row_scheme(dataset, feat_cols, original_folds, "original_stacked_purge")

    print("\noriginal_stacked_purge - geometria")
    if contamination.empty:
        print("Sin folds")
    else:
        overlap_rate = contamination["overlap"].mean() * 100.0
        print(contamination.to_string(index=False))
        print(f"Overlap train/test por fecha: {overlap_rate:.1f}% de folds")

    all_dates = sorted(dataset["date"].unique())
    kfolds = build_purged_kfold_splits(
        all_dates,
        n_splits=KFOLD_SPLITS,
        purge_days=PURGE_DAYS,
        embargo_days=EMBARGO_DAYS,
        min_train_days=MIN_HISTORY,
    )
    expanding = build_purged_expanding_splits(
        all_dates,
        n_splits=EXPANDING_SPLITS,
        test_days=TEST_DAYS,
        purge_days=PURGE_DAYS,
        min_train_days=MIN_HISTORY,
    )

    kfold_results = run_date_scheme(dataset, feat_cols, kfolds, "purged_kfold_date")
    expanding_results = run_date_scheme(dataset, feat_cols, expanding, "purged_expanding_date")
    summary = summarize(pd.concat([original_results, kfold_results, expanding_results], ignore_index=True))

    print_table(summary, "original_stacked_purge")
    print_table(summary, "purged_kfold_date")
    print_table(summary, "purged_expanding_date")

    print("\nLectura final")
    print("  - Si el stacked purge original mezcla fechas, el claim anti-leakage queda bajo sospecha.")
    print("  - Si el stack 62-feature no supera baselines simples con purge correcto por fecha, no merece promotion.")


if __name__ == "__main__":
    main()
