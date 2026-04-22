#!/usr/bin/env python3
"""
INVESTIGACION V19 - SECTOR FILTER + PANIC MODE PARA SIGNAL C5
==============================================================

Objetivo:
  Testear si filtrar C5 por sector y/o detectar regimen de panico en SPY
  mejora de forma honesta el edge operativo del scanner V11.

Hallazgos previos (auditoria cientifica 2026-04-12):
  - Semis en C5 : N=30,  WR=83.3%, avg=+6.07%, Sharpe=6.71
  - Tech en C5  : N=76,  WR=44.7%, avg=+0.46%, Sharpe=0.43 (por debajo del random!)
  - Health en C5: N=24,  WR=50%,   avg=-1.91%, Sharpe=-2.28
  - Consumer    : N=35,  WR=65.7%, avg=+3.26%
  - Finance     : N=31,  WR=71.0%, avg=+3.98%

  SPY ROC20 < -10% (panico): N=113, WR4=82.3%, avg=+6.46%, Sharpe=4.29
  SPY ROC20 >= -10% (normal): N=79, WR4=52.9%, avg=+0.78%, Sharpe=0.45

Preguntas:
  1. Bloquear health de C5 mejora el portfolio real (3 slots)?
  2. Agregar sector_weight al ranking (semis up, tech down) mejora Sharpe/MDD?
  3. Durante panic (SPY ROC20 < -10%), ignorar sector filter vale la pena?
  4. Exit D7 fijo bate al exit adaptativo V10 en portfolio (no solo per-trade)?
  5. La combinacion SECTOR_WEIGHT + PANIC_UNLOCK supera a V11 base en WF?

Politicas testeadas (portfolio 3 slots):
  BASE         : SCORE85_VOL4 (V11 base, exit adaptativo)
  HEALTH_BLOCK : BASE + bloquea sector health de C5
  SECTOR_WEIGHT: HEALTH_BLOCK + tech penalizado en ranking + semis/consumer/finance boost
  PANIC_UNLOCK : SECTOR_WEIGHT normal, pero durante panic relajamos sector filter
  COMBINED     : PANIC_UNLOCK (mejor candidato combinado)
  D7_FIXED     : BASE pero con exit fijo D7 (sin early TP)

Promotion gates (todos necesarios para PROMOVER):
  PG1. Baseline reproduce V11 Sharpe >= 0.65 (tolerancia 8% sobre 0.71)
  PG2. Mejor variante: Sharpe > baseline
  PG3. Mejor variante: MDD no peor de -50% (baseline ~-38%)
  PG4. Mejor variante: WR >= baseline - 2pp
  PG5. N trades mejor variante >= 0.75 * baseline trades (no filtrar demasiado)
  PG6. WF: mejor variante gana >= 5/7 ventanas vs BASE en Sharpe
  PG7. Sector health confirmado malo: avg_return_health < 0 en per-trade

Veredicto final:
  PROMOVER    : >= 5/7 gates PASS
  CONDICIONAL : 4/7 gates PASS
  RECHAZAR    : < 4 gates

Fecha: 2026-04-12
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import sys

import numpy as np
import pandas as pd

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
from titan_system.core.data_loader import get_sector

LINE = "=" * 100
SUBLINE = "-" * 100

# Sector priorities for C5 ranking bonus
SECTOR_BONUS: dict[str, float] = {
    "semis":    +20.0,   # WR=83%, strong boost
    "finance":  +10.0,   # WR=71%
    "consumer": +8.0,    # WR=66%
    "industrial": +4.0,  # WR=65%
    "mining":   +2.0,
    "energy":   +2.0,
    "telecom":  +0.0,
    "other":    +0.0,
    "tech":     -15.0,   # WR=44%, penalize
    "health":   -999.0,  # Blocked (avg=-1.91%)
    "latam":    +0.0,
}

# Sectors blocked in normal mode
SECTORS_BLOCKED = {"health"}

# SPY ROC20 threshold for panic mode
PANIC_ROC20_THRESHOLD = -10.0


# ---------------------------------------------------------------------------
# Extended Candidate (adds sector + panic flag)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    ticker: str
    signal: str
    signal_date: Any  # pd.Timestamp
    signal_idx: int
    entry_idx: int
    exit_idx: int
    raw_score: float
    sector: str = "other"
    is_panic: bool = False
    vol_ratio: float | None = None
    rsi: float | None = None
    neg_days10: float | None = None


# ---------------------------------------------------------------------------
# SPY ROC20 computation (added to prepared["SPY"])
# ---------------------------------------------------------------------------

def add_spy_roc20(prepared: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Add ROC20 and PANIC flag to SPY dataframe."""
    spy = prepared["SPY"].copy()
    spy["SPY_ROC20"] = (spy["Close"] / spy["Close"].shift(20) - 1) * 100
    spy["SPY_PANIC"] = spy["SPY_ROC20"] < PANIC_ROC20_THRESHOLD
    prepared["SPY"] = spy
    return prepared


# ---------------------------------------------------------------------------
# Policy functions
# ---------------------------------------------------------------------------

def policy_allows(candidate: Candidate, policy: str) -> bool:
    """Return True if this candidate passes the policy filter."""
    if candidate.signal != "C":
        return True  # Signal A: always pass

    # All policies require SCORE85_VOL4 baseline
    if candidate.raw_score >= 85.0:
        return False
    if (candidate.vol_ratio or 0.0) >= 4.0:
        return False

    if policy == "BASE":
        return True

    if policy == "HEALTH_BLOCK":
        return candidate.sector not in SECTORS_BLOCKED

    if policy == "SECTOR_WEIGHT":
        # Health blocked; tech is allowed but penalized in ranking
        return candidate.sector not in SECTORS_BLOCKED

    if policy == "PANIC_UNLOCK":
        # During panic: drop sector filter; normal: block health
        if candidate.is_panic:
            return True  # All sectors allowed in panic
        return candidate.sector not in SECTORS_BLOCKED

    if policy == "D7_FIXED":
        return True  # Same as BASE for filtering

    raise ValueError(f"Unknown policy: {policy}")


def candidate_rank(candidate: Candidate, policy: str) -> tuple[float, float, float]:
    """
    Return a tuple for sorting (higher = better priority).
    Returns (allowed, sector_bonus, score).
    """
    allowed = 1.0 if policy_allows(candidate, policy) else 0.0
    if candidate.signal != "C":
        return (allowed, 0.0, candidate.raw_score)

    if policy == "SECTOR_WEIGHT":
        bonus = SECTOR_BONUS.get(candidate.sector, 0.0)
        if candidate.sector == "health":
            bonus = -999.0
        return (allowed, bonus, candidate.raw_score)

    if policy == "PANIC_UNLOCK":
        if candidate.is_panic:
            # In panic: semis/finance get extra boost
            base_bonus = SECTOR_BONUS.get(candidate.sector, 0.0)
            panic_extra = 10.0 if candidate.sector in {"semis", "finance", "consumer"} else 0.0
            return (allowed, base_bonus + panic_extra, candidate.raw_score)
        else:
            bonus = SECTOR_BONUS.get(candidate.sector, 0.0)
            if candidate.sector == "health":
                bonus = -999.0
            return (allowed, bonus, candidate.raw_score)

    # BASE, HEALTH_BLOCK, D7_FIXED: no sector ranking
    return (allowed, 0.0, candidate.raw_score)


# ---------------------------------------------------------------------------
# Build candidates with sector + panic annotations
# ---------------------------------------------------------------------------

def build_candidates(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    use_d7_fixed: bool = False,
) -> tuple[dict[int, list[Candidate]], dict[str, Any]]:
    """Build all C5 + A candidates with sector and panic labels."""
    dates = prepared["SPY"].index
    pending: dict[int, list[Candidate]] = {}

    per_trade_rows: list[dict[str, Any]] = []
    daily_counts: list[int] = []

    for idx in range(START_IDX, len(dates) - 9):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
        is_panic = bool(prepared["SPY"]["SPY_PANIC"].iloc[idx])
        day_count = 0

        for ticker in tickers:
            if ticker == "SPY" or ticker not in prepared:
                continue

            df = prepared[ticker]
            sector = get_sector(ticker)
            candidate: Candidate | None = None

            # Signal A (mean reversion, regime required)
            if regime_safe and bool(df["SIG_A_GUARD"].iloc[idx]):
                entry_idx = idx + 1
                exit_idx = idx + 8
                entry_px = df["Close"].iloc[entry_idx]
                exit_px = df["Close"].iloc[exit_idx]
                if pd.notna(entry_px) and pd.notna(exit_px):
                    candidate = Candidate(
                        ticker=ticker,
                        signal="A",
                        signal_date=dates[idx],
                        signal_idx=idx,
                        entry_idx=entry_idx,
                        exit_idx=exit_idx,
                        raw_score=calc_a_score(df, idx),
                        sector=sector,
                        is_panic=is_panic,
                        vol_ratio=float(df["VOL_RATIO"].iloc[idx]),
                        rsi=float(df["RSI"].iloc[idx]),
                    )

            # Signal C5 (crash, no regime needed)
            elif bool(df["SIG_C_V9_NEG5"].iloc[idx]):
                # Check C5 cap (score < 85 and vol < 4x) — V11 baseline filter
                raw_score = calc_c_score(df, idx)
                vol_ratio = float(df["VOL_RATIO"].iloc[idx])

                if use_d7_fixed:
                    # Fixed D7 exit
                    if idx + 8 >= len(dates):
                        continue
                    entry_px = df["Close"].iloc[idx + 1]
                    exit_px = df["Close"].iloc[idx + 8]
                    if pd.isna(entry_px) or pd.isna(exit_px):
                        continue
                    ret = float((exit_px / entry_px - 1) * 100)
                    exit_day = 7
                    entry_idx = idx + 1
                    exit_idx = idx + 8
                else:
                    ret, exit_day, _ = c_exit_return(df, idx)
                    if ret is None or exit_day is None:
                        continue
                    entry_idx = idx + 1
                    exit_idx = idx + 1 + exit_day

                candidate = Candidate(
                    ticker=ticker,
                    signal="C",
                    signal_date=dates[idx],
                    signal_idx=idx,
                    entry_idx=entry_idx,
                    exit_idx=exit_idx,
                    raw_score=raw_score,
                    sector=sector,
                    is_panic=is_panic,
                    vol_ratio=vol_ratio,
                    rsi=float(df["RSI"].iloc[idx]),
                    neg_days10=float(df["NEG_DAYS10"].iloc[idx]),
                )
                per_trade_rows.append({
                    "ticker": ticker,
                    "signal_date": dates[idx],
                    "sector": sector,
                    "is_panic": is_panic,
                    "return_pct": ret,
                    "exit_day": exit_day,
                    "raw_score": raw_score,
                    "vol_ratio": vol_ratio,
                    "rsi": float(df["RSI"].iloc[idx]),
                    "passes_base": raw_score < 85.0 and vol_ratio < 4.0,
                })

            if candidate is None:
                continue

            pending.setdefault(candidate.entry_idx, []).append(candidate)
            day_count += 1

        daily_counts.append(day_count)

    per_trade_df = pd.DataFrame(per_trade_rows) if per_trade_rows else pd.DataFrame()
    return pending, per_trade_df


# ---------------------------------------------------------------------------
# Portfolio simulation (extended for sector/panic policies)
# ---------------------------------------------------------------------------

def simulate_portfolio(
    prepared: dict[str, pd.DataFrame],
    dates: Any,
    pending: dict[int, list[Candidate]],
    policy: str,
    start_idx: int | None = None,
    end_idx: int | None = None,
) -> dict[str, Any]:
    start = START_IDX + 1 if start_idx is None else start_idx
    end = len(dates) if end_idx is None else end_idx

    cash = INITIAL_EQUITY
    cooldown_until: dict[str, int] = {}
    open_positions: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    closed_rows: list[dict[str, Any]] = []

    for idx in range(start, end):
        # Mark-to-market equity
        equity = cash + sum(
            float(pos["shares"]) * float(prepared[str(pos["ticker"])]["Close"].iloc[idx])
            for pos in open_positions
        )
        equity_rows.append({
            "date": dates[idx],
            "equity": equity,
            "open_positions": len(open_positions),
        })

        # Close expired positions
        still_open: list[dict[str, Any]] = []
        for pos in open_positions:
            if int(pos["exit_idx"]) == idx:
                ticker = str(pos["ticker"])
                exit_px = float(prepared[ticker]["Close"].iloc[idx])
                cash += float(pos["shares"]) * exit_px
                closed_rows.append({
                    "ticker": ticker,
                    "signal": pos["signal"],
                    "sector": pos["sector"],
                    "is_panic": pos["is_panic"],
                    "entry_date": dates[int(pos["entry_idx"])].date().isoformat(),
                    "exit_date": dates[idx].date().isoformat(),
                    "return_pct": (exit_px / float(pos["entry_price"]) - 1.0) * 100.0,
                    "raw_score": float(pos["raw_score"]),
                })
            else:
                still_open.append(pos)
        open_positions = still_open

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
        slot_budget = total_equity / MAX_POSITIONS

        # Sort by policy rank (descending = best first)
        ranked = sorted(todays, key=lambda c: candidate_rank(c, policy), reverse=True)

        for candidate in ranked:
            if free_slots <= 0:
                break
            if not policy_allows(candidate, policy):
                continue
            if any(str(pos["ticker"]) == candidate.ticker for pos in open_positions):
                continue
            if idx <= cooldown_until.get(candidate.ticker, -999):
                continue

            entry_px = float(prepared[candidate.ticker]["Close"].iloc[idx])
            if not np.isfinite(entry_px) or entry_px <= 0:
                continue

            invested = min(slot_budget, cash)
            if invested <= 0:
                break

            open_positions.append({
                "ticker": candidate.ticker,
                "signal": candidate.signal,
                "sector": candidate.sector,
                "is_panic": candidate.is_panic,
                "entry_idx": candidate.entry_idx,
                "exit_idx": candidate.exit_idx,
                "raw_score": candidate.raw_score,
                "shares": invested / entry_px,
                "entry_price": entry_px,
            })
            cash -= invested
            cooldown_until[candidate.ticker] = candidate.signal_idx + ANTIKNIFE_DAYS
            free_slots -= 1

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(closed_rows)
    metrics = calc_portfolio_metrics(equity_df, trades_df)
    return {
        "equity_df": equity_df,
        "trades_df": trades_df,
        "metrics": metrics,
    }


def walk_forward(
    prepared: dict[str, pd.DataFrame],
    dates: Any,
    pending_base: dict[int, list[Candidate]],
    pending_d7: dict[int, list[Candidate]],
    windows: int = 7,
) -> dict[str, Any]:
    """Walk-forward for all policies."""
    total_span = len(dates) - (START_IDX + 1)
    window_size = total_span // windows

    policies = ["BASE", "HEALTH_BLOCK", "SECTOR_WEIGHT", "PANIC_UNLOCK", "D7_FIXED"]
    wf_wins: dict[str, int] = {p: 0 for p in policies}
    wf_details: list[dict[str, Any]] = []

    for w in range(windows):
        start = START_IDX + 1 + w * window_size
        end = min(START_IDX + 1 + (w + 1) * window_size, len(dates))
        window_sharpes: dict[str, float] = {}

        for policy in policies:
            pending = pending_d7 if policy == "D7_FIXED" else pending_base
            result = simulate_portfolio(prepared, dates, pending, policy, start_idx=start, end_idx=end)
            window_sharpes[policy] = float(result["metrics"]["sharpe"])

        base_sh = window_sharpes["BASE"]
        for policy in policies:
            if policy != "BASE" and window_sharpes[policy] > base_sh:
                wf_wins[policy] += 1

        wf_details.append({
            "window": w + 1,
            "start": dates[start].date().isoformat() if start < len(dates) else "?",
            "end": dates[end - 1].date().isoformat() if end - 1 < len(dates) else "?",
            **{p: round(window_sharpes[p], 3) for p in policies},
        })

    return {"wins": wf_wins, "windows": windows, "details": wf_details}


# ---------------------------------------------------------------------------
# Per-trade sector analysis
# ---------------------------------------------------------------------------

def analyze_per_trade(per_trade_df: pd.DataFrame) -> None:
    if per_trade_df.empty:
        print("  [!] No hay trades C5 para analizar")
        return

    # Filter to base policy (score < 85, vol < 4x)
    base = per_trade_df[per_trade_df["passes_base"]].copy()
    n_base = len(base)

    print(f"\n  [1] ANALISIS POR SECTOR (C5 base, N={n_base})")
    print(f"  {'Sector':<14} {'N':>5} {'WR%':>8} {'Avg%':>8} {'Sharpe':>8}")
    print(f"  {'-'*50}")

    sectors_found: list[tuple[str, int, float, float, float]] = []
    for sector in sorted(base["sector"].unique()):
        rows = base[base["sector"] == sector]
        n = len(rows)
        if n < 5:
            continue
        wr = float((rows["return_pct"] > 0).mean() * 100)
        avg = float(rows["return_pct"].mean())
        std = float(rows["return_pct"].std())
        sharpe = avg / std * np.sqrt(252 / 7) if std > 0 else 0.0
        sectors_found.append((sector, n, wr, avg, sharpe))
        print(f"  {sector:<14} {n:>5} {wr:>7.1f}% {avg:>+7.2f}% {sharpe:>+8.2f}")

    # All
    wr_all = float((base["return_pct"] > 0).mean() * 100)
    avg_all = float(base["return_pct"].mean())
    print(f"  {'ALL':<14} {n_base:>5} {wr_all:>7.1f}% {avg_all:>+7.2f}%")

    print(f"\n  [2] ANALISIS POR REGIME PANIC (C5 base)")
    for label, flag in [("PANIC (ROC20<-10%)", True), ("NORMAL", False)]:
        rows = base[base["is_panic"] == flag]
        n = len(rows)
        if n == 0:
            continue
        wr = float((rows["return_pct"] > 0).mean() * 100)
        avg = float(rows["return_pct"].mean())
        std = float(rows["return_pct"].std())
        sharpe = avg / std * np.sqrt(252 / 7) if std > 0 else 0.0
        print(f"  {label:<22} N={n:>4}  WR={wr:>5.1f}%  avg={avg:>+6.2f}%  Sharpe={sharpe:>+5.2f}")

    print(f"\n  [3] HEALTH GATE — avg return health C5 (passes_base):")
    health_rows = base[base["sector"] == "health"]
    n_h = len(health_rows)
    if n_h > 0:
        avg_h = float(health_rows["return_pct"].mean())
        wr_h = float((health_rows["return_pct"] > 0).mean() * 100)
        print(f"  health C5: N={n_h}  WR={wr_h:.1f}%  avg={avg_h:+.2f}%")
        pg7_pass = avg_h < 0
        print(f"  PG7 (health avg < 0): {'PASS' if pg7_pass else 'FAIL'}")
    else:
        print("  health C5: N=0 (no trades found in DB)")
        pg7_pass = True  # vacuously pass


# ---------------------------------------------------------------------------
# Promotion gates
# ---------------------------------------------------------------------------

def evaluate_promotion_gates(
    base_metrics: dict[str, Any],
    best_policy: str,
    best_metrics: dict[str, Any],
    wf_wins: dict[str, int],
    wf_windows: int,
    per_trade_df: pd.DataFrame,
) -> tuple[int, list[str]]:
    gates: list[str] = []

    # PG1: Baseline reproduced
    base_sharpe = float(base_metrics["sharpe"])
    pg1 = base_sharpe >= 0.65
    gates.append(f"[{'PASS' if pg1 else 'FAIL'}] PG1 Baseline sharpe >= 0.65: {base_sharpe:.3f}")

    # PG2: Best variant beats baseline in Sharpe
    best_sharpe = float(best_metrics["sharpe"])
    pg2 = best_sharpe > base_sharpe
    gates.append(f"[{'PASS' if pg2 else 'FAIL'}] PG2 Mejor variante Sharpe > base: {best_sharpe:.3f} vs {base_sharpe:.3f}")

    # PG3: MDD not catastrophic
    best_mdd = float(best_metrics["mdd"])
    base_mdd = float(base_metrics["mdd"])
    pg3 = best_mdd >= -50.0 and best_mdd >= base_mdd - 5.0  # not more than 5pp worse
    gates.append(f"[{'PASS' if pg3 else 'FAIL'}] PG3 MDD aceptable: {best_mdd:.1f}% (base {base_mdd:.1f}%)")

    # PG4: WR not degraded > 2pp
    best_wr = float(best_metrics["wr"])
    base_wr = float(base_metrics["wr"])
    pg4 = best_wr >= base_wr - 2.0
    gates.append(f"[{'PASS' if pg4 else 'FAIL'}] PG4 WR no degradado >2pp: {best_wr:.1f}% vs {base_wr:.1f}%")

    # PG5: N trades not too low
    best_trades = float(best_metrics["trades"])
    base_trades = float(base_metrics["trades"])
    pg5 = base_trades == 0 or best_trades >= 0.75 * base_trades
    gates.append(f"[{'PASS' if pg5 else 'FAIL'}] PG5 N trades >= 75% de base: {best_trades:.0f} vs {base_trades:.0f}")

    # PG6: WF >= 5/7 windows
    best_wins = wf_wins.get(best_policy, 0)
    pg6 = best_wins >= 5
    gates.append(f"[{'PASS' if pg6 else 'FAIL'}] PG6 WF {best_policy}: {best_wins}/{wf_windows} ventanas ganadas (necesita >= 5)")

    # PG7: Health avg_return < 0
    if not per_trade_df.empty:
        base_pt = per_trade_df[per_trade_df["passes_base"]]
        health_rows = base_pt[base_pt["sector"] == "health"]
        if len(health_rows) >= 5:
            avg_h = float(health_rows["return_pct"].mean())
            pg7 = avg_h < 0
            gates.append(f"[{'PASS' if pg7 else 'FAIL'}] PG7 Health avg < 0: {avg_h:+.2f}% (N={len(health_rows)})")
        else:
            pg7 = True
            gates.append(f"[SKIP] PG7 Health: insuficientes trades en DB (N={len(health_rows)})")
    else:
        pg7 = True
        gates.append("[SKIP] PG7 Health: sin datos per-trade")

    passes = sum(1 for g in gates if "[PASS]" in g)
    return passes, gates


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(LINE)
    print("  INVESTIGACION V19 — SECTOR FILTER + PANIC MODE PARA C5")
    print(LINE)

    # --- Load data ---
    print("\n[1] Cargando datos...")
    data, missing = load_db_data(BROAD_UNIVERSE)
    if missing:
        print(f"  Missing: {missing[:10]}")
    prepared = precompute(data)
    prepared = add_spy_roc20(prepared)

    dates = prepared["SPY"].index
    spy = prepared["SPY"]

    # Panic stats
    panic_days = int(spy["SPY_PANIC"].sum())
    total_days = len(spy)
    print(f"  Dias en DB: {total_days} | Dias en PANIC (SPY ROC20<-10%): {panic_days} ({100*panic_days/total_days:.1f}%)")
    print(f"  Rango: {dates[0].date()} -> {dates[-1].date()}")

    # --- Build candidates ---
    print("\n[2] Construyendo candidatos (exit adaptativo)...")
    pending_base, per_trade_df = build_candidates(prepared, BROAD_UNIVERSE, use_d7_fixed=False)

    print(f"  Dias con candidatos: {sum(1 for v in pending_base.values() if v)} / {len(pending_base)}")
    if not per_trade_df.empty:
        c5_base = per_trade_df[per_trade_df["passes_base"]]
        print(f"  C5 trades (passes_base): {len(c5_base)} | total C5 raw: {len(per_trade_df)}")

    print("\n[2b] Construyendo candidatos (exit D7 fijo)...")
    pending_d7, _ = build_candidates(prepared, BROAD_UNIVERSE, use_d7_fixed=True)

    # --- Per-trade analysis ---
    print(f"\n{SUBLINE}")
    print("[3] ANALISIS PER-TRADE C5 (sin portfolio constraints)")
    print(SUBLINE)
    analyze_per_trade(per_trade_df)

    # --- Portfolio simulation (full period) ---
    print(f"\n{SUBLINE}")
    print("[4] SIMULACION DE PORTFOLIO (3 slots, periodo completo)")
    print(SUBLINE)

    policies = ["BASE", "HEALTH_BLOCK", "SECTOR_WEIGHT", "PANIC_UNLOCK", "D7_FIXED"]
    full_results: dict[str, dict[str, Any]] = {}

    for policy in policies:
        pending = pending_d7 if policy == "D7_FIXED" else pending_base
        result = simulate_portfolio(prepared, dates, pending, policy)
        full_results[policy] = result
        m = result["metrics"]
        print(f"  {policy:<18} | Sharpe {m['sharpe']:>6.3f} | WR {m['wr']:>5.1f}% | "
              f"avg {m['avg_trade']:>+6.2f}% | MDD {m['mdd']:>7.1f}% | "
              f"trades {m['trades']:>4.0f} | total {m['total']:>+7.1f}%")

    # --- Compare sector composition of trades ---
    print(f"\n{SUBLINE}")
    print("[4b] COMPOSICION SECTORIAL TRADES CERRADOS (BASE vs SECTOR_WEIGHT)")
    print(SUBLINE)
    for policy in ["BASE", "SECTOR_WEIGHT", "PANIC_UNLOCK"]:
        trades_df = full_results[policy]["trades_df"]
        if trades_df.empty:
            continue
        c5 = trades_df[trades_df["signal"] == "C"] if "signal" in trades_df.columns else pd.DataFrame()
        if c5.empty:
            continue
        n = len(c5)
        print(f"\n  Policy: {policy} (C5 trades={n})")
        for sector in sorted(c5["sector"].unique()):
            rows = c5[c5["sector"] == sector]
            wr = float((rows["return_pct"] > 0).mean() * 100)
            avg = float(rows["return_pct"].mean())
            print(f"    {sector:<14} N={len(rows):>4}  WR={wr:>5.1f}%  avg={avg:>+6.2f}%")

    # --- Walk-forward ---
    print(f"\n{SUBLINE}")
    print("[5] WALK-FORWARD (7 ventanas)")
    print(SUBLINE)

    wf_result = walk_forward(prepared, dates, pending_base, pending_d7, windows=7)
    wf_wins = wf_result["wins"]

    header = f"  {'W':<4} {'Start':<12} {'End':<12}"
    for p in ["BASE", "HEALTH_BLOCK", "SECTOR_WEIGHT", "PANIC_UNLOCK", "D7_FIXED"]:
        header += f" {p[:10]:>12}"
    print(header)
    print(f"  {'-'*85}")
    for row in wf_result["details"]:
        line = f"  {row['window']:<4} {row['start']:<12} {row['end']:<12}"
        base_sh = row["BASE"]
        for p in ["BASE", "HEALTH_BLOCK", "SECTOR_WEIGHT", "PANIC_UNLOCK", "D7_FIXED"]:
            sh = row[p]
            marker = "*" if p != "BASE" and sh > base_sh else " "
            line += f" {sh:>+11.3f}{marker}"
        print(line)

    print(f"\n  Ventanas ganadas vs BASE:")
    for p, wins in wf_wins.items():
        print(f"    {p:<20}: {wins}/{wf_result['windows']}")

    # --- Find best policy ---
    base_metrics = full_results["BASE"]["metrics"]
    best_policy = max(
        [p for p in policies if p != "BASE"],
        key=lambda p: float(full_results[p]["metrics"]["sharpe"])
    )
    best_metrics = full_results[best_policy]["metrics"]

    print(f"\n  Mejor variante (por Sharpe): {best_policy}")
    bm = base_metrics
    pm = best_metrics
    print(f"  BASE:          Sharpe={bm['sharpe']:.3f}  WR={bm['wr']:.1f}%  MDD={bm['mdd']:.1f}%  trades={bm['trades']:.0f}")
    print(f"  {best_policy:<14} Sharpe={pm['sharpe']:.3f}  WR={pm['wr']:.1f}%  MDD={pm['mdd']:.1f}%  trades={pm['trades']:.0f}")

    # Delta vs base
    delta_sharpe = pm["sharpe"] - bm["sharpe"]
    delta_mdd = pm["mdd"] - bm["mdd"]
    delta_wr = pm["wr"] - bm["wr"]
    print(f"  Delta:         Sharpe={delta_sharpe:+.3f}  WR={delta_wr:+.1f}pp  MDD={delta_mdd:+.1f}pp")

    # --- Promotion gates ---
    print(f"\n{SUBLINE}")
    print("[6] PROMOTION GATES")
    print(SUBLINE)

    passes, gates = evaluate_promotion_gates(
        base_metrics, best_policy, best_metrics, wf_wins, wf_result["windows"], per_trade_df
    )
    for g in gates:
        print(f"  {g}")

    print(f"\n  {'-'*60}")
    print(f"  PASSES: {passes}/7")
    if passes >= 5:
        verdict = "PROMOVER"
    elif passes == 4:
        verdict = "CONDICIONAL"
    else:
        verdict = "RECHAZAR"
    print(f"\n  VEREDICTO: {verdict}")

    # --- Executive summary ---
    print(f"\n{LINE}")
    print("  RESUMEN EJECUTIVO V19")
    print(LINE)
    print(f"  V11 base (reproducido) : Sharpe={bm['sharpe']:.3f} | WR={bm['wr']:.1f}% | MDD={bm['mdd']:.1f}%")
    print(f"  Mejor variante ({best_policy}): Sharpe={pm['sharpe']:.3f} | WR={pm['wr']:.1f}% | MDD={pm['mdd']:.1f}%")
    print(f"  WF gana: {wf_wins[best_policy]}/{wf_result['windows']} ventanas")
    print(f"  Gates:   {passes}/7 -> {verdict}")
    print()
    print("  Hallazgos clave:")

    if not per_trade_df.empty:
        base_pt = per_trade_df[per_trade_df["passes_base"]]
        for sector in ["semis", "tech", "health", "finance", "consumer"]:
            rows = base_pt[base_pt["sector"] == sector]
            if len(rows) >= 5:
                wr = float((rows["return_pct"] > 0).mean() * 100)
                avg = float(rows["return_pct"].mean())
                print(f"  - C5 sector {sector:<12}: N={len(rows):>3}  WR={wr:>5.1f}%  avg={avg:>+6.2f}%")

        for label, flag in [("PANIC", True), ("NORMAL", False)]:
            rows = base_pt[base_pt["is_panic"] == flag]
            if len(rows) >= 5:
                wr = float((rows["return_pct"] > 0).mean() * 100)
                avg = float(rows["return_pct"].mean())
                print(f"  - C5 {label:<16}: N={len(rows):>3}  WR={wr:>5.1f}%  avg={avg:>+6.2f}%")

    print()
    print("  Recomendacion para V11:")
    if verdict == "PROMOVER":
        print(f"  -> Implementar {best_policy} en invertir_v11.py")
        print("  -> Agregar PANIC display cuando SPY ROC20 < -10%")
        print("  -> Bloquear sector health de Signal C5")
        if "SECTOR_WEIGHT" in best_policy or best_policy == "PANIC_UNLOCK":
            print("  -> Agregar sector bonus al priority ranking")
    elif verdict == "CONDICIONAL":
        print(f"  -> Revisar {best_policy}: evidencia insuficiente para promocion plena")
        print("  -> Solo implementar HEALTH_BLOCK (evidencia mas solida)")
    else:
        print("  -> No implementar cambios basados en sector. Evidencia insuficiente.")
        print("  -> Revisar si el sector effect persiste en OOS data")
    print(LINE)


if __name__ == "__main__":
    main()
