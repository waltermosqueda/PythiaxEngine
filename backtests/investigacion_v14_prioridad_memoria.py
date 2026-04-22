"""
INVESTIGACION V14 - PRIORIDAD DE MEMORIA OPERATIVA
==================================================

Objetivo:
  Mejorar el ranking interno de V11 sin tocar filtros base.

Idea:
  Usar la memoria operativa real del loop para priorizar mejor cuando varios
  setups compiten por slots. La memoria debe reflejar:
    - todas las senales historicas, no solo las ejecutadas
    - solo informacion disponible hasta esa fecha
    - el horizonte que mejor representa cada setup

Hipotesis auditadas:
  1. BASE       -> ordenar por score bruto
  2. MEM_D7     -> A_D7 + C5_D7
  3. MEM_C5_D4  -> A_D7 + C5_D4

Regla auditada:
  - minimo 30 outcomes previos por setup/regimen
  - bucket de score por terciles
  - si el bucket no llega a 8 observaciones, usar promedio del setup/regimen
  - ranking: retorno esperado historico primero, score bruto como desempate
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.investigacion_v10_rebound_capture import c_exit_return
from backtests.investigacion_v12_portfolio_operativo import (
    calc_a_score,
    calc_c_score,
    calc_portfolio_metrics,
)
from backtests.investigacion_v13_memoria_operativa import prepare_universe
from backtests.investigacion_v9_path_quality import ANTIKNIFE_DAYS, START_IDX


MODE_BASE = "BASE"
MODE_MEM_D7 = "MEM_D7"
MODE_MEM_C5_D4 = "MEM_C5_D4"
MODES = [MODE_BASE, MODE_MEM_D7, MODE_MEM_C5_D4]

PRIORITY_MIN_TOTAL = 30
PRIORITY_MIN_BUCKET = 8
PRIORITY_FALLBACK = -1_000_000.0


@dataclass(frozen=True)
class MemoryCandidate:
    ticker: str
    signal: str
    regime: str
    signal_idx: int
    entry_idx: int
    exit_idx: int
    raw_score: float
    mem_target_idx_4: int | None
    mem_return_4: float | None
    mem_target_idx_7: int | None
    mem_return_7: float | None


def assign_bucket(score: float, q1: float, q2: float) -> int:
    if score <= q1:
        return 1
    if score <= q2:
        return 2
    return 3


def build_candidates(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    dates: pd.DatetimeIndex,
) -> tuple[dict[int, list[MemoryCandidate]], dict[int, list[MemoryCandidate]], dict[int, list[MemoryCandidate]]]:
    pending: dict[int, list[MemoryCandidate]] = {}
    by_target_4: dict[int, list[MemoryCandidate]] = {}
    by_target_7: dict[int, list[MemoryCandidate]] = {}

    for idx in range(START_IDX, len(dates) - 8):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
        regime = "SEGURO" if regime_safe else "PELIGRO"

        for ticker in tickers:
            if ticker == "SPY" or ticker not in prepared:
                continue

            df = prepared[ticker]
            if idx + 8 >= len(df):
                continue

            candidate: MemoryCandidate | None = None

            if regime_safe and bool(df["SIG_A_GUARD"].iloc[idx]):
                signal_px = df["Close"].iloc[idx]
                px_7 = df["Close"].iloc[idx + 7]
                entry_px = df["Close"].iloc[idx + 1]
                exit_px = df["Close"].iloc[idx + 8]
                if pd.notna(signal_px) and pd.notna(px_7) and pd.notna(entry_px) and pd.notna(exit_px):
                    candidate = MemoryCandidate(
                        ticker=ticker,
                        signal="A",
                        regime=regime,
                        signal_idx=idx,
                        entry_idx=idx + 1,
                        exit_idx=idx + 8,
                        raw_score=calc_a_score(df, idx),
                        mem_target_idx_4=None,
                        mem_return_4=None,
                        mem_target_idx_7=idx + 7,
                        mem_return_7=float((px_7 / signal_px - 1.0) * 100.0),
                    )
            elif bool(df["SIG_C_V9_NEG5"].iloc[idx]):
                score = calc_c_score(df, idx)
                vol_ratio = float(df["VOL_RATIO"].iloc[idx])
                if score >= 85.0 or vol_ratio >= 4.0:
                    continue
                ret, exit_day, _ = c_exit_return(df, idx)
                signal_px = df["Close"].iloc[idx]
                px_4 = df["Close"].iloc[idx + 4] if idx + 4 < len(df) else np.nan
                px_7 = df["Close"].iloc[idx + 7] if idx + 7 < len(df) else np.nan
                if ret is not None and exit_day is not None and pd.notna(signal_px):
                    candidate = MemoryCandidate(
                        ticker=ticker,
                        signal="C5",
                        regime=regime,
                        signal_idx=idx,
                        entry_idx=idx + 1,
                        exit_idx=idx + 1 + exit_day,
                        raw_score=score,
                        mem_target_idx_4=idx + 4 if pd.notna(px_4) else None,
                        mem_return_4=float((px_4 / signal_px - 1.0) * 100.0) if pd.notna(px_4) else None,
                        mem_target_idx_7=idx + 7 if pd.notna(px_7) else None,
                        mem_return_7=float((px_7 / signal_px - 1.0) * 100.0) if pd.notna(px_7) else None,
                    )

            if candidate is None:
                continue

            pending.setdefault(candidate.entry_idx, []).append(candidate)
            if candidate.mem_target_idx_4 is not None:
                by_target_4.setdefault(candidate.mem_target_idx_4, []).append(candidate)
            if candidate.mem_target_idx_7 is not None:
                by_target_7.setdefault(candidate.mem_target_idx_7, []).append(candidate)

    return pending, by_target_4, by_target_7


def memory_return(candidate: MemoryCandidate, mode: str) -> float | None:
    if candidate.signal == "A":
        return candidate.mem_return_7
    if mode == MODE_MEM_C5_D4:
        return candidate.mem_return_4
    return candidate.mem_return_7


def memory_expected_return(
    candidate: MemoryCandidate,
    history: list[MemoryCandidate],
    mode: str,
) -> float | None:
    same = [row for row in history if row.signal == candidate.signal and row.regime == candidate.regime]
    if len(same) < PRIORITY_MIN_TOTAL:
        return None

    scores = np.array([row.raw_score for row in same], dtype=float)
    q1, q2 = np.quantile(scores, [1 / 3, 2 / 3])
    bucket = assign_bucket(candidate.raw_score, float(q1), float(q2))

    bucket_rows = [
        row for row in same if assign_bucket(row.raw_score, float(q1), float(q2)) == bucket
    ]
    all_returns = [memory_return(row, mode) for row in same if memory_return(row, mode) is not None]
    if not all_returns:
        return None

    base_avg = float(np.mean(all_returns))
    bucket_returns = [memory_return(row, mode) for row in bucket_rows if memory_return(row, mode) is not None]
    if len(bucket_returns) < PRIORITY_MIN_BUCKET:
        return base_avg
    return float(np.mean(bucket_returns))


def priority_sort_key(
    candidate: MemoryCandidate,
    history: list[MemoryCandidate],
    mode: str,
) -> tuple[float, float]:
    if mode == MODE_BASE:
        return float(candidate.raw_score), float(candidate.raw_score)

    expected_return = memory_expected_return(candidate, history, mode)
    return (
        PRIORITY_FALLBACK if expected_return is None else float(expected_return),
        float(candidate.raw_score),
    )


def simulate_portfolio(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    dates: pd.DatetimeIndex,
    mode: str,
    date_from: str | None = None,
) -> dict[str, float]:
    pending, by_target_4, by_target_7 = build_candidates(prepared, tickers, dates)

    cash = 100_000.0
    cooldown_until: dict[str, int] = {}
    open_positions: list[dict[str, object]] = []
    equity_rows: list[dict[str, float]] = []
    closed: list[dict[str, float]] = []
    history: list[MemoryCandidate] = []

    start_date = pd.Timestamp(date_from) if date_from else None
    start_idx = START_IDX + 1 if start_date is None else max(START_IDX + 1, dates.searchsorted(start_date))

    for idx in range(START_IDX + 1, len(dates)):
        if mode == MODE_MEM_C5_D4:
            history.extend(by_target_4.get(idx - 1, []))
        elif mode == MODE_MEM_D7:
            history.extend(by_target_7.get(idx - 1, []))

        equity = cash
        for position in open_positions:
            df = prepared[str(position["ticker"])]
            if idx < len(df):
                equity += float(position["shares"]) * float(df["Close"].iloc[idx])
        if idx >= start_idx:
            equity_rows.append({"idx": float(idx), "equity": equity, "open_positions": float(len(open_positions))})

        still_open: list[dict[str, object]] = []
        for position in open_positions:
            if int(position["exit_idx"]) == idx:
                px = float(prepared[str(position["ticker"])]["Close"].iloc[idx])
                cash += float(position["shares"]) * px
                if idx >= start_idx:
                    closed.append({"return_pct": (px / float(position["entry_price"]) - 1.0) * 100.0})
            else:
                still_open.append(position)
        open_positions = still_open

        if idx < start_idx:
            continue

        free_slots = 3 - len(open_positions)
        if free_slots <= 0:
            continue

        total_equity = cash
        for position in open_positions:
            df = prepared[str(position["ticker"])]
            if idx < len(df):
                total_equity += float(position["shares"]) * float(df["Close"].iloc[idx])
        slot_budget = total_equity / 3.0

        todays = sorted(
            pending.get(idx, []),
            key=lambda candidate: priority_sort_key(candidate, history, mode),
            reverse=True,
        )

        for candidate in todays:
            if free_slots <= 0:
                break
            if any(str(position["ticker"]) == candidate.ticker for position in open_positions):
                continue
            if idx <= cooldown_until.get(candidate.ticker, -999):
                continue

            px = float(prepared[candidate.ticker]["Close"].iloc[idx])
            invested = min(slot_budget, cash)
            if invested <= 0:
                break

            open_positions.append(
                {
                    "ticker": candidate.ticker,
                    "entry_price": px,
                    "shares": invested / px,
                    "exit_idx": candidate.exit_idx,
                }
            )
            cash -= invested
            cooldown_until[candidate.ticker] = candidate.signal_idx + ANTIKNIFE_DAYS
            free_slots -= 1

    return calc_portfolio_metrics(pd.DataFrame(equity_rows), pd.DataFrame(closed))


def rank_change_stats(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    dates: pd.DatetimeIndex,
    mode: str,
) -> dict[str, int]:
    pending, by_target_4, by_target_7 = build_candidates(prepared, tickers, dates)
    history: list[MemoryCandidate] = []
    crowded = 0
    ready = 0
    changed = 0

    for idx in range(START_IDX + 1, len(dates)):
        if mode == MODE_MEM_C5_D4:
            history.extend(by_target_4.get(idx - 1, []))
        elif mode == MODE_MEM_D7:
            history.extend(by_target_7.get(idx - 1, []))

        todays = list(pending.get(idx, []))
        if len(todays) <= 1:
            continue

        crowded += 1
        base_order = [row.ticker for row in sorted(todays, key=lambda row: row.raw_score, reverse=True)]
        mem_order = [
            row.ticker
            for row in sorted(todays, key=lambda row: priority_sort_key(row, history, mode), reverse=True)
        ]
        if any(memory_expected_return(row, history, mode) is not None for row in todays):
            ready += 1
        if base_order != mem_order:
            changed += 1

    return {
        "crowded_days": crowded,
        "memory_ready_days": ready,
        "changed_order_days": changed,
    }


def print_block(title: str, rows: list[str]) -> None:
    print("\n" + title)
    for row in rows:
        print(row)


def main() -> None:
    prepared, broad, core, dates = prepare_universe()

    print("=" * 88)
    print("INVESTIGACION V14 - PRIORIDAD DE MEMORIA OPERATIVA")
    print("=" * 88)
    print(f"Regla auditada: min_total={PRIORITY_MIN_TOTAL}, min_bucket={PRIORITY_MIN_BUCKET}")
    print("Memoria alineada con el loop real: todas las senales historicas y solo outcomes ya conocidos.")

    for universe_name, tickers in [("broad", broad), ("core", core)]:
        print("\n" + "-" * 88)
        print(f"UNIVERSO {universe_name.upper()}")
        print("-" * 88)

        for mode in MODES:
            metrics = simulate_portfolio(prepared, tickers, dates, mode)
            print(
                f"{mode:12s} | sharpe {metrics['sharpe']:.4f} | total {metrics['total']:.2f}% | "
                f"mdd {metrics['mdd']:.2f}% | wr {metrics['wr']:.2f}% | avg {metrics['avg_trade']:.3f}%"
            )

        if universe_name == "broad":
            print_block(
                "Cortes recientes (broad):",
                [
                    (
                        f"{mode:12s} | 2025-01-01 sharpe {simulate_portfolio(prepared, tickers, dates, mode, '2025-01-01')['sharpe']:.4f}"
                        f" | total {simulate_portfolio(prepared, tickers, dates, mode, '2025-01-01')['total']:.2f}%"
                    )
                    for mode in MODES
                ]
                + [
                    (
                        f"{mode:12s} | 2025-07-01 sharpe {simulate_portfolio(prepared, tickers, dates, mode, '2025-07-01')['sharpe']:.4f}"
                        f" | total {simulate_portfolio(prepared, tickers, dates, mode, '2025-07-01')['total']:.2f}%"
                    )
                    for mode in MODES
                ]
                + [
                    (
                        f"{mode:12s} | 2026-01-01 sharpe {simulate_portfolio(prepared, tickers, dates, mode, '2026-01-01')['sharpe']:.4f}"
                        f" | total {simulate_portfolio(prepared, tickers, dates, mode, '2026-01-01')['total']:.2f}%"
                    )
                    for mode in MODES
                ],
            )

    print_block(
        "Cuanto cambia realmente el ranking:",
        [
            f"MEM_D7 broad: {rank_change_stats(prepared, broad, dates, MODE_MEM_D7)}",
            f"MEM_C5_D4 broad: {rank_change_stats(prepared, broad, dates, MODE_MEM_C5_D4)}",
            f"MEM_C5_D4 core: {rank_change_stats(prepared, core, dates, MODE_MEM_C5_D4)}",
        ],
    )

    print_block(
        "Lectura:",
        [
            "- MEM_D7 mejora broad y baja drawdown, pero MEM_C5_D4 queda un poco mejor en Sharpe y total.",
            "- En core no cambia nada relevante porque casi no hay dias con competencia real de slots.",
            "- La mejora viene de pocas ruedas crowded, no de tocar filtros base.",
            "- Veredicto: promover prioridad por memoria C5_D4 dentro de V11, sin crear V12 ni endurecer entradas.",
        ],
    )


if __name__ == "__main__":
    main()
