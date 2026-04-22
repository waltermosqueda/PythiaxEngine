"""
AUDITORIA ML_TRADING_V39
========================

Objetivo:
  Auditar si `Machine Winners/ml_trading_v39.py` contiene un edge real que
  merezca ser rescatado para el proyecto Claude, o si su aparente acierto
  viene de una logica simple que puede expresarse sin el stack ML.

Enfoque:
  1. Reproducir la logica de features y el backtest rapido original sobre
     `titan.db`, usando SPY como proxy del benchmark.
  2. Medir el modelo contra baselines simples en el mismo universo y fechas.
  3. Identificar si sobrevive algun concepto portable al scanner productivo.

Fecha:
  2026-04-07
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import parallel_backend
from sklearn.ensemble import (
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.preprocessing import RobustScaler


# Evita problemas de joblib/OpenMP en Windows al reentrenar muchas veces.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "titan_system" / "data" / "titan.db"
SOURCE_PATH = ROOT.parent / "Machine Winners" / "ml_trading_v39.py"

V39_TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMD", "INTC", "QCOM", "AVGO", "TXN", "MU", "AMAT",
    "GOOGL", "META", "AMZN", "NFLX", "TSLA", "CRM", "ORCL", "ADBE", "NOW", "SNOW",
    "JPM", "BAC", "GS", "MS", "WFC", "C", "BLK", "AXP", "V", "MA",
    "JNJ", "PFE", "MRK", "ABBV", "LLY", "UNH", "CVS", "ABT", "TMO", "DHR",
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "HAL",
    "WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "NKE", "DIS", "CMCSA",
    "CAT", "DE", "BA", "HON", "MMM", "GE", "RTX", "LMT", "NOC", "UPS",
]

MARKET_TICKER = "SPY"
TOP_K = 10
MIN_TRAIN_DAYS = 90
RETRAIN_EVERY = 10
USED_HIST_FALLBACK = False


def load_panel() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, list[str], list[str]]:
    tickers = sorted(set(V39_TICKERS + [MARKET_TICKER]))
    placeholders = ",".join("?" for _ in tickers)
    query = f"""
        SELECT
            ticker,
            date,
            COALESCE(adj_close, close) AS close_px,
            volume
        FROM prices
        WHERE ticker IN ({placeholders})
        ORDER BY date, ticker
    """

    with sqlite3.connect(DB_PATH) as conn:
        raw = pd.read_sql_query(query, conn, params=tickers, parse_dates=["date"])

    available = sorted(raw["ticker"].unique().tolist())
    common = [ticker for ticker in V39_TICKERS if ticker in available]
    missing = [ticker for ticker in V39_TICKERS if ticker not in available]

    usable = raw[raw["ticker"].isin(common + [MARKET_TICKER])].copy()

    price_df = usable.pivot(index="date", columns="ticker", values="close_px").sort_index()
    volume_df = usable.pivot(index="date", columns="ticker", values="volume").sort_index()

    market_s = price_df[MARKET_TICKER].copy()
    market_ret = market_s.pct_change()

    price_df = price_df[common].copy()
    volume_df = volume_df[common].copy()

    common_dates = price_df.index.intersection(market_s.index)
    price_df = price_df.loc[common_dates].copy()
    volume_df = volume_df.loc[common_dates].copy()
    market_s = market_s.loc[common_dates].copy()
    market_ret = market_ret.loc[common_dates].copy()

    price_df = price_df.ffill()
    volume_df = volume_df.ffill().fillna(0)

    return price_df, volume_df, market_s, market_ret, common, missing


def compute_rsi(ret_df: pd.DataFrame | pd.Series, window: int = 14) -> pd.DataFrame | pd.Series:
    gain = ret_df.clip(lower=0)
    loss = (-ret_df).clip(lower=0)
    avg_gain = gain.ewm(span=window, adjust=False).mean()
    avg_loss = loss.ewm(span=window, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))


def build_features(
    price_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    market_s: pd.Series,
    market_ret_s: pd.Series,
    min_history: int = 65,
) -> tuple[pd.DataFrame, list[str]]:
    ret = price_df.pct_change()

    r1 = ret
    r3 = price_df.pct_change(3)
    r5 = price_df.pct_change(5)
    r10 = price_df.pct_change(10)
    r20 = price_df.pct_change(20)
    r40 = price_df.pct_change(40)
    r60 = price_df.pct_change(60)
    mom_accel = r5 - r20.shift(5)

    ma5 = price_df.rolling(5).mean()
    ma10 = price_df.rolling(10).mean()
    ma20 = price_df.rolling(20).mean()
    ma50 = price_df.rolling(50).mean()
    p_vs_ma5 = price_df / ma5 - 1
    p_vs_ma20 = price_df / ma20 - 1
    p_vs_ma50 = price_df / ma50 - 1
    cross_520 = ma5 / ma20 - 1

    rsi7 = compute_rsi(ret, 7)
    rsi14 = compute_rsi(ret, 14)
    rsi_slope = rsi14 - rsi14.shift(3)

    ema12 = price_df.ewm(span=12, adjust=False).mean()
    ema26 = price_df.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_sig = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_sig
    macd_norm = macd / (price_df + 1e-10)
    macd_cross = ((macd_hist > 0).astype(int) - (macd_hist.shift(1) > 0).astype(int))

    std20 = price_df.rolling(20).std()
    upper = ma20 + 2 * std20
    lower = ma20 - 2 * std20
    bb_pct = (price_df - lower) / (upper - lower + 1e-10)
    bb_width = (upper - lower) / (ma20 + 1e-10)

    vol5 = ret.rolling(5).std()
    vol20 = ret.rolling(20).std()
    vol_ratio = vol5 / (vol20 + 1e-8)

    lo14 = price_df.rolling(14).min()
    hi14 = price_df.rolling(14).max()
    stoch_k = (price_df - lo14) / (hi14 - lo14 + 1e-10) * 100
    stoch_d = stoch_k.rolling(3).mean()

    v_ma20 = volume_df.rolling(20).mean()
    v_ratio = volume_df / (v_ma20 + 1e-8)
    v_ratio5 = volume_df.rolling(5).mean() / (v_ma20 + 1e-8)
    pv_mom = r5 * np.log1p(v_ratio.clip(0, 10))

    direction = np.sign(ret)
    obv = (direction * volume_df).cumsum()
    obv_ma10 = obv.rolling(10).mean()
    obv_mom = obv / (obv_ma10.abs() + 1e-8) - 1

    mkt_rsi14 = compute_rsi(market_ret_s.to_frame(), 14).iloc[:, 0]
    mkt_trend = market_s / market_s.rolling(20).mean() - 1

    cov20 = ret.rolling(20).cov(market_ret_s)
    mkt_var20 = market_ret_s.rolling(20).var()
    beta20 = cov20.div(mkt_var20 + 1e-10, axis=0)
    roll_corr = ret.rolling(20).corr(market_ret_s)

    idio1 = ret.sub(beta20.mul(market_ret_s, axis=0))
    idio5 = idio1.rolling(5).sum()
    idio_v = idio1.rolling(5).std()

    ret1_rank = ret.rank(axis=1, pct=True)
    ret5_rank = r5.rank(axis=1, pct=True)
    ret20_rank = r20.rank(axis=1, pct=True)
    vol_rank = vol20.rank(axis=1, pct=True)

    rel_str5 = r5.sub(market_s.pct_change(5), axis=0)
    rel_str20 = r20.sub(market_s.pct_change(20), axis=0)

    zscore20 = (price_df - ma20) / (std20 + 1e-10)
    fwd_ret1 = ret.shift(-1)

    feature_frames = {
        "ret1": r1, "ret3": r3, "ret5": r5, "ret10": r10,
        "ret20": r20, "ret40": r40, "ret60": r60, "mom_accel": mom_accel,
        "p_vs_ma5": p_vs_ma5, "p_vs_ma20": p_vs_ma20, "p_vs_ma50": p_vs_ma50,
        "cross_520": cross_520, "rsi7": rsi7, "rsi14": rsi14, "rsi_slope": rsi_slope,
        "macd_norm": macd_norm, "macd_hist": macd_hist, "macd_cross": macd_cross,
        "bb_pct": bb_pct, "bb_width": bb_width, "vol5": vol5, "vol20": vol20,
        "vol_ratio": vol_ratio, "stoch_k": stoch_k, "stoch_d": stoch_d,
        "v_ratio": v_ratio, "v_ratio5": v_ratio5, "pv_mom": pv_mom, "obv_mom": obv_mom,
        "beta20": beta20, "roll_corr": roll_corr, "idio1": idio1, "idio5": idio5,
        "idio_v": idio_v, "ret1_rank": ret1_rank, "ret5_rank": ret5_rank,
        "ret20_rank": ret20_rank, "vol_rank": vol_rank, "rel_str5": rel_str5,
        "rel_str20": rel_str20, "zscore20": zscore20, "fwd_ret1": fwd_ret1,
    }

    long = {}
    for name, frame in feature_frames.items():
        stacked = frame.stack()
        stacked.index.names = ["date", "ticker"]
        long[name] = stacked

    df = pd.DataFrame(long).reset_index()

    market_trend_df = mkt_trend.rename("mkt_trend").reset_index()
    market_trend_df.columns = ["date", "mkt_trend"]
    market_rsi_df = mkt_rsi14.rename("mkt_rsi14").reset_index()
    market_rsi_df.columns = ["date", "mkt_rsi14"]

    df = df.merge(market_trend_df, on="date", how="left")
    df = df.merge(market_rsi_df, on="date", how="left")

    all_dates = sorted(df["date"].unique())
    if len(all_dates) <= min_history:
        raise RuntimeError("No hay suficientes datos historicos para V39.")

    min_date = all_dates[min_history]
    df = df[df["date"] >= min_date].copy()

    df["target"] = df.groupby("date")["fwd_ret1"].transform(
        lambda series: (series >= series.quantile(0.90)).astype(int)
    )

    feat_cols = [col for col in df.columns if col not in ["date", "ticker", "fwd_ret1", "target"]]
    df[feat_cols] = df[feat_cols].replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=feat_cols).copy()

    return df, feat_cols


def detect_regime(market_s: pd.Series, market_ret_s: pd.Series) -> pd.Series:
    ma20 = market_s.rolling(20).mean()
    ma50 = market_s.rolling(50).mean()
    ret20 = market_s.pct_change(20)
    vol10 = market_ret_s.rolling(10).std() * np.sqrt(252)

    regime = pd.Series("Neutral", index=market_s.index)

    bull = (
        (market_s > ma20)
        & (ma20 > ma50 * 0.99)
        & (ret20 > 0.02)
        & (vol10 < vol10.rolling(60).quantile(0.65))
    )
    bear = (
        (market_s < ma20)
        & (ret20 < -0.02)
        & (vol10 > vol10.rolling(60).quantile(0.40))
    )
    regime[bull] = "Bull"
    regime[bear] = "Bear"
    return regime


def fit_models(train_df: pd.DataFrame, feat_cols: list[str]) -> tuple[tuple[object, object, object], RobustScaler]:
    global USED_HIST_FALLBACK

    scaler = RobustScaler()
    x_train = scaler.fit_transform(train_df[feat_cols].values)
    y_train = train_df["target"].values

    m1 = HistGradientBoostingClassifier(
        max_iter=150,
        max_depth=4,
        learning_rate=0.06,
        min_samples_leaf=15,
        random_state=42,
    )
    m2 = RandomForestClassifier(
        n_estimators=80,
        max_depth=6,
        min_samples_leaf=12,
        max_features="sqrt",
        n_jobs=1,
        random_state=42,
    )
    m3 = ExtraTreesClassifier(
        n_estimators=80,
        max_depth=7,
        min_samples_leaf=10,
        max_features="sqrt",
        n_jobs=1,
        random_state=42,
    )

    # HistGradientBoosting intenta abrir un ThreadPool incluso con 1 hilo
    # en este entorno Windows. Intentamos medirlo; si falla por permisos,
    # degradamos a GradientBoosting serial para no bloquear la auditoria.
    try:
        with parallel_backend("sequential"):
            m1.fit(x_train, y_train)
    except PermissionError:
        USED_HIST_FALLBACK = True
        m1 = GradientBoostingClassifier(
            n_estimators=150,
            learning_rate=0.06,
            max_depth=3,
            min_samples_leaf=15,
            random_state=42,
        )
        m1.fit(x_train, y_train)
    m2.fit(x_train, y_train)
    m3.fit(x_train, y_train)

    return (m1, m2, m3), scaler


def score_ml(te: pd.DataFrame, feat_cols: list[str], models: tuple[object, object, object], scaler: RobustScaler) -> pd.Series:
    x_test = scaler.transform(te[feat_cols].values)
    m1, m2, m3 = models
    prob = (
        m1.predict_proba(x_test)[:, 1]
        + m2.predict_proba(x_test)[:, 1]
        + m3.predict_proba(x_test)[:, 1]
    ) / 3.0
    return pd.Series(prob, index=te.index)


def add_cross_sectional_ranks(te: pd.DataFrame, col: str, ascending: bool) -> pd.Series:
    if ascending:
        return te[col].rank(method="average", pct=True, ascending=False)
    return te[col].rank(method="average", pct=True, ascending=True)


def select_baseline(te: pd.DataFrame, name: str, k: int) -> tuple[list[str], pd.Series]:
    frame = te.copy()

    if name == "ret20_reversal":
        frame["score"] = -frame["ret20"]
    elif name == "rel20_reversal":
        frame["score"] = -frame["rel_str20"]
    elif name == "vol_rank":
        frame["score"] = frame["vol_rank"]
    elif name == "beta20":
        frame["score"] = frame["beta20"]
    elif name == "rev_vol_combo":
        beta_rank = frame["beta20"].rank(method="average", pct=True)
        frame["score"] = (1.0 - frame["ret20_rank"]) + frame["vol_rank"] + beta_rank
    else:
        raise ValueError(f"Baseline desconocido: {name}")

    chosen = frame.nlargest(k, "score")
    return chosen["ticker"].tolist(), chosen.set_index("ticker")["score"]


def evaluate_day(te: pd.DataFrame, picked: list[str], date: pd.Timestamp, regime: str, label: str) -> dict[str, object]:
    actual_top = te.nlargest(len(picked), "fwd_ret1")["ticker"].tolist()
    picked_set = set(picked)
    hits = sum(1 for ticker in picked if ticker in set(actual_top))
    pred_ret = te[te["ticker"].isin(picked_set)]["fwd_ret1"].mean()
    rand_ret = te["fwd_ret1"].mean()

    return {
        "model": label,
        "date": date,
        "regime": regime,
        "k": len(picked),
        "hits": hits,
        "precision": hits / len(picked) if picked else np.nan,
        "pred_ret": pred_ret,
        "excess_ret": pred_ret - rand_ret,
        "pred_top3": picked[:3],
        "picks": tuple(picked),
    }


def run_evaluation(
    df: pd.DataFrame,
    feat_cols: list[str],
    market_s: pd.Series,
    market_ret_s: pd.Series,
    days: int | None,
    use_regime_k: bool,
    baselines: list[str],
) -> pd.DataFrame:
    all_dates = sorted(df["date"].unique())
    regime_series = detect_regime(market_s, market_ret_s)

    if days is None:
        test_dates = all_dates[MIN_TRAIN_DAYS:-2]
    else:
        test_dates = all_dates[-(days + 2):-2]

    rows: list[dict[str, object]] = []
    models: tuple[object, object, object] | None = None
    scaler: RobustScaler | None = None

    for idx, test_date in enumerate(test_dates):
        if idx % RETRAIN_EVERY == 0:
            avail = [day for day in all_dates if day < test_date]
            if len(avail) < MIN_TRAIN_DAYS:
                continue
            train_df = df[df["date"].isin(avail)].dropna(subset=feat_cols + ["target"]).copy()
            models, scaler = fit_models(train_df, feat_cols)

        if models is None or scaler is None:
            continue

        te = df[df["date"] == test_date].dropna(subset=feat_cols).copy()
        if len(te) < TOP_K:
            continue

        regime = regime_series.get(test_date, "Neutral")
        k = TOP_K
        if use_regime_k and regime == "Bear":
            k = max(TOP_K // 2, 5)

        te["ml_score"] = score_ml(te, feat_cols, models, scaler)
        ml_picks = te.nlargest(k, "ml_score")["ticker"].tolist()
        rows.append(evaluate_day(te, ml_picks, test_date, regime, "ml"))

        for baseline in baselines:
            picks, _ = select_baseline(te, baseline, k)
            rows.append(evaluate_day(te, picks, test_date, regime, baseline))

    return pd.DataFrame(rows)


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    grouped = []
    for model, subset in results.groupby("model"):
        grouped.append(
            {
                "model": model,
                "days": len(subset),
                "precision": subset["precision"].mean(),
                "hit_ge1": (subset["hits"] > 0).mean(),
                "pred_ret": subset["pred_ret"].mean(),
                "excess_ret": subset["excess_ret"].mean(),
                "best_day": subset["pred_ret"].max(),
                "worst_day": subset["pred_ret"].min(),
                "cum_excess": subset["excess_ret"].sum(),
            }
        )

    out = pd.DataFrame(grouped)
    return out.sort_values(["excess_ret", "precision"], ascending=False).reset_index(drop=True)


def summarize_regime(results: pd.DataFrame, model_name: str) -> pd.DataFrame:
    subset = results[results["model"] == model_name].copy()
    if subset.empty:
        return pd.DataFrame()

    rows = []
    for regime, frame in subset.groupby("regime"):
        rows.append(
            {
                "regime": regime,
                "days": len(frame),
                "precision": frame["precision"].mean(),
                "pred_ret": frame["pred_ret"].mean(),
                "excess_ret": frame["excess_ret"].mean(),
            }
        )
    return pd.DataFrame(rows).sort_values("regime").reset_index(drop=True)


def train_importance_snapshot(df: pd.DataFrame, feat_cols: list[str], test_days: int = 60) -> pd.Series:
    all_dates = sorted(df["date"].unique())
    test_dates = all_dates[-(test_days + 2):-2]
    cutoff = test_dates[0]
    train_df = df[df["date"] < cutoff].dropna(subset=feat_cols + ["target"]).copy()
    x_train = RobustScaler().fit_transform(train_df[feat_cols].values)
    y_train = train_df["target"].values

    rf = RandomForestClassifier(
        n_estimators=120,
        max_depth=6,
        min_samples_leaf=12,
        max_features="sqrt",
        n_jobs=1,
        random_state=42,
    )
    et = ExtraTreesClassifier(
        n_estimators=120,
        max_depth=7,
        min_samples_leaf=10,
        max_features="sqrt",
        n_jobs=1,
        random_state=42,
    )
    rf.fit(x_train, y_train)
    et.fit(x_train, y_train)

    fi = (
        pd.Series(rf.feature_importances_, index=feat_cols)
        + pd.Series(et.feature_importances_, index=feat_cols)
    ) / 2.0
    return fi.sort_values(ascending=False)


def overlap_vs_baseline(results: pd.DataFrame, baseline: str) -> pd.DataFrame:
    ml = results[results["model"] == "ml"][["date", "picks"]].copy().rename(columns={"picks": "ml_picks"})
    base = results[results["model"] == baseline][["date", "picks"]].copy().rename(columns={"picks": "base_picks"})
    merged = ml.merge(base, on="date", how="inner")
    merged["overlap"] = merged.apply(
        lambda row: len(set(row["ml_picks"]).intersection(set(row["base_picks"]))),
        axis=1,
    )
    return merged[["date", "overlap"]]


def print_summary(title: str, summary_df: pd.DataFrame) -> None:
    print()
    print("=" * 100)
    print(f"  {title}")
    print("=" * 100)
    print(
        f"  {'Modelo':<18} {'Dias':>5} {'Prec':>7} {'Hit>=1':>8} "
        f"{'PredRet':>9} {'Excess':>9} {'Best':>9} {'Worst':>9} {'CumEx':>9}"
    )
    print("  " + "-" * 92)
    for _, row in summary_df.iterrows():
        print(
            f"  {row['model']:<18} {int(row['days']):>5d} {row['precision']*100:>6.1f}% "
            f"{row['hit_ge1']*100:>7.1f}% {row['pred_ret']*100:>+8.3f}% "
            f"{row['excess_ret']*100:>+8.3f}% {row['best_day']*100:>+8.2f}% "
            f"{row['worst_day']*100:>+8.2f}% {row['cum_excess']*100:>+8.2f}%"
        )


def print_regime(title: str, regime_df: pd.DataFrame) -> None:
    print()
    print(title)
    print("  " + "-" * 58)
    for _, row in regime_df.iterrows():
        print(
            f"  {row['regime']:<8} dias={int(row['days']):>3d} "
            f"prec={row['precision']*100:>5.1f}% pred_ret={row['pred_ret']*100:>+6.3f}% "
            f"excess={row['excess_ret']*100:>+6.3f}%"
        )


def print_tail(results: pd.DataFrame, model_name: str, days: int = 10) -> None:
    subset = results[results["model"] == model_name].sort_values("date").tail(days)
    print()
    print(f"Ultimos {days} dias de {model_name}:")
    print("  " + "-" * 92)
    for _, row in subset.iterrows():
        top3 = ", ".join(row["pred_top3"])
        print(
            f"  {row['date'].date()} regime={row['regime']:<7} k={int(row['k'])} "
            f"hits={int(row['hits'])}/{int(row['k'])} prec={row['precision']*100:>4.0f}% "
            f"pred={row['pred_ret']*100:>+6.2f}% excess={row['excess_ret']*100:>+6.2f}% "
            f"top3=[{top3}]"
        )


def main() -> None:
    print()
    print("=" * 100)
    print("  AUDITORIA ML_TRADING_V39")
    print("=" * 100)
    print(f"  Fuente auditada : {SOURCE_PATH}")
    print(f"  Base usada      : {DB_PATH}")

    price_df, volume_df, market_s, market_ret, common, missing = load_panel()

    print()
    print("Universo:")
    print(f"  Tickers V39 originales : {len(V39_TICKERS)}")
    print(f"  Tickers presentes DB   : {len(common)}")
    print(f"  Faltantes DB           : {len(missing)}")
    print(f"  Rango fechas DB        : {price_df.index.min().date()} -> {price_df.index.max().date()}")
    if missing:
        print(f"  Faltantes              : {', '.join(missing)}")

    df, feat_cols = build_features(price_df, volume_df, market_s, market_ret)
    print()
    print("Dataset reproducido:")
    print(f"  Filas                  : {len(df):,}")
    print(f"  Features               : {len(feat_cols)}")
    print(f"  Rango features         : {df['date'].min().date()} -> {df['date'].max().date()}")

    baselines = ["ret20_reversal", "rel20_reversal", "vol_rank", "beta20", "rev_vol_combo"]

    results_60 = run_evaluation(
        df=df,
        feat_cols=feat_cols,
        market_s=market_s,
        market_ret_s=market_ret,
        days=60,
        use_regime_k=False,
        baselines=baselines,
    )
    results_60_regimek = run_evaluation(
        df=df,
        feat_cols=feat_cols,
        market_s=market_s,
        market_ret_s=market_ret,
        days=60,
        use_regime_k=True,
        baselines=baselines,
    )
    results_full = run_evaluation(
        df=df,
        feat_cols=feat_cols,
        market_s=market_s,
        market_ret_s=market_ret,
        days=None,
        use_regime_k=False,
        baselines=baselines,
    )

    if USED_HIST_FALLBACK:
        print()
        print("Nota entorno:")
        print("  HistGradientBoosting fallo por permisos/thread-pool en Windows.")
        print("  La auditoria uso GradientBoosting serial como reemplazo controlado.")

    print_summary("BACKTEST ULTIMOS 60 DIAS - REGLA ORIGINAL DE QUICK_BACKTEST", summarize(results_60))
    print_summary("BACKTEST ULTIMOS 60 DIAS - VARIANTE CON K AJUSTADO POR REGIMEN", summarize(results_60_regimek))
    print_summary("WALK-FORWARD COMPLETO DISPONIBLE", summarize(results_full))

    print_regime("Desglose por regimen - modelo ML (60 dias)", summarize_regime(results_60, "ml"))
    print_regime("Desglose por regimen - modelo ML (full)", summarize_regime(results_full, "ml"))

    fi = train_importance_snapshot(df, feat_cols, test_days=60)
    print()
    print("Top 15 importancias promedio RF/ET antes del test de 60 dias:")
    print("  " + "-" * 58)
    for feat, imp in fi.head(15).items():
        print(f"  {feat:<14} {imp:>8.5f}")

    overlap = overlap_vs_baseline(results_60, "rev_vol_combo")
    if not overlap.empty:
        print()
        print("Solapamiento ML vs rev_vol_combo (60 dias):")
        print("  " + "-" * 58)
        print(f"  Overlap medio picks/dia : {overlap['overlap'].mean():.2f} de {TOP_K}")
        print(f"  Overlap mediano         : {overlap['overlap'].median():.2f}")
        print(f"  Overlap maximo          : {overlap['overlap'].max():.0f}")

    print_tail(results_60, "ml", 10)
    print_tail(results_60, "rev_vol_combo", 10)

    print()
    print("Lectura tentativa:")
    print("  - Si un baseline simple iguala o supera al ML, el ensemble no merece portarse a produccion.")
    print("  - Si el ML solo vive en Bear/Neutral, no es un modelo generalista; es un detector situacional.")
    print("  - Si el mejor baseline mezcla debilidad 20d + volatilidad/beta, ahi puede haber una hipotesis rescatable.")


if __name__ == "__main__":
    main()
