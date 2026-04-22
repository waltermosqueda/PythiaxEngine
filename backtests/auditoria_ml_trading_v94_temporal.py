"""
AUDITORIA ML_TRADING_V94 - TEMPORAL VS ROW-SPLIT
================================================

Objetivo:
  Auditar si `Machine Winners/ml_trading_v94.py` contiene un edge portable o si
  su aparente precision viene inflada por un split incorrecto del panel.

Metodologia:
  - reconstruccion del dataset desde `titan.db`
  - features y target equivalentes al script original
  - comparacion entre:
      * row_split_original (como en v94)
      * purged_kfold temporal
      * purged_expanding temporal
  - baselines simples sobre el mismo espacio de features
"""

from __future__ import annotations

import ast
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.purged_cv_utils import build_purged_expanding_splits, build_purged_kfold_splits


DB_PATH = ROOT / "titan_system" / "data" / "titan.db"
SOURCE_PATH = ROOT.parent / "Machine Winners" / "ml_trading_v94.py"

TOP_K = 10
MIN_HISTORY = 120
KFOLD_SPLITS = 5
EXPANDING_SPLITS = 5
TEST_DAYS = 20
PURGE_DAYS = 5
EMBARGO_DAYS = 5


def parse_source_config() -> tuple[list[str], int, float]:
    tree = ast.parse(SOURCE_PATH.read_text(encoding="utf-8", errors="ignore"))
    universe: list[str] | None = None
    ventana: int | None = None
    umbral: float | None = None

    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id == "activos":
            universe = ast.literal_eval(node.value)
        elif target.id == "VENTANA_PREDICCION":
            ventana = int(ast.literal_eval(node.value))
        elif target.id == "UMBRAL_SUBA":
            umbral = float(ast.literal_eval(node.value))

    if universe is None or ventana is None or umbral is None:
        raise ValueError("No se pudo parsear la configuracion base de ml_trading_v94.py")
    return universe, ventana, umbral


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


def calcular_indicadores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for window in [5, 10, 20]:
        df[f"SMA_{window}"] = df["Close"].rolling(window=window).mean()
        df[f"EMA_{window}"] = df["Close"].ewm(span=window, adjust=False).mean()

    df["SMA_Cross"] = df["SMA_5"] - df["SMA_20"]
    df["EMA_Cross"] = df["EMA_5"] - df["EMA_20"]

    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))

    exp1 = df["Close"].ewm(span=12, adjust=False).mean()
    exp2 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = exp1 - exp2
    df["Signal_Line"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_Hist"] = df["MACD"] - df["Signal_Line"]

    df["BB_Middle"] = df["Close"].rolling(window=20).mean()
    bb_std = df["Close"].rolling(window=20).std()
    df["BB_Upper"] = df["BB_Middle"] + (bb_std * 2)
    df["BB_Lower"] = df["BB_Middle"] - (bb_std * 2)
    df["BB_Position"] = (df["Close"] - df["BB_Lower"]) / (df["BB_Upper"] - df["BB_Lower"])

    df["Volatility"] = df["Close"].pct_change().rolling(window=10).std()
    df["Volume_Ratio"] = df["Volume"] / df["Volume"].rolling(window=20).mean()
    df["ROC"] = (df["Close"] - df["Close"].shift(10)) / df["Close"].shift(10) * 100

    high_low = df["High"] - df["Low"]
    high_close = np.abs(df["High"] - df["Close"].shift())
    low_close = np.abs(df["Low"] - df["Close"].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df["ATR"] = true_range.rolling(14).mean()

    for i in range(1, 4):
        df[f"Return_Lag_{i}"] = df["Close"].pct_change().shift(i)

    return df


def crear_target(df: pd.DataFrame, ventana: int, umbral: float) -> pd.DataFrame:
    future_max = df["Close"].shift(-ventana).rolling(window=ventana).max()
    future_ret = (future_max - df["Close"]) / df["Close"]
    df["Target"] = (future_ret >= umbral).astype(float)
    df["fwd_pop"] = future_ret
    df["fwd_close1"] = df["Close"].shift(-1) / df["Close"] - 1.0
    df.loc[df.index[-ventana:], "Target"] = np.nan
    return df


def build_dataset(universe: list[str], ventana: int, umbral: float) -> tuple[pd.DataFrame, list[str], dict[str, object]]:
    data = load_adjusted_ohlcv(universe)
    loaded = [ticker for ticker in universe if ticker in data and len(data[ticker]) >= MIN_HISTORY]
    missing = sorted(set(universe) - set(loaded))

    frames = []
    for ticker in loaded:
        frame = calcular_indicadores(data[ticker])
        frame = crear_target(frame, ventana=ventana, umbral=umbral)
        frame["Ticker"] = ticker
        frame["date"] = frame.index
        frames.append(frame.reset_index(drop=True))

    dataset = pd.concat(frames, ignore_index=True)
    feature_cols = [
        col
        for col in dataset.columns
        if col not in ["Target", "Ticker", "Open", "High", "Low", "Close", "Adj Close", "Volume", "date", "fwd_pop", "fwd_close1"]
    ]
    dataset = dataset.replace([np.inf, -np.inf], np.nan)
    dataset = dataset.dropna(subset=feature_cols + ["Target", "fwd_pop", "fwd_close1"]).copy()
    dataset["date"] = pd.to_datetime(dataset["date"])
    dataset["Target"] = dataset["Target"].astype(int)
    meta = {"loaded": loaded, "missing": missing}
    return dataset, feature_cols, meta


class V94Model:
    def __init__(self) -> None:
        self.used_fallback = False
        self.model = None

    def fit(self, frame: pd.DataFrame, feat_cols: list[str]) -> "V94Model":
        train = frame.dropna(subset=feat_cols + ["Target"]).copy()
        y_train = train["Target"].astype(int)
        scale_pos_weight = float(y_train.value_counts().get(0, 1) / max(y_train.value_counts().get(1, 1), 1))
        try:
            self.model = xgb.XGBClassifier(
                objective="binary:logistic",
                n_estimators=100,
                max_depth=4,
                learning_rate=0.1,
                subsample=0.8,
                colsample_bytree=0.8,
                scale_pos_weight=scale_pos_weight,
                eval_metric="auc",
                tree_method="hist",
                random_state=42,
                n_jobs=1,
            )
            self.model.fit(train[feat_cols], y_train)
        except Exception:
            self.used_fallback = True
            self.model = GradientBoostingClassifier(
                n_estimators=180,
                learning_rate=0.05,
                max_depth=3,
                min_samples_leaf=20,
                random_state=42,
            )
            self.model.fit(train[feat_cols], y_train)
        return self

    def predict_proba(self, frame: pd.DataFrame, feat_cols: list[str]) -> pd.Series:
        scores = self.model.predict_proba(frame[feat_cols])[:, 1]
        return pd.Series(scores, index=frame.index)


def baseline_scores(frame: pd.DataFrame) -> dict[str, pd.Series]:
    rsi_inv = 1.0 - frame["RSI"].rank(pct=True)
    bb_low = 1.0 - frame["BB_Position"].rank(pct=True)
    roc_rank = frame["ROC"].rank(pct=True)
    macd_rank = frame["MACD_Hist"].rank(pct=True)
    vol_rank = frame["Volume_Ratio"].rank(pct=True)
    cross_rank = frame["SMA_Cross"].rank(pct=True)
    ema_rank = frame["EMA_Cross"].rank(pct=True)
    volat_rank = frame["Volatility"].rank(pct=True)

    momentum_combo = (
        0.30 * roc_rank
        + 0.25 * macd_rank
        + 0.20 * cross_rank
        + 0.15 * ema_rank
        + 0.10 * frame["Return_Lag_1"].rank(pct=True)
    )
    reversal_combo = 0.40 * rsi_inv + 0.30 * bb_low + 0.20 * vol_rank + 0.10 * volat_rank
    setup_combo = 0.25 * rsi_inv + 0.20 * bb_low + 0.20 * vol_rank + 0.20 * macd_rank + 0.15 * roc_rank

    return {
        "momentum_combo": momentum_combo,
        "reversal_combo": reversal_combo,
        "setup_combo": setup_combo,
        "roc_only": frame["ROC"],
        "rsi_inv": -frame["RSI"],
    }


def evaluate_pickset(frame: pd.DataFrame, picked: list[str], label: str, scheme: str, current_date: pd.Timestamp) -> dict[str, object]:
    subset = frame[frame["Ticker"].isin(set(picked))].copy()
    return {
        "scheme": scheme,
        "model": label,
        "date": current_date,
        "top_k": len(subset),
        "hit_rate": float((subset["Target"] == 1).mean()) if len(subset) else np.nan,
        "avg_pop_pct": float(subset["fwd_pop"].mean() * 100.0) if len(subset) else np.nan,
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

        model = V94Model().fit(train, feat_cols)
        used_fallback = used_fallback or model.used_fallback

        for current_date in fold.test_dates:
            frame = test[test["date"] == current_date].dropna(subset=feat_cols).copy()
            if len(frame) < TOP_K:
                continue

            frame["ml_score"] = model.predict_proba(frame, feat_cols)
            ml_picks = frame.nlargest(TOP_K, "ml_score")["Ticker"].tolist()
            rows.append(evaluate_pickset(frame, ml_picks, "ml_v94", scheme_name, current_date))

            for name, score in baseline_scores(frame).items():
                picked = pd.DataFrame({"Ticker": frame["Ticker"].values, "score": score.values}).nlargest(TOP_K, "score")["Ticker"].tolist()
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


def evaluate_row_split(dataset: pd.DataFrame, feat_cols: list[str]) -> tuple[dict[str, object], pd.DataFrame, bool]:
    split_idx = int(len(dataset) * 0.8)
    train = dataset.iloc[:split_idx].copy()
    test = dataset.iloc[split_idx:].copy()

    model = V94Model().fit(train, feat_cols)
    test["ml_score"] = model.predict_proba(test, feat_cols)
    test["ml_pred"] = (test["ml_score"] >= 0.5).astype(int)

    metrics = {
        "scheme": "row_split_original",
        "train_rows": len(train),
        "test_rows": len(test),
        "train_min_date": pd.Timestamp(train["date"].min()),
        "train_max_date": pd.Timestamp(train["date"].max()),
        "test_min_date": pd.Timestamp(test["date"].min()),
        "test_max_date": pd.Timestamp(test["date"].max()),
        "precision": float(precision_score(test["Target"], test["ml_pred"], zero_division=0)),
        "recall": float(recall_score(test["Target"], test["ml_pred"], zero_division=0)),
        "accuracy": float(accuracy_score(test["Target"], test["ml_pred"])),
    }

    rows = []
    for current_date, frame in test.groupby("date"):
        if len(frame) < TOP_K:
            continue
        ml_picks = frame.nlargest(TOP_K, "ml_score")["Ticker"].tolist()
        rows.append(evaluate_pickset(frame, ml_picks, "ml_v94", "row_split_original", current_date))
        for name, score in baseline_scores(frame).items():
            picked = pd.DataFrame({"Ticker": frame["Ticker"].values, "score": score.values}).nlargest(TOP_K, "score")["Ticker"].tolist()
            rows.append(evaluate_pickset(frame, picked, name, "row_split_original", current_date))
    return metrics, pd.DataFrame(rows), model.used_fallback


def main() -> None:
    universe, ventana, umbral = parse_source_config()
    dataset, feat_cols, meta = build_dataset(universe, ventana, umbral)

    print("AUDITORIA ML_TRADING_V94 - TEMPORAL VS ROW-SPLIT")
    print(f"Dataset rows={len(dataset):,} | features={len(feat_cols)} | horizon={ventana}d | target={umbral:.1%}")
    print(f"Tradable loaded={len(meta['loaded'])}/{len(universe)}")
    if meta["missing"]:
        print(f"Missing sample={meta['missing'][:12]}")

    row_metrics, row_results, row_fallback = evaluate_row_split(dataset, feat_cols)
    print("\nrow_split_original")
    print(
        f"rows train/test={row_metrics['train_rows']:,}/{row_metrics['test_rows']:,} | "
        f"precision={row_metrics['precision']:.3f} | recall={row_metrics['recall']:.3f} | accuracy={row_metrics['accuracy']:.3f}"
    )
    print(
        f"train_dates={row_metrics['train_min_date'].date()} -> {row_metrics['train_max_date'].date()} | "
        f"test_dates={row_metrics['test_min_date'].date()} -> {row_metrics['test_max_date'].date()}"
    )
    if row_metrics["train_max_date"] > row_metrics["test_min_date"]:
        print("ATENCION: el split por filas mezcla futuro de algunos tickers con pasado de otros. Validacion contaminada.")

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
    summary = summarize(pd.concat([row_results, kfold_results, expanding_results], ignore_index=True))

    if row_fallback or kfold_fallback or expanding_fallback:
        print("XGBoost fallo en al menos un fit; se uso fallback serial controlado.")

    print_table(summary, "row_split_original")
    print_table(summary, "purged_kfold")
    print_table(summary, "purged_expanding")

    print("\nLectura final")
    print("  - Si row_split luce fuerte pero purged_expanding se cae, el edge era metodologico y no portable.")
    print("  - Si un baseline simple empata o supera al ML, conviene rescatar la logica y no el modelo entero.")


if __name__ == "__main__":
    main()
