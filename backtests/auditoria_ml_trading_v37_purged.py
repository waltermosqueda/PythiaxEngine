"""
AUDITORIA ML_TRADING_V37 - PURGED VALIDATION
===========================================

Objetivo:
  Auditar si `Machine Winners/ml_trading_v37.py` contiene un edge T+1 robusto o
  si su aparente valor puede reducirse a reglas simples de microestructura.

Metodologia:
  - reconstruccion del dataset desde `titan.db`
  - features identicas al script original
  - target identico: close T+1 >= +2.5%
  - validacion con:
      * purged k-fold
      * purged expanding walk-forward
  - comparacion contra baselines simples del mismo espacio de features
"""

from __future__ import annotations

import os
import importlib.util
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, HistGradientBoostingClassifier
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
SOURCE_PATH = ROOT.parent / "Machine Winners" / "ml_trading_v37.py"

TOP_K = 5
TARGET_THRESHOLD = 0.025
MIN_HISTORY = 160
KFOLD_SPLITS = 5
EXPANDING_SPLITS = 5
TEST_DAYS = 20
PURGE_DAYS = 1
EMBARGO_DAYS = 1


def load_v37_module():
    spec = importlib.util.spec_from_file_location("ml_trading_v37_audit", SOURCE_PATH)
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
    return data


def build_features_for_ticker(module, ticker: str, frame: pd.DataFrame, feat_cols: list[str]) -> pd.DataFrame:
    feat = module.compute_surge_features(frame)
    target = module.make_t1_target(frame["Close"], surge_threshold=TARGET_THRESHOLD)

    out = feat.copy()
    out["fwd_pop1"] = frame["Close"].shift(-1) / frame["Close"] - 1.0
    out["fwd_close1"] = out["fwd_pop1"]
    out["target_pop"] = target
    out.insert(0, "ticker", ticker)
    out.insert(0, "date", out.index)
    out = out.replace([np.inf, -np.inf], np.nan)
    out = out.dropna(subset=feat_cols + ["target_pop", "fwd_pop1", "fwd_close1"]).copy()
    return out.reset_index(drop=True)


def build_dataset(module) -> tuple[pd.DataFrame, list[str], dict[str, object]]:
    universe = list(dict.fromkeys(module.ACTIVOS.keys()))
    feat_cols = module.NovaBrain().feat_cols
    data = load_adjusted_ohlcv(universe)
    loaded = [ticker for ticker, frame in data.items() if len(frame) >= MIN_HISTORY]
    missing = sorted(set(universe) - set(loaded))

    frames = []
    for ticker in loaded:
        frame = build_features_for_ticker(module, ticker, data[ticker], feat_cols)
        if not frame.empty:
            frames.append(frame)

    dataset = pd.concat(frames, ignore_index=True)
    dataset["date"] = pd.to_datetime(dataset["date"])
    dataset["target_pop"] = dataset["target_pop"].astype(int)
    meta = {"loaded": loaded, "missing": missing}
    return dataset, feat_cols, meta


class V37Model:
    def __init__(self) -> None:
        self.scaler = RobustScaler()
        self.used_fallback = False
        self.model = HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=300,
            max_depth=5,
            l2_regularization=0.1,
            class_weight="balanced",
            random_state=42,
        )

    def fit(self, frame: pd.DataFrame, feat_cols: list[str]) -> "V37Model":
        train = frame.dropna(subset=feat_cols + ["target_pop"]).copy()
        x = self.scaler.fit_transform(train[feat_cols].values)
        y = train["target_pop"].astype(int).values
        try:
            self.model.fit(x, y)
        except PermissionError:
            self.used_fallback = True
            self.model = GradientBoostingClassifier(
                n_estimators=220,
                learning_rate=0.05,
                max_depth=3,
                min_samples_leaf=20,
                random_state=42,
            )
            self.model.fit(x, y)
        return self

    def score(self, frame: pd.DataFrame, feat_cols: list[str]) -> pd.Series:
        x = self.scaler.transform(frame[feat_cols].fillna(0.0).values)
        return pd.Series(self.model.predict_proba(x)[:, 1], index=frame.index)


def baseline_scores(frame: pd.DataFrame) -> dict[str, pd.Series]:
    squeeze_breakout = (
        0.35 * frame["close_strength"].rank(pct=True)
        + 0.35 * frame["vol_zscore"].rank(pct=True)
        + 0.30 * (1.0 - frame["bb_squeeze_rank"].rank(pct=True))
    )
    momentum_t1 = (
        0.30 * frame["close_strength"].rank(pct=True)
        + 0.25 * frame["intraday_return"].rank(pct=True)
        + 0.20 * frame["gap_open"].rank(pct=True)
        + 0.15 * frame["vol_zscore"].rank(pct=True)
        + 0.10 * frame["rsi_3"].rank(pct=True)
    )
    vol_squeeze = (
        0.55 * frame["vol_zscore"].rank(pct=True)
        + 0.45 * (1.0 - frame["bb_squeeze_rank"].rank(pct=True))
    )
    return {
        "squeeze_breakout": squeeze_breakout,
        "momentum_t1": momentum_t1,
        "vol_squeeze": vol_squeeze,
        "close_strength": frame["close_strength"],
        "vol_zscore": frame["vol_zscore"],
    }


def evaluate_pickset(frame: pd.DataFrame, picked: list[str], label: str, scheme: str, current_date: pd.Timestamp) -> dict[str, object]:
    subset = frame[frame["ticker"].isin(set(picked))].copy()
    return {
        "scheme": scheme,
        "model": label,
        "date": current_date,
        "top_k": len(subset),
        "hit_rate": float((subset["target_pop"] == 1).mean()) if len(subset) else np.nan,
        "avg_pop_pct": float(subset["fwd_pop1"].mean() * 100.0) if len(subset) else np.nan,
        "avg_close_pct": float(subset["fwd_close1"].mean() * 100.0) if len(subset) else np.nan,
        "avg_excess_close_pct": float((subset["fwd_close1"].mean() - frame["fwd_close1"].mean()) * 100.0) if len(subset) else np.nan,
    }


def run_scheme(dataset: pd.DataFrame, feat_cols: list[str], folds, scheme_name: str) -> tuple[pd.DataFrame, bool]:
    rows: list[dict[str, object]] = []
    used_fallback = False

    for fold in folds:
        train = dataset[dataset["date"].isin(fold.train_dates)].copy()
        test = dataset[dataset["date"].isin(fold.test_dates)].copy()
        if train.empty or test.empty:
            continue

        model = V37Model().fit(train, feat_cols)
        used_fallback = used_fallback or model.used_fallback

        for current_date in fold.test_dates:
            frame = test[test["date"] == current_date].dropna(subset=feat_cols).copy()
            if len(frame) < TOP_K:
                continue

            frame["ml_score"] = model.score(frame, feat_cols)
            ml_picks = frame.nlargest(TOP_K, "ml_score")["ticker"].tolist()
            rows.append(evaluate_pickset(frame, ml_picks, "ml_v37", scheme_name, current_date))

            for name, score in baseline_scores(frame).items():
                picked = pd.DataFrame({"ticker": frame["ticker"].values, "score": score.values}).nlargest(TOP_K, "score")["ticker"].tolist()
                rows.append(evaluate_pickset(frame, picked, name, scheme_name, current_date))

    return pd.DataFrame(rows), used_fallback


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


def print_table(summary: pd.DataFrame, scheme_name: str) -> None:
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
    module = load_v37_module()
    dataset, feat_cols, meta = build_dataset(module)

    print("AUDITORIA ML_TRADING_V37 - PURGED VALIDATION")
    print(f"Dataset rows={len(dataset):,} | features={len(feat_cols)}")
    print(f"Tradable loaded={len(meta['loaded'])}/{len(module.ACTIVOS)}")
    if meta["missing"]:
        print(f"Missing sample={meta['missing'][:12]}")

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

    kfold_results, kfold_fallback = run_scheme(dataset, feat_cols, kfolds, "purged_kfold")
    expanding_results, expanding_fallback = run_scheme(dataset, feat_cols, expanding, "purged_expanding")
    summary = summarize(pd.concat([kfold_results, expanding_results], ignore_index=True))

    if kfold_fallback or expanding_fallback:
        print("HGB fallo por restricciones del entorno en al menos un fold; se uso fallback serial controlado.")

    print_table(summary, "purged_kfold")
    print_table(summary, "purged_expanding")

    print("\nLectura final")
    print("  - Si ML no supera a combinaciones simples en expanding purged, no merece promotion.")
    print("  - Si el ML domina en T+1 y los baselines no lo igualan, hay edge microestructural real.")


if __name__ == "__main__":
    main()
