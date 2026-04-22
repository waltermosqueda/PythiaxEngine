"""
INVESTIGACION V17 - AUDITORIA DURA DE SIGNAL D (LIDERAZGO/TENDENCIA)
=====================================================================

Objetivo:
  Someter D_LEADERSHIP_STRICT a la auditoria mas exigente posible antes de
  decidir si merece ser promovida como tercer eje ortogonal de un futuro V12.

  V16 (sesion 49) mostro que V11+LEAD_STRICT gana en 3/7 ventanas WF.
  Eso NO es suficiente para promover. Esta investigacion cubre:

  [A] Grid de sensibilidad completo (16+ combinaciones de parametros)
  [B] Walk-forward de 10 ventanas
  [C] Sensibilidad al hold period (5d, 7d, 10d, 14d)
  [D] Analisis de regime split profundo (SEGURO / PELIGRO independientes)
  [E] Concentracion sectorial y por ticker (HHI, top-N dominance)
  [F] Monte Carlo sobre el portfolio hibrido (1000 permutaciones)
  [G] Promotion gate explicito: reglas concretas PASS/FAIL

Criterios de promotion gate (todos deben cumplirse):
  PG1. WF >= 7/10 ventanas donde hybrid_sharpe > base_sharpe
  PG2. Sharpe portfolio hibrido full-period >= 1.10
  PG3. MDD portfolio hibrido full-period <= -45%
  PG4. MC P(hybrid_sharpe > base_sharpe) >= 70%
  PG5. Concentracion: ningun ticker > 15% del total de trades
  PG6. Hold period ganador coincide con 10d (el usado en el backtest)
  PG7. En regime SEGURO Y en PELIGRO la pata D tiene avg_return >= 0 con >= 30 trades

Veredicto final:
  PROMOVER  : cumple >= 6/7 gates
  CONDICIONAL : cumple 5/7 gates
  RECHAZAR    : cumple < 5 gates

Fecha: 2026-04-09
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.investigacion_v10_rebound_capture import c_exit_return
from backtests.investigacion_v12_portfolio_operativo import (
    INITIAL_EQUITY,
    MAX_POSITIONS,
    calc_a_score,
    calc_c_score,
    calc_portfolio_metrics,
)
from backtests.investigacion_v9_path_quality import (
    ANTIKNIFE_DAYS,
    BROAD_UNIVERSE,
    START_IDX,
    calc_metrics,
    load_db_data,
    precompute,
)

LINE = "=" * 100
SUBLINE = "-" * 100

# Arquitectura sleeve
V11_PRIMARY_SLOTS = 2
LEADERSHIP_SLOTS = 1
TOTAL_SLOTS = V11_PRIMARY_SLOTS + LEADERSHIP_SLOTS

# Parametros D_LEADERSHIP_STRICT de referencia (V16)
D_STRICT_REF = {
    "roc20_min": 12.0,
    "rel20_min": 7.0,
    "rsi_min": 55.0,
    "rsi_max": 75.0,
    "vol_min": 0.8,
    "vol_max": 2.0,
}

LEADERSHIP_HOLD_DEFAULT = 10

MC_ITERATIONS = 1_000
random.seed(42)
np.random.seed(42)


# ─────────────────────────────────────────────────────────────────────────────
# ESTRUCTURA DE DATOS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Candidate:
    ticker: str
    signal: str
    entry_idx: int
    exit_idx: int
    raw_score: float
    signal_date: pd.Timestamp
    regime: str
    sector: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# SECTOR LOOKUP SIMPLE (para concentracion)
# ─────────────────────────────────────────────────────────────────────────────

SECTOR_MAP = {
    # Tech
    "AAPL": "Tech", "ADBE": "Tech", "ADI": "Tech", "ALAB": "Tech", "AMAT": "Tech",
    "AMD": "Tech", "ARM": "Tech", "ASML": "Tech", "AVGO": "Tech", "BIDU": "Tech",
    "COIN": "Tech", "CRM": "Tech", "CRWV": "Tech", "CSCO": "Tech", "DOCU": "Tech",
    "ETSY": "Tech", "GOOGL": "Tech", "IBM": "Tech", "INTC": "Tech", "IREN": "Tech",
    "LRCX": "Tech", "META": "Tech", "MRVL": "Tech", "MSFT": "Tech", "MSTR": "Tech",
    "MU": "Tech", "NTES": "Tech", "NVDA": "Tech", "ORCL": "Tech", "PANW": "Tech",
    "PATH": "Tech", "PLTR": "Tech", "QCOM": "Tech", "RBLX": "Tech", "RGTI": "Tech",
    "ROKU": "Tech", "SAP": "Tech", "SE": "Tech", "SHOP": "Tech", "SNAP": "Tech",
    "SNOW": "Tech", "SONY": "Tech", "SPOT": "Tech", "TEAM": "Tech", "TSM": "Tech",
    "TWLO": "Tech", "UBER": "Tech", "UPST": "Tech", "ZM": "Tech",
    # HW/Industrial Tech
    "GLW": "HW", "GRMN": "HW", "HPQ": "HW", "MSI": "HW", "SWKS": "HW", "TXN": "HW",
    "EA": "HW", "ASTS": "HW", "RKLB": "HW", "ERIC": "HW", "BB": "HW",
    # Finance
    "AXP": "Finance", "BAC": "Finance", "BCS": "Finance", "BK": "Finance",
    "BKNG": "Finance", "C": "Finance", "GS": "Finance", "HOOD": "Finance",
    "HSBC": "Finance", "ING": "Finance", "JPM": "Finance", "LYG": "Finance",
    "MA": "Finance", "MUFG": "Finance", "PYPL": "Finance", "SCHW": "Finance",
    "USB": "Finance", "V": "Finance", "WFC": "Finance", "AIG": "Finance", "HDB": "Finance",
    # Healthcare
    "ABBV": "Health", "ABT": "Health", "AMGN": "Health", "AZN": "Health",
    "BIIB": "Health", "BMY": "Health", "CVS": "Health", "DHR": "Health",
    "GILD": "Health", "GSK": "Health", "ISRG": "Health", "JNJ": "Health",
    "LLY": "Health", "MDT": "Health", "MRK": "Health", "MRNA": "Health",
    "NVS": "Health", "PFE": "Health", "TMO": "Health", "UNH": "Health",
    # Energy
    "BKR": "Energy", "BP": "Energy", "CVX": "Energy", "E": "Energy",
    "EQNR": "Energy", "HAL": "Energy", "OXY": "Energy", "PSX": "Energy",
    "SHEL": "Energy", "SLB": "Energy", "TTE": "Energy", "XOM": "Energy",
    # Materials/Mining
    "AEM": "Mining", "B": "Mining", "BHP": "Mining", "CDE": "Mining",
    "FCX": "Mining", "GFI": "Mining", "HL": "Mining", "HMY": "Mining",
    "KGC": "Mining", "LAC": "Mining", "MOS": "Mining", "MUX": "Mining",
    "NEM": "Mining", "NG": "Mining", "NUE": "Mining", "PAAS": "Mining",
    "RIO": "Mining", "AAP": "Mining",
    # Consumer
    "ANF": "Consumer", "CL": "Consumer", "COST": "Consumer", "DEO": "Consumer",
    "EBAY": "Consumer", "HD": "Consumer", "HSY": "Consumer", "KMB": "Consumer",
    "KO": "Consumer", "MCD": "Consumer", "MDLZ": "Consumer", "MO": "Consumer",
    "NKE": "Consumer", "ORLY": "Consumer", "PEP": "Consumer", "PG": "Consumer",
    "PM": "Consumer", "ROST": "Consumer", "SBUX": "Consumer", "SYY": "Consumer",
    "TGT": "Consumer", "TJX": "Consumer", "UL": "Consumer", "WMT": "Consumer",
    "YELP": "Consumer",
    # Industrial
    "AVY": "Indust", "BA": "Indust", "CAT": "Indust", "DD": "Indust",
    "DE": "Indust", "FDX": "Indust", "GE": "Indust", "HON": "Indust",
    "HWM": "Indust", "IFF": "Indust", "IP": "Indust", "LMT": "Indust",
    "MMM": "Indust", "PCAR": "Indust", "PBI": "Indust", "RTX": "Indust",
    "SNA": "Indust", "UNP": "Indust",
    # Auto/Aero
    "F": "Auto", "GM": "Auto", "HMC": "Auto", "HOG": "Auto", "NIO": "Auto",
    "RACE": "Auto", "STLA": "Auto", "TM": "Auto", "TSLA": "Auto",
    # Travel
    "AAL": "Travel", "ABNB": "Travel", "CAR": "Travel", "CCL": "Travel",
    "DAL": "Travel", "LVS": "Travel", "SPCE": "Travel", "TCOM": "Travel",
    "TRIP": "Travel", "UAL": "Travel",
    # Telecom
    "TMUS": "Telecom", "VOD": "Telecom", "VZ": "Telecom",
}


def get_sector(ticker: str) -> str:
    return SECTOR_MAP.get(ticker, "Other")


# ─────────────────────────────────────────────────────────────────────────────
# PREPARACION DE DATOS
# ─────────────────────────────────────────────────────────────────────────────

def prepare_universe() -> tuple[dict[str, pd.DataFrame], Any]:
    data, missing = load_db_data(BROAD_UNIVERSE)
    if missing:
        print(f"  [WARN] Tickers faltantes en DB: {len(missing)}")

    prepared = precompute(data)

    spy = prepared["SPY"].copy()
    spy["SMA200"] = spy["Close"].rolling(200).mean()
    spy["REGIME_SMA200"] = spy["Close"] > spy["SMA200"]
    spy["SPY_ROC20"] = (spy["Close"] / spy["Close"].shift(20) - 1.0) * 100.0
    prepared["SPY"] = spy

    for ticker, df in prepared.items():
        work = df.copy()
        work["SMA20"] = work["Close"].rolling(20).mean()
        work["SMA200"] = work["Close"].rolling(200).mean()
        work["DIST_SMA200"] = (work["Close"] / work["SMA200"] - 1.0) * 100.0
        work["ROC20"] = (work["Close"] / work["Close"].shift(20) - 1.0) * 100.0
        work["RET5"] = (work["Close"] / work["Close"].shift(5) - 1.0) * 100.0
        work["REL20"] = work["ROC20"] - spy["SPY_ROC20"]
        work["HH20"] = work["Close"].shift(1).rolling(20).max()
        work["BB_WIDTH"] = (work["Close"].rolling(20).std() * 4.0 / (work["SMA20"] + 1e-10)) * 100.0
        work["BB_WIDTH_P20"] = work["BB_WIDTH"].shift(1).rolling(20).quantile(0.2)
        prepared[ticker] = work

    return prepared, prepared["SPY"].index


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL D_LEADERSHIP
# ─────────────────────────────────────────────────────────────────────────────

def signal_d_leadership(
    row: pd.Series,
    *,
    roc20_min: float = 12.0,
    rel20_min: float = 7.0,
    rsi_min: float = 55.0,
    rsi_max: float = 75.0,
    vol_min: float = 0.8,
    vol_max: float = 2.0,
) -> bool:
    return bool(
        pd.notna(row["SMA200"])
        and (row["Close"] > row["SMA50"])
        and (row["SMA50"] > row["SMA200"])
        and (row["ROC20"] > roc20_min)
        and (row["REL20"] > rel20_min)
        and (rsi_min <= row["RSI"] <= rsi_max)
        and (vol_min <= row["VOL_RATIO"] <= vol_max)
        and not bool(row["CORP_ACTION_10D"])
    )


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUCCION DE CANDIDATOS
# ─────────────────────────────────────────────────────────────────────────────

def build_v11_candidates(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
) -> tuple[dict[int, list[Candidate]], list[dict]]:
    pending: dict[int, list[Candidate]] = {}
    rows: list[dict] = []
    last_entry: dict[str, int] = {}

    for idx in range(START_IDX, len(dates) - 8):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
        signal_date = dates[idx]
        regime_label = "SEGURO" if regime_safe else "PELIGRO"

        for ticker in BROAD_UNIVERSE:
            if ticker == "SPY" or ticker not in prepared:
                continue
            if ticker in last_entry and (idx - last_entry[ticker]) < ANTIKNIFE_DAYS:
                continue

            df = prepared[ticker]
            candidate: Candidate | None = None
            ret: float | None = None

            if regime_safe and bool(df["SIG_A_GUARD"].iloc[idx]):
                entry = df["Close"].iloc[idx + 1]
                exit_px = df["Close"].iloc[idx + 8]
                if pd.notna(entry) and pd.notna(exit_px):
                    ret = float((exit_px / entry - 1.0) * 100.0)
                    candidate = Candidate(
                        ticker=ticker,
                        signal="A",
                        entry_idx=idx + 1,
                        exit_idx=idx + 8,
                        raw_score=calc_a_score(df, idx),
                        signal_date=signal_date,
                        regime=regime_label,
                        sector=get_sector(ticker),
                    )

            elif bool(df["SIG_C_V9_NEG5"].iloc[idx]):
                score = calc_c_score(df, idx)
                vol_ratio = float(df["VOL_RATIO"].iloc[idx])
                if score < 85.0 and vol_ratio < 4.0:
                    ret_c, exit_day, _ = c_exit_return(df, idx)
                    if ret_c is not None and exit_day is not None:
                        ret = ret_c
                        candidate = Candidate(
                            ticker=ticker,
                            signal="C5",
                            entry_idx=idx + 1,
                            exit_idx=idx + 1 + exit_day,
                            raw_score=score,
                            signal_date=signal_date,
                            regime=regime_label,
                            sector=get_sector(ticker),
                        )

            if candidate is None or ret is None:
                continue

            pending.setdefault(candidate.entry_idx, []).append(candidate)
            rows.append({
                "ticker": candidate.ticker,
                "date": candidate.signal_date,
                "signal": candidate.signal,
                "regime": candidate.regime,
                "sector": candidate.sector,
                "return_pct": ret,
            })
            last_entry[ticker] = idx

    return pending, rows


def build_d_candidates(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    *,
    params: dict[str, float],
    hold_days: int = LEADERSHIP_HOLD_DEFAULT,
) -> tuple[dict[int, list[Candidate]], list[dict]]:
    pending: dict[int, list[Candidate]] = {}
    rows: list[dict] = []
    last_entry: dict[str, int] = {}

    for idx in range(START_IDX, len(dates) - (hold_days + 2)):
        signal_date = dates[idx]
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
        regime_label = "SEGURO" if regime_safe else "PELIGRO"

        for ticker in BROAD_UNIVERSE:
            if ticker == "SPY" or ticker not in prepared:
                continue
            if ticker in last_entry and (idx - last_entry[ticker]) < ANTIKNIFE_DAYS:
                continue

            df = prepared[ticker]
            row = df.iloc[idx]

            if not signal_d_leadership(row, **params):
                continue

            entry = df["Close"].iloc[idx + 1]
            exit_px = df["Close"].iloc[idx + 1 + hold_days]
            if pd.isna(entry) or pd.isna(exit_px):
                continue

            score = float(row["REL20"] + row["ROC20"])
            candidate = Candidate(
                ticker=ticker,
                signal="D_LEAD",
                entry_idx=idx + 1,
                exit_idx=idx + 1 + hold_days,
                raw_score=score,
                signal_date=signal_date,
                regime=regime_label,
                sector=get_sector(ticker),
            )
            pending.setdefault(candidate.entry_idx, []).append(candidate)
            rows.append({
                "ticker": candidate.ticker,
                "date": candidate.signal_date,
                "signal": candidate.signal,
                "regime": candidate.regime,
                "sector": candidate.sector,
                "return_pct": float((exit_px / entry - 1.0) * 100.0),
            })
            last_entry[ticker] = idx

    return pending, rows


# ─────────────────────────────────────────────────────────────────────────────
# SIMULACION DE PORTFOLIO SLEEVE
# ─────────────────────────────────────────────────────────────────────────────

def simulate_sleeves(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    primary_pending: dict[int, list[Candidate]],
    *,
    primary_slots: int,
    secondary_pending: dict[int, list[Candidate]] | None = None,
    secondary_slots: int = 0,
    start_idx: int | None = None,
    end_idx: int | None = None,
) -> dict[str, object]:
    start = START_IDX + 1 if start_idx is None else start_idx
    end = len(dates) if end_idx is None else end_idx

    cash = INITIAL_EQUITY
    cooldown_until: dict[str, int] = {}
    primary_positions: list[dict] = []
    secondary_positions: list[dict] = []
    equity_rows: list[dict] = []
    closed_rows: list[dict] = []
    total_slots = max(1, primary_slots + secondary_slots)

    for idx in range(start, end):
        equity = cash
        for pos in primary_positions + secondary_positions:
            if pos["ticker"] in prepared:
                px = float(prepared[pos["ticker"]]["Close"].iloc[idx])
                equity += float(pos["shares"]) * px
        equity_rows.append({
            "equity": equity,
            "open_positions": float(len(primary_positions) + len(secondary_positions)),
        })

        still_primary = []
        still_secondary = []

        for pos in primary_positions:
            if int(pos["exit_idx"]) == idx:
                px = float(prepared[pos["ticker"]]["Close"].iloc[idx])
                cash += float(pos["shares"]) * px
                closed_rows.append({
                    "return_pct": (px / float(pos["entry_price"]) - 1.0) * 100.0,
                    "signal": pos["signal"],
                    "ticker": pos["ticker"],
                    "sector": pos.get("sector", ""),
                })
            else:
                still_primary.append(pos)

        for pos in secondary_positions:
            if int(pos["exit_idx"]) == idx:
                px = float(prepared[pos["ticker"]]["Close"].iloc[idx])
                cash += float(pos["shares"]) * px
                closed_rows.append({
                    "return_pct": (px / float(pos["entry_price"]) - 1.0) * 100.0,
                    "signal": pos["signal"],
                    "ticker": pos["ticker"],
                    "sector": pos.get("sector", ""),
                })
            else:
                still_secondary.append(pos)

        primary_positions = still_primary
        secondary_positions = still_secondary

        total_equity = cash
        for pos in primary_positions + secondary_positions:
            if pos["ticker"] in prepared:
                px = float(prepared[pos["ticker"]]["Close"].iloc[idx])
                total_equity += float(pos["shares"]) * px
        slot_budget = total_equity / float(total_slots)

        free_primary = primary_slots - len(primary_positions)
        if free_primary > 0:
            ranked = sorted(
                primary_pending.get(idx, []),
                key=lambda c: c.raw_score,
                reverse=True,
            )
            for candidate in ranked:
                if free_primary <= 0:
                    break
                occupied = {pos["ticker"] for pos in primary_positions + secondary_positions}
                if candidate.ticker in occupied:
                    continue
                if idx <= cooldown_until.get(candidate.ticker, -999):
                    continue
                if candidate.ticker not in prepared:
                    continue

                px = float(prepared[candidate.ticker]["Close"].iloc[idx])
                invested = min(slot_budget, cash)
                if invested <= 0:
                    break

                primary_positions.append({
                    "ticker": candidate.ticker,
                    "signal": candidate.signal,
                    "entry_price": px,
                    "shares": invested / px,
                    "exit_idx": candidate.exit_idx,
                    "sector": candidate.sector,
                })
                cash -= invested
                cooldown_until[candidate.ticker] = idx + ANTIKNIFE_DAYS
                free_primary -= 1

        if secondary_pending and secondary_slots > 0:
            free_secondary = secondary_slots - len(secondary_positions)
            if free_secondary > 0:
                ranked_sec = sorted(
                    secondary_pending.get(idx, []),
                    key=lambda c: c.raw_score,
                    reverse=True,
                )
                for candidate in ranked_sec:
                    if free_secondary <= 0:
                        break
                    occupied = {pos["ticker"] for pos in primary_positions + secondary_positions}
                    if candidate.ticker in occupied:
                        continue
                    if idx <= cooldown_until.get(candidate.ticker, -999):
                        continue
                    if candidate.ticker not in prepared:
                        continue

                    px = float(prepared[candidate.ticker]["Close"].iloc[idx])
                    invested = min(slot_budget, cash)
                    if invested <= 0:
                        break

                    secondary_positions.append({
                        "ticker": candidate.ticker,
                        "signal": candidate.signal,
                        "entry_price": px,
                        "shares": invested / px,
                        "exit_idx": candidate.exit_idx,
                        "sector": candidate.sector,
                    })
                    cash -= invested
                    cooldown_until[candidate.ticker] = idx + ANTIKNIFE_DAYS
                    free_secondary -= 1

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(closed_rows)
    return {
        "metrics": calc_portfolio_metrics(equity_df, trades_df),
        "trades": trades_df,
        "equity": equity_df,
    }


# ─────────────────────────────────────────────────────────────────────────────
# [A] GRID DE SENSIBILIDAD COMPLETO
# ─────────────────────────────────────────────────────────────────────────────

def run_sensitivity_grid(
    prepared: dict[str, pd.DataFrame],
    dates: Any,
    v11_pending: dict[int, list[Candidate]],
) -> pd.DataFrame:
    grid = []
    for roc20_min in [8.0, 10.0, 12.0, 15.0]:
        for rel20_min in [3.0, 5.0, 7.0, 10.0]:
            for rsi_min in [50.0, 55.0]:
                for vol_max in [2.0, 2.5]:
                    params = {
                        "roc20_min": roc20_min,
                        "rel20_min": rel20_min,
                        "rsi_min": rsi_min,
                        "rsi_max": 75.0,
                        "vol_min": 0.8,
                        "vol_max": vol_max,
                    }
                    d_pending, d_rows = build_d_candidates(prepared, dates, params=params)
                    if not d_rows:
                        continue
                    d_df = pd.DataFrame(d_rows)
                    result = simulate_sleeves(
                        prepared,
                        dates,
                        v11_pending,
                        primary_slots=V11_PRIMARY_SLOTS,
                        secondary_pending=d_pending,
                        secondary_slots=LEADERSHIP_SLOTS,
                    )
                    m = result["metrics"]
                    d_metrics = calc_metrics(d_df)
                    grid.append({
                        "roc20_min": roc20_min,
                        "rel20_min": rel20_min,
                        "rsi_min": rsi_min,
                        "vol_max": vol_max,
                        "d_signals": len(d_df),
                        "d_wr": round(float(d_metrics["wr"]), 1),
                        "d_avg": round(float(d_metrics["avg"]), 2),
                        "d_sharpe": round(float(d_metrics["sharpe"]), 2),
                        "hyb_sharpe": round(float(m["sharpe"]), 2),
                        "hyb_total": round(float(m["total"]), 1),
                        "hyb_mdd": round(float(m["mdd"]), 1),
                    })

    df = pd.DataFrame(grid)
    return df.sort_values(["hyb_sharpe", "hyb_total"], ascending=[False, False])


# ─────────────────────────────────────────────────────────────────────────────
# [B] WALK-FORWARD 10 VENTANAS
# ─────────────────────────────────────────────────────────────────────────────

def run_walk_forward_10(
    prepared: dict[str, pd.DataFrame],
    dates: Any,
    v11_pending: dict[int, list[Candidate]],
    d_pending: dict[int, list[Candidate]],
) -> pd.DataFrame:
    start = START_IDX + 1
    usable = len(dates) - start
    step = usable // 10
    rows = []

    for window in range(10):
        a = start + window * step
        b = len(dates) if window == 9 else start + (window + 1) * step

        base = simulate_sleeves(
            prepared, dates, v11_pending,
            primary_slots=MAX_POSITIONS,
            start_idx=a, end_idx=b,
        )["metrics"]

        hybrid = simulate_sleeves(
            prepared, dates, v11_pending,
            primary_slots=V11_PRIMARY_SLOTS,
            secondary_pending=d_pending,
            secondary_slots=LEADERSHIP_SLOTS,
            start_idx=a, end_idx=b,
        )["metrics"]

        rows.append({
            "window": window + 1,
            "from": str(dates[a].date()),
            "to": str(dates[min(b - 1, len(dates) - 1)].date()),
            "base_sharpe": round(float(base["sharpe"]), 2),
            "base_total": round(float(base["total"]), 1),
            "base_mdd": round(float(base["mdd"]), 1),
            "hyb_sharpe": round(float(hybrid["sharpe"]), 2),
            "hyb_total": round(float(hybrid["total"]), 1),
            "hyb_mdd": round(float(hybrid["mdd"]), 1),
            "hyb_wins": int(hybrid["sharpe"] > base["sharpe"]),
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# [C] SENSIBILIDAD AL HOLD PERIOD
# ─────────────────────────────────────────────────────────────────────────────

def run_hold_sensitivity(
    prepared: dict[str, pd.DataFrame],
    dates: Any,
    v11_pending: dict[int, list[Candidate]],
    params: dict[str, float],
) -> pd.DataFrame:
    rows = []
    for hold_days in [5, 7, 10, 14]:
        d_pending, d_rows = build_d_candidates(prepared, dates, params=params, hold_days=hold_days)
        if not d_rows:
            continue
        d_df = pd.DataFrame(d_rows)
        result = simulate_sleeves(
            prepared, dates, v11_pending,
            primary_slots=V11_PRIMARY_SLOTS,
            secondary_pending=d_pending,
            secondary_slots=LEADERSHIP_SLOTS,
        )
        m = result["metrics"]
        d_m = calc_metrics(d_df)
        rows.append({
            "hold_days": hold_days,
            "d_signals": len(d_df),
            "d_wr": round(float(d_m["wr"]), 1),
            "d_avg": round(float(d_m["avg"]), 2),
            "d_sharpe": round(float(d_m["sharpe"]), 2),
            "hyb_sharpe": round(float(m["sharpe"]), 2),
            "hyb_total": round(float(m["total"]), 1),
            "hyb_mdd": round(float(m["mdd"]), 1),
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# [D] ANALISIS REGIME SPLIT PROFUNDO
# ─────────────────────────────────────────────────────────────────────────────

def run_regime_split(d_rows: list[dict[str, Any]]) -> None:
    if not d_rows:
        print("  [WARN] Sin trades para analizar")
        return

    d_df = pd.DataFrame(d_rows)
    print(f"  Total trades D: {len(d_df)}")

    for regime in ["SEGURO", "PELIGRO"]:
        sub = d_df[d_df["regime"] == regime]
        if sub.empty:
            print(f"  {regime:8s}: sin trades")
            continue
        m = calc_metrics(sub)
        print(
            f"  {regime:8s}: trades={int(m['trades']):4d}  "
            f"wr={m['wr']:5.1f}%  avg={m['avg']:+6.2f}%  sh={m['sharpe']:5.2f}  "
            f"mdd={m['mdd']:6.1f}%"
        )

    print()
    print("  Distribucion por anio:")
    d_df["year"] = pd.to_datetime(d_df["date"]).dt.year
    for year, sub in d_df.groupby("year"):
        m = calc_metrics(sub)
        print(
            f"    {year}: trades={int(m['trades']):4d}  "
            f"wr={m['wr']:5.1f}%  avg={m['avg']:+6.2f}%"
        )


# ─────────────────────────────────────────────────────────────────────────────
# [E] CONCENTRACION SECTORIAL Y POR TICKER
# ─────────────────────────────────────────────────────────────────────────────

def run_concentration_analysis(d_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not d_rows:
        return {"hhi_ticker": 0.0, "hhi_sector": 0.0, "top1_ticker_pct": 0.0, "max_ticker": "N/A"}

    d_df = pd.DataFrame(d_rows)
    n = len(d_df)

    # HHI por ticker
    ticker_counts = d_df["ticker"].value_counts()
    ticker_shares = ticker_counts / n
    hhi_ticker = float((ticker_shares ** 2).sum())

    # HHI por sector
    sector_counts = d_df["sector"].value_counts()
    sector_shares = sector_counts / n
    hhi_sector = float((sector_shares ** 2).sum())

    # Top ticker
    top1_ticker = ticker_counts.index[0]
    top1_pct = float(ticker_shares.iloc[0] * 100)

    print(f"  HHI Ticker    : {hhi_ticker:.4f}  (1.0=monopolio, 0.0=uniforme)")
    print(f"  HHI Sector    : {hhi_sector:.4f}")
    print(f"  Top ticker    : {top1_ticker} con {top1_pct:.1f}% de los trades")
    print()
    print("  Top 5 tickers:")
    for tk, cnt in ticker_counts.head(5).items():
        print(f"    {tk:8s}: {cnt:4d} trades ({cnt/n*100:.1f}%)")
    print()
    print("  Distribucion por sector:")
    for sec, cnt in sector_counts.items():
        print(f"    {sec:10s}: {cnt:4d} trades ({cnt/n*100:.1f}%)")

    return {
        "hhi_ticker": hhi_ticker,
        "hhi_sector": hhi_sector,
        "top1_ticker_pct": top1_pct,
        "max_ticker": str(top1_ticker),
    }


# ─────────────────────────────────────────────────────────────────────────────
# [F] MONTE CARLO
# ─────────────────────────────────────────────────────────────────────────────

def run_monte_carlo(
    base_result: dict[str, Any],
    hybrid_result: dict[str, Any],
    n_iterations: int = MC_ITERATIONS,
) -> dict[str, float]:
    base_trades: pd.DataFrame = base_result["trades"]
    hybrid_trades: pd.DataFrame = hybrid_result["trades"]

    if base_trades.empty or hybrid_trades.empty:
        print("  [WARN] Sin trades suficientes para Monte Carlo")
        return {"p_hybrid_wins_sharpe": 0.0, "p_hybrid_wins_total": 0.0}

    base_returns = base_trades["return_pct"].values / 100.0
    hybrid_returns = hybrid_trades["return_pct"].values / 100.0

    base_sharpes = []
    hybrid_sharpes = []
    base_totals = []
    hybrid_totals = []

    n_base = len(base_returns)
    n_hybrid = len(hybrid_returns)

    for _ in range(n_iterations):
        bs = np.random.choice(base_returns, size=n_base, replace=True)
        hs = np.random.choice(hybrid_returns, size=n_hybrid, replace=True)

        bs_total = float(np.prod(1.0 + bs) - 1.0) * 100.0
        hs_total = float(np.prod(1.0 + hs) - 1.0) * 100.0

        bs_sharpe = float(np.mean(bs) / (np.std(bs) + 1e-9) * np.sqrt(252))
        hs_sharpe = float(np.mean(hs) / (np.std(hs) + 1e-9) * np.sqrt(252))

        base_sharpes.append(bs_sharpe)
        hybrid_sharpes.append(hs_sharpe)
        base_totals.append(bs_total)
        hybrid_totals.append(hs_total)

    base_sharpes_arr = np.array(base_sharpes)
    hybrid_sharpes_arr = np.array(hybrid_sharpes)
    hybrid_totals_arr = np.array(hybrid_totals)

    p_wins_sharpe = float((hybrid_sharpes_arr > base_sharpes_arr).mean() * 100.0)
    p_wins_total = float((np.array(hybrid_totals) > np.array(base_totals)).mean() * 100.0)

    p1_sharpe = float(np.percentile(hybrid_sharpes_arr, 1))
    p5_sharpe = float(np.percentile(hybrid_sharpes_arr, 5))
    p50_sharpe = float(np.percentile(hybrid_sharpes_arr, 50))
    p1_total = float(np.percentile(hybrid_totals_arr, 1))
    p5_total = float(np.percentile(hybrid_totals_arr, 5))

    print(f"  Iteraciones: {n_iterations}")
    print(f"  P(hybrid_sharpe > base_sharpe) : {p_wins_sharpe:.1f}%")
    print(f"  P(hybrid_total  > base_total)  : {p_wins_total:.1f}%")
    print(f"  Hybrid Sharpe  p1={p1_sharpe:+.2f}  p5={p5_sharpe:+.2f}  p50={p50_sharpe:+.2f}")
    print(f"  Hybrid Total % p1={p1_total:+.1f}%  p5={p5_total:+.1f}%")

    return {
        "p_hybrid_wins_sharpe": p_wins_sharpe,
        "p_hybrid_wins_total": p_wins_total,
        "p1_sharpe": p1_sharpe,
        "p5_sharpe": p5_sharpe,
        "p50_sharpe": p50_sharpe,
        "p1_total": p1_total,
        "p5_total": p5_total,
    }


# ─────────────────────────────────────────────────────────────────────────────
# [G] PROMOTION GATE
# ─────────────────────────────────────────────────────────────────────────────

def evaluate_promotion_gate(
    wf_df: pd.DataFrame,
    base_metrics: dict,
    hybrid_metrics: dict,
    mc_stats: dict[str, float],
    conc_stats: dict[str, float],
    hold_df: pd.DataFrame,
    d_rows: list[dict],
) -> None:
    print(LINE)
    print("  [G] PROMOTION GATE — Signal D hacia V12")
    print(LINE)

    gates: list[tuple[str, bool, str]] = []

    # PG1: WF >= 7/10 ventanas donde hybrid_sharpe > base_sharpe
    wf_wins = int(wf_df["hyb_wins"].sum())
    pg1 = wf_wins >= 7
    gates.append(("PG1 WF>=7/10 ventanas", pg1, f"hybrid gana {wf_wins}/10 ventanas"))

    # PG2: Sharpe portfolio hibrido full-period >= 1.10
    hyb_sharpe = float(hybrid_metrics["sharpe"])
    pg2 = hyb_sharpe >= 1.10
    gates.append(("PG2 Sharpe hyb >= 1.10", pg2, f"Sharpe={hyb_sharpe:.2f}"))

    # PG3: MDD portfolio hibrido full-period <= -45%
    hyb_mdd = float(hybrid_metrics["mdd"])
    pg3 = hyb_mdd >= -45.0
    gates.append(("PG3 MDD <= -45%", pg3, f"MDD={hyb_mdd:.1f}%"))

    # PG4: MC P(hybrid_sharpe > base_sharpe) >= 70%
    p_mc = mc_stats.get("p_hybrid_wins_sharpe", 0.0)
    pg4 = p_mc >= 70.0
    gates.append(("PG4 MC P(wins)>=70%", pg4, f"P={p_mc:.1f}%"))

    # PG5: Concentracion: ningun ticker > 15% del total de trades
    top1_pct = conc_stats.get("top1_ticker_pct", 100.0)
    max_tk = conc_stats.get("max_ticker", "N/A")
    pg5 = top1_pct <= 15.0
    gates.append(("PG5 Top ticker <= 15%", pg5, f"{max_tk}={top1_pct:.1f}%"))

    # PG6: Hold period 10d tiene mejor hyb_sharpe que 5d y 14d
    if not hold_df.empty and len(hold_df) >= 3:
        sharpe_10d = hold_df[hold_df["hold_days"] == 10]["hyb_sharpe"].values
        sharpe_5d = hold_df[hold_df["hold_days"] == 5]["hyb_sharpe"].values
        sharpe_14d = hold_df[hold_df["hold_days"] == 14]["hyb_sharpe"].values
        if len(sharpe_10d) > 0 and len(sharpe_5d) > 0 and len(sharpe_14d) > 0:
            pg6 = float(sharpe_10d[0]) >= float(sharpe_5d[0]) and float(sharpe_10d[0]) >= float(sharpe_14d[0])
            gates.append(("PG6 Hold 10d optimo", pg6, f"sh10d={sharpe_10d[0]:.2f} sh5d={sharpe_5d[0]:.2f} sh14d={sharpe_14d[0]:.2f}"))
        else:
            gates.append(("PG6 Hold 10d optimo", False, "datos insuficientes en hold_df"))
    else:
        gates.append(("PG6 Hold 10d optimo", False, "hold_df insuficiente"))

    # PG7: D tiene avg_return >= 0 en SEGURO y en PELIGRO (con >= 30 trades cada uno)
    if d_rows:
        d_df_g = pd.DataFrame(d_rows)
        pg7 = True
        detail7 = []
        for regime in ["SEGURO", "PELIGRO"]:
            sub = d_df_g[d_df_g["regime"] == regime]
            if len(sub) < 30:
                pg7 = False
                detail7.append(f"{regime}: solo {len(sub)} trades")
                continue
            avg_r = float(sub["return_pct"].mean())
            if avg_r < 0:
                pg7 = False
            detail7.append(f"{regime}: avg={avg_r:+.2f}% n={len(sub)}")
        gates.append(("PG7 D avg>=0 ambos regimes", pg7, " | ".join(detail7)))
    else:
        gates.append(("PG7 D avg>=0 ambos regimes", False, "sin trades D"))

    # Resultado
    print()
    passed = 0
    for name, result, detail in gates:
        mark = "PASS" if result else "FAIL"
        print(f"  [{mark}]  {name:35s}  {detail}")
        if result:
            passed += 1

    print()
    print(f"  Gates cumplidos: {passed}/{len(gates)}")
    print()

    if passed >= 6:
        veredicto = "PROMOVER — evidencia suficiente para crear V12 con Signal D"
        print(f"  VEREDICTO: {veredicto}")
    elif passed == 5:
        veredicto = "CONDICIONAL — repetir en el siguiente ciclo de mercado antes de promover"
        print(f"  VEREDICTO: {veredicto}")
    else:
        veredicto = f"RECHAZAR — solo {passed}/7 gates pasados; no hay evidencia suficiente"
        print(f"  VEREDICTO: {veredicto}")

    return passed, veredicto


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS DE PRESENTACION
# ─────────────────────────────────────────────────────────────────────────────

def print_port_row(name: str, result: dict) -> None:
    m = result["metrics"]
    n_d = len([r for r in result["trades"].to_dict("records") if r.get("signal", "") == "D_LEAD"]) if not result["trades"].empty else 0
    print(
        f"  {name:18s}  trades={int(m['trades']):4d} (D={n_d:3d})  "
        f"wr={m['wr']:5.1f}%  avg={m['avg_trade']:+6.2f}%  "
        f"sh={m['sharpe']:5.2f}  total={m['total']:8.1f}%  mdd={m['mdd']:6.1f}%"
    )


def print_ind_row(name: str, rows: list[dict]) -> None:
    if not rows:
        print(f"  {name:18s}  sin trades")
        return
    df = pd.DataFrame(rows)
    m = calc_metrics(df)
    print(
        f"  {name:18s}  trades={int(m['trades']):4d}  "
        f"wr={m['wr']:5.1f}%  avg={m['avg']:+6.2f}%  "
        f"sh={m['sharpe']:5.2f}  mdd={m['mdd']:6.1f}%"
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print(LINE)
    print("  INVESTIGACION V17 - AUDITORIA DURA DE SIGNAL D")
    print(LINE)
    print("  Objetivo: someter D_LEADERSHIP_STRICT a 7 gates de promotion")
    print("  antes de decidir si merece ser un eje ortogonal real en V12.")
    print()

    # ── Preparacion ──────────────────────────────────────────────────────────
    print("[0] Cargando y preparando datos")
    prepared, dates = prepare_universe()
    print(f"  Universo broad : {len(BROAD_UNIVERSE)} tickers")
    print(f"  Rango DB       : {dates[0].date()} -> {dates[-1].date()}")
    print()

    # ── V11 base ─────────────────────────────────────────────────────────────
    print("[1] Construyendo candidatos V11 (base)")
    v11_pending, v11_rows = build_v11_candidates(prepared, dates)
    print_ind_row("V11_BASE", v11_rows)
    base_result = simulate_sleeves(
        prepared, dates, v11_pending,
        primary_slots=MAX_POSITIONS,
    )
    print_port_row("V11_3SLOTS_PORT", base_result)
    print()

    # ── D_STRICT referencia (V16) ─────────────────────────────────────────────
    print("[2] Candidatos D_LEADERSHIP_STRICT (referencia V16)")
    d_strict_pending, d_strict_rows = build_d_candidates(
        prepared, dates, params=D_STRICT_REF
    )
    print_ind_row("D_STRICT_IND", d_strict_rows)
    hybrid_strict = simulate_sleeves(
        prepared, dates, v11_pending,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=d_strict_pending,
        secondary_slots=LEADERSHIP_SLOTS,
    )
    print_port_row("V11+D_STRICT", hybrid_strict)
    print()

    # ── [A] Grid de sensibilidad ──────────────────────────────────────────────
    print("[A] Grid de sensibilidad completo (64 combinaciones)")
    grid_df = run_sensitivity_grid(prepared, dates, v11_pending)
    print(f"  Top 10 combinaciones (orden por hyb_sharpe):")
    print(grid_df.head(10).to_string(index=False))
    print()

    # Identificar la mejor combinacion del grid
    best_row = grid_df.iloc[0]
    best_params = {
        "roc20_min": float(best_row["roc20_min"]),
        "rel20_min": float(best_row["rel20_min"]),
        "rsi_min": float(best_row["rsi_min"]),
        "rsi_max": 75.0,
        "vol_min": 0.8,
        "vol_max": float(best_row["vol_max"]),
    }
    print(f"  Mejor combinacion del grid: {best_params}")
    print(f"  Nota: se usa D_STRICT_REF para los gates de promotion (consistencia con V16)")
    print()

    # ── [B] Walk-forward 10 ventanas ─────────────────────────────────────────
    print("[B] Walk-forward 10 ventanas (D_STRICT_REF)")
    wf_df = run_walk_forward_10(prepared, dates, v11_pending, d_strict_pending)
    print(wf_df.to_string(index=False))
    wf_wins = int(wf_df["hyb_wins"].sum())
    print(f"  Ventanas donde hybrid gana por Sharpe: {wf_wins}/10")
    print()

    # ── [C] Sensibilidad al hold period ──────────────────────────────────────
    print("[C] Sensibilidad al hold period")
    hold_df = run_hold_sensitivity(prepared, dates, v11_pending, D_STRICT_REF)
    print(hold_df.to_string(index=False))
    print()

    # ── [D] Regime split profundo ─────────────────────────────────────────────
    print("[D] Analisis de regime split (D_STRICT_REF)")
    run_regime_split(d_strict_rows)
    print()

    # ── [E] Concentracion ─────────────────────────────────────────────────────
    print("[E] Concentracion sectorial y por ticker (D_STRICT_REF)")
    conc_stats = run_concentration_analysis(d_strict_rows)
    print()

    # ── [F] Monte Carlo ───────────────────────────────────────────────────────
    print("[F] Monte Carlo 1000 iteraciones (D_STRICT_REF vs V11 base)")
    mc_stats = run_monte_carlo(base_result, hybrid_strict, n_iterations=MC_ITERATIONS)
    print()

    # ── [G] Promotion gate ────────────────────────────────────────────────────
    passed, veredicto = evaluate_promotion_gate(
        wf_df=wf_df,
        base_metrics=base_result["metrics"],
        hybrid_metrics=hybrid_strict["metrics"],
        mc_stats=mc_stats,
        conc_stats=conc_stats,
        hold_df=hold_df,
        d_rows=d_strict_rows,
    )

    # ── Resumen ejecutivo ─────────────────────────────────────────────────────
    print()
    print(LINE)
    print("  RESUMEN EJECUTIVO")
    print(LINE)
    bm = base_result["metrics"]
    hm = hybrid_strict["metrics"]
    print(f"  V11 base  : Sharpe={bm['sharpe']:.2f}  total={bm['total']:.1f}%  mdd={bm['mdd']:.1f}%")
    print(f"  V11+D_STR : Sharpe={hm['sharpe']:.2f}  total={hm['total']:.1f}%  mdd={hm['mdd']:.1f}%")
    print(f"  WF        : {wf_wins}/10 ventanas ganadas")
    print(f"  MC        : P(hybrid>base) = {mc_stats.get('p_hybrid_wins_sharpe', 0):.1f}%")
    print(f"  Gates     : {passed}/7  ->  {veredicto}")
    print(LINE)


if __name__ == "__main__":
    main()
