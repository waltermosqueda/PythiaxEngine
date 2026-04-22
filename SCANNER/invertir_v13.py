#!/usr/bin/env python3
"""
INVERTIR V13 - Scanner con Cuarto Eje Ortogonal: RS New High (Hardware)
=======================================================================
AUTOCONTENIDO: no depende de otros scanners. Solo usa titan_system.

Arquitectura V13:
  Signal A    - Mean Reversion con regime (heredado de V11)
  Signal C5   - Crash + Path Quality + Health Block (heredado de V12)
  Signal D    - Leadership / Tendencia ortogonal (heredado de V12)
  Signal E_HW - RS New High sector Hardware/IndustrialTech (NUEVO)

Evolucion:
  V7 -> V9 path quality -> V10 rebound -> V11 cap operativa ->
  V12 signal D -> V13 signal E_HW (RS New High)

Promotion gate V13 (investigacion_v23_promotion_gate.py):
  - 6/7 gates PASS
  - Sharpe 4-slot: 1.62 vs V12 1.36 (+18%)
  - MDD: -37.0% vs -39.9% (mejora +2.9pp)
  - E_HW individual: WR 75%, avg +13.75%, n=64, WF 6/7
  - MC P(WR>50%) = 100%

Parametros Signal E_HW validados:
  - HW tickers: GLW, GRMN, HPQ, MSI, SWKS, TXN, EA, ASTS, RKLB, ERIC, BB
  - RS_LINE >= RS_52W_MAX (RS a maximo de 52 semanas, sin look-ahead)
  - Close > SMA50 > SMA200
  - RSI 50-75 | ROC20 > 8% | Vol ratio 0.8-2.5x
  - Hold 15d | Corp action guard

Resultados de referencia (Abr 2020 - Abr 2026, auditados en V23):
  V12 base (3 slots): Sharpe 1.36 | MDD -39.9% | Total +896%
  V13 (4 slots)     : Sharpe 1.62 | MDD -37.0% | Total +1293%

Uso:
  python SCANNER/invertir_v13.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from titan_system.core.database import TitanDB
from titan_system.core.data_loader import get_sector


MODEL_NAME = "INVERTIR_V13"
MEMORY_BASE_MODEL_NAME = "INVERTIR_V11"   # memoria A y C5 sigue en V11
LINE = "=" * 100
SUBLINE = "-" * 100
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
USE_COLOR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None
WEEKDAY_ES = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
MARKET_CLOSE_HOUR = 19

# ─────────────────────────────────────────────────────────────────────────────
# PARAMETROS DE SENALES
# ─────────────────────────────────────────────────────────────────────────────

# Signal A — Mean Reversion
A_RSI_MAX       = 25
A_SMA_DIST_MAX  = -10.0
A_SCORE_MIN     = 30
A_VOL_MAX       = 1.5
A_HOLDING_DAYS  = 7

# Signal C5 — Crash + Path Quality
C_ROC10_MAX        = -15.0
C_VOL_RATIO_MIN    = 2.0
C_VOL_RATIO_CAP    = 4.0
C_RSI_MAX          = 35.0
C_NEG_DAYS10_MIN   = 5
C_SCORE_MAX        = 85.0
C_HOLDING_DAYS     = 7
C_EARLY_TP_PCT     = 6.0
C_EARLY_TP_DAYS    = 4

# Signal D — Liderazgo / Tendencia
D_ROC20_MIN     = 12.0
D_REL20_MIN     = 7.0
D_RSI_MIN       = 55.0
D_RSI_MAX       = 75.0
D_VOL_MIN       = 0.8
D_VOL_MAX       = 2.0
D_HOLDING_DAYS  = 10
D_TARGET_PCT    = 6.0

# Signal E_HW — RS New High (Hardware/IndustrialTech)
# Validado en V23: WR 75%, avg +13.75%, hold=15d optimo, 6/7 gates PASS
E_HW_TICKERS = frozenset({
    "GLW", "GRMN", "HPQ", "MSI", "SWKS", "TXN",
    "EA", "ASTS", "RKLB", "ERIC", "BB"
})
E_RSI_MIN       = 50.0
E_RSI_MAX       = 75.0
E_ROC20_MIN     = 8.0
E_VOL_MIN       = 0.8
E_VOL_MAX       = 2.5
E_HOLDING_DAYS  = 15
E_TARGET_PCT    = 10.0

# Corporate action guard
CORP_RET1_ABS_MIN       = 0.60
CORP_INTRADAY_ABS_MAX   = 0.15
CORP_RANGE_MAX          = 0.15

ANTIKNIFE_DAYS = 5

# V15 ATR Sizing
SIZING_MAX_SLOTS      = 4   # V13: 4 slots (A/C5 + D + E_HW)
SIZING_ATR_TARGET_PCT = 4.0
SIZING_ATR_MIN_FACTOR = 0.3
SIZING_ATR_MAX_FACTOR = 2.0
GESTOR_STATE_PATH = ROOT / "herramientas" / "v11_open_positions.json"

PRIORITY_MIN_TOTAL  = 30
PRIORITY_MIN_BUCKET = 8
PRIORITY_FALLBACK   = -1_000_000.0


TICKERS_STR = """
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

UNIVERSE = [t.strip() for t in TICKERS_STR.replace("\n", "").split(",") if t.strip()]


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ScanResult:
    ticker: str
    signal: str
    price: float
    sector: str
    rsi: float | None
    dist_sma50: float | None
    roc10: float | None
    roc20: float | None
    rel20: float | None
    vol_ratio: float | None
    stop: float
    target: float
    risk_pct: float
    score: float
    note: str = ""
    atr_pct: float | None = None
    priority_score: float | None = None
    priority_expected_return: float | None = None
    priority_source: str = "score"


@dataclass
class Snapshot:
    run_started: datetime
    run_finished: datetime
    analyzed_date: str
    db_last_write: datetime | None
    freshness: str
    regime_label: str
    breadth_pct: float
    results_a: list[ScanResult]
    results_c5: list[ScanResult]
    results_d: list[ScanResult]
    results_e: list[ScanResult]
    blocked_extreme: list[ScanResult]
    quality_alerts: list[dict[str, object]]
    memory_context: list[str]
    is_panic: bool = False


@dataclass(frozen=True)
class PriorityProfile:
    model_name: str
    regime: str
    total: int
    q1: float
    q2: float
    base_avg_return_pct: float
    bucket_counts: dict[int, int]
    bucket_avg_return_pct: dict[int, float]


# ─────────────────────────────────────────────────────────────────────────────
# INDICADORES TECNICOS
# ─────────────────────────────────────────────────────────────────────────────

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI: ewm(com=period-1, adjust=False)."""
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs    = gain / (loss + 1e-10)
    return 100 - 100 / (1 + rs)


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast   = close.ewm(span=fast, adjust=False).mean()
    ema_slow   = close.ewm(span=slow, adjust=False).mean()
    macd       = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line, macd - signal_line


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low  - close.shift(1)).abs()
    tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ─────────────────────────────────────────────────────────────────────────────
# FECHAS Y UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def business_days_between(start_date: date, end_date: date) -> int:
    if end_date <= start_date:
        return 0
    count  = 0
    cursor = start_date + timedelta(days=1)
    while cursor <= end_date:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


# ─────────────────────────────────────────────────────────────────────────────
# CARGA Y PRECOMPUTO
# ─────────────────────────────────────────────────────────────────────────────

def load_universe_data(
    db: TitanDB, tickers: list[str]
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    available = set(db.get_all_tickers())
    present   = [t for t in tickers if t in available]
    if "SPY" not in present:
        present.append("SPY")

    data: dict[str, pd.DataFrame] = {}
    for ticker in present:
        df = db.get_prices(ticker)
        if df.empty:
            continue
        df = df.rename(columns={"open": "Open", "high": "High",
                                 "low": "Low", "close": "Close", "volume": "Volume"})
        data[ticker] = df[["Open", "High", "Low", "Close", "Volume"]].copy()

    missing = sorted([t for t in tickers if t not in data])
    return data, missing


def precompute_indicators(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """
    Primera pasada: indicadores clasicos + SMA200.
    Segunda pasada: RS_LINE y RS_52W_MAX para Signal E (requiere SPY completo).
    """
    prepared: dict[str, pd.DataFrame] = {}

    # Primera pasada
    for ticker, df in data.items():
        work = df.copy()
        work["RSI"]           = calc_rsi(work["Close"])
        _, _, work["MACD_HIST"] = calc_macd(work["Close"])
        work["SMA50"]         = work["Close"].rolling(50).mean()
        work["SMA200"]        = work["Close"].rolling(200).mean()
        work["ATR"]           = calc_atr(work["High"], work["Low"], work["Close"])
        work["VOL_AVG20"]     = work["Volume"].rolling(20).mean()
        work["VOL_RATIO"]     = work["Volume"] / (work["VOL_AVG20"] + 1e-10)
        work["DIST_SMA50"]    = (work["Close"] / work["SMA50"] - 1) * 100
        work["ROC10"]         = (work["Close"] / work["Close"].shift(10) - 1) * 100
        work["ROC20"]         = (work["Close"] / work["Close"].shift(20) - 1) * 100
        work["RET1"]          = work["Close"].pct_change()
        work["NEG_DAYS10"]    = (work["RET1"] < 0).rolling(10).sum()
        work["INTRADAY"]      = work["Close"] / (work["Open"] + 1e-10) - 1
        work["RANGE_PCT"]     = (work["High"] - work["Low"]) / (work["Open"] + 1e-10)
        work["CORP_ACTION_DAY"] = (
            (work["RET1"].abs()   > CORP_RET1_ABS_MIN)
            & (work["INTRADAY"].abs() < CORP_INTRADAY_ABS_MAX)
            & (work["RANGE_PCT"]      < CORP_RANGE_MAX)
        )
        work["CORP_ACTION_10D"] = (
            work["CORP_ACTION_DAY"].rolling(10, min_periods=1).max().fillna(0).astype(bool)
        )
        work["REL20"] = pd.NA
        # Placeholders para E (calculados en segunda pasada)
        work["RS_LINE"]    = float("nan")
        work["RS_52W_MAX"] = float("nan")
        prepared[ticker] = work

    # SPY extras
    spy = prepared.get("SPY")
    if spy is not None:
        spy["SPY_ROC20"] = spy["ROC20"]
        prepared["SPY"] = spy
        for ticker, work in prepared.items():
            if ticker == "SPY":
                work["REL20"] = 0.0
                continue
            work["REL20"] = work["ROC20"] - spy["SPY_ROC20"]
            prepared[ticker] = work

    # Segunda pasada: RS_LINE y RS_52W_MAX (sin look-ahead via shift(1))
    if spy is not None:
        spy_close = spy["Close"]
        for ticker, work in prepared.items():
            if ticker == "SPY":
                continue
            spy_aligned         = spy_close.reindex(work.index, fill_value=float("nan"))
            work["RS_LINE"]     = work["Close"] / (spy_aligned + 1e-10)
            work["RS_52W_MAX"]  = work["RS_LINE"].shift(1).rolling(252, min_periods=126).max()
            prepared[ticker]    = work

    return prepared


# ─────────────────────────────────────────────────────────────────────────────
# REGIMEN Y MERCADO
# ─────────────────────────────────────────────────────────────────────────────

def check_regime(spy_df: pd.DataFrame) -> tuple[bool, dict[str, object]]:
    if spy_df is None or spy_df.empty or len(spy_df) < 55:
        return False, {"reason": "Datos insuficientes"}
    row   = spy_df.iloc[-1]
    price = float(row["Close"])
    sma50 = float(row["SMA50"])
    vol_20d   = float(spy_df["Close"].pct_change().rolling(20).std().iloc[-1] * 100)
    dist_sma50 = (price / sma50 - 1) * 100 if sma50 else 0
    above_sma  = price > sma50
    low_vol    = vol_20d < 1.0
    roc20 = float((spy_df["Close"] / spy_df["Close"].shift(20) - 1).iloc[-1] * 100) if len(spy_df) >= 21 else 0.0
    is_panic   = roc20 < -10.0
    info = {
        "spy_price": round(price, 2),
        "spy_sma50": round(sma50, 2),
        "spy_dist":  round(dist_sma50, 2),
        "spy_vol20d": round(vol_20d, 2),
        "spy_roc20": round(roc20, 2),
        "above_sma": above_sma,
        "low_vol":   low_vol,
        "safe":      above_sma and low_vol,
        "is_panic":  is_panic,
    }
    return info["safe"], info


# ─────────────────────────────────────────────────────────────────────────────
# SENALES
# ─────────────────────────────────────────────────────────────────────────────

def signal_a_mean_reversion(ticker: str, df: pd.DataFrame) -> ScanResult | None:
    """Signal A — Mean Reversion (requiere regime SEGURO)."""
    if len(df) < 55:
        return None
    row  = df.iloc[-1]
    prev = df.iloc[-2]

    curr_rsi   = row["RSI"]
    curr_hist  = row["MACD_HIST"]
    prev_hist  = prev["MACD_HIST"]
    price      = row["Close"]
    curr_atr   = row["ATR"]
    vol_ratio  = row["VOL_RATIO"]
    dist_sma50 = row["DIST_SMA50"]
    corp_action = bool(row["CORP_ACTION_10D"])

    if any(pd.isna(v) for v in [curr_rsi, curr_hist, prev_hist, price, curr_atr, vol_ratio, dist_sma50]):
        return None
    if corp_action:
        return None
    if curr_hist <= prev_hist or vol_ratio > A_VOL_MAX:
        return None
    if curr_rsi >= A_RSI_MAX or dist_sma50 > A_SMA_DIST_MAX:
        return None

    macd_accel   = (curr_hist - prev_hist) / (curr_atr * 0.01 + 1e-6)
    rsi_score    = max(0.0, min(40.0, (30.0 - curr_rsi) / 30.0 * 40.0))
    stretch_score = max(0.0, min(30.0, (abs(dist_sma50) - 5.0) / 15.0 * 30.0))
    macd_score   = max(0.0, min(20.0, macd_accel * 5.0))
    vol_score    = max(0.0, min(10.0, (1.5 - vol_ratio) / 1.5 * 10.0))
    total_score  = rsi_score + stretch_score + macd_score + vol_score
    if total_score < A_SCORE_MIN:
        return None

    stop     = price - 2 * curr_atr
    target   = price * 1.03
    risk_pct = (1 - stop / price) * 100
    atr_pct  = float(curr_atr / price * 100) if price > 0 else None
    return ScanResult(
        ticker=ticker, signal="A (MeanRev)",
        price=round(float(price), 2), sector=get_sector(ticker),
        rsi=round(float(curr_rsi), 1), dist_sma50=round(float(dist_sma50), 1),
        roc10=None, roc20=None, rel20=None,
        vol_ratio=round(float(vol_ratio), 2),
        stop=round(float(stop), 2), target=round(float(target), 2),
        risk_pct=round(float(risk_pct), 1), score=float(total_score),
        note=f"hold {A_HOLDING_DAYS}d",
        atr_pct=round(atr_pct, 2) if atr_pct is not None else None,
    )


def build_c5_candidate(ticker: str, df: pd.DataFrame) -> ScanResult | None:
    """Signal C5 — Crash + Path Quality (sin gate de SPY)."""
    if len(df) < 25:
        return None
    row        = df.iloc[-1]
    roc10      = row["ROC10"]
    vol_ratio  = row["VOL_RATIO"]
    curr_rsi   = row["RSI"]
    price      = row["Close"]
    curr_atr   = row["ATR"]
    dist_sma50 = row["DIST_SMA50"]
    neg_days10 = row["NEG_DAYS10"]
    corp_action = bool(row["CORP_ACTION_10D"])

    if any(pd.isna(v) for v in [roc10, vol_ratio, curr_rsi, price, neg_days10]):
        return None
    if corp_action:
        return None
    # V19: bloquear sector Health (WR=33%, avg=-1.84% en portfolio)
    if get_sector(ticker) == "health":
        return None
    if roc10 >= C_ROC10_MAX or vol_ratio < C_VOL_RATIO_MIN or curr_rsi >= C_RSI_MAX:
        return None
    if neg_days10 < C_NEG_DAYS10_MIN:
        return None

    if pd.isna(curr_atr):
        curr_atr = price * 0.03

    stop     = price - 2 * curr_atr
    target   = price * 1.05
    risk_pct = (1 - stop / price) * 100
    score = abs(float(roc10)) * float(vol_ratio) * (1 + max(0.0, (C_RSI_MAX - float(curr_rsi))) / 100)
    note  = (
        f"neg_days={int(neg_days10)} | cap: score<{C_SCORE_MAX:.0f} y vol<{C_VOL_RATIO_CAP:.1f}x | "
        f"exit +{C_EARLY_TP_PCT:.0f}% <= day {C_EARLY_TP_DAYS}, sino day {C_HOLDING_DAYS}"
    )
    atr_pct = float(curr_atr / price * 100) if price > 0 else None
    return ScanResult(
        ticker=ticker, signal="C5 (CrashCap)",
        price=round(float(price), 2), sector=get_sector(ticker),
        rsi=round(float(curr_rsi), 1),
        dist_sma50=round(float(dist_sma50), 1) if not pd.isna(dist_sma50) else None,
        roc10=round(float(roc10), 1), roc20=None, rel20=None,
        vol_ratio=round(float(vol_ratio), 2),
        stop=round(float(stop), 2), target=round(float(target), 2),
        risk_pct=round(float(risk_pct), 1), score=float(score),
        note=note,
        atr_pct=round(atr_pct, 2) if atr_pct is not None else None,
    )


def c5_is_preferred(result: ScanResult) -> bool:
    if result.vol_ratio is None:
        return False
    return result.score < C_SCORE_MAX and float(result.vol_ratio) < C_VOL_RATIO_CAP


def signal_c5_crash_cap(ticker: str, df: pd.DataFrame) -> ScanResult | None:
    candidate = build_c5_candidate(ticker, df)
    if candidate is None:
        return None
    if not c5_is_preferred(candidate):
        return None
    return candidate


def signal_d_leadership(ticker: str, df: pd.DataFrame) -> ScanResult | None:
    """Signal D — Liderazgo / Tendencia (sin gate de SPY)."""
    if len(df) < 220:
        return None
    row        = df.iloc[-1]
    price      = row["Close"]
    sma50      = row["SMA50"]
    sma200     = row["SMA200"]
    roc20      = row["ROC20"]
    rel20      = row["REL20"]
    curr_rsi   = row["RSI"]
    vol_ratio  = row["VOL_RATIO"]
    curr_atr   = row["ATR"]
    corp_action = bool(row["CORP_ACTION_10D"])

    required = [price, sma50, sma200, roc20, rel20, curr_rsi, vol_ratio]
    if any(pd.isna(v) for v in required):
        return None
    if corp_action:
        return None
    if price <= sma50 or sma50 <= sma200:
        return None
    if roc20 <= D_ROC20_MIN or rel20 <= D_REL20_MIN:
        return None
    if curr_rsi < D_RSI_MIN or curr_rsi > D_RSI_MAX:
        return None
    if vol_ratio < D_VOL_MIN or vol_ratio > D_VOL_MAX:
        return None

    if pd.isna(curr_atr):
        curr_atr = price * 0.03

    stop     = price - 2.0 * curr_atr
    target   = max(price * (1 + D_TARGET_PCT / 100.0), price + 2.0 * curr_atr)
    risk_pct = (1 - stop / price) * 100
    score    = float(roc20 + rel20)
    atr_pct  = float(curr_atr / price * 100) if price > 0 else None
    return ScanResult(
        ticker=ticker, signal="D (Leadership)",
        price=round(float(price), 2), sector=get_sector(ticker),
        rsi=round(float(curr_rsi), 1),
        dist_sma50=round(float((price / sma50 - 1.0) * 100.0), 1),
        roc10=None, roc20=round(float(roc20), 1), rel20=round(float(rel20), 1),
        vol_ratio=round(float(vol_ratio), 2),
        stop=round(float(stop), 2), target=round(float(target), 2),
        risk_pct=round(float(risk_pct), 1), score=score,
        note=f"hold {D_HOLDING_DAYS}d | liderazgo sin gate SPY",
        atr_pct=round(atr_pct, 2) if atr_pct is not None else None,
    )


def signal_e_hw_rs_new_high(ticker: str, df: pd.DataFrame) -> ScanResult | None:
    """
    Signal E_HW — RS New High en Hardware/IndustrialTech.

    Trigger: RS_LINE (Close/SPY) >= maximo de RS_LINE en 52 semanas anteriores.
    Interpretacion: el activo supera al mercado a niveles historicos recientes.
    Validado en V23: WR 75%, avg +13.75%, hold 15d, WF 6/7, MC P(WR>50%)=100%.

    Sector concentrado: RKLB (~33% de trades). Riesgo de concentracion conocido.
    """
    if ticker not in E_HW_TICKERS:
        return None
    if len(df) < 260:   # 252 para RS_52W_MAX + warmup
        return None

    row = df.iloc[-1]
    required_cols = [
        "RS_LINE", "RS_52W_MAX", "Close", "SMA50", "SMA200",
        "RSI", "VOL_RATIO", "ROC20", "ATR",
    ]
    if any(pd.isna(row.get(c, float("nan"))) for c in required_cols):
        return None

    corp_action = bool(row.get("CORP_ACTION_10D", False))
    if corp_action:
        return None

    price      = float(row["Close"])
    sma50      = float(row["SMA50"])
    sma200     = float(row["SMA200"])
    rs_line    = float(row["RS_LINE"])
    rs_52w_max = float(row["RS_52W_MAX"])
    rsi        = float(row["RSI"])
    vol_ratio  = float(row["VOL_RATIO"])
    roc20      = float(row["ROC20"])
    curr_atr   = float(row["ATR"])

    # Filtros Signal E_HW (validados en V23)
    if rs_line < rs_52w_max:           # RS no en maximo de 52 semanas
        return None
    if price <= sma50 or sma50 <= sma200:  # no en tendencia estructural
        return None
    if rsi < E_RSI_MIN or rsi > E_RSI_MAX:
        return None
    if roc20 <= E_ROC20_MIN:
        return None
    if vol_ratio < E_VOL_MIN or vol_ratio > E_VOL_MAX:
        return None

    if pd.isna(curr_atr) or curr_atr <= 0:
        curr_atr = price * 0.03

    stop     = price - 2.0 * curr_atr
    target   = max(price * (1 + E_TARGET_PCT / 100.0), price + 2.0 * curr_atr)
    risk_pct = (1 - stop / price) * 100
    # Score: ROC20 + bonus por exceso de RS vs maximo previo
    rs_excess = (rs_line / (rs_52w_max + 1e-10) - 1.0) * 100.0
    score     = float(roc20) + float(rs_excess) * 0.5
    atr_pct   = curr_atr / price * 100

    return ScanResult(
        ticker=ticker, signal="E (RS High HW)",
        price=round(price, 2), sector=get_sector(ticker),
        rsi=round(rsi, 1),
        dist_sma50=round((price / sma50 - 1.0) * 100.0, 1),
        roc10=None, roc20=round(roc20, 1), rel20=None,
        vol_ratio=round(vol_ratio, 2),
        stop=round(stop, 2), target=round(target, 2),
        risk_pct=round(risk_pct, 1), score=score,
        note=(
            f"RS New High HW | hold {E_HOLDING_DAYS}d | "
            f"WR hist 75% | RS excess {rs_excess:+.1f}%"
        ),
        atr_pct=round(atr_pct, 2),
    )


# ─────────────────────────────────────────────────────────────────────────────
# MERCADO Y CALIDAD
# ─────────────────────────────────────────────────────────────────────────────

def compute_breadth(universe_data: dict[str, pd.DataFrame]) -> dict[str, object]:
    eligible = []
    for ticker, df in universe_data.items():
        if ticker == "SPY" or len(df) < 55:
            continue
        sma50 = df["Close"].rolling(50).mean().iloc[-1]
        price = df["Close"].iloc[-1]
        if pd.isna(sma50):
            continue
        eligible.append(price > sma50)
    if not eligible:
        return {"pct_above_sma50": 0.0, "count": 0}
    return {"pct_above_sma50": round(sum(eligible) / len(eligible) * 100, 1), "count": len(eligible)}


def recent_quality_alerts(prepared: dict[str, pd.DataFrame]) -> list[dict[str, object]]:
    alerts: list[dict[str, object]] = []
    for ticker, df in prepared.items():
        if ticker == "SPY" or "CORP_ACTION_DAY" not in df.columns:
            continue
        flagged = df[df["CORP_ACTION_DAY"]]
        if flagged.empty:
            continue
        last = flagged.iloc[-1]
        if (df.index[-1] - flagged.index[-1]).days > 10:
            continue
        alerts.append({
            "ticker": ticker,
            "date": flagged.index[-1].date().isoformat(),
            "ret1": round(float(last["RET1"] * 100), 1),
            "intraday": round(float(last["INTRADAY"] * 100), 1),
            "range_pct": round(float(last["RANGE_PCT"] * 100), 1),
        })
    alerts.sort(key=lambda item: item["date"], reverse=True)
    return alerts


# ─────────────────────────────────────────────────────────────────────────────
# MEMORIA OPERATIVA Y PRIORIDAD
# ─────────────────────────────────────────────────────────────────────────────

def load_memory_context(db: TitanDB, regime_label: str) -> list[str]:
    specs: list[tuple[str, str]] = []
    if regime_label == "SEGURO":
        specs.append((f"{MEMORY_BASE_MODEL_NAME}_A_D7",  "A / D7"))
        specs.append((f"{MEMORY_BASE_MODEL_NAME}_C5_D7", "C5 / D7"))
    else:
        specs.append((f"{MEMORY_BASE_MODEL_NAME}_C5_D4", "C5 / D4"))
        specs.append((f"{MEMORY_BASE_MODEL_NAME}_C5_D7", "C5 / D7"))

    lines: list[str] = []
    for model_name, label in specs:
        row = db.conn.execute(
            """
            SELECT COUNT(*) AS total,
                   AVG(o.hit) * 100.0 AS accuracy_pct,
                   AVG(o.actual_return) * 100.0 AS avg_return_pct
            FROM predictions p
            JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name = ? AND p.regime = ?
            """,
            (model_name, regime_label),
        ).fetchone()
        total = int(row[0] or 0)
        if total == 0:
            continue
        accuracy_pct    = float(row[1] or 0.0)
        avg_return_pct  = float(row[2] or 0.0)
        lines.append(
            f"{label} en {regime_label}: hit {accuracy_pct:.1f}% | avg {avg_return_pct:+.3f}% | n={total}"
        )

    # D global
    row_d = db.conn.execute(
        """
        SELECT COUNT(*) AS total,
               AVG(o.hit) * 100.0 AS accuracy_pct,
               AVG(o.actual_return) * 100.0 AS avg_return_pct
        FROM predictions p
        JOIN outcomes o ON p.id = o.prediction_id
        WHERE p.model_name = ? AND p.regime IS NOT NULL
        """,
        (f"{MODEL_NAME}_D_D10",),
    ).fetchone()
    total_d = int(row_d[0] or 0)
    if total_d > 0:
        lines.append(
            f"D / D10 global: hit {float(row_d[1] or 0):.1f}% | "
            f"avg {float(row_d[2] or 0):+.3f}% | n={total_d}"
        )

    # E_HW global (se acumulara con el tiempo)
    row_e = db.conn.execute(
        """
        SELECT COUNT(*) AS total,
               AVG(o.hit) * 100.0 AS accuracy_pct,
               AVG(o.actual_return) * 100.0 AS avg_return_pct
        FROM predictions p
        JOIN outcomes o ON p.id = o.prediction_id
        WHERE p.model_name = ? AND p.regime IS NOT NULL
        """,
        (f"{MODEL_NAME}_E_D15",),
    ).fetchone()
    total_e = int(row_e[0] or 0)
    if total_e > 0:
        lines.append(
            f"E_HW / D15 global: hit {float(row_e[1] or 0):.1f}% | "
            f"avg {float(row_e[2] or 0):+.3f}% | n={total_e}"
        )

    return lines


def priority_model_name(result: ScanResult) -> str | None:
    if result.signal.startswith("A"):
        return f"{MEMORY_BASE_MODEL_NAME}_A_D7"
    if result.signal.startswith("C5"):
        return f"{MEMORY_BASE_MODEL_NAME}_C5_D4"
    return None   # D y E usan score_proxy hasta acumular historial


def assign_priority_bucket(score: float, q1: float, q2: float) -> int:
    if score <= q1:
        return 1
    if score <= q2:
        return 2
    return 3


def load_priority_profiles(db: TitanDB, as_of_date: str) -> dict[tuple[str, str], PriorityProfile]:
    df = pd.read_sql_query(
        """
        SELECT p.model_name, p.regime, p.score, o.actual_return
        FROM predictions p
        JOIN outcomes o ON p.id = o.prediction_id
        WHERE p.model_name IN (?, ?)
          AND p.regime IS NOT NULL
          AND p.target_date <= ?
        ORDER BY p.model_name, p.regime, p.score
        """,
        db.conn,
        params=[
            f"{MEMORY_BASE_MODEL_NAME}_A_D7",
            f"{MEMORY_BASE_MODEL_NAME}_C5_D4",
            as_of_date,
        ],
    )
    if df.empty:
        return {}

    profiles: dict[tuple[str, str], PriorityProfile] = {}
    for (model_name, regime), group in df.groupby(["model_name", "regime"]):
        work   = group.copy()
        total  = int(len(work))
        if total < PRIORITY_MIN_TOTAL:
            continue
        q1 = float(work["score"].quantile(1 / 3))
        q2 = float(work["score"].quantile(2 / 3))
        work["bucket"] = work["score"].apply(
            lambda s: assign_priority_bucket(float(s), q1, q2)
        )
        bucket_stats = work.groupby("bucket")["actual_return"].agg(["count", "mean"])
        profiles[(str(model_name), str(regime))] = PriorityProfile(
            model_name=str(model_name), regime=str(regime), total=total,
            q1=q1, q2=q2,
            base_avg_return_pct=float(work["actual_return"].mean() * 100.0),
            bucket_counts={int(b): int(r["count"]) for b, r in bucket_stats.iterrows()},
            bucket_avg_return_pct={int(b): float(r["mean"] * 100.0) for b, r in bucket_stats.iterrows()},
        )
    return profiles


def apply_priority_layer(
    db: TitanDB,
    results: list[ScanResult],
    regime_label: str,
    as_of_date: str,
) -> list[ScanResult]:
    profiles = load_priority_profiles(db, as_of_date)
    for result in results:
        model_name = priority_model_name(result)
        profile    = profiles.get((model_name, regime_label)) if model_name is not None else None
        expected_return = None
        source          = "score"
        if profile is not None:
            bucket       = assign_priority_bucket(float(result.score), profile.q1, profile.q2)
            bucket_count = profile.bucket_counts.get(bucket, 0)
            if bucket_count >= PRIORITY_MIN_BUCKET:
                expected_return = profile.bucket_avg_return_pct.get(bucket, profile.base_avg_return_pct)
                source = f"mem_bucket_{bucket}"
            else:
                expected_return = profile.base_avg_return_pct
                source = "mem_base"
        result.priority_expected_return = expected_return
        result.priority_source = source
        if expected_return is None:
            proxy = float(result.score) / 10.0
            result.priority_expected_return = proxy
            result.priority_score = round(max(0.0, min(99.9, 50.0 + float(result.score) / 4.0)), 1)
            result.priority_source = "score_proxy"
        else:
            calibrated = 50.0 + expected_return * 8.0 + float(result.score) / 1000.0
            result.priority_score = round(max(0.0, min(99.9, calibrated)), 1)

    return sorted(
        results,
        key=lambda item: (
            float(item.priority_score) if item.priority_score is not None else float(item.score),
        ),
        reverse=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# RENDER UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def paint(text: str, style: str) -> str:
    if not USE_COLOR:
        return text
    return f"\x1b[{style}m{text}\x1b[0m"


def visible_len(text: str) -> int:
    return len(ANSI_RE.sub("", text))


def pad_visible(text: str, width: int) -> str:
    return text + (" " * max(0, width - visible_len(text)))


def labeled_line(label: str, value: str, width: int = 24) -> str:
    return f"  {label.ljust(width)}: {value}"


def split_banner(left_text: str, right_text: str, total_width: int = len(LINE)) -> str:
    gap = total_width - visible_len(left_text) - visible_len(right_text)
    if gap < 3:
        return f"{left_text} | {right_text}"
    return left_text + (" " * gap) + right_text


def format_spanish_date(date_text: str | None) -> str:
    if not date_text:
        return "-"
    dt = datetime.strptime(date_text, "%Y-%m-%d")
    return f"{WEEKDAY_ES[dt.weekday()]} {dt.strftime('%Y-%m-%d')}"


def format_spanish_datetime(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    return f"{WEEKDAY_ES[dt.weekday()]} {dt.strftime('%Y-%m-%d %H:%M:%S')}"


def next_business_day(date_text: str) -> str:
    cursor = datetime.strptime(date_text, "%Y-%m-%d").date() + timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor += timedelta(days=1)
    return cursor.isoformat()


def money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"${value:.2f}"


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [visible_len(h) for h in headers]
    for row in rows:
        widths = [max(w, visible_len(v)) for w, v in zip(widths, row)]

    def fmt(row_: list[str]) -> str:
        return " | ".join(pad_visible(v, w) for v, w in zip(row_, widths))

    lines = [fmt(headers), "-+-".join("-" * w for w in widths)]
    lines.extend(fmt(row) for row in rows)
    return "\n".join(lines)


def prediction_target(snapshot: Snapshot) -> str:
    return format_spanish_date(next_business_day(snapshot.analyzed_date))


def prediction_target_date(snapshot: Snapshot) -> date:
    return datetime.strptime(next_business_day(snapshot.analyzed_date), "%Y-%m-%d").date()


def prediction_status(snapshot: Snapshot, now: datetime | None = None) -> tuple[str, str, bool]:
    now = now or datetime.now()
    analyzed_dt = datetime.strptime(snapshot.analyzed_date, "%Y-%m-%d").date()
    target_dt   = prediction_target_date(snapshot)
    if target_dt < now.date() or (target_dt == now.date() and now.hour >= MARKET_CLOSE_HOUR):
        return (
            "VENCIDA",
            f"La rueda objetivo {format_spanish_date(target_dt.isoformat())} ya cerro. "
            f"La base solo llega a {format_spanish_date(analyzed_dt.isoformat())}.",
            False,
        )
    if snapshot.freshness != "AL DIA":
        return (
            "STALE",
            f"La base llega a {format_spanish_date(analyzed_dt.isoformat())}. Actualizar antes de operar.",
            False,
        )
    return (
        "VIGENTE",
        f"Cierre usado {format_spanish_date(analyzed_dt.isoformat())} | "
        f"rueda objetivo {format_spanish_date(target_dt.isoformat())}",
        True,
    )


def prediction_status_text(snapshot: Snapshot) -> str:
    status, detail, actionable = prediction_status(snapshot)
    color = "92" if actionable else ("91" if status == "VENCIDA" else "93")
    return f"{paint(status, color)} | {detail}"


def snapshot_actionable(snapshot: Snapshot) -> bool:
    return prediction_status(snapshot)[2]


def execution_window(snapshot: Snapshot) -> str:
    return (
        f"Inicio {snapshot.run_started.strftime('%Y-%m-%d %H:%M:%S')} | "
        f"Finalizacion {snapshot.run_finished.strftime('%Y-%m-%d %H:%M:%S')}"
    )


def db_update_text(snapshot: Snapshot) -> str:
    if snapshot.db_last_write is None:
        value = f"Cierre base de datos : {format_spanish_date(snapshot.analyzed_date)}"
    else:
        value = f"Actualizado : {format_spanish_datetime(snapshot.db_last_write)}"
    if snapshot.freshness != "AL DIA":
        value += f" | Estado : {snapshot.freshness}"
    return value


def market_context(snapshot: Snapshot) -> str:
    regime = "favorable (SEGURO)" if snapshot.regime_label == "SEGURO" else "defensivo (PELIGRO)"
    regime = paint(regime, "1;92") if snapshot.regime_label == "SEGURO" else paint(regime, "1;93")
    breadth = paint(f"{snapshot.breadth_pct:.1f}%", "96")
    base   = f"Mercado {regime} | Activos arriba de SMA50: {breadth}"
    if snapshot.is_panic:
        panic_tag  = paint("PANICO: SPY ROC20 < -10%", "1;91")
        panic_edge = paint("C5 historico en panico: WR 88.9% avg +9.2%", "93")
        return f"{base}\n  {panic_tag} | {panic_edge}"
    return base


def opportunities_summary(snapshot: Snapshot) -> str:
    total = (
        len(snapshot.results_a)
        + len(snapshot.results_c5)
        + len(snapshot.results_d)
        + len(snapshot.results_e)
    )
    return (
        f"Total {total} Detectadas | "
        f"Rebotes {len(snapshot.results_a)} | "
        f"Crashes {len(snapshot.results_c5)} | "
        f"Liderazgo {len(snapshot.results_d)} | "
        f"RS High HW {len(snapshot.results_e)}"
    )


def setup_label(result: ScanResult) -> str:
    if result.signal.startswith("A"):
        return "Rebote (A)"
    if result.signal.startswith("C5"):
        return "Crash (C5)"
    if result.signal.startswith("E"):
        return "RS High HW (E)"
    return "Liderazgo (D)"


def color_upside(result: ScanResult) -> str:
    if result.price == 0:
        return "0.0%"
    upside = (result.target / result.price - 1.0) * 100.0
    return paint(f"{upside:+.1f}%", "92")


def color_risk(result: ScanResult) -> str:
    risk_text = f"{result.risk_pct:.1f}%"
    if result.risk_pct >= 15:
        return paint(risk_text, "93")
    if result.risk_pct >= 8:
        return paint(risk_text, "33")
    return risk_text


def color_priority(result: ScanResult) -> str:
    value = result.priority_score if result.priority_score is not None else result.score
    score_text = f"{value:.1f}"
    if value >= 80:
        return paint(score_text, "92")
    if value >= 65:
        return paint(score_text, "36")
    return score_text


def blocked_reason(result: ScanResult) -> str:
    reasons = []
    if result.score >= C_SCORE_MAX:
        reasons.append(f"score extremo ({result.score:.1f})")
    if result.vol_ratio is not None and float(result.vol_ratio) >= C_VOL_RATIO_CAP:
        reasons.append(f"volumen fuera de cap ({result.vol_ratio:.2f}x)")
    if not reasons:
        reasons.append("fuera de cap operativa")
    return " + ".join(reasons)


# ─────────────────────────────────────────────────────────────────────────────
# SIZING (V15 ATR)
# ─────────────────────────────────────────────────────────────────────────────

def load_equity_base() -> float | None:
    if not GESTOR_STATE_PATH.exists():
        return None
    try:
        with open(GESTOR_STATE_PATH, "r", encoding="utf-8") as fh:
            state = json.load(fh)
        val = state.get("account", {}).get("equity_base")
        return float(val) if val is not None and float(val) > 0 else None
    except Exception:
        return None


def calc_sizing(atr_pct: float | None, equity_base: float) -> dict[str, float | None]:
    slot_base = equity_base / SIZING_MAX_SLOTS
    if atr_pct is None or atr_pct <= 0:
        factor = 1.0
    else:
        raw    = SIZING_ATR_TARGET_PCT / max(atr_pct, 0.5)
        factor = max(SIZING_ATR_MIN_FACTOR, min(SIZING_ATR_MAX_FACTOR, raw))
    factor   = round(factor, 2)
    notional = round(slot_base * factor, 2)
    return {"slot_base": round(slot_base, 2), "factor": factor, "notional": notional}


def render_sizing_block(results: list[ScanResult], equity_base: float | None) -> str:
    if equity_base is None:
        return (
            SUBLINE + "\n"
            "  Sizing V15: No configurado. Ejecutar:\n"
            "    python herramientas/gestor_posiciones_v11.py config --equity-base TU_CAPITAL\n"
            "  O correr el scanner con: python SCANNER/invertir_v13.py --equity TU_CAPITAL\n"
        )
    if not results:
        return ""

    sized: list[tuple[ScanResult, dict]] = []
    for result in results:
        sizing = calc_sizing(result.atr_pct, equity_base)
        shares   = round(sizing["notional"] / result.price, 1) if result.price > 0 else 0.0
        gain_usd = round(shares * (result.target - result.price), 2)
        risk_usd = round(shares * (result.price - result.stop), 2) if result.stop > 0 else 0.0
        sized.append((result, {
            **sizing, "shares": shares,
            "gain_usd": gain_usd,
            "gain_pct": round(gain_usd / equity_base * 100, 2),
            "risk_usd": risk_usd,
            "risk_pct": round(risk_usd / equity_base * 100, 2),
        }))

    lines = [SUBLINE]
    lines.append(
        f"  Cuanto invertir | Equity: {money(equity_base)} | "
        f"Slot base: {money(equity_base / SIZING_MAX_SLOTS)} | Slots max: {SIZING_MAX_SLOTS}"
    )
    lines.append(SUBLINE)

    headers = ["#", "Ticker", "Setup", "Comprar", "Invertir", "Si sube", "Si cae", "Riesgo eq."]
    rows: list[list[str]] = []
    for idx, (result, info) in enumerate(sized, start=1):
        risk_color = "91" if info["risk_pct"] > 3 else ("93" if info["risk_pct"] > 2 else "32")
        rows.append([
            str(idx), result.ticker, setup_label(result),
            f"{info['shares']:.0f} acc a {money(result.price)}",
            paint(money(info["notional"]), "1"),
            paint(f"+{money(info['gain_usd'])} (+{info['gain_pct']:.1f}%)", "92"),
            paint(f"-{money(info['risk_usd'])} (-{info['risk_pct']:.1f}%)", "91"),
            paint(f"{info['risk_pct']:.1f}%", risk_color),
        ])

    lines.append(render_table(headers, rows))
    lines.append("")
    lines.append("  Orden: de mayor a menor prioridad (#1 = mejor oportunidad segun el modelo).")
    lines.append("  Monto: ajustado por volatilidad ATR para riesgo parejo en todas las posiciones.")
    lines.append("  Activos volatiles reciben menos capital, tranquilos mas, pero todos arriesgan lo mismo.")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# RENDER HEADER Y BODY
# ─────────────────────────────────────────────────────────────────────────────

def quality_alert_summary(alert: dict[str, object]) -> str:
    ticker    = str(alert["ticker"])
    date_text = format_spanish_date(str(alert["date"]))
    ret1      = alert.get("ret1")
    intraday  = alert.get("intraday")
    metrics   = ""
    if ret1 is not None and intraday is not None:
        metrics = f" ({float(ret1):+.1f}% | intraday {float(intraday):+.1f}%)"
    return (
        f"{ticker}{metrics} | Posible split o ajuste el {date_text} | "
        "No usar esa caida como oportunidad."
    )


def render_header(snapshot: Snapshot) -> str:
    lines = [
        LINE,
        f"  {MODEL_NAME}",
        LINE,
        split_banner(
            f"Cierre analizado : {format_spanish_date(snapshot.analyzed_date)}",
            f"Ventana objetivo : {prediction_target(snapshot)}",
        ),
        SUBLINE,
        "  Control del informe",
        labeled_line("Datos ejecucion", execution_window(snapshot)),
        labeled_line("BBDD",           db_update_text(snapshot)),
        labeled_line("Estado senal",   prediction_status_text(snapshot)),
        SUBLINE,
        labeled_line("Oportunidades",  opportunities_summary(snapshot)),
        labeled_line("Salud mercado",  market_context(snapshot)),
    ]
    if snapshot.quality_alerts:
        lines.append(labeled_line("Alerta", quality_alert_summary(snapshot.quality_alerts[0])))
    lines.append(LINE)
    return "\n".join(lines)


def render_no_signals(snapshot: Snapshot) -> str:
    lines: list[str] = []
    if not snapshot_actionable(snapshot):
        lines.append(f"Atencion: {prediction_status(snapshot)[1]}")
        lines.append("No operar esta salida como si fuera la rueda vigente.")
    msg = (
        "No hay senales preferred hoy. El mercado sigue en modo defensivo."
        if snapshot.regime_label == "PELIGRO"
        else "No hay setups de calidad hoy. Esperar tambien es una decision valida."
    )
    lines.append(msg)
    lines.append("Que mirar igual:")
    lines.append("  - Liderazgo (D): tendencia fuerte y relativa, sin depender del gate de SPY.")
    lines.append("  - RS High HW (E): RS New High en Hardware — WR hist 75%, esperar setups de alta calidad.")
    lines.append("  - Crash (C5): caida fuerte filtrada por calidad.")
    lines.append("  - Revisar el gestor de posiciones si ya hay trades abiertos.")
    if snapshot.blocked_extreme:
        tickers = ", ".join(r.ticker for r in snapshot.blocked_extreme[:5])
        lines.append(f"  - Hoy hubo crashes extremos bloqueados: {tickers}")
    if snapshot.memory_context:
        lines.append("Contexto memoria:")
        for row in snapshot.memory_context:
            lines.append(f"  - {row}")
    return "\n".join(lines)


def render_blocked_details(snapshot: Snapshot) -> list[str]:
    if not snapshot.blocked_extreme:
        return []
    lines = [SUBLINE, "Activos bloqueados hoy:"]
    for result in snapshot.blocked_extreme[:4]:
        lines.append(f"  - {result.ticker}: {blocked_reason(result)}")
    extra = len(snapshot.blocked_extreme) - 4
    if extra > 0:
        lines.append(f"  - +{extra} bloqueados adicionales")
    lines.append("  - Lectura: activaron crash pero el modelo los descarta por demasiado violentos.")
    return lines


def render_body(snapshot: Snapshot) -> str:
    results = sorted(
        snapshot.results_a + snapshot.results_c5 + snapshot.results_d + snapshot.results_e,
        key=lambda item: (
            float(item.priority_score) if item.priority_score is not None else float(item.score),
        ),
        reverse=True,
    )
    if not results:
        lines = [render_no_signals(snapshot), SUBLINE, "Guia rapida:"]
        lines.append("  - Rebote (A): rebote tecnico en mercado mas sano (requiere SEGURO).")
        lines.append("  - Crash (C5): caida fuerte filtrada por calidad.")
        lines.append("  - Liderazgo (D): tendencia relativa fuerte, cualquier regimen.")
        lines.append("  - RS High HW (E): RS a nuevo maximo 52sem en Hardware. WR hist 75%.")
        return "\n".join(lines)

    headers = [
        "#", "Ticker", "Precio ref.", "Objetivo", "Stop",
        "Setup", "Upside", "Riesgo", "RSI", "ROC20d", "Rel20d", "Vol", "Prioridad",
    ]
    rows: list[list[str]] = []
    for idx, result in enumerate(results, start=1):
        rows.append([
            str(idx),
            result.ticker,
            money(result.price),
            money(result.target),
            money(result.stop),
            setup_label(result),
            color_upside(result),
            color_risk(result),
            "-" if result.rsi is None       else f"{result.rsi:.1f}",
            "-" if result.roc20 is None     else f"{result.roc20:.1f}%",
            "-" if result.rel20 is None     else f"{result.rel20:.1f}%",
            "-" if result.vol_ratio is None else f"{result.vol_ratio:.2f}x",
            color_priority(result),
        ])

    lines: list[str] = []
    if not snapshot_actionable(snapshot):
        lines.append(f"Atencion: {prediction_status(snapshot)[1]}")
        lines.append("No operar esta salida como vigente; sirve solo como auditoria.")
        lines.append(SUBLINE)

    lines.append(render_table(headers, rows))
    lines.extend(render_blocked_details(snapshot))
    if snapshot.memory_context:
        lines.append(SUBLINE)
        lines.append("Contexto memoria:")
        for row in snapshot.memory_context:
            lines.append(f"  - {row}")
    lines.append(SUBLINE)
    lines.append("Como leer esta tabla:")
    lines.append(
        "  - Setup: Rebote(A) reversion | Crash(C5) caida filtrada | "
        "Liderazgo(D) tendencia relativa | RS High HW(E) RS a nuevo maximo en hardware."
    )
    lines.append("  - Precio ref.: ultimo cierre. No implica comprar exactamente en ese numero.")
    lines.append("  - Objetivo / Stop: salida esperada y limite defensivo propuestos por el modelo.")
    lines.append("  - ROC20d: momentum 20 dias. Rel20d: liderazgo vs SPY en 20d.")
    lines.append("  - Vol: volumen vs promedio de 20 ruedas.")
    lines.append(
        "  - Prioridad: score interno y, cuando hay suficiente historia, retorno medio historico por setup/regimen."
    )
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="INVERTIR V13 - Scanner con 4 slots: A + C5 + D + RS High HW (E)"
    )
    parser.add_argument(
        "--equity", type=float, default=None,
        help="Capital disponible en USD (sobreescribe el valor guardado en el gestor)"
    )
    return parser.parse_args()


def main() -> None:
    args        = parse_args()
    run_started = datetime.now()
    today       = date.today()

    with TitanDB() as db:
        universe_data, _missing = load_universe_data(db, UNIVERSE)
        prepared = precompute_indicators(universe_data)

        if "SPY" not in prepared:
            print("ERROR: SPY no esta en titan.db. No se puede evaluar el regimen.")
            return

        latest_date_str = db.get_latest_date("SPY")
        latest_dt  = datetime.strptime(latest_date_str, "%Y-%m-%d").date() if latest_date_str else None
        staleness  = business_days_between(latest_dt, today) if latest_dt else None
        freshness  = "AL DIA" if staleness is not None and staleness <= 1 else (
            f"STALE ({staleness} dias habiles)" if staleness is not None else "SIN DATO"
        )

        regime_safe, regime_info = check_regime(prepared["SPY"])
        breadth        = compute_breadth(universe_data)
        quality_alerts = recent_quality_alerts(prepared)
        memory_context = load_memory_context(
            db, "SEGURO" if regime_info.get("safe") else "PELIGRO"
        )
        market_status      = db.get_market_data_status()
        db_last_write      = None
        updated_at_text    = market_status.get("market_data_updated_at")
        latest_prices_date = market_status.get("latest_prices_date")
        if updated_at_text and latest_prices_date == latest_date_str:
            db_last_write = datetime.strptime(updated_at_text, "%Y-%m-%d %H:%M:%S")

        results_a: list[ScanResult] = []
        results_c5: list[ScanResult] = []
        results_d: list[ScanResult] = []
        results_e: list[ScanResult] = []
        blocked_extreme: list[ScanResult] = []

        for ticker in sorted(t for t in prepared.keys() if t != "SPY"):
            df = prepared[ticker]

            # Signal A (solo en SEGURO)
            if regime_safe:
                sig_a = signal_a_mean_reversion(ticker, df)
                if sig_a is not None:
                    results_a.append(sig_a)

            # Signal D (cualquier regimen; sin duplicar con A)
            d_candidate = signal_d_leadership(ticker, df)
            if d_candidate is not None and not any(
                ex.ticker == ticker for ex in results_a
            ):
                results_d.append(d_candidate)

            # Signal E_HW (RS New High; sin duplicar con A o D)
            e_candidate = signal_e_hw_rs_new_high(ticker, df)
            if e_candidate is not None and not any(
                ex.ticker == ticker for ex in results_a + results_d
            ):
                results_e.append(e_candidate)

            # Signal C5 (cualquier regimen; sin duplicar con A)
            c_candidate = build_c5_candidate(ticker, df)
            if c_candidate is None:
                continue
            if any(ex.ticker == ticker for ex in results_a):
                continue
            if c5_is_preferred(c_candidate):
                results_c5.append(c_candidate)
            else:
                blocked_extreme.append(c_candidate)

        regime_label = "SEGURO" if regime_info.get("safe") else "PELIGRO"
        all_results  = apply_priority_layer(
            db, results_a + results_c5 + results_d + results_e,
            regime_label, latest_date_str
        )
        results_a   = [r for r in all_results if r.signal.startswith("A")]
        results_c5  = [r for r in all_results if r.signal.startswith("C5")]
        results_d   = [r for r in all_results if r.signal.startswith("D")]
        results_e   = [r for r in all_results if r.signal.startswith("E")]
        blocked_extreme.sort(key=lambda item: item.score, reverse=True)

        analyzed_date = prepared["SPY"].index[-1].date().isoformat()
        snapshot = Snapshot(
            run_started=run_started,
            run_finished=datetime.now(),
            analyzed_date=analyzed_date,
            db_last_write=db_last_write,
            freshness=freshness,
            regime_label=regime_label,
            breadth_pct=float(breadth["pct_above_sma50"]),
            results_a=results_a,
            results_c5=results_c5,
            results_d=results_d,
            results_e=results_e,
            blocked_extreme=blocked_extreme,
            quality_alerts=quality_alerts,
            memory_context=memory_context,
            is_panic=bool(regime_info.get("is_panic", False)),
        )

    print(render_header(snapshot))
    print(render_body(snapshot))

    all_signals = sorted(
        snapshot.results_a + snapshot.results_c5 + snapshot.results_d + snapshot.results_e,
        key=lambda item: (
            float(item.priority_score) if item.priority_score is not None else float(item.score),
        ),
        reverse=True,
    )

    if not all_signals:
        return

    if not snapshot_actionable(snapshot):
        print(SUBLINE)
        print("  Sizing omitido: la senal no esta vigente o la base esta stale.")
        return

    # Equity: argumento > guardado > interactivo
    equity_base = args.equity
    if equity_base is None:
        saved = load_equity_base()
        print(SUBLINE)
        try:
            hint = f" (Enter = usar guardado ${saved:,.0f})" if saved else ""
            raw  = input(f"  Capital disponible en USD{hint}: ").strip()
            if raw == "":
                equity_base = saved
            else:
                raw = raw.replace(",", "").replace("$", "").strip()
                equity_base = float(raw) if raw else saved
        except (EOFError, KeyboardInterrupt):
            equity_base = saved
        except ValueError:
            print("  Valor no valido, usando guardado." if saved else "  Valor no valido, sizing omitido.")
            equity_base = saved

    sizing_block = render_sizing_block(all_signals, equity_base)
    if sizing_block:
        print(sizing_block)


if __name__ == "__main__":
    main()
