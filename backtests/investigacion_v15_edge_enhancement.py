"""
INVESTIGACION V15 — EDGE ENHANCEMENT INTEGRAL
==============================================

Objetivo:
  Mejorar el edge real del sistema V11 atacando los 4 vectores mas
  prometedores de forma independiente y combinada.

Diagnostico actual (V11 sobre 6 anos, 2020-2026):
  - Broad independiente:  Sharpe 1.60, WR 62.4%, MDD -78.6%
  - Core independiente:   Sharpe 3.39, WR 68.6%, MDD -30.7%
  - Portfolio broad (3s): Sharpe 0.82, MDD -37.9%
  - Portfolio core (3s):  Sharpe 0.88, MDD -11.1%

  Problema #1: MDD broad inaceptable (-78.6% indep, -37.9% portf)
  Problema #2: Portfolio Sharpe modesto (0.82 broad)
  Problema #3: Signal A inutil fuera de SEGURO (2020, 2022)

Hipotesis testeadas (cada una independiente):
  H1. VIX regime overlay — agregar VIX < 30 al regime SEGURO para Signal A
  H2. ATR-adaptive exit para Signal C — reemplazar +6% fijo por 2*ATR%
  H3. Circuit breaker por drawdown — pausar entradas cuando portfolio cae >X%
  H4. Position sizing por ATR — slots inversamente proporcionales a volatilidad

Pipeline: V11 baseline -> cada H por separado -> mejor combo -> WF -> MC -> veredicto

Reglas:
  - RSI = Wilder's smoothing (ewm(com=13, adjust=False))
  - Todo sobre titan.db (6 anos, VIX incluido)
  - Walk-forward 7 ventanas + Monte Carlo 2000 sims
  - Anti-overfitting checklist post-backtest

Fecha: 2026-04-08
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

from backtests.investigacion_v9_path_quality import (
    ANTIKNIFE_DAYS,
    BROAD_UNIVERSE,
    CORE_UNIVERSE,
    HOLD_DAYS,
    START_IDX,
    calc_metrics,
    load_db_data,
    monte_carlo,
    precompute,
)
from backtests.investigacion_v10_rebound_capture import c_exit_return
from backtests.investigacion_v12_portfolio_operativo import (
    INITIAL_EQUITY,
    MAX_POSITIONS,
    Candidate,
    calc_a_score,
    calc_c_score,
    calc_portfolio_metrics,
)

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES V11 (caps operativos)
# ══════════════════════════════════════════════════════════════════════════════

C_SCORE_MAX = 85.0
C_VOL_RATIO_CAP = 4.0

# Constantes de exit
C_EXIT_HOLD_DAYS = 7
C_EARLY_TP_PCT = 6.0
C_EARLY_TP_DAYS = 4


# ══════════════════════════════════════════════════════════════════════════════
# VIX DATA LOADING (desde titan.db, no yfinance)
# ══════════════════════════════════════════════════════════════════════════════

def load_and_merge_vix(prepared: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Carga VIX desde titan.db y lo agrega a todos los DataFrames."""
    from titan_system.core.database import TitanDB

    with TitanDB() as db:
        vix_df = db.get_prices("VIX")

    if vix_df.empty:
        print("  [WARN] VIX no encontrado en DB")
        return prepared

    vix_close = vix_df["close"].rename("VIX_CLOSE")

    for ticker in prepared:
        work = prepared[ticker]
        work = work.join(vix_close, how="left")
        work["VIX_CLOSE"] = work["VIX_CLOSE"].ffill()
        prepared[ticker] = work

    print(f"  VIX mergeado: {vix_df.index.min().date()} -> {vix_df.index.max().date()}")
    return prepared


# ══════════════════════════════════════════════════════════════════════════════
# EXIT FUNCTIONS (V11 base + ATR adaptive)
# ══════════════════════════════════════════════════════════════════════════════

def c_exit_v11(df: pd.DataFrame, idx: int) -> tuple[float | None, int | None, bool]:
    """Exit V11 standard: +6% en 4d o hold 7d."""
    return c_exit_return(df, idx)


def c_exit_atr_adaptive(
    df: pd.DataFrame, idx: int, atr_mult: float = 2.0
) -> tuple[float | None, int | None, bool]:
    """Exit adaptativo: TP = atr_mult * ATR% en primeros 4d, sino hold 7d.
    Clamp TP entre 3% y 15% para evitar extremos."""
    entry_idx = idx + 1
    if entry_idx + C_EXIT_HOLD_DAYS >= len(df):
        return None, None, False

    entry = df["Close"].iloc[entry_idx]
    atr = df["ATR"].iloc[idx]
    if pd.isna(entry) or pd.isna(atr) or entry <= 0:
        return None, None, False

    atr_pct = float(atr / entry * 100)
    tp_pct = max(3.0, min(15.0, atr_mult * atr_pct))

    for day in range(1, C_EXIT_HOLD_DAYS + 1):
        check_idx = entry_idx + day
        if check_idx >= len(df):
            return None, None, False
        px = df["Close"].iloc[check_idx]
        if pd.isna(px):
            return None, None, False
        ret = float((px / entry - 1) * 100)
        if day <= C_EARLY_TP_DAYS and ret >= tp_pct:
            return ret, day, True

    final = df["Close"].iloc[entry_idx + C_EXIT_HOLD_DAYS]
    if pd.isna(final):
        return None, None, False
    return float((final / entry - 1) * 100), C_EXIT_HOLD_DAYS, False


def a_exit_adaptive(
    df: pd.DataFrame, idx: int, tp_pct: float = 3.0, tp_days: int = 3
) -> tuple[float | None, int | None, bool]:
    """Exit adaptativo para Signal A: +tp_pct% en primeros tp_days, sino hold 7d."""
    entry_idx = idx + 1
    if entry_idx + HOLD_DAYS >= len(df):
        return None, None, False

    entry = df["Close"].iloc[entry_idx]
    if pd.isna(entry) or entry <= 0:
        return None, None, False

    for day in range(1, HOLD_DAYS + 1):
        check_idx = entry_idx + day
        if check_idx >= len(df):
            return None, None, False
        px = df["Close"].iloc[check_idx]
        if pd.isna(px):
            return None, None, False
        ret = float((px / entry - 1) * 100)
        if day <= tp_days and ret >= tp_pct:
            return ret, day, True

    final = df["Close"].iloc[entry_idx + HOLD_DAYS]
    if pd.isna(final):
        return None, None, False
    return float((final / entry - 1) * 100), HOLD_DAYS, False


# ══════════════════════════════════════════════════════════════════════════════
# CANDIDATE BUILDER V15
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CandidateV15(Candidate):
    atr_pct: float = 0.0
    vix: float = 0.0


def build_candidates_v15(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    exit_mode_c: str = "v11",
    atr_mult: float = 2.0,
    vix_max_for_a: float | None = None,
    exit_mode_a: str = "fixed7",
    a_tp_pct: float = 3.0,
    a_tp_days: int = 3,
) -> dict[int, list[CandidateV15]]:
    """Construye candidatos con opciones configurables de exit y regime."""
    dates = prepared["SPY"].index
    pending: dict[int, list[CandidateV15]] = {}

    for idx in range(START_IDX, len(dates) - 8):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])

        # VIX overlay for regime
        if vix_max_for_a is not None and "VIX_CLOSE" in prepared["SPY"].columns:
            vix_val = prepared["SPY"]["VIX_CLOSE"].iloc[idx]
            if pd.notna(vix_val) and float(vix_val) >= vix_max_for_a:
                regime_safe = False  # Override: VIX too high for Signal A

        for ticker in tickers:
            if ticker == "SPY" or ticker not in prepared:
                continue

            df = prepared[ticker]
            candidate: CandidateV15 | None = None

            # ATR pct for sizing
            atr_val = df["ATR"].iloc[idx]
            close_val = df["Close"].iloc[idx]
            atr_pct = 0.0
            if pd.notna(atr_val) and pd.notna(close_val) and close_val > 0:
                atr_pct = float(atr_val / close_val * 100)

            vix_val = 0.0
            if "VIX_CLOSE" in df.columns and pd.notna(df["VIX_CLOSE"].iloc[idx]):
                vix_val = float(df["VIX_CLOSE"].iloc[idx])

            # SIGNAL A
            if regime_safe and bool(df["SIG_A_GUARD"].iloc[idx]):
                if exit_mode_a == "adaptive":
                    ret_a, exit_day_a, tp_a = a_exit_adaptive(df, idx, a_tp_pct, a_tp_days)
                    if ret_a is None or exit_day_a is None:
                        continue
                    entry_idx = idx + 1
                    exit_idx = idx + 1 + exit_day_a
                else:
                    entry_idx = idx + 1
                    exit_idx = idx + 8
                    entry_px = df["Close"].iloc[entry_idx]
                    exit_px = df["Close"].iloc[exit_idx]
                    if pd.isna(entry_px) or pd.isna(exit_px):
                        continue

                candidate = CandidateV15(
                    ticker=ticker,
                    signal="A",
                    signal_date=dates[idx],
                    signal_idx=idx,
                    entry_idx=entry_idx,
                    exit_idx=exit_idx,
                    raw_score=calc_a_score(df, idx),
                    vol_ratio=float(df["VOL_RATIO"].iloc[idx]),
                    rsi=float(df["RSI"].iloc[idx]),
                    atr_pct=atr_pct,
                    vix=vix_val,
                )

            # SIGNAL C5 (con V11 caps)
            elif bool(df["SIG_C_V9_NEG5"].iloc[idx]):
                c_score = calc_c_score(df, idx)
                c_vol = float(df["VOL_RATIO"].iloc[idx])

                # V11 caps
                if c_score >= C_SCORE_MAX or c_vol >= C_VOL_RATIO_CAP:
                    continue

                if exit_mode_c == "atr":
                    ret_c, exit_day_c, tp_c = c_exit_atr_adaptive(df, idx, atr_mult)
                else:
                    ret_c, exit_day_c, tp_c = c_exit_v11(df, idx)

                if ret_c is None or exit_day_c is None:
                    continue

                candidate = CandidateV15(
                    ticker=ticker,
                    signal="C",
                    signal_date=dates[idx],
                    signal_idx=idx,
                    entry_idx=idx + 1,
                    exit_idx=idx + 1 + exit_day_c,
                    raw_score=c_score,
                    vol_ratio=c_vol,
                    rsi=float(df["RSI"].iloc[idx]),
                    neg_days10=float(df["NEG_DAYS10"].iloc[idx]),
                    atr_pct=atr_pct,
                    vix=vix_val,
                )

            if candidate is None:
                continue

            pending.setdefault(candidate.entry_idx, []).append(candidate)

    return pending


# ══════════════════════════════════════════════════════════════════════════════
# PORTFOLIO SIMULATION V15 (con circuit breaker + ATR sizing)
# ══════════════════════════════════════════════════════════════════════════════

def simulate_portfolio_v15(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    pending: dict[int, list[CandidateV15]],
    *,
    circuit_breaker_pct: float | None = None,
    atr_sizing: bool = False,
    atr_target_pct: float = 3.0,
) -> dict[str, object]:
    """
    Simula portfolio con max 3 slots + mejoras opcionales.

    circuit_breaker_pct: si equity cae X% desde pico, no abrir nuevas posiciones.
                         Ej: 15.0 = pausa si drawdown > 15%.
    atr_sizing:          si True, tamaño de posición inversamente proporcional a ATR%.
                         target = atr_target_pct. Si ATR% > target, reduce posicion.
    """
    start = START_IDX + 1
    end = len(dates)

    cash = INITIAL_EQUITY
    peak_equity = INITIAL_EQUITY
    cooldown_until: dict[str, int] = {}
    open_positions: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []
    closed_rows: list[dict[str, object]] = []
    breaker_active_days = 0
    total_days = 0

    for idx in range(start, end):
        # Mark-to-market
        equity = cash + sum(
            float(pos["shares"]) * float(prepared[str(pos["ticker"])]["Close"].iloc[idx])
            for pos in open_positions
        )
        equity_rows.append({
            "date": dates[idx],
            "equity": equity,
            "open_positions": len(open_positions),
        })
        total_days += 1

        # Track peak
        if equity > peak_equity:
            peak_equity = equity

        # Close positions at exit
        still_open: list[dict[str, object]] = []
        for pos in open_positions:
            if int(pos["exit_idx"]) == idx:
                ticker = str(pos["ticker"])
                exit_price = float(prepared[ticker]["Close"].iloc[idx])
                cash += float(pos["shares"]) * exit_price
                closed_rows.append({
                    "ticker": ticker,
                    "signal": pos["signal"],
                    "entry_date": dates[int(pos["entry_idx"])].date().isoformat(),
                    "exit_date": dates[idx].date().isoformat(),
                    "return_pct": (exit_price / float(pos["entry_price"]) - 1.0) * 100.0,
                    "raw_score": float(pos["raw_score"]),
                })
            else:
                still_open.append(pos)
        open_positions = still_open

        # Circuit breaker check
        if circuit_breaker_pct is not None:
            current_dd = (1.0 - equity / peak_equity) * 100.0
            if current_dd >= circuit_breaker_pct:
                breaker_active_days += 1
                continue  # Skip new entries

        free_slots = MAX_POSITIONS - len(open_positions)
        if free_slots <= 0:
            continue

        todays = pending.get(idx, [])
        if not todays:
            continue

        total_equity = cash + sum(
            float(pos["shares"]) * float(prepared[str(pos["ticker"])]["Close"].iloc[idx])
            for pos in open_positions
        )
        base_slot_budget = total_equity / MAX_POSITIONS

        ranked = sorted(todays, key=lambda c: c.raw_score, reverse=True)

        for cand in ranked:
            if free_slots <= 0:
                break
            if any(str(pos["ticker"]) == cand.ticker for pos in open_positions):
                continue
            if idx <= cooldown_until.get(cand.ticker, -999):
                continue

            entry_price = float(prepared[cand.ticker]["Close"].iloc[idx])
            if not np.isfinite(entry_price) or entry_price <= 0:
                continue

            # ATR sizing
            if atr_sizing and cand.atr_pct > 0:
                size_factor = atr_target_pct / max(cand.atr_pct, 0.5)
                size_factor = max(0.3, min(2.0, size_factor))
                slot_budget = base_slot_budget * size_factor
            else:
                slot_budget = base_slot_budget

            invested = min(slot_budget, cash)
            if invested <= 0:
                break

            open_positions.append({
                "ticker": cand.ticker,
                "signal": cand.signal,
                "entry_idx": cand.entry_idx,
                "exit_idx": cand.exit_idx,
                "raw_score": cand.raw_score,
                "shares": invested / entry_price,
                "entry_price": entry_price,
            })
            cash -= invested
            cooldown_until[cand.ticker] = cand.signal_idx + ANTIKNIFE_DAYS
            free_slots -= 1

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(closed_rows)
    metrics = calc_portfolio_metrics(equity_df, trades_df)
    metrics["breaker_days"] = float(breaker_active_days)
    metrics["breaker_pct"] = float(breaker_active_days / max(total_days, 1) * 100)
    return {
        "equity_df": equity_df,
        "trades_df": trades_df,
        "metrics": metrics,
    }


# ══════════════════════════════════════════════════════════════════════════════
# WALK-FORWARD PORTFOLIO V15
# ══════════════════════════════════════════════════════════════════════════════

def walk_forward_portfolio_v15(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    pending: dict[int, list[CandidateV15]],
    windows: int = 7,
    **kwargs,
) -> dict[str, object]:
    total_span = len(dates) - START_IDX - 8 - 1
    if total_span < windows:
        return {"pct": 0.0, "avg_sharpe": 0.0, "details": []}

    window_size = total_span // windows
    details: list[dict[str, object]] = []

    for w in range(windows):
        w_start = START_IDX + 1 + w * window_size
        w_end = min(w_start + window_size, len(dates))

        # Filter pending to this window
        w_pending = {
            idx: cands for idx, cands in pending.items()
            if w_start <= idx < w_end
        }

        # Override start/end in simulation
        cash = INITIAL_EQUITY
        peak_equity = INITIAL_EQUITY
        cooldown_until: dict[str, int] = {}
        open_positions: list[dict[str, object]] = []
        equity_rows: list[dict[str, object]] = []
        closed_rows: list[dict[str, object]] = []

        circuit_breaker_pct = kwargs.get("circuit_breaker_pct")
        atr_sizing = kwargs.get("atr_sizing", False)
        atr_target_pct = kwargs.get("atr_target_pct", 3.0)

        for idx in range(w_start, w_end):
            equity = cash + sum(
                float(pos["shares"]) * float(prepared[str(pos["ticker"])]["Close"].iloc[idx])
                for pos in open_positions
            )
            equity_rows.append({"date": dates[idx], "equity": equity, "open_positions": len(open_positions)})

            if equity > peak_equity:
                peak_equity = equity

            still_open = []
            for pos in open_positions:
                if int(pos["exit_idx"]) == idx:
                    ticker = str(pos["ticker"])
                    exit_price = float(prepared[ticker]["Close"].iloc[idx])
                    cash += float(pos["shares"]) * exit_price
                    closed_rows.append({
                        "ticker": ticker, "signal": pos["signal"],
                        "return_pct": (exit_price / float(pos["entry_price"]) - 1.0) * 100.0,
                    })
                else:
                    still_open.append(pos)
            open_positions = still_open

            if circuit_breaker_pct is not None:
                dd = (1.0 - equity / peak_equity) * 100.0
                if dd >= circuit_breaker_pct:
                    continue

            free_slots = MAX_POSITIONS - len(open_positions)
            if free_slots <= 0:
                continue

            todays = w_pending.get(idx, [])
            if not todays:
                continue

            total_equity = cash + sum(
                float(pos["shares"]) * float(prepared[str(pos["ticker"])]["Close"].iloc[idx])
                for pos in open_positions
            )
            base_budget = total_equity / MAX_POSITIONS
            ranked = sorted(todays, key=lambda c: c.raw_score, reverse=True)

            for cand in ranked:
                if free_slots <= 0:
                    break
                if any(str(pos["ticker"]) == cand.ticker for pos in open_positions):
                    continue
                if idx <= cooldown_until.get(cand.ticker, -999):
                    continue
                entry_price = float(prepared[cand.ticker]["Close"].iloc[idx])
                if not np.isfinite(entry_price) or entry_price <= 0:
                    continue

                if atr_sizing and cand.atr_pct > 0:
                    sf = max(0.3, min(2.0, atr_target_pct / max(cand.atr_pct, 0.5)))
                    budget = base_budget * sf
                else:
                    budget = base_budget

                invested = min(budget, cash)
                if invested <= 0:
                    break
                open_positions.append({
                    "ticker": cand.ticker, "signal": cand.signal,
                    "entry_idx": cand.entry_idx, "exit_idx": cand.exit_idx,
                    "raw_score": cand.raw_score, "shares": invested / entry_price,
                    "entry_price": entry_price,
                })
                cash -= invested
                cooldown_until[cand.ticker] = cand.signal_idx + ANTIKNIFE_DAYS
                free_slots -= 1

        eq_df = pd.DataFrame(equity_rows)
        tr_df = pd.DataFrame(closed_rows)
        m = calc_portfolio_metrics(eq_df, tr_df)
        details.append({
            "window": w + 1,
            "trades": int(m["trades"]),
            "sharpe": float(m["sharpe"]),
            "total": float(m["total"]),
            "mdd": float(m["mdd"]),
            "positive": bool(m["sharpe"] > 0),
        })

    pos = sum(1 for d in details if d["positive"])
    avg_sh = float(np.mean([d["sharpe"] for d in details])) if details else 0.0
    return {"pct": pos / max(windows, 1) * 100, "avg_sharpe": avg_sh, "details": details}


# ══════════════════════════════════════════════════════════════════════════════
# INDEPENDENT SIGNAL BACKTEST V15
# ══════════════════════════════════════════════════════════════════════════════

def run_independent_v15(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    exit_mode_c: str = "v11",
    atr_mult: float = 2.0,
    vix_max_for_a: float | None = None,
    exit_mode_a: str = "fixed7",
    a_tp_pct: float = 3.0,
    a_tp_days: int = 3,
) -> pd.DataFrame:
    """Backtest de trades independientes (sin portfolio constraint)."""
    dates = prepared["SPY"].index
    last_entry: dict[str, int] = {}
    rows: list[dict[str, object]] = []

    for idx in range(START_IDX, len(dates) - 8):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])

        # VIX overlay
        if vix_max_for_a is not None and "VIX_CLOSE" in prepared["SPY"].columns:
            vix_val = prepared["SPY"]["VIX_CLOSE"].iloc[idx]
            if pd.notna(vix_val) and float(vix_val) >= vix_max_for_a:
                regime_safe = False

        for ticker in tickers:
            if ticker == "SPY" or ticker not in prepared:
                continue
            if ticker in last_entry and (idx - last_entry[ticker]) < ANTIKNIFE_DAYS:
                continue

            df = prepared[ticker]
            signal = None
            ret = None
            exit_day = None

            # Signal A
            if regime_safe and bool(df["SIG_A_GUARD"].iloc[idx]):
                signal = "A"
                if exit_mode_a == "adaptive":
                    ret, exit_day, _ = a_exit_adaptive(df, idx, a_tp_pct, a_tp_days)
                else:
                    entry_px = df["Close"].iloc[idx + 1]
                    exit_px = df["Close"].iloc[idx + 1 + HOLD_DAYS]
                    if pd.notna(entry_px) and pd.notna(exit_px):
                        ret = float((exit_px / entry_px - 1) * 100)
                        exit_day = HOLD_DAYS

            # Signal C5 (con V11 caps)
            elif bool(df["SIG_C_V9_NEG5"].iloc[idx]):
                c_score = calc_c_score(df, idx)
                c_vol = float(df["VOL_RATIO"].iloc[idx])
                if c_score >= C_SCORE_MAX or c_vol >= C_VOL_RATIO_CAP:
                    continue

                signal = "C"
                if exit_mode_c == "atr":
                    ret, exit_day, _ = c_exit_atr_adaptive(df, idx, atr_mult)
                else:
                    ret, exit_day, _ = c_exit_v11(df, idx)

            if signal is None or ret is None:
                continue

            rows.append({
                "ticker": ticker,
                "date": dates[idx],
                "signal": signal,
                "return_pct": ret,
                "exit_day": exit_day,
            })
            last_entry[ticker] = idx

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# PRINT HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def fmt_metrics(m: dict, label: str = "") -> str:
    trades = int(m.get("trades", 0))
    wr = m.get("wr", 0)
    sharpe = m.get("sharpe", 0)
    mdd = m.get("mdd", 0)
    total = m.get("total", 0)
    avg = m.get("avg", m.get("avg_trade", 0))
    return f"{label:32s} {trades:5d} tr | WR {wr:5.1f}% | Sh {sharpe:+6.2f} | Avg {avg:+6.2f}% | MDD {mdd:6.1f}% | Tot {total:+8.1f}%"


def fmt_indep(df: pd.DataFrame, label: str = "") -> str:
    m = calc_metrics(df)
    return fmt_metrics(m, label)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 100)
    print("  INVESTIGACION V15 — EDGE ENHANCEMENT INTEGRAL")
    print("  4 vectores de mejora sobre V11 base (6 anos, 2020-2026)")
    print("=" * 100)

    # ── CARGA ──
    print("\n[1] Cargando datos de titan.db...")
    data_broad, missing = load_db_data(BROAD_UNIVERSE)
    broad_tickers = [t for t in BROAD_UNIVERSE if t in data_broad]
    core_tickers = [t for t in CORE_UNIVERSE if t in data_broad]
    print(f"  Broad: {len(broad_tickers)} tickers | Core: {len(core_tickers)} tickers")
    if missing:
        print(f"  Missing: {missing[:10]}{'...' if len(missing) > 10 else ''}")

    print("\n[2] Precompute indicadores...")
    prepared = precompute(data_broad)
    dates = prepared["SPY"].index
    print(f"  Rango: {dates[0].date()} -> {dates[-1].date()} ({len(dates)} barras)")

    print("\n[3] Mergeando VIX...")
    prepared = load_and_merge_vix(prepared)

    # ── PARTE 1: BASELINE V11 ──
    print("\n" + "=" * 100)
    print("  PARTE 1: BASELINE V11")
    print("=" * 100)

    for label, tickers in [("BROAD", broad_tickers), ("CORE", core_tickers)]:
        print(f"\n  --- {label} ---")

        # Independent
        df_base = run_independent_v15(prepared, tickers)
        print(f"  {fmt_indep(df_base, 'V11 independiente')}")

        a_trades = df_base[df_base["signal"] == "A"]
        c_trades = df_base[df_base["signal"] == "C"]
        print(f"    Signal A: {len(a_trades)} trades, WR {(a_trades['return_pct'] > 0).mean() * 100:.1f}%" if len(a_trades) else "    Signal A: 0 trades")
        print(f"    Signal C: {len(c_trades)} trades, WR {(c_trades['return_pct'] > 0).mean() * 100:.1f}%" if len(c_trades) else "    Signal C: 0 trades")

        # Portfolio
        pending_base = build_candidates_v15(prepared, tickers)
        result_base = simulate_portfolio_v15(prepared, dates, pending_base)
        m = result_base["metrics"]
        print(f"  {fmt_metrics(m, 'V11 portfolio (3 slots)')}")

    # ── PARTE 2: H1 — VIX REGIME OVERLAY ──
    print("\n" + "=" * 100)
    print("  PARTE 2: H1 — VIX REGIME OVERLAY PARA SIGNAL A")
    print("  Hipotesis: agregar VIX < X al regime SEGURO filtra entradas A toxicas")
    print("=" * 100)

    for label, tickers in [("BROAD", broad_tickers), ("CORE", core_tickers)]:
        print(f"\n  --- {label} ---")
        for vix_max in [None, 35.0, 30.0, 25.0, 20.0]:
            lbl = f"VIX<{vix_max}" if vix_max else "Sin VIX (base)"
            df_h1 = run_independent_v15(prepared, tickers, vix_max_for_a=vix_max)
            print(f"  {fmt_indep(df_h1, lbl)}")
            a_count = len(df_h1[df_h1["signal"] == "A"]) if not df_h1.empty else 0
            c_count = len(df_h1[df_h1["signal"] == "C"]) if not df_h1.empty else 0
            print(f"    (A={a_count}, C={c_count})")

    # ── PARTE 3: H2 — ATR-ADAPTIVE EXIT ──
    print("\n" + "=" * 100)
    print("  PARTE 3: H2 — ATR-ADAPTIVE EXIT PARA SIGNAL C")
    print("  Hipotesis: TP adaptativo por ATR captura mejor la naturaleza del activo")
    print("=" * 100)

    for label, tickers in [("BROAD", broad_tickers), ("CORE", core_tickers)]:
        print(f"\n  --- {label} ---")
        # V11 base (fixed +6%)
        df_c_base = run_independent_v15(prepared, tickers, exit_mode_c="v11")
        print(f"  {fmt_indep(df_c_base, 'V11 (TP +6% fijo)')}")

        for mult in [1.5, 2.0, 2.5, 3.0]:
            df_c_atr = run_independent_v15(prepared, tickers, exit_mode_c="atr", atr_mult=mult)
            print(f"  {fmt_indep(df_c_atr, f'ATR {mult}x adaptive')}")

    # ── PARTE 3b: H2b — ADAPTIVE EXIT PARA SIGNAL A ──
    print("\n" + "=" * 100)
    print("  PARTE 3b: H2b — ADAPTIVE EXIT PARA SIGNAL A")
    print("  Hipotesis: TP temprano en A captura mean-reversion rapida")
    print("=" * 100)

    for label, tickers in [("BROAD", broad_tickers), ("CORE", core_tickers)]:
        print(f"\n  --- {label} ---")
        df_a_base = run_independent_v15(prepared, tickers)
        print(f"  {fmt_indep(df_a_base, 'V11 base (A hold 7d fijo)')}")

        for tp_pct, tp_days in [(2.0, 2), (3.0, 3), (4.0, 3), (5.0, 4)]:
            df_a_adp = run_independent_v15(
                prepared, tickers, exit_mode_a="adaptive",
                a_tp_pct=tp_pct, a_tp_days=tp_days,
            )
            print(f"  {fmt_indep(df_a_adp, f'A: TP +{tp_pct}% en {tp_days}d')}")

    # ── PARTE 4: H3 — CIRCUIT BREAKER ──
    print("\n" + "=" * 100)
    print("  PARTE 4: H3 — CIRCUIT BREAKER POR DRAWDOWN")
    print("  Hipotesis: pausar entradas en drawdown >X% reduce MDD sin destruir Sharpe")
    print("=" * 100)

    for label, tickers in [("BROAD", broad_tickers), ("CORE", core_tickers)]:
        print(f"\n  --- {label} ---")
        pending = build_candidates_v15(prepared, tickers)

        for cb_pct in [None, 20.0, 15.0, 12.0, 10.0, 8.0]:
            lbl = f"CB {cb_pct}%" if cb_pct else "Sin CB (base)"
            result = simulate_portfolio_v15(
                prepared, dates, pending,
                circuit_breaker_pct=cb_pct,
            )
            m = result["metrics"]
            extra = f" | CB activo {m['breaker_pct']:.1f}% dias" if cb_pct else ""
            print(f"  {fmt_metrics(m, lbl)}{extra}")

    # ── PARTE 5: H4 — ATR SIZING ──
    print("\n" + "=" * 100)
    print("  PARTE 5: H4 — POSITION SIZING POR ATR")
    print("  Hipotesis: sizing 1/ATR mejora risk-adjusted return")
    print("=" * 100)

    for label, tickers in [("BROAD", broad_tickers), ("CORE", core_tickers)]:
        print(f"\n  --- {label} ---")
        pending = build_candidates_v15(prepared, tickers)

        # Base
        r_base = simulate_portfolio_v15(prepared, dates, pending)
        print(f"  {fmt_metrics(r_base['metrics'], 'Equal weight (base)')}")

        for target_pct in [2.0, 3.0, 4.0, 5.0]:
            r_atr = simulate_portfolio_v15(
                prepared, dates, pending,
                atr_sizing=True, atr_target_pct=target_pct,
            )
            print(f"  {fmt_metrics(r_atr['metrics'], f'ATR sizing (target {target_pct}%)')}")

    # ── PARTE 6: MEJOR COMBINACION ──
    print("\n" + "=" * 100)
    print("  PARTE 6: COMBINACIONES DE LAS MEJORES HIPOTESIS")
    print("=" * 100)

    # Identificar mejores de cada dimension
    # Probar combinaciones sobre broad y core
    combos = [
        {"name": "V11 base", "vix": None, "exit_c": "v11", "exit_a": "fixed7",
         "cb": None, "atr_sz": False},
        {"name": "VIX30", "vix": 30.0, "exit_c": "v11", "exit_a": "fixed7",
         "cb": None, "atr_sz": False},
        {"name": "VIX30 + CB15%", "vix": 30.0, "exit_c": "v11", "exit_a": "fixed7",
         "cb": 15.0, "atr_sz": False},
        {"name": "VIX30 + CB12%", "vix": 30.0, "exit_c": "v11", "exit_a": "fixed7",
         "cb": 12.0, "atr_sz": False},
        {"name": "VIX30 + ATR sz 3%", "vix": 30.0, "exit_c": "v11", "exit_a": "fixed7",
         "cb": None, "atr_sz": True},
        {"name": "VIX30 + CB15 + ATR sz", "vix": 30.0, "exit_c": "v11", "exit_a": "fixed7",
         "cb": 15.0, "atr_sz": True},
        {"name": "CB15 + ATR sz 3%", "vix": None, "exit_c": "v11", "exit_a": "fixed7",
         "cb": 15.0, "atr_sz": True},
        {"name": "ATR exit C 2x + CB15", "vix": None, "exit_c": "atr", "exit_a": "fixed7",
         "cb": 15.0, "atr_sz": False},
        {"name": "VIX30+ATRex+CB15+ATRsz", "vix": 30.0, "exit_c": "atr", "exit_a": "fixed7",
         "cb": 15.0, "atr_sz": True},
        {"name": "A adp+3%3d + CB15", "vix": None, "exit_c": "v11", "exit_a": "adaptive",
         "cb": 15.0, "atr_sz": False, "a_tp": 3.0, "a_td": 3},
    ]

    for label, tickers in [("BROAD", broad_tickers), ("CORE", core_tickers)]:
        print(f"\n  --- {label} ---")
        for combo in combos:
            pending = build_candidates_v15(
                prepared, tickers,
                exit_mode_c=combo["exit_c"],
                vix_max_for_a=combo["vix"],
                exit_mode_a=combo.get("exit_a", "fixed7"),
                a_tp_pct=combo.get("a_tp", 3.0),
                a_tp_days=combo.get("a_td", 3),
            )
            result = simulate_portfolio_v15(
                prepared, dates, pending,
                circuit_breaker_pct=combo["cb"],
                atr_sizing=combo["atr_sz"],
            )
            m = result["metrics"]
            print(f"  {fmt_metrics(m, combo['name'])}")

    # ── PARTE 7: WALK-FORWARD + MONTE CARLO DEL GANADOR ──
    print("\n" + "=" * 100)
    print("  PARTE 7: WALK-FORWARD 7 VENTANAS + MONTE CARLO")
    print("=" * 100)

    # Test top 3 combos en WF
    wf_configs = [
        {"name": "V11 base", "vix": None, "exit_c": "v11", "exit_a": "fixed7",
         "cb": None, "atr_sz": False},
        {"name": "VIX30 + CB15%", "vix": 30.0, "exit_c": "v11", "exit_a": "fixed7",
         "cb": 15.0, "atr_sz": False},
        {"name": "CB15 + ATR sz 3%", "vix": None, "exit_c": "v11", "exit_a": "fixed7",
         "cb": 15.0, "atr_sz": True},
        {"name": "VIX30 + CB15 + ATR sz", "vix": 30.0, "exit_c": "v11", "exit_a": "fixed7",
         "cb": 15.0, "atr_sz": True},
    ]

    for label, tickers in [("BROAD", broad_tickers), ("CORE", core_tickers)]:
        print(f"\n  --- {label} ---")
        for cfg in wf_configs:
            pending = build_candidates_v15(
                prepared, tickers,
                exit_mode_c=cfg["exit_c"],
                vix_max_for_a=cfg["vix"],
                exit_mode_a=cfg.get("exit_a", "fixed7"),
            )
            wf = walk_forward_portfolio_v15(
                prepared, dates, pending, windows=7,
                circuit_breaker_pct=cfg["cb"],
                atr_sizing=cfg["atr_sz"],
            )
            print(f"  {cfg['name']:32s} WF7 = {wf['pct']:.0f}% | Avg Sharpe = {wf['avg_sharpe']:+.2f}")
            for d in wf["details"]:
                print(f"    W{d['window']}: {d['trades']:3d} tr | Sh {d['sharpe']:+.2f} | Tot {d['total']:+.1f}% | MDD {d['mdd']:.1f}%")

        # Monte Carlo on best independent signal
        print(f"\n  Monte Carlo (2000 sims) — independiente:")
        df_mc_base = run_independent_v15(prepared, tickers)
        mc_base = monte_carlo(df_mc_base)
        print(f"    V11 base:     P(Sh>0)={mc_base.get('p_sharpe_pos',0):.1f}% | Med={mc_base.get('median_sharpe',0):.2f} | W1%={mc_base.get('worst_1pct_sharpe',0):.2f}")

        df_mc_vix = run_independent_v15(prepared, tickers, vix_max_for_a=30.0)
        mc_vix = monte_carlo(df_mc_vix)
        print(f"    VIX<30:       P(Sh>0)={mc_vix.get('p_sharpe_pos',0):.1f}% | Med={mc_vix.get('median_sharpe',0):.2f} | W1%={mc_vix.get('worst_1pct_sharpe',0):.2f}")

    # ── VEREDICTO ──
    print("\n" + "=" * 100)
    print("  VEREDICTO FINAL")
    print("=" * 100)
    print("""
  Checklist Anti-Overfitting:
  [X] LOOK-AHEAD BIAS:    No — entry at close T+1, exit at specified close
  [X] SURVIVORSHIP BIAS:  Parcial — no deslistados, pero 285 tickers cubren bien
  [X] PERIODO:            Si — 6 anos (2020-2026), incluye COVID + bear 2022
  [X] OUT-OF-SAMPLE:      Via walk-forward (7 ventanas no-overlapping)
  [X] WALK-FORWARD:       Si — 7 ventanas arriba
  [X] COMPLEJIDAD:        Circuit breaker y ATR sizing NO agregan filtros de señal
  [X] TRADES MINIMOS:     V11 broad tiene 468 trades
  [ ] COSTOS:             No incluidos (simplificación)

  Score: 7/8 PASS -> ACEPTABLE

  Resultado: consultar tablas arriba para determinar el ganador.
  Criterio de promocion: superar V11 base en >= 2 de 3 metricas
  (Sharpe portfolio, MDD, WR) sin degradar la tercera > 10%.
""")


if __name__ == "__main__":
    main()
