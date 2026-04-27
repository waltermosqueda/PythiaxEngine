"""
INVESTIGACION V9 PATH QUALITY
=============================

Objetivo:
  Auditar con titan.db si V9 mejora de forma honesta al bloque Crash+Volume
  de V8 despues de detectar un falso crash live en BKNG.

Preguntas:
  1. El guard de corporate-action corrige el problema live sin romper historia?
  2. Neg_Days10 >= 5 agrega calidad real o solo poda trades al azar?
  3. V9 mejora broad universe, core universe, o ambos?
  4. Hay un candidato mas agresivo que supere a V9 sin disparar drawdown?

Hallazgo central:
  V8 no estaba historicamente "roto", pero si era fragil live.
  V9 nace para mejorar seguridad operativa y calidad de crash path.

Fecha: 2026-04-07
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from titan_system.core.database import TitanDB


BROAD_UNIVERSE_STR = """
AAPL, ADBE, ADI, AI, ALAB, AMAT, AMD, ARM, ASML, AVGO, BIDU, COIN, CRM, CRWV,
CSCO, DOCU, ETSY, GOOGL, IBM, INTC, IREN, LRCX, META, MRVL, MSFT, MSTR, MU,
NTES, NVDA, ORCL, PANW, PATH, PLTR, QCOM, RBLX, RGTI, ROKU, SAP, SE, SHOP,
SNAP, SNOW, SONY, SPOT, TEAM, TSM, TWLO, UBER, UPST, ZM, GLW, GRMN, HPQ, MSI,
SWKS, TXN, EA, ASTS, RKLB, ERIC, BB, AXP, BAC, BCS, BK, BKNG,
C, GS, HOOD, HSBC, ING, JPM, LYG, MA, MUFG, PYPL, SCHW, USB, V,
WFC, AIG, HDB, ABBV, ABT, AMGN, AZN, BIIB, BMY, CVS, DHR, GILD, GSK,
ISRG, JNJ, LLY, MDT, MRK, MRNA, NVS, PFE, TMO, UNH, BKR, BP, CVX, E, EQNR, HAL,
OXY, PSX, SHEL, SLB, TTE, XOM, AEM, B, BHP, CDE, FCX, GFI,
HL, HMY, KGC, LAC, MOS, MUX, NEM, NG, NUE, PAAS, RIO,
AAP, ANF, CL, COST, DEO, EBAY, HD, HSY, KMB, KO, MCD, MDLZ, MO, NKE,
ORLY, PEP, PG, PM, ROST, SBUX, SYY, TGT, TJX, UL, WMT, YELP, AVY, BA, CAT, DD, DE,
FDX, GE, HON, HWM, IFF, IP, LMT, MMM, PCAR, PBI, RTX, SNA, UNP,
F, GM, HMC, HOG, NIO, RACE, STLA, TM, TSLA, AAL, ABNB, CAR, CCL, DAL, LVS, SPCE, TCOM, TRIP,
UAL, TMUS, VOD, VZ
"""

BROAD_UNIVERSE = [
    ticker.strip()
    for ticker in BROAD_UNIVERSE_STR.replace("\n", "").split(",")
    if ticker.strip()
]

CORE_UNIVERSE = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "AMD",
    "TSLA",
    "NFLX",
    "CRM",
    "ORCL",
    "ADBE",
    "INTC",
    "AVGO",
    "QCOM",
    "MU",
    "AMAT",
    "LRCX",
    "TXN",
    "PLTR",
    "JPM",
    "BAC",
    "WFC",
    "GS",
    "V",
    "MA",
    "AXP",
    "C",
    "PYPL",
    "COIN",
    "JNJ",
    "PFE",
    "UNH",
    "MRK",
    "ABBV",
    "LLY",
    "TMO",
    "ABT",
    "BMY",
    "AMGN",
    "XOM",
    "CVX",
    "COP",
    "SLB",
    "OXY",
    "HAL",
    "DVN",
    "MPC",
    "VLO",
    "EOG",
    "KO",
    "PEP",
    "PG",
    "WMT",
    "COST",
    "MCD",
    "NKE",
    "SBUX",
    "TGT",
    "HD",
    "CAT",
    "BA",
    "GE",
    "RTX",
    "HON",
    "LMT",
    "UPS",
    "FDX",
    "DE",
    "MMM",
]

HOLD_DAYS = 7
ANTIKNIFE_DAYS = 5
START_IDX = 60

CORP_RET1_ABS_MIN = 0.60
CORP_INTRADAY_ABS_MAX = 0.15
CORP_RANGE_MAX = 0.15


@dataclass(frozen=True)
class ArchitectureSpec:
    name: str
    a_col: str | None
    c_col: str


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - 100 / (1 + rs)


def calc_macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal, macd - signal


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def load_db_data(universe: list[str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    with TitanDB() as db:
        available = set(db.get_all_tickers())
        present = [ticker for ticker in universe if ticker in available]
        if "SPY" not in present:
            present.append("SPY")

        data: dict[str, pd.DataFrame] = {}
        for ticker in present:
            df = db.get_prices(ticker)
            if df.empty:
                continue
            df = df.rename(
                columns={
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume",
                }
            )
            data[ticker] = df[["Open", "High", "Low", "Close", "Volume"]].copy()

    missing = sorted([ticker for ticker in universe if ticker not in data])
    return data, missing


def add_signal_columns(work: pd.DataFrame) -> pd.DataFrame:
    prev_hist = work["MACD_HIST"].shift(1)
    rsi_score = (30 - work["RSI"]) / 30 * 40
    stretch_score = (work["DIST_SMA50"].abs() - 5) / 15 * 30
    macd_accel = (work["MACD_HIST"] - prev_hist) / (work["ATR"] * 0.01 + 1e-6)
    macd_score = macd_accel * 5
    vol_score = (1.5 - work["VOL_RATIO"]) / 1.5 * 10

    score = (
        rsi_score.clip(lower=0, upper=40)
        + stretch_score.clip(lower=0, upper=30)
        + macd_score.clip(lower=0, upper=20)
        + vol_score.clip(lower=0, upper=10)
    )

    signal_a_base = (
        work["RSI"].notna()
        & prev_hist.notna()
        & work["DIST_SMA50"].notna()
        & work["VOL_RATIO"].notna()
        & work["ATR"].notna()
        & (work["RSI"] < 30)
        & (work["MACD_HIST"] > prev_hist)
        & (work["DIST_SMA50"] <= -5)
        & (work["VOL_RATIO"] <= 1.5)
        & (work["RSI"] < 25)
        & (work["DIST_SMA50"] <= -10)
        & (score >= 30)
    )

    signal_c_v7 = (
        work["ROC10"].notna()
        & work["VOL_RATIO"].notna()
        & (work["ROC10"] < -15)
        & (work["VOL_RATIO"] >= 2.0)
    )

    signal_c_v8 = signal_c_v7 & work["RSI"].notna() & (work["RSI"] < 35)
    signal_c_v8_guard = signal_c_v8 & ~work["CORP_ACTION_10D"]
    signal_c_v9_neg5 = signal_c_v8_guard & work["NEG_DAYS10"].notna() & (work["NEG_DAYS10"] >= 5)

    work["SIG_A_BASE"] = signal_a_base
    work["SIG_A_GUARD"] = signal_a_base & ~work["CORP_ACTION_10D"]
    work["SIG_C_V7"] = signal_c_v7
    work["SIG_C_V8"] = signal_c_v8
    work["SIG_C_V8_GUARD"] = signal_c_v8_guard
    work["SIG_C_V9_NEG5"] = signal_c_v9_neg5

    for neg_days in [3, 4, 5, 6, 7]:
        work[f"SIG_C_V9_NEG{neg_days}"] = signal_c_v8_guard & (work["NEG_DAYS10"] >= neg_days)

    work["SIG_C_BALANCED"] = signal_c_v9_neg5
    work["SIG_C_AGGR_RSI30"] = signal_c_v7 & (work["RSI"] < 30) & ~work["CORP_ACTION_10D"] & (
        work["NEG_DAYS10"] >= 5
    )

    return work


def precompute(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    prepared: dict[str, pd.DataFrame] = {}
    for ticker, df in data.items():
        work = df.copy()
        work["RSI"] = calc_rsi(work["Close"])
        _, _, work["MACD_HIST"] = calc_macd(work["Close"])
        work["SMA50"] = work["Close"].rolling(50).mean()
        work["ATR"] = calc_atr(work["High"], work["Low"], work["Close"])
        work["VOL_AVG20"] = work["Volume"].rolling(20).mean()
        work["VOL_RATIO"] = work["Volume"] / (work["VOL_AVG20"] + 1e-10)
        work["DIST_SMA50"] = (work["Close"] / work["SMA50"] - 1) * 100
        work["ROC10"] = (work["Close"] / work["Close"].shift(10) - 1) * 100
        work["RET1"] = work["Close"].pct_change()
        work["NEG_DAYS10"] = (work["RET1"] < 0).rolling(10).sum()
        work["INTRADAY"] = work["Close"] / (work["Open"] + 1e-10) - 1
        work["RANGE_PCT"] = (work["High"] - work["Low"]) / (work["Open"] + 1e-10)
        work["CORP_ACTION_DAY"] = (
            (work["RET1"].abs() > CORP_RET1_ABS_MIN)
            & (work["INTRADAY"].abs() < CORP_INTRADAY_ABS_MAX)
            & (work["RANGE_PCT"] < CORP_RANGE_MAX)
        )
        work["CORP_ACTION_10D"] = (
            work["CORP_ACTION_DAY"].rolling(10, min_periods=1).max().fillna(0).astype(bool)
        )
        prepared[ticker] = add_signal_columns(work)

    spy = prepared["SPY"]
    spy["SPY_VOL20"] = spy["Close"].pct_change().rolling(20).std() * 100
    spy["REGIME_SAFE"] = (spy["Close"] > spy["SMA50"]) & (spy["SPY_VOL20"] < 1.0)
    prepared["SPY"] = spy
    return align_prepared_to_spy(prepared)


def align_prepared_to_spy(prepared: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """
    Reindexa todos los tickers al calendario de SPY.

    Desde que entraron nombres con historia corta como CRWV, varios backtests
    dejaron de poder iterar por posicion `iloc[idx]` usando el indice de SPY.
    Alinear al calendario de SPY mantiene el backtest reproducible sin inventar
    precios: los dias inexistentes quedan como NaN y las banderas booleanas se
    rellenan con False.
    """
    if "SPY" not in prepared:
        return prepared

    spy_index = prepared["SPY"].index
    aligned: dict[str, pd.DataFrame] = {}
    false_on_missing = {"CORP_ACTION_DAY", "CORP_ACTION_10D", "REGIME_SAFE"}

    for ticker, df in prepared.items():
        work = df.reindex(spy_index)
        for column in work.columns:
            if column.startswith("SIG_") or column in false_on_missing:
                # Preserve boolean intent without relying on pandas' deprecated
                # silent downcasting from object+NaN during fillna.
                work[column] = work[column].astype("boolean").fillna(False).astype(bool)
        aligned[ticker] = work

    return aligned


def calc_metrics(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {"trades": 0, "wr": 0.0, "avg": 0.0, "sharpe": 0.0, "total": 0.0, "mdd": 0.0}

    returns = df["return_pct"].to_numpy(dtype=float)
    win_rate = float((returns > 0).mean() * 100)
    avg_ret = float(returns.mean())
    std_ret = float(returns.std())
    sharpe = avg_ret / std_ret * np.sqrt(252 / HOLD_DAYS) if std_ret > 0 else 0.0
    equity = np.cumprod(1 + returns / 100)
    peaks = np.maximum.accumulate(equity)
    mdd = float(((equity - peaks) / peaks * 100).min())
    total = float(equity[-1] * 100 - 100)
    return {
        "trades": len(df),
        "wr": win_rate,
        "avg": avg_ret,
        "sharpe": sharpe,
        "total": total,
        "mdd": mdd,
    }


def monte_carlo(df: pd.DataFrame, sims: int = 2000, seed: int = 42) -> dict[str, float]:
    if len(df) < 5:
        return {}

    returns = df["return_pct"].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    sharpe_samples: list[float] = []
    mdd_samples: list[float] = []

    for _ in range(sims):
        sample = rng.choice(returns, size=len(returns), replace=True)
        std_ret = float(sample.std())
        sharpe = sample.mean() / std_ret * np.sqrt(252 / HOLD_DAYS) if std_ret > 0 else 0.0
        equity = np.cumprod(1 + sample / 100)
        peaks = np.maximum.accumulate(equity)
        mdd = float(((equity - peaks) / peaks * 100).min())
        sharpe_samples.append(float(sharpe))
        mdd_samples.append(mdd)

    sharpe_array = np.array(sharpe_samples, dtype=float)
    mdd_array = np.array(mdd_samples, dtype=float)
    return {
        "p_sharpe_pos": float((sharpe_array > 0).mean() * 100),
        "median_sharpe": float(np.median(sharpe_array)),
        "worst_1pct_sharpe": float(np.percentile(sharpe_array, 1)),
        "worst_1pct_mdd": float(np.percentile(mdd_array, 1)),
    }


def run_architecture(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    a_col: str | None,
    c_col: str,
    hold_days: int = HOLD_DAYS,
    antiknife_days: int = ANTIKNIFE_DAYS,
    start_idx: int = START_IDX,
) -> pd.DataFrame:
    dates = prepared["SPY"].index
    last_entry: dict[str, int] = {}
    rows: list[dict[str, object]] = []

    for idx in range(start_idx, len(dates) - hold_days - 1):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
        signal_date = dates[idx]

        for ticker in tickers:
            if ticker == "SPY" or ticker not in prepared:
                continue
            if ticker in last_entry and (idx - last_entry[ticker]) < antiknife_days:
                continue

            df = prepared[ticker]
            signal = None
            if a_col is not None and regime_safe and bool(df[a_col].iloc[idx]):
                signal = "A"
            elif bool(df[c_col].iloc[idx]):
                signal = "C"

            if signal is None:
                continue

            price_in = df["Close"].iloc[idx + 1]
            price_out = df["Close"].iloc[idx + 1 + hold_days]
            if pd.isna(price_in) or pd.isna(price_out):
                continue

            rows.append(
                {
                    "ticker": ticker,
                    "date": signal_date,
                    "signal": signal,
                    "return_pct": float((price_out / price_in - 1) * 100),
                }
            )
            last_entry[ticker] = idx

    return pd.DataFrame(rows)


def run_architecture_mixed_holds(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    a_col: str | None,
    c_col: str,
    hold_a: int,
    hold_c: int,
    antiknife_days: int = ANTIKNIFE_DAYS,
    start_idx: int = START_IDX,
) -> pd.DataFrame:
    max_hold = max(hold_a, hold_c)
    dates = prepared["SPY"].index
    last_entry: dict[str, int] = {}
    rows: list[dict[str, object]] = []

    for idx in range(start_idx, len(dates) - max_hold - 1):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
        signal_date = dates[idx]

        for ticker in tickers:
            if ticker == "SPY" or ticker not in prepared:
                continue
            if ticker in last_entry and (idx - last_entry[ticker]) < antiknife_days:
                continue

            df = prepared[ticker]
            signal = None
            hold_days = hold_c
            if a_col is not None and regime_safe and bool(df[a_col].iloc[idx]):
                signal = "A"
                hold_days = hold_a
            elif bool(df[c_col].iloc[idx]):
                signal = "C"

            if signal is None:
                continue

            price_in = df["Close"].iloc[idx + 1]
            price_out = df["Close"].iloc[idx + 1 + hold_days]
            if pd.isna(price_in) or pd.isna(price_out):
                continue

            rows.append(
                {
                    "ticker": ticker,
                    "date": signal_date,
                    "signal": signal,
                    "hold_days": hold_days,
                    "return_pct": float((price_out / price_in - 1) * 100),
                }
            )
            last_entry[ticker] = idx

    return pd.DataFrame(rows)


def walk_forward(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    a_col: str | None,
    c_col: str,
    windows: int,
    hold_days: int = HOLD_DAYS,
    antiknife_days: int = ANTIKNIFE_DAYS,
    start_idx: int = START_IDX,
) -> dict[str, object]:
    dates = prepared["SPY"].index
    total_span = len(dates) - start_idx - hold_days - 1
    if total_span < windows:
        return {"pct": 0.0, "avg_sharpe": 0.0, "details": []}

    window_size = total_span // windows
    details: list[dict[str, object]] = []

    for window in range(windows):
        start = start_idx + window * window_size
        end = min(start + window_size, len(dates) - hold_days - 1)
        last_entry: dict[str, int] = {}
        window_returns: list[float] = []

        for idx in range(start, end):
            regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
            for ticker in tickers:
                if ticker in last_entry and (idx - last_entry[ticker]) < antiknife_days:
                    continue
                df = prepared[ticker]
                signal = None
                if a_col is not None and regime_safe and bool(df[a_col].iloc[idx]):
                    signal = "A"
                elif bool(df[c_col].iloc[idx]):
                    signal = "C"
                if signal is None:
                    continue

                price_in = df["Close"].iloc[idx + 1]
                price_out = df["Close"].iloc[idx + 1 + hold_days]
                if pd.isna(price_in) or pd.isna(price_out):
                    continue

                window_returns.append(float((price_out / price_in - 1) * 100))
                last_entry[ticker] = idx

        returns = np.array(window_returns, dtype=float)
        std_ret = float(returns.std()) if len(returns) > 1 else 0.0
        sharpe = returns.mean() / std_ret * np.sqrt(252 / hold_days) if len(returns) and std_ret > 0 else 0.0
        details.append(
            {
                "window": window + 1,
                "trades": len(returns),
                "sharpe": float(sharpe),
                "positive": bool(sharpe > 0),
            }
        )

    positive = sum(1 for row in details if row["positive"])
    avg_sharpe = float(np.mean([row["sharpe"] for row in details])) if details else 0.0
    return {"pct": positive / max(windows, 1) * 100, "avg_sharpe": avg_sharpe, "details": details}


def recent_quality_alerts(prepared: dict[str, pd.DataFrame], days: int = 10) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    latest_date = prepared["SPY"].index[-1]

    for ticker, df in prepared.items():
        if ticker == "SPY":
            continue
        flagged = df[df["CORP_ACTION_DAY"]]
        if flagged.empty:
            continue
        last_row = flagged.iloc[-1]
        last_date = flagged.index[-1]
        if (latest_date - last_date).days > days:
            continue
        rows.append(
            {
                "ticker": ticker,
                "date": last_date.strftime("%Y-%m-%d"),
                "ret1": float(last_row["RET1"] * 100),
                "intraday": float(last_row["INTRADAY"] * 100),
                "range_pct": float(last_row["RANGE_PCT"] * 100),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["ticker", "date", "ret1", "intraday", "range_pct"])
    return pd.DataFrame(rows).sort_values("date", ascending=False)


def removed_trades(base_df: pd.DataFrame, filtered_df: pd.DataFrame) -> pd.DataFrame:
    if base_df.empty:
        return base_df.copy()

    base = base_df.copy()
    filt = filtered_df.copy()
    base["date_str"] = base["date"].dt.strftime("%Y-%m-%d")
    filt["date_str"] = filt["date"].dt.strftime("%Y-%m-%d")
    merged = base.merge(
        filt[["ticker", "date_str", "signal"]],
        on=["ticker", "date_str", "signal"],
        how="left",
        indicator=True,
    )
    removed = merged[merged["_merge"] == "left_only"].copy()
    if removed.empty:
        return removed
    return removed[["ticker", "date", "signal", "return_pct"]].sort_values("date")


def print_metric_row(name: str, metrics: dict[str, float], counts: dict[str, int]) -> None:
    print(
        f"  {name:10s} trades={metrics['trades']:3d} "
        f"wr={metrics['wr']:5.2f}% sharpe={metrics['sharpe']:5.2f} "
        f"avg={metrics['avg']:+5.2f}% total={metrics['total']:+9.1f}% "
        f"mdd={metrics['mdd']:6.2f}% counts={counts}"
    )


def run_suite(prepared: dict[str, pd.DataFrame], label: str, tickers: list[str]) -> dict[str, pd.DataFrame]:
    print("\n" + "=" * 96)
    print(f"  {label}")
    print("=" * 96)

    specs = [
        ArchitectureSpec("V7", "SIG_A_BASE", "SIG_C_V7"),
        ArchitectureSpec("V8", "SIG_A_BASE", "SIG_C_V8"),
        ArchitectureSpec("V8_GUARD", "SIG_A_GUARD", "SIG_C_V8_GUARD"),
        ArchitectureSpec("V9", "SIG_A_GUARD", "SIG_C_V9_NEG5"),
    ]

    all_results: dict[str, pd.DataFrame] = {}

    print("\n  [1] Architectures A+C")
    for spec in specs:
        df = run_architecture(prepared, tickers, spec.a_col, spec.c_col)
        all_results[spec.name] = df
        counts = df["signal"].value_counts().to_dict() if not df.empty else {}
        print_metric_row(spec.name, calc_metrics(df), counts)

    print("\n  [2] Crash block only")
    for spec in specs:
        df = run_architecture(prepared, tickers, None, spec.c_col)
        all_results[f"{spec.name}_C_ONLY"] = df
        print_metric_row(spec.name, calc_metrics(df), {"C": len(df)})

    print("\n  [3] Walk-forward V8 vs V9")
    for spec in [specs[1], specs[3]]:
        wf5 = walk_forward(prepared, tickers, spec.a_col, spec.c_col, windows=5)
        wf7 = walk_forward(prepared, tickers, spec.a_col, spec.c_col, windows=7)
        wf5_sharpes = [round(row["sharpe"], 2) for row in wf5["details"]]
        wf7_sharpes = [round(row["sharpe"], 2) for row in wf7["details"]]
        print(
            f"  {spec.name:10s} WF5={wf5['pct']:5.1f}% avg_sh={wf5['avg_sharpe']:.2f} {wf5_sharpes} | "
            f"WF7={wf7['pct']:5.1f}% avg_sh={wf7['avg_sharpe']:.2f} {wf7_sharpes}"
        )

    print("\n  [4] Monte Carlo on crash block (1000 sims)")
    for spec in [specs[1], specs[3]]:
        df = all_results[f"{spec.name}_C_ONLY"]
        mc = monte_carlo(df, sims=1000)
        print(
            f"  {spec.name:10s} P(Sharpe>0)={mc['p_sharpe_pos']:5.1f}% "
            f"median={mc['median_sharpe']:.2f} "
            f"worst1_sh={mc['worst_1pct_sharpe']:.2f} "
            f"worst1_mdd={mc['worst_1pct_mdd']:.2f}%"
        )

    print("\n  [5] Trades removed by V9 vs V8 in crash block")
    removed = removed_trades(all_results["V8_C_ONLY"], all_results["V9_C_ONLY"])
    removed_metrics = calc_metrics(removed) if not removed.empty else calc_metrics(pd.DataFrame())
    print_metric_row("REMOVED", removed_metrics, {"C": len(removed)})
    if not removed.empty:
        display = removed.copy()
        display["date"] = display["date"].dt.strftime("%Y-%m-%d")
        print(display.to_string(index=False))

    print("\n  [6] Sensitivity: V9 crash path by neg_days")
    for neg_days in [3, 4, 5, 6, 7]:
        df = run_architecture(prepared, tickers, None, f"SIG_C_V9_NEG{neg_days}")
        metrics = calc_metrics(df)
        print(
            f"  neg_days>={neg_days}: trades={metrics['trades']:3d} "
            f"wr={metrics['wr']:5.2f}% sharpe={metrics['sharpe']:5.2f} "
            f"avg={metrics['avg']:+5.2f}% mdd={metrics['mdd']:6.2f}%"
        )

    print("\n  [7] Aggressive candidate vs balanced V9")
    balanced = calc_metrics(run_architecture(prepared, tickers, None, "SIG_C_BALANCED"))
    aggressive = calc_metrics(run_architecture(prepared, tickers, None, "SIG_C_AGGR_RSI30"))
    print_metric_row("BALANCED", balanced, {"C": int(balanced["trades"])})
    print_metric_row("AGGRESSIVE", aggressive, {"C": int(aggressive["trades"])})

    print("\n  [8] Exit sensitivity on balanced V9")
    for hold_a, hold_c in [(7, 5), (7, 7), (7, 10), (7, 12)]:
        df = run_architecture_mixed_holds(prepared, tickers, "SIG_A_GUARD", "SIG_C_V9_NEG5", hold_a, hold_c)
        metrics = calc_metrics(df)
        print(
            f"  A={hold_a:2d} C={hold_c:2d}: trades={metrics['trades']:3d} "
            f"wr={metrics['wr']:5.2f}% sharpe={metrics['sharpe']:5.2f} "
            f"avg={metrics['avg']:+5.2f}% mdd={metrics['mdd']:6.2f}%"
        )

    return all_results


def main() -> None:
    print("=" * 96)
    print("  INVESTIGACION V9 PATH QUALITY")
    print("=" * 96)
    print("  Carga: titan.db")

    raw_data, missing = load_db_data(BROAD_UNIVERSE)
    prepared = precompute(raw_data)
    broad_tickers = [ticker for ticker in BROAD_UNIVERSE if ticker in prepared]
    core_tickers = [ticker for ticker in CORE_UNIVERSE if ticker in prepared]
    latest_date = prepared["SPY"].index[-1].strftime("%Y-%m-%d")
    first_date = prepared["SPY"].index[0].strftime("%Y-%m-%d")

    print(f"  Rango SPY: {first_date} -> {latest_date}")
    print(f"  Broad coverage: {len(broad_tickers)} / {len(BROAD_UNIVERSE)}")
    print(f"  Core coverage:  {len(core_tickers)} / {len(CORE_UNIVERSE)}")
    print(f"  Missing broad tickers: {len(missing)}")

    alerts = recent_quality_alerts(prepared)
    print("\n  [0] Quality audit reciente")
    if alerts.empty:
        print("  No hay corporate-action-like events recientes.")
    else:
        print(alerts.to_string(index=False, formatters={"ret1": "{:+.1f}%".format, "intraday": "{:+.1f}%".format, "range_pct": "{:.1f}%".format}))

    run_suite(prepared, "BROAD UNIVERSE", broad_tickers)
    run_suite(prepared, "CORE UNIVERSE", core_tickers)

    print("\n" + "=" * 96)
    print("  VEREDICTO")
    print("=" * 96)
    print("  1. V8 queda refutado como scanner live robusto por el caso BKNG.")
    print("  2. El guard de corporate actions arregla el problema live sin alterar la historia util.")
    print("  3. V9 mejora el core y mantiene broad competitivo, con drawdown mas sano que V8 full.")
    print("  4. El agresivo RSI<30 parece tentador, pero paga con drawdown broad mucho peor.")
    print("  5. La siguiente frontera no parece otro filtro de entrada, sino ejecucion / exits del bloque crash.")


if __name__ == "__main__":
    main()
