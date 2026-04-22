#!/usr/bin/env python3
"""
INVERTIR V9 - DB-Integrated Scanner
===================================

Objetivo:
  Evolucionar V8 con una lectura mas critica del bloque Crash+Volume.

Hallazgo clave:
  V8 detecto como "crash" un evento corporativo reciente en BKNG.
  Eso no invalida los backtests historicos de V8, pero si demuestra que
  el scanner live necesita una capa de calidad de senal.

Mejora V9:
  Signal C3 = ROC 10d < -15% + Vol > 2x + RSI < 35
              + al menos 5 ruedas negativas en las ultimas 10
              + guard contra corporate-action / split-like repricing

Evidencia local sobre titan.db:
  Universo amplio:
    V8  : 171 trades | WR 68.4% | Sharpe 3.08 | MDD -20.5%
    V9  : 166 trades | WR 68.1% | Sharpe 3.08 | MDD -18.9%
  Universo core:
    V8  :  47 trades | WR 66.0% | Sharpe 3.64 | MDD  -9.8%
    V9  :  45 trades | WR 66.7% | Sharpe 3.92 | MDD  -9.8%

Estado:
  CANDIDATO SUPERADOR. Mejora la calidad de ejecucion y filtra crashes
  falsos por eventos corporativos. Aun no reemplaza automaticamente a V7.

Uso:
  python SCANNER/invertir_v9.py
"""

from __future__ import annotations

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


MODEL_NAME = "INVERTIR_V9"

# Signal A: se mantiene igual que V7
V7_RSI_MAX = 25
V7_SMA_DIST_MAX = -10.0
V7_SCORE_MIN = 30
V7_VOL_MAX = 1.5

# Signal C3: mejora candidata sobre V8
V9_ROC10_MAX = -15.0
V9_VOL_RATIO_MIN = 2.0
V9_C_RSI_MAX = 35.0
V9_NEG_DAYS10_MIN = 5

# Guard de corporate action / split-like event
V9_CORP_RET1_ABS_MIN = 0.60
V9_CORP_INTRADAY_ABS_MAX = 0.15
V9_CORP_RANGE_MAX = 0.15

V7_HOLDING_DAYS = 7
V7_ANTIKNIFE_DAYS = 5

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


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - 100 / (1 + rs)


def calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    return macd, signal_line, macd - signal_line


def calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def business_days_between(start_date: date, end_date: date) -> int:
    if end_date <= start_date:
        return 0
    count = 0
    cursor = start_date + timedelta(days=1)
    while cursor <= end_date:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def load_universe_data(db: TitanDB, tickers: list[str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    available = set(db.get_all_tickers())
    present = [ticker for ticker in tickers if ticker in available]

    if "SPY" not in present:
        present.append("SPY")

    data = {}
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

    missing = sorted([ticker for ticker in tickers if ticker not in data])
    return data, missing


def precompute_indicators(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
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
        work["CORP_ACTION_DAY"] = (
            (work["RET1"].abs() > V9_CORP_RET1_ABS_MIN)
            & (work["INTRADAY"].abs() < V9_CORP_INTRADAY_ABS_MAX)
            & (work["RANGE_PCT"] < V9_CORP_RANGE_MAX)
        )
        work["CORP_ACTION_10D"] = (
            work["CORP_ACTION_DAY"].rolling(10, min_periods=1).max().fillna(0).astype(bool)
        )
        prepared[ticker] = work
    return prepared


def latest_row(df: pd.DataFrame) -> pd.Series | None:
    if df is None or df.empty:
        return None
    return df.iloc[-1]


def check_regime(spy_df: pd.DataFrame) -> tuple[bool, dict[str, object]]:
    row = latest_row(spy_df)
    if row is None or len(spy_df) < 55:
        return False, {"reason": "Datos insuficientes"}

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


def signal_a_mean_reversion(ticker: str, df: pd.DataFrame) -> ScanResult | None:
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

    if corp_action:
        return None
    if curr_rsi >= 30 or curr_hist <= prev_hist or dist_sma50 > -5 or vol_ratio > V7_VOL_MAX:
        return None
    if curr_rsi >= V7_RSI_MAX or dist_sma50 > V7_SMA_DIST_MAX:
        return None

    macd_accel = curr_hist - prev_hist
    macd_accel_norm = macd_accel / (curr_atr * 0.01 + 1e-6)

    rsi_score = max(0, min(40, (30 - curr_rsi) / 30 * 40))
    stretch_score = max(0, min(30, (abs(dist_sma50) - 5) / 15 * 30))
    macd_score = max(0, min(20, macd_accel_norm * 5))
    vol_score = max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10))
    total_score = rsi_score + stretch_score + macd_score + vol_score

    if total_score < V7_SCORE_MIN:
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
        note="V7 base + quality guard",
    )


def signal_c3_crash_path_quality(ticker: str, df: pd.DataFrame) -> ScanResult | None:
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

    if corp_action:
        return None
    if roc10 >= V9_ROC10_MAX or vol_ratio < V9_VOL_RATIO_MIN or curr_rsi >= V9_C_RSI_MAX:
        return None
    if neg_days10 < V9_NEG_DAYS10_MIN:
        return None

    if pd.isna(curr_atr):
        curr_atr = price * 0.03

    stop = price - 2 * curr_atr
    target = price * 1.05
    risk_pct = (1 - stop / price) * 100
    score = abs(float(roc10)) * float(vol_ratio) * (1 + max(0.0, (V9_C_RSI_MAX - float(curr_rsi))) / 100)

    note = f"V9 path-quality | neg_days10={int(neg_days10)}"
    if get_sector(ticker) == "health":
        note += " | healthcare: vigilar"

    return ScanResult(
        ticker=ticker,
        signal="C3 (Crash+Path)",
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


def format_signal_rows(results: list[ScanResult]) -> pd.DataFrame:
    rows = []
    for result in results:
        rows.append(
            {
                "Ticker": result.ticker,
                "Signal": result.signal,
                "Sector": result.sector,
                "Precio": result.price,
                "RSI": "" if result.rsi is None else result.rsi,
                "vs SMA50": "" if result.dist_sma50 is None else f"{result.dist_sma50:.1f}%",
                "ROC 10d": "" if result.roc10 is None else f"{result.roc10:.1f}%",
                "Vol": "" if result.vol_ratio is None else f"{result.vol_ratio:.2f}x",
                "Stop": f"${result.stop:.2f}",
                "Target": f"${result.target:.2f}",
                "Riesgo": f"{result.risk_pct:.1f}%",
                "Score": round(result.score, 1),
                "Nota": result.note,
            }
        )
    return pd.DataFrame(rows)


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

    pct = sum(eligible) / len(eligible) * 100
    return {"pct_above_sma50": round(pct, 1), "count": len(eligible)}


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
        alerts.append(
            {
                "ticker": ticker,
                "date": flagged.index[-1].date().isoformat(),
                "ret1": round(float(last["RET1"] * 100), 1),
                "intraday": round(float(last["INTRADAY"] * 100), 1),
                "range_pct": round(float(last["RANGE_PCT"] * 100), 1),
            }
        )
    alerts.sort(key=lambda item: item["date"], reverse=True)
    return alerts


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

        results_a: list[ScanResult] = []
        results_c3: list[ScanResult] = []

        for ticker in sorted(t for t in prepared.keys() if t != "SPY"):
            df = prepared[ticker]

            if regime_safe:
                sig_a = signal_a_mean_reversion(ticker, df)
                if sig_a is not None:
                    results_a.append(sig_a)

            sig_c3 = signal_c3_crash_path_quality(ticker, df)
            if sig_c3 is not None and not any(existing.ticker == ticker for existing in results_a):
                results_c3.append(sig_c3)

        all_results = results_a + results_c3
        all_results.sort(key=lambda item: item.score, reverse=True)

        print("=" * 88)
        print(f"  {MODEL_NAME} - {today.isoformat()}")
        print("=" * 88)
        print("  Fuente datos     : titan.db")
        print(f"  Ultima fecha DB  : {latest_date_str}")
        if staleness is not None:
            freshness = "AL DIA" if staleness <= 1 else f"STALE ({staleness} dias habiles)"
            print(f"  Frescura DB      : {freshness}")
        print(f"  Universo V7      : {len(UNIVERSE)} tickers esperados")
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
        print("  PASO 2: SENALES V9")
        print("=" * 88)
        print("  Signal A         : RSI<25 + SMA<-10% + Score>30 [igual a V7, con quality guard]")
        print(
            "  Signal C3        : ROC10d<-15% + Vol>2x + RSI<35 + >=5 down days/10 + corp-action guard"
        )
        print(f"  Total senales    : {len(all_results)} ({len(results_a)} tipo A + {len(results_c3)} tipo C3)")

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

        if quality_alerts:
            print("  V9 detecto eventos corporativos recientes y los bloqueo para evitar falsos crashes.")

        if all_results:
            top = all_results[:3]
            print("  Top oportunidades:")
            for idx, signal in enumerate(top, start=1):
                print(
                    f"  {idx}. {signal.ticker:<6} | {signal.signal:<16} | ${signal.price:>8.2f} | "
                    f"Sector {signal.sector:<10} | Score {signal.score:>6.1f}"
                )
            print("\n  Reglas:")
            print("  - Maximo 3 posiciones simultaneas")
            print(f"  - Holding de referencia: {V7_HOLDING_DAYS} dias habiles")
            print(f"  - Anti-knife conceptual: no repetir ticker en {V7_ANTIKNIFE_DAYS} dias")
            print("  - C3 exige que el crash sea real y persistente, no un solo evento aislado")
            print("  - Corporate-action guard bloquea splits y repricings sospechosos")
        elif regime_safe:
            print("  Regimen seguro, pero sin setups de calidad. Esperar tambien es edge.")
        else:
            print("  Regimen peligroso y sin crashes de calidad suficientes. Mejor esperar.")

        print("\n" + "=" * 88)
        print("  VEREDICTO")
        print("=" * 88)
        print("  V9 refuta la lectura ingenua de V8 sobre crashes recientes.")
        print("  Mejora la seguridad live y mantiene un perfil cuantitativo competitivo.")
        print("  Ejecutar: python SCANNER/invertir_v9.py")
        print("  Referencia activa: python SCANNER/invertir_v7.py")


if __name__ == "__main__":
    main()
