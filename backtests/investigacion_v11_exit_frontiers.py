"""
INVESTIGACION V11 EXIT FRONTIERS
================================

Objetivo:
  Intentar superar honestamente a V10 explorando overlays de salida sobre
  Signal A y variantes parciales sobre Signal C.

Pregunta:
  Existe un V11 claro, o V10 ya es la mejor frontera honesta encontrada?

Respuesta corta:
  V10 sigue ganando.
  Aparecen variantes marginales, pero ninguna supera de forma clara y
  consistente a V10 en broad + core + robustez.

Fecha: 2026-04-07
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.investigacion_v10_rebound_capture import run_v10, walk_forward_v10
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


def a_exit_return(df: pd.DataFrame, idx: int, mode: str) -> float | None:
    entry = df["Close"].iloc[idx + 1]
    exit_px = df["Close"].iloc[idx + 1 + 7]
    if pd.isna(entry) or pd.isna(exit_px):
        return None

    hold_ret = float((exit_px / entry - 1) * 100)

    if mode == "fixed7":
        return hold_ret

    if mode in {"full4_3d", "half4_3d"}:
        for day in range(1, 8):
            px = df["Close"].iloc[idx + 1 + day]
            if pd.isna(px):
                return None
            ret = float((px / entry - 1) * 100)
            if day <= 3 and ret >= 4.0:
                if mode == "full4_3d":
                    return ret
                return 0.5 * ret + 0.5 * hold_ret
        return hold_ret

    raise ValueError(f"Modo A desconocido: {mode}")


def c_exit_return(df: pd.DataFrame, idx: int, mode: str) -> float | None:
    entry = df["Close"].iloc[idx + 1]
    exit_px = df["Close"].iloc[idx + 1 + 7]
    if pd.isna(entry) or pd.isna(exit_px):
        return None

    hold_ret = float((exit_px / entry - 1) * 100)

    if mode == "full6_4d":
        for day in range(1, 8):
            px = df["Close"].iloc[idx + 1 + day]
            if pd.isna(px):
                return None
            ret = float((px / entry - 1) * 100)
            if day <= 4 and ret >= 6.0:
                return ret
        return hold_ret

    if mode == "half6_4d":
        for day in range(1, 8):
            px = df["Close"].iloc[idx + 1 + day]
            if pd.isna(px):
                return None
            ret = float((px / entry - 1) * 100)
            if day <= 4 and ret >= 6.0:
                return 0.5 * ret + 0.5 * hold_ret
        return hold_ret

    raise ValueError(f"Modo C desconocido: {mode}")


def run_variant(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    a_mode: str,
    c_mode: str,
    start_idx: int = START_IDX,
    antiknife_days: int = ANTIKNIFE_DAYS,
) -> pd.DataFrame:
    dates = prepared["SPY"].index
    rows: list[dict[str, object]] = []
    last_entry: dict[str, int] = {}

    for idx in range(start_idx, len(dates) - 8):
        regime_safe = bool(prepared["SPY"]["REGIME_SAFE"].iloc[idx])
        signal_date = dates[idx]

        for ticker in tickers:
            if ticker == "SPY" or ticker not in prepared:
                continue
            if ticker in last_entry and (idx - last_entry[ticker]) < antiknife_days:
                continue

            df = prepared[ticker]
            signal = None
            ret = None

            if regime_safe and bool(df["SIG_A_GUARD"].iloc[idx]):
                signal = "A"
                ret = a_exit_return(df, idx, a_mode)
            elif bool(df["SIG_C_V9_NEG5"].iloc[idx]):
                signal = "C"
                ret = c_exit_return(df, idx, c_mode)

            if signal is None or ret is None:
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


def walk_forward_variant(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
    a_mode: str,
    c_mode: str,
    windows: int,
) -> dict[str, object]:
    dates = prepared["SPY"].index
    total_span = len(dates) - START_IDX - 8
    window_size = total_span // windows
    details: list[dict[str, object]] = []

    for window in range(windows):
        start = START_IDX + window * window_size
        end = min(start + window_size, len(dates) - 8)
        df = run_variant(prepared, tickers, a_mode, c_mode, start_idx=start)
        df = df[(df["date"] >= dates[start]) & (df["date"] < dates[end])].copy()
        metrics = calc_metrics(df)
        details.append(
            {
                "window": window + 1,
                "trades": len(df),
                "sharpe": float(metrics["sharpe"]),
            }
        )

    avg_sharpe = float(np.mean([row["sharpe"] for row in details])) if details else 0.0
    positive = sum(1 for row in details if row["sharpe"] > 0)
    return {"pct": positive / max(windows, 1) * 100, "avg_sharpe": avg_sharpe, "details": details}


def print_result(name: str, df: pd.DataFrame) -> None:
    metrics = calc_metrics(df)
    mc = monte_carlo(df, sims=1000)
    print(
        f"  {name:12s} trades={metrics['trades']:3d} wr={metrics['wr']:5.2f}% "
        f"sh={metrics['sharpe']:5.2f} avg={metrics['avg']:+5.2f}% "
        f"mdd={metrics['mdd']:6.2f}% | MC worst1_sh={mc['worst_1pct_sharpe']:.2f}"
    )


def run_suite(prepared: dict[str, pd.DataFrame], label: str, tickers: list[str]) -> None:
    print("\n" + "=" * 96)
    print(f"  {label}")
    print("=" * 96)

    v10 = run_v10(prepared, tickers)
    v11_full_a = run_variant(prepared, tickers, a_mode="full4_3d", c_mode="full6_4d")
    v11_half_a = run_variant(prepared, tickers, a_mode="half4_3d", c_mode="full6_4d")
    v11_half_c = run_variant(prepared, tickers, a_mode="fixed7", c_mode="half6_4d")

    print("\n  [1] Model comparison")
    print_result("V10", v10)
    print_result("V11_FULL_A", v11_full_a)
    print_result("V11_HALF_A", v11_half_a)
    print_result("V11_HALF_C", v11_half_c)

    print("\n  [2] Walk-forward avg Sharpe")
    wf_v10_5 = walk_forward_v10(prepared, tickers, windows=5)
    wf_v10_7 = walk_forward_v10(prepared, tickers, windows=7)
    wf_v11_full_5 = walk_forward_variant(prepared, tickers, "full4_3d", "full6_4d", windows=5)
    wf_v11_full_7 = walk_forward_variant(prepared, tickers, "full4_3d", "full6_4d", windows=7)
    wf_v11_half_5 = walk_forward_variant(prepared, tickers, "half4_3d", "full6_4d", windows=5)
    wf_v11_half_7 = walk_forward_variant(prepared, tickers, "half4_3d", "full6_4d", windows=7)

    print(f"  V10       WF5={wf_v10_5['avg_sharpe']:.2f} | WF7={wf_v10_7['avg_sharpe']:.2f}")
    print(f"  V11_FULLA WF5={wf_v11_full_5['avg_sharpe']:.2f} | WF7={wf_v11_full_7['avg_sharpe']:.2f}")
    print(f"  V11_HALFA WF5={wf_v11_half_5['avg_sharpe']:.2f} | WF7={wf_v11_half_7['avg_sharpe']:.2f}")


def main() -> None:
    print("=" * 96)
    print("  INVESTIGACION V11 EXIT FRONTIERS")
    print("=" * 96)
    print("  Meta: intentar destronar a V10 con overlays adicionales de salida")

    raw_data, _ = load_db_data(BROAD_UNIVERSE)
    prepared = precompute(raw_data)
    broad_tickers = [ticker for ticker in BROAD_UNIVERSE if ticker in prepared]
    core_tickers = [ticker for ticker in CORE_UNIVERSE if ticker in prepared]

    run_suite(prepared, "BROAD UNIVERSE", broad_tickers)
    run_suite(prepared, "CORE UNIVERSE", core_tickers)

    print("\n" + "=" * 96)
    print("  VEREDICTO")
    print("=" * 96)
    print("  1. Los overlays extras sobre Signal A mejoran muy poco y no baten a V10 con claridad.")
    print("  2. Los overlays parciales sobre Signal C quedan por debajo del exit total de V10.")
    print("  3. V10 sigue siendo la mejor frontera honesta: mejora grande, simple y consistente.")
    print("  4. No aparece un V11 claramente superior sin entrar en zona de sobreajuste.")


if __name__ == "__main__":
    main()
