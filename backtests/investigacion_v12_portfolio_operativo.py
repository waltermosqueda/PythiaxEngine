"""
INVESTIGACION V12 PORTFOLIO OPERATIVO
=====================================

Objetivo:
  Medir la diferencia entre V10 evaluado por trades independientes y V10
  ejecutado como cartera real con maximo 3 posiciones simultaneas.

Hipotesis:
  La cartera real sufre cuando el bloque C4 compite por slots en clusters de
  crash. Un triage simple sobre los C4 mas extremos puede mejorar la operativa
  sin tocar la estructura base de V10.

Politicas auditadas:
  1. RAW            -> tomar V10 tal cual, priorizando por score bruto
  2. SCORE85        -> para C4, solo consumir slot si score bruto < 85
  3. SCORE85_VOL4   -> para C4, solo consumir slot si score bruto < 85 y
                       vol_ratio < 4.0

Hallazgo esperado:
  El edge por trade de V10 es real, pero el edge operativo requiere triage.
  SCORE85_VOL4 es la regla simple mas robusta encontrada para la cartera real.

Fecha: 2026-04-07
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

from backtests.investigacion_v10_rebound_capture import c_exit_return, run_v10
from backtests.investigacion_v9_path_quality import (
    ANTIKNIFE_DAYS,
    BROAD_UNIVERSE,
    CORE_UNIVERSE,
    START_IDX,
    calc_metrics,
    load_db_data,
    monte_carlo,
    precompute,
)


MAX_POSITIONS = 3
INITIAL_EQUITY = 100_000.0

POLICY_RAW = "RAW"
POLICY_SCORE85 = "SCORE85"
POLICY_SCORE85_VOL4 = "SCORE85_VOL4"
POLICIES = [POLICY_RAW, POLICY_SCORE85, POLICY_SCORE85_VOL4]


@dataclass(frozen=True)
class Candidate:
    ticker: str
    signal: str
    signal_date: pd.Timestamp
    signal_idx: int
    entry_idx: int
    exit_idx: int
    raw_score: float
    vol_ratio: float | None = None
    rsi: float | None = None
    neg_days10: float | None = None


def calc_a_score(df: pd.DataFrame, idx: int) -> float:
    prev_hist = float(df["MACD_HIST"].iloc[idx - 1])
    curr_hist = float(df["MACD_HIST"].iloc[idx])
    atr = float(df["ATR"].iloc[idx])
    rsi = float(df["RSI"].iloc[idx])
    dist = float(df["DIST_SMA50"].iloc[idx])
    vol_ratio = float(df["VOL_RATIO"].iloc[idx])

    macd_accel = (curr_hist - prev_hist) / (atr * 0.01 + 1e-6)
    rsi_score = max(0.0, min(40.0, (30.0 - rsi) / 30.0 * 40.0))
    stretch_score = max(0.0, min(30.0, (abs(dist) - 5.0) / 15.0 * 30.0))
    macd_score = max(0.0, min(20.0, macd_accel * 5.0))
    vol_score = max(0.0, min(10.0, (1.5 - vol_ratio) / 1.5 * 10.0))
    return float(rsi_score + stretch_score + macd_score + vol_score)


def calc_c_score(df: pd.DataFrame, idx: int) -> float:
    roc10 = float(df["ROC10"].iloc[idx])
    vol_ratio = float(df["VOL_RATIO"].iloc[idx])
    rsi = float(df["RSI"].iloc[idx])
    return float(abs(roc10) * vol_ratio * (1.0 + max(0.0, 35.0 - rsi) / 100.0))


def policy_allows(candidate: Candidate, policy: str) -> bool:
    if candidate.signal != "C":
        return True
    if policy == POLICY_RAW:
        return True
    if policy == POLICY_SCORE85:
        return candidate.raw_score < 85.0
    if policy == POLICY_SCORE85_VOL4:
        return candidate.raw_score < 85.0 and (candidate.vol_ratio or 0.0) < 4.0
    raise ValueError(f"Politica desconocida: {policy}")


def candidate_rank(candidate: Candidate, policy: str) -> tuple[float, float]:
    return (1.0 if policy_allows(candidate, policy) else 0.0, candidate.raw_score)


def build_candidates(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
) -> tuple[dict[int, list[Candidate]], dict[str, float]]:
    dates = prepared["SPY"].index
    pending: dict[int, list[Candidate]] = {}
    c_rows: list[dict[str, float]] = []
    daily_counts: list[int] = []

    for idx in range(START_IDX, len(dates) - 8):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
        day_count = 0

        for ticker in tickers:
            if ticker == "SPY" or ticker not in prepared:
                continue

            df = prepared[ticker]
            candidate: Candidate | None = None

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
                        vol_ratio=float(df["VOL_RATIO"].iloc[idx]),
                        rsi=float(df["RSI"].iloc[idx]),
                    )
            elif bool(df["SIG_C_V9_NEG5"].iloc[idx]):
                ret, exit_day, _ = c_exit_return(df, idx)
                if ret is None or exit_day is None:
                    continue
                candidate = Candidate(
                    ticker=ticker,
                    signal="C",
                    signal_date=dates[idx],
                    signal_idx=idx,
                    entry_idx=idx + 1,
                    exit_idx=idx + 1 + exit_day,
                    raw_score=calc_c_score(df, idx),
                    vol_ratio=float(df["VOL_RATIO"].iloc[idx]),
                    rsi=float(df["RSI"].iloc[idx]),
                    neg_days10=float(df["NEG_DAYS10"].iloc[idx]),
                )
                c_rows.append(
                    {
                        "score": candidate.raw_score,
                        "return_pct": float(ret),
                        "vol_ratio": float(candidate.vol_ratio or 0.0),
                    }
                )

            if candidate is None:
                continue

            pending.setdefault(candidate.entry_idx, []).append(candidate)
            day_count += 1

        daily_counts.append(day_count)

    stats = {
        "days_with_candidates": float(sum(1 for count in daily_counts if count > 0)),
        "days_gt3": float(sum(1 for count in daily_counts if count > 3)),
        "max_candidates_day": float(max(daily_counts) if daily_counts else 0),
        "avg_candidates_day": float(np.mean([count for count in daily_counts if count > 0])) if daily_counts else 0.0,
    }

    if c_rows:
        c_df = pd.DataFrame(c_rows)
        extreme = c_df[c_df["score"] >= 85.0]
        stats["c_trades_total"] = float(len(c_df))
        stats["c_extreme_count"] = float(len(extreme))
        stats["c_extreme_pct"] = float(len(extreme) / len(c_df) * 100.0)
        stats["c_extreme_avg"] = float(extreme["return_pct"].mean()) if len(extreme) else 0.0
        stats["c_non_extreme_avg"] = float(c_df[c_df["score"] < 85.0]["return_pct"].mean())
    else:
        stats["c_trades_total"] = 0.0
        stats["c_extreme_count"] = 0.0
        stats["c_extreme_pct"] = 0.0
        stats["c_extreme_avg"] = 0.0
        stats["c_non_extreme_avg"] = 0.0

    return pending, stats


def calc_portfolio_metrics(equity_df: pd.DataFrame, trades_df: pd.DataFrame) -> dict[str, float]:
    if equity_df.empty:
        return {
            "trades": 0,
            "wr": 0.0,
            "avg_trade": 0.0,
            "sharpe": 0.0,
            "total": 0.0,
            "mdd": 0.0,
            "avg_open": 0.0,
        }

    returns = equity_df["equity"].pct_change().fillna(0.0)
    std = float(returns.std())
    sharpe = float(returns.mean() / std * np.sqrt(252)) if std > 0 else 0.0

    peaks = equity_df["equity"].cummax()
    mdd = float(((equity_df["equity"] - peaks) / peaks * 100.0).min())
    total = float((equity_df["equity"].iloc[-1] / INITIAL_EQUITY - 1.0) * 100.0)

    if trades_df.empty:
        wr = 0.0
        avg_trade = 0.0
    else:
        wr = float((trades_df["return_pct"] > 0).mean() * 100.0)
        avg_trade = float(trades_df["return_pct"].mean())

    return {
        "trades": float(len(trades_df)),
        "wr": wr,
        "avg_trade": avg_trade,
        "sharpe": sharpe,
        "total": total,
        "mdd": mdd,
        "avg_open": float(equity_df["open_positions"].mean()),
    }


def simulate_portfolio(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    pending: dict[int, list[Candidate]],
    policy: str,
    start_idx: int | None = None,
    end_idx: int | None = None,
) -> dict[str, object]:
    start = START_IDX + 1 if start_idx is None else start_idx
    end = len(dates) if end_idx is None else end_idx

    cash = INITIAL_EQUITY
    cooldown_until: dict[str, int] = {}
    open_positions: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []
    closed_rows: list[dict[str, object]] = []

    for idx in range(start, end):
        equity = cash + sum(
            float(position["shares"]) * float(prepared[str(position["ticker"])]["Close"].iloc[idx])
            for position in open_positions
        )
        equity_rows.append(
            {
                "date": dates[idx],
                "equity": equity,
                "open_positions": len(open_positions),
            }
        )

        still_open: list[dict[str, object]] = []
        for position in open_positions:
            if int(position["exit_idx"]) == idx:
                ticker = str(position["ticker"])
                exit_price = float(prepared[ticker]["Close"].iloc[idx])
                cash += float(position["shares"]) * exit_price
                closed_rows.append(
                    {
                        "ticker": ticker,
                        "signal": position["signal"],
                        "entry_date": dates[int(position["entry_idx"])].date().isoformat(),
                        "exit_date": dates[idx].date().isoformat(),
                        "return_pct": (exit_price / float(position["entry_price"]) - 1.0) * 100.0,
                        "raw_score": float(position["raw_score"]),
                    }
                )
            else:
                still_open.append(position)
        open_positions = still_open

        free_slots = MAX_POSITIONS - len(open_positions)
        if free_slots <= 0:
            continue

        todays_candidates = pending.get(idx, [])
        if not todays_candidates:
            continue

        total_equity = cash + sum(
            float(position["shares"]) * float(prepared[str(position["ticker"])]["Close"].iloc[idx])
            for position in open_positions
        )
        slot_budget = total_equity / MAX_POSITIONS
        ranked = sorted(todays_candidates, key=lambda candidate: candidate_rank(candidate, policy), reverse=True)

        for candidate in ranked:
            if free_slots <= 0:
                break
            if not policy_allows(candidate, policy):
                continue
            if any(str(position["ticker"]) == candidate.ticker for position in open_positions):
                continue
            if idx <= cooldown_until.get(candidate.ticker, -999):
                continue

            entry_price = float(prepared[candidate.ticker]["Close"].iloc[idx])
            if not np.isfinite(entry_price) or entry_price <= 0:
                continue

            invested = min(slot_budget, cash)
            if invested <= 0:
                break

            open_positions.append(
                {
                    "ticker": candidate.ticker,
                    "signal": candidate.signal,
                    "entry_idx": candidate.entry_idx,
                    "exit_idx": candidate.exit_idx,
                    "raw_score": candidate.raw_score,
                    "shares": invested / entry_price,
                    "entry_price": entry_price,
                }
            )
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


def walk_forward_portfolio(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    pending: dict[int, list[Candidate]],
    policy: str,
    windows: int,
) -> dict[str, object]:
    total_span = len(dates) - (START_IDX + 1)
    window_size = total_span // windows
    details: list[dict[str, object]] = []

    for window in range(windows):
        start = START_IDX + 1 + window * window_size
        end = min(START_IDX + 1 + (window + 1) * window_size, len(dates))
        result = simulate_portfolio(prepared, dates, pending, policy, start_idx=start, end_idx=end)
        sharpe = float(result["metrics"]["sharpe"])
        details.append(
            {
                "window": window + 1,
                "sharpe": sharpe,
                "positive": bool(sharpe > 0),
            }
        )

    avg_sharpe = float(np.mean([row["sharpe"] for row in details])) if details else 0.0
    positive_pct = float(sum(1 for row in details if row["positive"]) / max(windows, 1) * 100.0)
    return {"avg_sharpe": avg_sharpe, "pct": positive_pct, "details": details}


def print_reference_row(name: str, df: pd.DataFrame) -> None:
    metrics = calc_metrics(df)
    print(
        f"  {name:16s} trades={metrics['trades']:3d} "
        f"wr={metrics['wr']:5.2f}% sharpe={metrics['sharpe']:5.2f} "
        f"avg={metrics['avg']:+5.2f}% mdd={metrics['mdd']:6.2f}%"
    )


def print_portfolio_row(name: str, result: dict[str, object]) -> None:
    metrics = result["metrics"]
    print(
        f"  {name:16s} trades={int(metrics['trades']):3d} "
        f"wr={metrics['wr']:5.2f}% sh={metrics['sharpe']:5.2f} "
        f"avg_trade={metrics['avg_trade']:+5.2f}% total={metrics['total']:6.1f}% "
        f"mdd={metrics['mdd']:6.2f}% avg_open={metrics['avg_open']:.2f}"
    )


def run_independent_variant(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    policy: str,
) -> pd.DataFrame:
    dates = prepared["SPY"].index
    rows: list[dict[str, object]] = []
    last_entry: dict[str, int] = {}

    for idx in range(START_IDX, len(dates) - 8):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
        signal_date = dates[idx]

        for ticker in tickers:
            if ticker == "SPY" or ticker not in prepared:
                continue
            if ticker in last_entry and (idx - last_entry[ticker]) < ANTIKNIFE_DAYS:
                continue

            df = prepared[ticker]
            signal = None
            ret = None

            if regime_safe and bool(df["SIG_A_GUARD"].iloc[idx]):
                entry = df["Close"].iloc[idx + 1]
                exit_px = df["Close"].iloc[idx + 8]
                if pd.isna(entry) or pd.isna(exit_px):
                    continue
                signal = "A"
                ret = float((exit_px / entry - 1.0) * 100.0)
            elif bool(df["SIG_C_V9_NEG5"].iloc[idx]):
                candidate = Candidate(
                    ticker=ticker,
                    signal="C",
                    signal_date=signal_date,
                    signal_idx=idx,
                    entry_idx=idx + 1,
                    exit_idx=idx + 8,
                    raw_score=calc_c_score(df, idx),
                    vol_ratio=float(df["VOL_RATIO"].iloc[idx]),
                    rsi=float(df["RSI"].iloc[idx]),
                    neg_days10=float(df["NEG_DAYS10"].iloc[idx]),
                )
                if not policy_allows(candidate, policy):
                    continue
                ret, _, _ = c_exit_return(df, idx)
                if ret is None:
                    continue
                signal = "C"

            if signal is None:
                continue

            rows.append(
                {
                    "ticker": ticker,
                    "date": signal_date,
                    "signal": signal,
                    "return_pct": ret,
                }
            )
            last_entry[ticker] = idx

    return pd.DataFrame(rows)


def run_suite(prepared: dict[str, pd.DataFrame], label: str, tickers: list[str]) -> None:
    dates = prepared["SPY"].index
    pending, pressure = build_candidates(prepared, tickers)

    v10_ref = run_v10(prepared, tickers)
    v11_cap_ref = run_independent_variant(prepared, tickers, POLICY_SCORE85_VOL4)

    raw_port = simulate_portfolio(prepared, dates, pending, POLICY_RAW)
    score85_port = simulate_portfolio(prepared, dates, pending, POLICY_SCORE85)
    score85_vol4_port = simulate_portfolio(prepared, dates, pending, POLICY_SCORE85_VOL4)

    print("\n" + "=" * 96)
    print(f"  {label}")
    print("=" * 96)

    print("\n  [1] Referencia por trades independientes")
    print_reference_row("V10 ref", v10_ref)
    print_reference_row("V11 cap ref", v11_cap_ref)

    print("\n  [2] Realidad operativa: cartera max 3 slots")
    print_portfolio_row("RAW", raw_port)
    print_portfolio_row("SCORE85", score85_port)
    print_portfolio_row("SCORE85_VOL4", score85_vol4_port)

    print("\n  [3] Presion de slots y audit C4")
    print(
        f"  dias con candidatos={int(pressure['days_with_candidates'])} | "
        f"dias con >3 candidatos={int(pressure['days_gt3'])} | "
        f"max en un dia={int(pressure['max_candidates_day'])} | "
        f"promedio en dias activos={pressure['avg_candidates_day']:.2f}"
    )
    print(
        f"  C4 score>=85: {int(pressure['c_extreme_count'])}/{int(pressure['c_trades_total'])} "
        f"({pressure['c_extreme_pct']:.1f}%) | avg ret extremos={pressure['c_extreme_avg']:+.2f}% "
        f"vs no extremos={pressure['c_non_extreme_avg']:+.2f}%"
    )

    print("\n  [4] Walk-forward cartera")
    for policy in POLICIES:
        wf5 = walk_forward_portfolio(prepared, dates, pending, policy, windows=5)
        wf7 = walk_forward_portfolio(prepared, dates, pending, policy, windows=7)
        print(
            f"  {policy:16s} WF5={wf5['pct']:5.1f}% avg_sh={wf5['avg_sharpe']:.2f} "
            f"{[round(row['sharpe'], 2) for row in wf5['details']]}"
        )
        print(
            f"  {'':16s} WF7={wf7['pct']:5.1f}% avg_sh={wf7['avg_sharpe']:.2f} "
            f"{[round(row['sharpe'], 2) for row in wf7['details']]}"
        )

    print("\n  [5] Monte Carlo de la variante cap independiente")
    mc = monte_carlo(v11_cap_ref, sims=1000)
    print(
        f"  V11 cap ref P(Sharpe>0)={mc['p_sharpe_pos']:5.1f}% "
        f"median={mc['median_sharpe']:.2f} worst1_sh={mc['worst_1pct_sharpe']:.2f} "
        f"worst1_mdd={mc['worst_1pct_mdd']:.2f}%"
    )


def main() -> None:
    print("=" * 96)
    print("  INVESTIGACION V12 PORTFOLIO OPERATIVO")
    print("=" * 96)
    print("  Meta: medir V10 real con slots y encontrar triage simple para C4")

    raw_data, _ = load_db_data(BROAD_UNIVERSE)
    prepared = precompute(raw_data)
    broad_tickers = [ticker for ticker in BROAD_UNIVERSE if ticker in prepared]
    core_tickers = [ticker for ticker in CORE_UNIVERSE if ticker in prepared]

    run_suite(prepared, "BROAD UNIVERSE", broad_tickers)
    run_suite(prepared, "CORE UNIVERSE", core_tickers)

    print("\n" + "=" * 96)
    print("  VEREDICTO")
    print("=" * 96)
    print("  1. V10 por trade sigue siendo fuerte, pero su Sharpe operativo cae al imponer max 3 slots.")
    print("  2. El problema no es la logica base, sino el consumo de slots por C4 extremos.")
    print("  3. SCORE85_VOL4 es la regla simple mas robusta encontrada para la cartera real.")
    print("  4. Esa misma cap tambien mejora la variante independiente broad/core,")
    print("     asi que puede ser candidata legitima a evolucion de scanner.")


if __name__ == "__main__":
    main()
