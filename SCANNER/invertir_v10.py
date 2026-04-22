#!/usr/bin/env python3
"""
INVERTIR V10 REBOUND CAPTURE — Scanner Activo
==============================================
AUTOCONTENIDO: no depende de ningun otro scanner. Solo usa titan_system (infraestructura).

Arquitectura V10 (validada 2026-04-07):
  Signal A (Mean Reversion) — CON SPY regime
  Signal C4 (Crash + Path Quality + Rebound Capture) — SIN regime (contrarian)

Evolucion:
  V7 base (A+C) -> V9 path quality (corp guard + neg_days) -> V10 exit adaptativo
  V10 NO cambia la entrada. Cambia la SALIDA de Signal C:
    si sube +6% antes de day 4, tomar ganancia (capturar snapback).
    si no, hold fijo a day 7.

Resultados backtested V10 sobre titan.db (Mar 2024 - Abr 2026):
  Broad (171 tickers):
    V7  : Sharpe 2.89 | WR 67.0% | MDD -26.9%
    V10 : Sharpe 3.85 | WR 71.1% | MDD -19.0%
  Core (60 tickers):
    V7  : Sharpe 3.87 | WR 67.3% | MDD -9.8%
    V10 : Sharpe 5.60 | WR 71.1% | MDD -7.3%
  Walk-forward: WF5 100%, WF7 100% (broad) / 85.7% (core)
  Monte Carlo: P(Sharpe>0) 100%, worst 1% Sharpe 2.76 (broad) / 3.50 (core)

RSI: Wilder's smoothing ewm(com=13, adjust=False) — VERIFICADO

Uso:
  python SCANNER/invertir_v10.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Solo importamos INFRAESTRUCTURA (base de datos y sector map) — NUNCA otros scanners
from titan_system.core.database import TitanDB
from titan_system.core.data_loader import get_sector

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES Y PARAMETROS
# ══════════════════════════════════════════════════════════════════════════════

MODEL_NAME = "INVERTIR_V10_REBOUND_CAPTURE"

# Signal A: Mean Reversion (heredado de V7, intacto)
A_RSI_MAX = 25
A_SMA_DIST_MAX = -10.0
A_SCORE_MIN = 30
A_VOL_MAX = 1.5
A_HOLDING_DAYS = 7

# Signal C4: Crash + Path Quality + Rebound Capture
C_ROC10_MAX = -15.0
C_VOL_RATIO_MIN = 2.0
C_RSI_MAX = 35.0
C_NEG_DAYS10_MIN = 5
C_HOLDING_DAYS = 7
C_EARLY_TP_PCT = 6.0
C_EARLY_TP_DAYS = 4

# Guard de corporate action / split-like event
CORP_RET1_ABS_MIN = 0.60
CORP_INTRADAY_ABS_MAX = 0.15
CORP_RANGE_MAX = 0.15

# General
ANTIKNIFE_DAYS = 5

# ══════════════════════════════════════════════════════════════════════════════
# UNIVERSO (~197 tickers, sin LatAm)
# ══════════════════════════════════════════════════════════════════════════════

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

# ══════════════════════════════════════════════════════════════════════════════
# DATA CLASS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScanResult:
    ticker: str
    signal: str
    price: float
    sector: str
    rsi: float | None
    dist_sma50: float | None
    roc10: float | None
    vol_ratio: float | None
    stop: float
    target: float
    risk_pct: float
    score: float
    note: str = ""

# ══════════════════════════════════════════════════════════════════════════════
# INDICADORES TECNICOS
# ══════════════════════════════════════════════════════════════════════════════

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI con Wilder's smoothing: ewm(com=13, adjust=False). NUNCA rolling."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - 100 / (1 + rs)


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD estandar (12, 26, 9)."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line, macd - signal_line


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range."""
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

# ══════════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ══════════════════════════════════════════════════════════════════════════════

def business_days_between(start_date: date, end_date: date) -> int:
    """Cuenta dias habiles entre dos fechas."""
    if end_date <= start_date:
        return 0
    count = 0
    cursor = start_date + timedelta(days=1)
    while cursor <= end_date:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count

# ══════════════════════════════════════════════════════════════════════════════
# CARGA Y PREPARACION DE DATOS
# ══════════════════════════════════════════════════════════════════════════════

def load_universe_data(db: TitanDB, tickers: list[str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Carga OHLCV de titan.db para el universo + SPY."""
    available = set(db.get_all_tickers())
    present = [ticker for ticker in tickers if ticker in available]

    if "SPY" not in present:
        present.append("SPY")

    data = {}
    for ticker in present:
        df = db.get_prices(ticker)
        if df.empty:
            continue
        df = df.rename(columns={
            "open": "Open", "high": "High", "low": "Low",
            "close": "Close", "volume": "Volume",
        })
        data[ticker] = df[["Open", "High", "Low", "Close", "Volume"]].copy()

    missing = sorted([ticker for ticker in tickers if ticker not in data])
    return data, missing


def precompute_indicators(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Calcula todos los indicadores necesarios para ambas senales."""
    prepared = {}
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
        # Corporate action guard: detecta splits y repricings
        work["CORP_ACTION_DAY"] = (
            (work["RET1"].abs() > CORP_RET1_ABS_MIN)
            & (work["INTRADAY"].abs() < CORP_INTRADAY_ABS_MAX)
            & (work["RANGE_PCT"] < CORP_RANGE_MAX)
        )
        work["CORP_ACTION_10D"] = (
            work["CORP_ACTION_DAY"].rolling(10, min_periods=1).max().fillna(0).astype(bool)
        )
        prepared[ticker] = work
    return prepared

# ══════════════════════════════════════════════════════════════════════════════
# REGIME CHECK
# ══════════════════════════════════════════════════════════════════════════════

def check_regime(spy_df: pd.DataFrame) -> tuple[bool, dict[str, object]]:
    """SPY regime: safe = SPY > SMA50 AND vol 20d < 1%."""
    if spy_df is None or spy_df.empty or len(spy_df) < 55:
        return False, {"reason": "Datos insuficientes"}

    row = spy_df.iloc[-1]
    price = float(row["Close"])
    sma50 = float(row["SMA50"])
    vol_20d = float(spy_df["Close"].pct_change().rolling(20).std().iloc[-1] * 100)
    dist_sma50 = (price / sma50 - 1) * 100 if sma50 else 0

    above_sma = price > sma50
    low_vol = vol_20d < 1.0

    info = {
        "spy_price": round(price, 2),
        "spy_sma50": round(sma50, 2),
        "spy_dist": round(dist_sma50, 2),
        "spy_vol20d": round(vol_20d, 2),
        "above_sma": above_sma,
        "low_vol": low_vol,
        "safe": above_sma and low_vol,
    }
    return info["safe"], info

# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL A: MEAN REVERSION (con regime + quality guard)
# ══════════════════════════════════════════════════════════════════════════════

def signal_a_mean_reversion(ticker: str, df: pd.DataFrame) -> ScanResult | None:
    """
    Signal A: RSI<25 + MACD subiendo + SMA50 dist<-10% + Score>30
    Requiere regime safe. Guard de corporate action.
    """
    if len(df) < 55:
        return None

    row = df.iloc[-1]
    prev = df.iloc[-2]

    curr_rsi = row["RSI"]
    curr_hist = row["MACD_HIST"]
    prev_hist = prev["MACD_HIST"]
    price = row["Close"]
    curr_sma50 = row["SMA50"]
    curr_atr = row["ATR"]
    vol_ratio = row["VOL_RATIO"]
    dist_sma50 = row["DIST_SMA50"]
    corp_action = bool(row["CORP_ACTION_10D"])

    if any(pd.isna(v) for v in [curr_rsi, curr_hist, prev_hist, price, curr_sma50, curr_atr, vol_ratio, dist_sma50]):
        return None

    # Corporate action guard
    if corp_action:
        return None
    # Filtros base
    if curr_rsi >= 30 or curr_hist <= prev_hist or dist_sma50 > -5 or vol_ratio > A_VOL_MAX:
        return None
    # Filtros estrictos V7
    if curr_rsi >= A_RSI_MAX or dist_sma50 > A_SMA_DIST_MAX:
        return None

    # Score compuesto
    macd_accel = curr_hist - prev_hist
    macd_accel_norm = macd_accel / (curr_atr * 0.01 + 1e-6)

    rsi_score = max(0, min(40, (30 - curr_rsi) / 30 * 40))
    stretch_score = max(0, min(30, (abs(dist_sma50) - 5) / 15 * 30))
    macd_score = max(0, min(20, macd_accel_norm * 5))
    vol_score = max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10))
    total_score = rsi_score + stretch_score + macd_score + vol_score

    if total_score < A_SCORE_MIN:
        return None

    stop = price - 2 * curr_atr
    target = price * 1.03
    risk_pct = (1 - stop / price) * 100

    return ScanResult(
        ticker=ticker,
        signal="A (MeanRev)",
        price=round(float(price), 2),
        sector=get_sector(ticker),
        rsi=round(float(curr_rsi), 1),
        dist_sma50=round(float(dist_sma50), 1),
        roc10=None,
        vol_ratio=round(float(vol_ratio), 2),
        stop=round(float(stop), 2),
        target=round(float(target), 2),
        risk_pct=round(float(risk_pct), 1),
        score=float(total_score),
        note=f"hold {A_HOLDING_DAYS}d",
    )

# ══════════════════════════════════════════════════════════════════════════════
# SIGNAL C4: CRASH + PATH QUALITY + REBOUND CAPTURE
# ══════════════════════════════════════════════════════════════════════════════

def signal_c4_crash_rebound(ticker: str, df: pd.DataFrame) -> ScanResult | None:
    """
    Signal C4: ROC 10d < -15% + Volume > 2x + RSI < 35
               + neg_days10 >= 5 + corporate action guard
    Exit adaptativo: si cierre >= +6% en los primeros 4 dias, tomar ganancia.
                     Si no, cerrar en day 7.
    NO requiere regime safe (contrarian: funciona en mercados bajistas).
    """
    if len(df) < 25:
        return None

    row = df.iloc[-1]
    roc10 = row["ROC10"]
    vol_ratio = row["VOL_RATIO"]
    curr_rsi = row["RSI"]
    price = row["Close"]
    curr_atr = row["ATR"]
    dist_sma50 = row["DIST_SMA50"]
    neg_days10 = row["NEG_DAYS10"]
    corp_action = bool(row["CORP_ACTION_10D"])

    if any(pd.isna(v) for v in [roc10, vol_ratio, curr_rsi, price, neg_days10]):
        return None

    # Corporate action guard
    if corp_action:
        return None
    # Filtros de crash
    if roc10 >= C_ROC10_MAX or vol_ratio < C_VOL_RATIO_MIN or curr_rsi >= C_RSI_MAX:
        return None
    # Path quality: al menos 5 ruedas negativas de 10
    if neg_days10 < C_NEG_DAYS10_MIN:
        return None

    if pd.isna(curr_atr):
        curr_atr = price * 0.03

    stop = price - 2 * curr_atr
    target = price * 1.05
    risk_pct = (1 - stop / price) * 100
    score = abs(float(roc10)) * float(vol_ratio) * (1 + max(0.0, (C_RSI_MAX - float(curr_rsi))) / 100)

    note = f"neg_days={int(neg_days10)} | exit: +{C_EARLY_TP_PCT:.0f}% <= day {C_EARLY_TP_DAYS}, sino day {C_HOLDING_DAYS}"
    if get_sector(ticker) == "health":
        note += " | healthcare: vigilar"

    return ScanResult(
        ticker=ticker,
        signal="C4 (Crash+Rebound)",
        price=round(float(price), 2),
        sector=get_sector(ticker),
        rsi=round(float(curr_rsi), 1),
        dist_sma50=round(float(dist_sma50), 1) if not pd.isna(dist_sma50) else None,
        roc10=round(float(roc10), 1),
        vol_ratio=round(float(vol_ratio), 2),
        stop=round(float(stop), 2),
        target=round(float(target), 2),
        risk_pct=round(float(risk_pct), 1),
        score=score,
        note=note,
    )

# ══════════════════════════════════════════════════════════════════════════════
# BREADTH Y QUALITY ALERTS
# ══════════════════════════════════════════════════════════════════════════════

def compute_breadth(universe_data: dict[str, pd.DataFrame]) -> dict[str, object]:
    """Porcentaje de tickers del universo por encima de su SMA50."""
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
    """Detecta corporate actions recientes para alertar al usuario."""
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

# ══════════════════════════════════════════════════════════════════════════════
# DISPLAY
# ══════════════════════════════════════════════════════════════════════════════

def format_signal_rows(results: list[ScanResult]) -> pd.DataFrame:
    """Formatea resultados para display en consola."""
    rows = []
    for r in results:
        rows.append({
            "Ticker": r.ticker,
            "Signal": r.signal,
            "Sector": r.sector,
            "Precio": r.price,
            "RSI": "" if r.rsi is None else r.rsi,
            "vs SMA50": "" if r.dist_sma50 is None else f"{r.dist_sma50:.1f}%",
            "ROC 10d": "" if r.roc10 is None else f"{r.roc10:.1f}%",
            "Vol": "" if r.vol_ratio is None else f"{r.vol_ratio:.2f}x",
            "Stop": f"${r.stop:.2f}",
            "Target": f"${r.target:.2f}",
            "Riesgo": f"{r.risk_pct:.1f}%",
            "Score": round(r.score, 1),
            "Nota": r.note,
        })
    return pd.DataFrame(rows)

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    today = date.today()

    with TitanDB() as db:
        universe_data, missing = load_universe_data(db, UNIVERSE)
        prepared = precompute_indicators(universe_data)

        if "SPY" not in prepared:
            print("ERROR: SPY no esta en titan.db. No se puede evaluar el regimen.")
            return

        latest_date_str = db.get_latest_date("SPY")
        latest_dt = datetime.strptime(latest_date_str, "%Y-%m-%d").date() if latest_date_str else None
        staleness = business_days_between(latest_dt, today) if latest_dt else None
        regime_safe, regime_info = check_regime(prepared["SPY"])
        breadth = compute_breadth(universe_data)
        quality_alerts = recent_quality_alerts(prepared)

        # ── Generar senales ──────────────────────────────────────────────
        results_a: list[ScanResult] = []
        results_c4: list[ScanResult] = []

        for ticker in sorted(t for t in prepared.keys() if t != "SPY"):
            df = prepared[ticker]

            # Signal A solo si regime es safe
            if regime_safe:
                sig_a = signal_a_mean_reversion(ticker, df)
                if sig_a is not None:
                    results_a.append(sig_a)

            # Signal C4 siempre activa (contrarian), pero no duplicar ticker si ya dio Signal A
            sig_c4 = signal_c4_crash_rebound(ticker, df)
            if sig_c4 is not None and not any(existing.ticker == ticker for existing in results_a):
                results_c4.append(sig_c4)

        all_results = results_a + results_c4
        all_results.sort(key=lambda item: item.score, reverse=True)

        # ── Output ───────────────────────────────────────────────────────
        print("=" * 88)
        print(f"  {MODEL_NAME} - {today.isoformat()}")
        print("=" * 88)
        print("  Fuente datos     : titan.db")
        print(f"  Ultima fecha DB  : {latest_date_str}")
        if staleness is not None:
            freshness = "AL DIA" if staleness <= 1 else f"STALE ({staleness} dias habiles)"
            print(f"  Frescura DB      : {freshness}")
        print(f"  Universo         : {len(UNIVERSE)} tickers esperados")
        print(f"  Cobertura DB     : {len(prepared) - 1} tickers + SPY")
        if missing:
            print(f"  Tickers faltantes: {len(missing)}")

        print("\n" + "=" * 88)
        print("  PASO 1: REGIMEN, BREADTH Y CALIDAD")
        print("=" * 88)
        if "safe" in regime_info:
            regime_label = "SEGURO" if regime_info["safe"] else "PELIGRO"
            print(
                f"  SPY ${regime_info['spy_price']:.2f} | dist SMA50 {regime_info['spy_dist']:+.2f}% | "
                f"vol20 {regime_info['spy_vol20d']:.2f}% | regimen {regime_label}"
            )
        else:
            print(f"  Regimen: {regime_info.get('reason', 'sin informacion')}")
        print(f"  Breadth > SMA50  : {breadth['pct_above_sma50']:.1f}% ({breadth['count']} tickers evaluables)")
        if quality_alerts:
            print("  Alertas calidad  :")
            for alert in quality_alerts[:5]:
                print(
                    f"    - {alert['ticker']} | {alert['date']} | ret1 {alert['ret1']:+.1f}% | "
                    f"intraday {alert['intraday']:+.1f}% | rango {alert['range_pct']:.1f}%"
                )

        print("\n" + "=" * 88)
        print("  PASO 2: SENALES V10")
        print("=" * 88)
        print(f"  Signal A         : RSI<{A_RSI_MAX} + SMA<{A_SMA_DIST_MAX}% + Score>{A_SCORE_MIN} [con regime + quality guard]")
        print(
            f"  Signal C4        : ROC10d<{C_ROC10_MAX}% + Vol>{C_VOL_RATIO_MIN}x + RSI<{C_RSI_MAX} "
            f"+ >={C_NEG_DAYS10_MIN} down days/10 + corp-action guard"
        )
        print(f"  Exit C4          : cierre >= +{C_EARLY_TP_PCT:.0f}% en primeros {C_EARLY_TP_DAYS} dias = tomar ganancia; sino day {C_HOLDING_DAYS}")
        print(f"  Total senales    : {len(all_results)} ({len(results_a)} tipo A + {len(results_c4)} tipo C4)")

        if all_results:
            df_show = format_signal_rows(all_results)
            print()
            print(df_show.to_string(index=False))
        else:
            print("\n  Sin senales hoy en la ultima fecha de la DB.")

        print("\n" + "=" * 88)
        print("  PASO 3: LECTURA OPERATIVA")
        print("=" * 88)

        if staleness and staleness > 1:
            print("  AVISO: la DB no esta fresca. Actualiza antes de tomar una decision real.")
            print("  Ejecutar: python herramientas/actualizar_datos.py")

        if quality_alerts:
            print("  Corporate-action guard activo: eventos corporativos recientes bloqueados.")

        if all_results:
            top = all_results[:3]
            print("  Top oportunidades:")
            for idx, signal in enumerate(top, start=1):
                print(
                    f"  {idx}. {signal.ticker:<6} | {signal.signal:<20} | ${signal.price:>8.2f} | "
                    f"Sector {signal.sector:<10} | Score {signal.score:>6.1f}"
                )
            print("\n  Reglas de ejecucion:")
            print("  - Maximo 3 posiciones simultaneas")
            print(f"  - Signal A: hold {A_HOLDING_DAYS} dias habiles")
            print(f"  - Signal C4: si cierre >= +{C_EARLY_TP_PCT:.0f}% antes de day {C_EARLY_TP_DAYS}, tomar ganancia")
            print(f"  - Signal C4: si no activa TP temprano, cerrar en day {C_HOLDING_DAYS}")
            print(f"  - Anti-knife: no repetir ticker en {ANTIKNIFE_DAYS} dias")
            print("  - Corporate-action guard bloquea splits y repricings sospechosos")
        elif regime_safe:
            print("  Regimen seguro, pero sin setups de calidad. Esperar tambien es edge.")
        else:
            print("  Regimen peligroso y sin crashes de calidad suficientes. Mejor esperar.")

        print("\n" + "=" * 88)
        print("  FIN")
        print("=" * 88)
        print("  Scanner activo: python SCANNER/invertir_v10.py")
        print("  Actualizar DB  : python herramientas/actualizar_datos.py")


if __name__ == "__main__":
    main()
