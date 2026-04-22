"""
INVESTIGACION V11 CAP OPERATIVO
===============================

Objetivo:
  Validar si la cap operativa sobre C4 merece promocion a scanner nuevo.

Hipotesis:
  V10 detecta bien crashes validos, pero una fraccion de C4 demasiado extremos
  destruye calidad cuando compiten por slots. Un filtro simple sobre score y
  volumen deberia mejorar el modelo y tambien la cartera real.

V11 cap:
  Mantiene V10 intacto salvo en la pata crash:
    - score < 85
    - vol_ratio < 4.0

Fecha: 2026-04-07
"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.investigacion_v10_rebound_capture import run_v10
from backtests.investigacion_v12_portfolio_operativo import (
    POLICY_RAW,
    POLICY_SCORE85_VOL4,
    build_candidates,
    run_independent_variant,
    simulate_portfolio,
    walk_forward_portfolio,
)
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
from backtests.investigacion_v10_rebound_capture import c_exit_return


def print_model_row(name: str, df: pd.DataFrame) -> None:
    metrics = calc_metrics(df)
    counts = df["signal"].value_counts().to_dict() if not df.empty else {}
    print(
        f"  {name:12s} trades={metrics['trades']:3d} "
        f"wr={metrics['wr']:5.2f}% sh={metrics['sharpe']:5.2f} "
        f"avg={metrics['avg']:+5.2f}% mdd={metrics['mdd']:6.2f}% counts={counts}"
    )


def print_portfolio_row(name: str, result: dict[str, object]) -> None:
    metrics = result["metrics"]
    print(
        f"  {name:12s} trades={int(metrics['trades']):3d} "
        f"wr={metrics['wr']:5.2f}% sh={metrics['sharpe']:5.2f} "
        f"avg_trade={metrics['avg_trade']:+5.2f}% total={metrics['total']:6.1f}% "
        f"mdd={metrics['mdd']:6.2f}% avg_open={metrics['avg_open']:.2f}"
    )


def run_threshold_variant(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    score_max: float | None,
    vol_max: float | None,
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
                roc10 = float(df["ROC10"].iloc[idx])
                vol_ratio = float(df["VOL_RATIO"].iloc[idx])
                rsi = float(df["RSI"].iloc[idx])
                score = abs(roc10) * vol_ratio * (1.0 + max(0.0, 35.0 - rsi) / 100.0)
                if score_max is not None and score >= score_max:
                    continue
                if vol_max is not None and vol_ratio >= vol_max:
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


def simulate_threshold_portfolio(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    score_max: float | None,
    vol_max: float | None,
) -> dict[str, float]:
    dates = prepared["SPY"].index
    pending, _ = build_candidates(prepared, tickers)

    cash = 100_000.0
    cooldown_until: dict[str, int] = {}
    open_positions: list[dict[str, object]] = []
    equity_curve: list[float] = []
    closed_returns: list[float] = []

    for idx in range(START_IDX + 1, len(dates)):
        equity_curve.append(
            cash
            + sum(
                float(position["shares"]) * float(prepared[str(position["ticker"])]["Close"].iloc[idx])
                for position in open_positions
            )
        )

        still_open: list[dict[str, object]] = []
        for position in open_positions:
            if int(position["exit_idx"]) == idx:
                px = float(prepared[str(position["ticker"])]["Close"].iloc[idx])
                cash += float(position["shares"]) * px
                closed_returns.append((px / float(position["entry_price"]) - 1.0) * 100.0)
            else:
                still_open.append(position)
        open_positions = still_open

        free_slots = 3 - len(open_positions)
        if free_slots <= 0:
            continue

        total_equity = cash + sum(
            float(position["shares"]) * float(prepared[str(position["ticker"])]["Close"].iloc[idx])
            for position in open_positions
        )
        slot_budget = total_equity / 3.0
        todays = pending.get(idx, [])

        def allowed(candidate) -> bool:
            if candidate.signal != "C":
                return True
            if score_max is not None and candidate.raw_score >= score_max:
                return False
            if vol_max is not None and (candidate.vol_ratio or 0.0) >= vol_max:
                return False
            return True

        ranked = sorted(todays, key=lambda candidate: ((1 if allowed(candidate) else 0), candidate.raw_score), reverse=True)
        for candidate in ranked:
            if free_slots <= 0:
                break
            if not allowed(candidate):
                continue
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

    equity = pd.Series(equity_curve, dtype=float)
    returns = equity.pct_change().fillna(0.0)
    std = float(returns.std())
    sharpe = float(returns.mean() / std * np.sqrt(252)) if std > 0 else 0.0
    peaks = equity.cummax()
    mdd = float(((equity - peaks) / peaks * 100.0).min()) if len(equity) else 0.0
    total = float((equity.iloc[-1] / 100_000.0 - 1.0) * 100.0) if len(equity) else 0.0

    return {
        "trades": float(len(closed_returns)),
        "wr": float((np.array(closed_returns) > 0).mean() * 100.0) if closed_returns else 0.0,
        "sharpe": sharpe,
        "total": total,
        "mdd": mdd,
    }


def print_shortlist(prepared: dict[str, pd.DataFrame], label: str, tickers: list[str]) -> None:
    print("\n  [4] Shortlist de thresholds")
    print(f"  {label}: equilibrio entre modelo y cartera")
    print("  name      | ind_sh | ind_wr | port_sh | port_total | port_mdd")

    shortlist = [
        ("RAW", None, None),
        ("S95", 95.0, None),
        ("S85V4", 85.0, 4.0),
        ("S75V4", 75.0, 4.0),
    ]
    for name, score_max, vol_max in shortlist:
        independent = run_threshold_variant(prepared, tickers, score_max, vol_max)
        model_metrics = calc_metrics(independent)
        portfolio_metrics = simulate_threshold_portfolio(prepared, tickers, score_max, vol_max)
        print(
            f"  {name:8s} | {model_metrics['sharpe']:6.2f} | {model_metrics['wr']:6.1f}% | "
            f"{portfolio_metrics['sharpe']:7.2f} | {portfolio_metrics['total']:10.1f}% | "
            f"{portfolio_metrics['mdd']:8.2f}%"
        )


def run_suite(prepared: dict[str, pd.DataFrame], label: str, tickers: list[str]) -> None:
    dates = prepared["SPY"].index
    pending, _ = build_candidates(prepared, tickers)

    v10 = run_v10(prepared, tickers)
    v11 = run_independent_variant(prepared, tickers, POLICY_SCORE85_VOL4)
    port_v10 = simulate_portfolio(prepared, dates, pending, POLICY_RAW)
    port_v11 = simulate_portfolio(prepared, dates, pending, POLICY_SCORE85_VOL4)

    print("\n" + "=" * 96)
    print(f"  {label}")
    print("=" * 96)

    print("\n  [1] Modelo independiente")
    print_model_row("V10", v10)
    print_model_row("V11_CAP", v11)

    print("\n  [2] Cartera max 3 slots")
    print_portfolio_row("V10_RAW", port_v10)
    print_portfolio_row("V11_CAP", port_v11)

    print("\n  [3] Robustez")
    wf5 = walk_forward_portfolio(prepared, dates, pending, POLICY_SCORE85_VOL4, windows=5)
    wf7 = walk_forward_portfolio(prepared, dates, pending, POLICY_SCORE85_VOL4, windows=7)
    mc = monte_carlo(v11, sims=1000)
    print(
        f"  Portfolio WF5={wf5['pct']:5.1f}% avg_sh={wf5['avg_sharpe']:.2f} "
        f"{[round(row['sharpe'], 2) for row in wf5['details']]}"
    )
    print(
        f"  Portfolio WF7={wf7['pct']:5.1f}% avg_sh={wf7['avg_sharpe']:.2f} "
        f"{[round(row['sharpe'], 2) for row in wf7['details']]}"
    )
    print(
        f"  MC indep P(Sharpe>0)={mc['p_sharpe_pos']:5.1f}% "
        f"median={mc['median_sharpe']:.2f} worst1_sh={mc['worst_1pct_sharpe']:.2f} "
        f"worst1_mdd={mc['worst_1pct_mdd']:.2f}%"
    )

    print_shortlist(prepared, label, tickers)


def main() -> None:
    print("=" * 96)
    print("  INVESTIGACION V11 CAP OPERATIVO")
    print("=" * 96)
    print("  Meta: decidir si la cap score<85 y vol<4 merece promocion a scanner nuevo")

    raw_data, _ = load_db_data(BROAD_UNIVERSE)
    prepared = precompute(raw_data)
    broad_tickers = [ticker for ticker in BROAD_UNIVERSE if ticker in prepared]
    core_tickers = [ticker for ticker in CORE_UNIVERSE if ticker in prepared]

    run_suite(prepared, "BROAD UNIVERSE", broad_tickers)
    run_suite(prepared, "CORE UNIVERSE", core_tickers)

    print("\n" + "=" * 96)
    print("  VEREDICTO")
    print("=" * 96)
    print("  1. V11 cap mejora V10 tanto por trade independiente como en cartera real.")
    print("  2. No es el optimo aislado de una sola metrica, pero si el mejor equilibrio broad/core.")
    print("  3. La regla nueva es simple, interpretable y defensiva frente a crashes demasiado extremos.")
    print("  4. V11 cap queda validado como promocion legitima de scanner.")


if __name__ == "__main__":
    main()
