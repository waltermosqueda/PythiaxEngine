"""
INVESTIGACION V12 — VIX TERM STRUCTURE + ATR-ADAPTIVE EXIT
===========================================================
Dos hipotesis nuevas que nadie testeo:

1. VIX TERM STRUCTURE (VIX/VIX3M ratio):
   - Ratio > 1 = backwardation = panico real (instituciones cubriendo)
   - Ratio < 1 = contango = mercado tranquilo
   - Hipotesis: Signal C en backwardation tiene MEJOR recovery
     porque el panico es genuino y reversible, no structural decay

2. ATR-ADAPTIVE TAKE PROFIT:
   - V10 usa +6% fijo para TP temprano
   - Hipotesis: usar 2x ATR(14) como TP adaptativo captura mejor
     la naturaleza del activo (NVDA necesita mas espacio que KO)
   - Ejemplo: si ATR es 3%, TP = 6%. Si ATR es 5%, TP = 10%

Pipeline: titan.db + yfinance para VIX data -> backtest -> WF -> MC -> veredicto

Fecha: 2026-04-07
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import warnings

warnings.filterwarnings('ignore')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from titan_system.core.database import TitanDB

# ══════════════════════════════════════════════════════════════════════════════
# UNIVERSOS (mismos que V9/V10 backtests)
# ══════════════════════════════════════════════════════════════════════════════

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

BROAD_UNIVERSE = [t.strip() for t in BROAD_UNIVERSE_STR.replace("\n", "").split(",") if t.strip()]

CORE_UNIVERSE = [
    "AAPL","MSFT","GOOGL","AMZN","META","NVDA","AMD","TSLA","NFLX","CRM",
    "ORCL","ADBE","INTC","AVGO","QCOM","MU","AMAT","LRCX","TXN","PLTR",
    "JPM","BAC","WFC","GS","V","MA","AXP","C","PYPL","COIN",
    "JNJ","PFE","UNH","MRK","ABBV","LLY","TMO","ABT","BMY","AMGN",
    "XOM","CVX","COP","SLB","OXY","HAL","DVN","MPC","VLO","EOG",
    "KO","PEP","PG","WMT","COST","MCD","NKE","SBUX","TGT","HD",
    "CAT","BA","GE","RTX","HON","LMT","UPS","FDX","DE","MMM",
]

# ══════════════════════════════════════════════════════════════════════════════
# INDICADORES
# ══════════════════════════════════════════════════════════════════════════════

HOLD_DAYS = 7
ANTIKNIFE_DAYS = 5
START_IDX = 60

# Corporate action guard
CORP_RET1_ABS_MIN = 0.60
CORP_INTRADAY_ABS_MAX = 0.15
CORP_RANGE_MAX = 0.15


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI Wilder's smoothing — ewm(com=13, adjust=False). NUNCA rolling."""
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


# ══════════════════════════════════════════════════════════════════════════════
# CARGA DE DATOS
# ══════════════════════════════════════════════════════════════════════════════

def load_db_data(universe: list[str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    with TitanDB() as db:
        available = set(db.get_all_tickers())
        present = [t for t in universe if t in available]
        if "SPY" not in present:
            present.append("SPY")

        data = {}
        for ticker in present:
            df = db.get_prices(ticker)
            if df.empty:
                continue
            df = df.rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"})
            data[ticker] = df[["Open","High","Low","Close","Volume"]].copy()

    missing = sorted([t for t in universe if t not in data])
    return data, missing


def load_vix_data(start: str = "2024-03-01", end: str = "2026-04-07") -> pd.DataFrame:
    """Descarga VIX y VIX3M de yfinance para calcular term structure."""
    print("  Descargando VIX y VIX3M...")
    vix = yf.download("^VIX", start=start, end=end, progress=False)
    vix3m = yf.download("^VIX3M", start=start, end=end, progress=False)

    if vix.empty or vix3m.empty:
        print("  WARNING: No se pudo descargar VIX o VIX3M")
        return pd.DataFrame()

    # Flatten MultiIndex if present
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    if isinstance(vix3m.columns, pd.MultiIndex):
        vix3m.columns = vix3m.columns.get_level_values(0)

    result = pd.DataFrame(index=vix.index)
    result["VIX"] = vix["Close"]
    result["VIX3M"] = vix3m["Close"].reindex(vix.index, method="ffill")
    result["VIX_RATIO"] = result["VIX"] / (result["VIX3M"] + 1e-10)
    result["VIX_BACKWARDATION"] = result["VIX_RATIO"] > 1.0

    print(f"  VIX data: {result.index[0].strftime('%Y-%m-%d')} -> {result.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Dias en backwardation: {result['VIX_BACKWARDATION'].sum()} / {len(result)} ({result['VIX_BACKWARDATION'].mean()*100:.1f}%)")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# PRECOMPUTE
# ══════════════════════════════════════════════════════════════════════════════

def precompute(data: dict[str, pd.DataFrame], vix_data: pd.DataFrame) -> dict[str, pd.DataFrame]:
    prepared = {}
    for ticker, df in data.items():
        work = df.copy()
        work["RSI"] = calc_rsi(work["Close"])
        _, _, work["MACD_HIST"] = calc_macd(work["Close"])
        work["SMA50"] = work["Close"].rolling(50).mean()
        work["ATR"] = calc_atr(work["High"], work["Low"], work["Close"])
        work["ATR_PCT"] = work["ATR"] / (work["Close"] + 1e-10) * 100
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
        work["CORP_ACTION_10D"] = work["CORP_ACTION_DAY"].rolling(10, min_periods=1).max().fillna(0).astype(bool)

        # Merge VIX data
        if not vix_data.empty:
            work = work.join(vix_data[["VIX", "VIX_RATIO", "VIX_BACKWARDATION"]], how="left")
            work["VIX"] = work["VIX"].ffill()
            work["VIX_RATIO"] = work["VIX_RATIO"].ffill()
            work["VIX_BACKWARDATION"] = work["VIX_BACKWARDATION"].ffill().fillna(False)

        prepared[ticker] = work

    # SPY regime
    if "SPY" in prepared:
        spy = prepared["SPY"]
        spy["SPY_VOL20"] = spy["Close"].pct_change().rolling(20).std() * 100
        spy["REGIME_SAFE"] = (spy["Close"] > spy["SMA50"]) & (spy["SPY_VOL20"] < 1.0)
        prepared["SPY"] = spy

    return prepared


# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════════

def add_signals(work: pd.DataFrame) -> pd.DataFrame:
    prev_hist = work["MACD_HIST"].shift(1)
    rsi_score = (30 - work["RSI"]) / 30 * 40
    stretch_score = (work["DIST_SMA50"].abs() - 5) / 15 * 30
    macd_accel = (work["MACD_HIST"] - prev_hist) / (work["ATR"] * 0.01 + 1e-6)
    macd_score = macd_accel * 5
    vol_score = (1.5 - work["VOL_RATIO"]) / 1.5 * 10
    score = (
        rsi_score.clip(lower=0, upper=40) + stretch_score.clip(lower=0, upper=30)
        + macd_score.clip(lower=0, upper=20) + vol_score.clip(lower=0, upper=10)
    )

    work["SIG_A"] = (
        work["RSI"].notna() & prev_hist.notna() & work["DIST_SMA50"].notna()
        & work["VOL_RATIO"].notna() & work["ATR"].notna()
        & (work["RSI"] < 30) & (work["MACD_HIST"] > prev_hist)
        & (work["DIST_SMA50"] <= -5) & (work["VOL_RATIO"] <= 1.5)
        & (work["RSI"] < 25) & (work["DIST_SMA50"] <= -10) & (score >= 30)
        & ~work["CORP_ACTION_10D"]
    )

    work["SIG_C"] = (
        work["ROC10"].notna() & work["VOL_RATIO"].notna() & work["RSI"].notna()
        & work["NEG_DAYS10"].notna()
        & (work["ROC10"] < -15) & (work["VOL_RATIO"] >= 2.0)
        & (work["RSI"] < 35) & (work["NEG_DAYS10"] >= 5)
        & ~work["CORP_ACTION_10D"]
    )

    return work


# ══════════════════════════════════════════════════════════════════════════════
# EXIT FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def exit_fixed(df: pd.DataFrame, idx: int, hold: int = 7) -> float | None:
    """Exit fijo a N dias."""
    entry_idx = idx + 1
    exit_idx = entry_idx + hold
    if exit_idx >= len(df):
        return None
    entry = df["Close"].iloc[entry_idx]
    exit_px = df["Close"].iloc[exit_idx]
    if pd.isna(entry) or pd.isna(exit_px):
        return None
    return float((exit_px / entry - 1) * 100)


def exit_v10(df: pd.DataFrame, idx: int, tp_pct: float = 6.0, tp_days: int = 4, hold: int = 7) -> tuple[float | None, bool]:
    """V10 exit: TP fijo a +tp_pct% en primeros tp_days, sino hold."""
    entry_idx = idx + 1
    if entry_idx + hold >= len(df):
        return None, False
    entry = df["Close"].iloc[entry_idx]
    if pd.isna(entry):
        return None, False

    for day in range(1, hold + 1):
        px = df["Close"].iloc[entry_idx + day]
        if pd.isna(px):
            return None, False
        ret = float((px / entry - 1) * 100)
        if day <= tp_days and ret >= tp_pct:
            return ret, True

    final = df["Close"].iloc[entry_idx + hold]
    if pd.isna(final):
        return None, False
    return float((final / entry - 1) * 100), False


def exit_atr_adaptive(df: pd.DataFrame, idx: int, atr_mult: float = 2.0, tp_days: int = 4, hold: int = 7) -> tuple[float | None, bool]:
    """ATR-adaptive exit: TP a atr_mult * ATR% en primeros tp_days, sino hold."""
    entry_idx = idx + 1
    if entry_idx + hold >= len(df):
        return None, False
    entry = df["Close"].iloc[entry_idx]
    atr_pct = df["ATR_PCT"].iloc[idx]
    if pd.isna(entry) or pd.isna(atr_pct):
        return None, False

    tp_pct = atr_mult * float(atr_pct)
    tp_pct = max(3.0, min(15.0, tp_pct))  # clamp between 3% and 15%

    for day in range(1, hold + 1):
        px = df["Close"].iloc[entry_idx + day]
        if pd.isna(px):
            return None, False
        ret = float((px / entry - 1) * 100)
        if day <= tp_days and ret >= tp_pct:
            return ret, True

    final = df["Close"].iloc[entry_idx + hold]
    if pd.isna(final):
        return None, False
    return float((final / entry - 1) * 100), False


# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def run_backtest(prepared, tickers, exit_func, label="", vix_filter=None):
    """
    Corre backtest con exit_func flexible.
    vix_filter: None (no filtro), 'backwardation', 'contango', 'high' (VIX>25)
    """
    dates = prepared["SPY"].index
    rows = []
    last_entry = {}

    for idx in range(START_IDX, len(dates) - HOLD_DAYS - 1):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])

        for ticker in tickers:
            if ticker == "SPY" or ticker not in prepared:
                continue
            if ticker in last_entry and (idx - last_entry[ticker]) < ANTIKNIFE_DAYS:
                continue

            df = prepared[ticker]
            signal = None

            if regime_safe and bool(df["SIG_A"].iloc[idx]):
                signal = "A"
            elif bool(df["SIG_C"].iloc[idx]):
                # Apply VIX filter if specified (only to Signal C)
                if vix_filter is not None and "VIX_BACKWARDATION" in df.columns:
                    vix_back = bool(df["VIX_BACKWARDATION"].iloc[idx]) if not pd.isna(df["VIX_BACKWARDATION"].iloc[idx]) else False
                    vix_val = float(df["VIX"].iloc[idx]) if not pd.isna(df["VIX"].iloc[idx]) else 20.0

                    if vix_filter == "backwardation" and not vix_back:
                        continue
                    elif vix_filter == "contango" and vix_back:
                        continue
                    elif vix_filter == "high" and vix_val < 25:
                        continue
                    elif vix_filter == "low" and vix_val >= 25:
                        continue

                signal = "C"

            if signal is None:
                continue

            if signal == "A":
                ret = exit_fixed(df, idx, hold=7)
                tp = False
            else:
                ret, tp = exit_func(df, idx)

            if ret is None:
                continue

            vix_val = float(df["VIX"].iloc[idx]) if "VIX" in df.columns and not pd.isna(df["VIX"].iloc[idx]) else None
            vix_ratio = float(df["VIX_RATIO"].iloc[idx]) if "VIX_RATIO" in df.columns and not pd.isna(df["VIX_RATIO"].iloc[idx]) else None

            rows.append({
                "ticker": ticker, "date": dates[idx], "signal": signal,
                "return_pct": ret, "tp_triggered": tp,
                "vix": vix_val, "vix_ratio": vix_ratio,
                "atr_pct": float(df["ATR_PCT"].iloc[idx]) if not pd.isna(df["ATR_PCT"].iloc[idx]) else None,
            })
            last_entry[ticker] = idx

    return pd.DataFrame(rows)


def calc_metrics(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"trades":0, "wr":0, "avg":0, "sharpe":0, "mdd":0, "pf":0}
    r = df["return_pct"].to_numpy(dtype=float)
    wr = float((r > 0).mean() * 100)
    avg = float(r.mean())
    std = float(r.std())
    sh = avg / std * np.sqrt(252/7) if std > 0 else 0
    eq = np.cumprod(1 + r/100)
    pk = np.maximum.accumulate(eq)
    mdd = float(((eq - pk) / pk * 100).min())
    wins = r[r > 0].sum()
    losses = abs(r[r < 0].sum())
    pf = wins / losses if losses > 0 else 99.0
    return {"trades":len(df), "wr":round(wr,1), "avg":round(avg,2), "sharpe":round(sh,2), "mdd":round(mdd,1), "pf":round(pf,2)}


def walk_forward(prepared, tickers, exit_func, windows=7, vix_filter=None):
    dates = prepared["SPY"].index
    total_span = len(dates) - START_IDX - HOLD_DAYS - 1
    if total_span < windows:
        return {"pct": 0, "avg_sh": 0, "details": []}

    window_size = total_span // windows
    details = []

    for w in range(windows):
        start = START_IDX + w * window_size
        end = min(start + window_size, len(dates) - HOLD_DAYS - 1)

        rows = []
        last_entry = {}
        for idx in range(start, end):
            regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
            for ticker in tickers:
                if ticker == "SPY" or ticker not in prepared:
                    continue
                if ticker in last_entry and (idx - last_entry[ticker]) < ANTIKNIFE_DAYS:
                    continue
                df = prepared[ticker]
                signal = None
                if regime_safe and bool(df["SIG_A"].iloc[idx]):
                    signal = "A"
                elif bool(df["SIG_C"].iloc[idx]):
                    if vix_filter is not None and "VIX_BACKWARDATION" in df.columns:
                        vix_back = bool(df["VIX_BACKWARDATION"].iloc[idx]) if not pd.isna(df["VIX_BACKWARDATION"].iloc[idx]) else False
                        vix_val = float(df["VIX"].iloc[idx]) if not pd.isna(df["VIX"].iloc[idx]) else 20
                        if vix_filter == "backwardation" and not vix_back:
                            continue
                        elif vix_filter == "high" and vix_val < 25:
                            continue
                    signal = "C"
                if signal is None:
                    continue

                if signal == "A":
                    ret = exit_fixed(df, idx, hold=7)
                    tp = False
                else:
                    ret, tp = exit_func(df, idx)
                if ret is None:
                    continue
                rows.append({"return_pct": ret})
                last_entry[ticker] = idx

        wdf = pd.DataFrame(rows)
        m = calc_metrics(wdf)
        details.append({"w": w+1, "n": m["trades"], "sh": m["sharpe"], "pos": m["sharpe"] > 0})

    pos = sum(d["pos"] for d in details)
    avg_sh = np.mean([d["sh"] for d in details if d["n"] > 0])
    return {"pct": round(pos/windows*100), "avg_sh": round(float(avg_sh), 2), "details": details}


def monte_carlo(df: pd.DataFrame, sims: int = 2000) -> dict:
    if len(df) < 5:
        return {}
    r = df["return_pct"].to_numpy(dtype=float)
    n = len(r)
    rng = np.random.default_rng(42)
    shs, mdds = [], []
    for _ in range(sims):
        s = rng.choice(r, n, replace=True)
        a = s.mean(); st = s.std()
        shs.append(a/st*np.sqrt(252/7) if st > 0 else 0)
        eq = np.cumprod(1 + s/100); pk = np.maximum.accumulate(eq)
        mdds.append(((eq-pk)/pk*100).min())
    return {
        "p_sh": round(np.mean([s>0 for s in shs])*100, 1),
        "med_sh": round(float(np.median(shs)), 2),
        "w1_sh": round(float(np.percentile(shs, 1)), 2),
        "w1_mdd": round(float(np.percentile(mdds, 1)), 1),
    }


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 96)
    print("  INVESTIGACION V12 — VIX TERM STRUCTURE + ATR-ADAPTIVE EXIT")
    print("  Dos hipotesis nuevas que nadie testeo aun")
    print("=" * 96)

    # Load data
    print("\n[1] Cargando datos...")
    data_broad, missing_b = load_db_data(BROAD_UNIVERSE)
    vix_data = load_vix_data()
    broad_tickers = [t for t in BROAD_UNIVERSE if t in data_broad]
    core_tickers = [t for t in CORE_UNIVERSE if t in data_broad]
    print(f"  Broad: {len(broad_tickers)} tickers | Core: {len(core_tickers)} tickers")

    # Precompute
    print("\n[2] Calculando indicadores + VIX merge...")
    prepared = precompute(data_broad, vix_data)

    # Add signals
    for ticker in prepared:
        prepared[ticker] = add_signals(prepared[ticker])

    # ════════════════════════════════════════════════════════════════
    # PARTE 1: V10 BASELINE vs ATR-ADAPTIVE EXIT (sin VIX)
    # ════════════════════════════════════════════════════════════════

    for label, tickers in [("BROAD", broad_tickers), ("CORE", core_tickers)]:
        print("\n" + "=" * 96)
        print(f"  PARTE 1: EXIT COMPARISON — {label}")
        print("=" * 96)

        # V7 baseline (fixed 7d)
        v7 = run_backtest(prepared, tickers, lambda df, idx: (exit_fixed(df, idx, 7), False))
        # V10 (TP +6% <= 4d)
        v10 = run_backtest(prepared, tickers, lambda df, idx: exit_v10(df, idx, 6.0, 4, 7))
        # ATR adaptive 1.5x
        atr15 = run_backtest(prepared, tickers, lambda df, idx: exit_atr_adaptive(df, idx, 1.5, 4, 7))
        # ATR adaptive 2.0x
        atr20 = run_backtest(prepared, tickers, lambda df, idx: exit_atr_adaptive(df, idx, 2.0, 4, 7))
        # ATR adaptive 2.5x
        atr25 = run_backtest(prepared, tickers, lambda df, idx: exit_atr_adaptive(df, idx, 2.5, 4, 7))
        # V10 with TP +8% (wider)
        v10_8 = run_backtest(prepared, tickers, lambda df, idx: exit_v10(df, idx, 8.0, 4, 7))
        # V10 with TP +4% (tighter)
        v10_4 = run_backtest(prepared, tickers, lambda df, idx: exit_v10(df, idx, 4.0, 4, 7))

        models = [
            ("V7 (fixed 7d)", v7),
            ("V10 (TP+6% 4d)", v10),
            ("V10 (TP+4% 4d)", v10_4),
            ("V10 (TP+8% 4d)", v10_8),
            ("ATR 1.5x 4d", atr15),
            ("ATR 2.0x 4d", atr20),
            ("ATR 2.5x 4d", atr25),
        ]

        print(f"\n  {'Model':20s} {'Trades':>7s} {'WR':>7s} {'Sharpe':>8s} {'Avg':>8s} {'MDD':>8s} {'PF':>6s}")
        print(f"  {'-'*70}")
        for name, df in models:
            m = calc_metrics(df)
            flag = " ***" if m["sharpe"] > calc_metrics(v10)["sharpe"] else ""
            print(f"  {name:20s} {m['trades']:7d} {m['wr']:6.1f}% {m['sharpe']:8.2f} {m['avg']:+7.2f}% {m['mdd']:7.1f}% {m['pf']:5.2f}{flag}")

        # ATR distribution of Signal C trades
        c_trades = v10[v10["signal"] == "C"]
        if not c_trades.empty and "atr_pct" in c_trades.columns:
            atr_vals = c_trades["atr_pct"].dropna()
            print(f"\n  ATR% distribution of Signal C trades:")
            print(f"    Mean: {atr_vals.mean():.2f}% | Median: {atr_vals.median():.2f}% | "
                  f"P10: {atr_vals.quantile(0.1):.2f}% | P90: {atr_vals.quantile(0.9):.2f}%")
            # What fixed TP equivalent?
            print(f"    2x ATR median = {atr_vals.median()*2:.2f}% (vs V10 fixed 6%)")

    # ════════════════════════════════════════════════════════════════
    # PARTE 2: VIX TERM STRUCTURE ANALYSIS
    # ════════════════════════════════════════════════════════════════

    for label, tickers in [("BROAD", broad_tickers), ("CORE", core_tickers)]:
        print("\n" + "=" * 96)
        print(f"  PARTE 2: VIX TERM STRUCTURE — {label}")
        print("=" * 96)

        v10_base = run_backtest(prepared, tickers, lambda df, idx: exit_v10(df, idx, 6.0, 4, 7))
        v10_back = run_backtest(prepared, tickers, lambda df, idx: exit_v10(df, idx, 6.0, 4, 7), vix_filter="backwardation")
        v10_cont = run_backtest(prepared, tickers, lambda df, idx: exit_v10(df, idx, 6.0, 4, 7), vix_filter="contango")
        v10_high = run_backtest(prepared, tickers, lambda df, idx: exit_v10(df, idx, 6.0, 4, 7), vix_filter="high")
        v10_low = run_backtest(prepared, tickers, lambda df, idx: exit_v10(df, idx, 6.0, 4, 7), vix_filter="low")

        vix_models = [
            ("V10 (no filter)", v10_base),
            ("V10 + Backwardation", v10_back),
            ("V10 + Contango only", v10_cont),
            ("V10 + VIX > 25", v10_high),
            ("V10 + VIX < 25", v10_low),
        ]

        print(f"\n  {'Model':25s} {'Trades':>7s} {'WR':>7s} {'Sharpe':>8s} {'Avg':>8s} {'MDD':>8s} {'PF':>6s}")
        print(f"  {'-'*75}")
        for name, df in vix_models:
            m = calc_metrics(df)
            print(f"  {name:25s} {m['trades']:7d} {m['wr']:6.1f}% {m['sharpe']:8.2f} {m['avg']:+7.2f}% {m['mdd']:7.1f}% {m['pf']:5.2f}")

        # Analyze C trades by VIX regime
        c_all = v10_base[v10_base["signal"] == "C"]
        if not c_all.empty and "vix_ratio" in c_all.columns:
            c_back = c_all[c_all["vix_ratio"] > 1.0]
            c_cont = c_all[c_all["vix_ratio"] <= 1.0]
            print(f"\n  Signal C trades by VIX regime:")
            if not c_back.empty:
                mb = calc_metrics(c_back)
                print(f"    Backwardation (VIX>VIX3M): {mb['trades']} trades | WR {mb['wr']}% | Avg {mb['avg']:+.2f}% | Sharpe {mb['sharpe']}")
            if not c_cont.empty:
                mc = calc_metrics(c_cont)
                print(f"    Contango (VIX<VIX3M):      {mc['trades']} trades | WR {mc['wr']}% | Avg {mc['avg']:+.2f}% | Sharpe {mc['sharpe']}")

    # ════════════════════════════════════════════════════════════════
    # PARTE 3: WALK-FORWARD del mejor candidato
    # ════════════════════════════════════════════════════════════════

    print("\n" + "=" * 96)
    print("  PARTE 3: WALK-FORWARD + MONTE CARLO")
    print("=" * 96)

    for label, tickers in [("BROAD", broad_tickers), ("CORE", core_tickers)]:
        print(f"\n  --- {label} ---")

        # V10 baseline WF
        wf_v10 = walk_forward(prepared, tickers, lambda df, idx: exit_v10(df, idx, 6.0, 4, 7), windows=7)
        print(f"  V10 (TP+6%)     WF7={wf_v10['pct']}% avg_sh={wf_v10['avg_sh']} {[d['sh'] for d in wf_v10['details']]}")

        # Best ATR candidate
        wf_atr20 = walk_forward(prepared, tickers, lambda df, idx: exit_atr_adaptive(df, idx, 2.0, 4, 7), windows=7)
        print(f"  ATR 2.0x        WF7={wf_atr20['pct']}% avg_sh={wf_atr20['avg_sh']} {[d['sh'] for d in wf_atr20['details']]}")

        wf_atr15 = walk_forward(prepared, tickers, lambda df, idx: exit_atr_adaptive(df, idx, 1.5, 4, 7), windows=7)
        print(f"  ATR 1.5x        WF7={wf_atr15['pct']}% avg_sh={wf_atr15['avg_sh']} {[d['sh'] for d in wf_atr15['details']]}")

        # VIX backwardation
        wf_vix = walk_forward(prepared, tickers, lambda df, idx: exit_v10(df, idx, 6.0, 4, 7), windows=7, vix_filter="backwardation")
        print(f"  V10+Backward    WF7={wf_vix['pct']}% avg_sh={wf_vix['avg_sh']} {[d['sh'] for d in wf_vix['details']]}")

        # MC on best
        print(f"\n  Monte Carlo (2000 sims):")
        v10_full = run_backtest(prepared, tickers, lambda df, idx: exit_v10(df, idx, 6.0, 4, 7))
        mc_v10 = monte_carlo(v10_full)
        print(f"  V10:      P(Sh>0)={mc_v10.get('p_sh',0)}% Med={mc_v10.get('med_sh',0)} W1%={mc_v10.get('w1_sh',0)} W1%MDD={mc_v10.get('w1_mdd',0)}%")

        atr20_full = run_backtest(prepared, tickers, lambda df, idx: exit_atr_adaptive(df, idx, 2.0, 4, 7))
        mc_atr = monte_carlo(atr20_full)
        print(f"  ATR 2.0x: P(Sh>0)={mc_atr.get('p_sh',0)}% Med={mc_atr.get('med_sh',0)} W1%={mc_atr.get('w1_sh',0)} W1%MDD={mc_atr.get('w1_mdd',0)}%")

    # ════════════════════════════════════════════════════════════════
    # VEREDICTO
    # ════════════════════════════════════════════════════════════════
    print("\n" + "=" * 96)
    print("  VEREDICTO")
    print("=" * 96)
    print("""
  Hipotesis testeadas:
    1. VIX term structure (backwardation = panico real) como filtro de Signal C
    2. ATR-adaptive TP en lugar de +6% fijo

  Resultados arriba determinan si alguna mejora V10 o si V10 se mantiene.
  Criterios: WF >= 80%, Sharpe > V10, sin agregar complejidad excesiva.
""")


if __name__ == "__main__":
    main()
