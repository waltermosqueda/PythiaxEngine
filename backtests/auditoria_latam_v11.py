"""
AUDITORIA LATAM V10/V11
=======================

Objetivo:
  Validar si la exclusion de LatAm fue una conclusion robusta del proyecto o
  solo una intuicion vieja que ya no aplica al modelo actual.

Que prueba:
  1. V10 y V11 en el universo base actual (sin LatAm)
  2. V10 y V11 reintroduciendo LatAm estricto por sector
  3. V10 y V11 reintroduciendo el basket "LatAm legado" usado en V5
  4. Basket-only para ver si LatAm aporta edge propio o si solo contamina

Fecha: 2026-04-08
"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.investigacion_v9_path_quality import (
    BROAD_UNIVERSE,
    calc_metrics,
    load_db_data,
    monte_carlo,
    precompute,
)
from backtests.investigacion_v10_rebound_capture import run_v10
from backtests.investigacion_v12_portfolio_operativo import (
    POLICY_RAW,
    POLICY_SCORE85_VOL4,
    build_candidates,
    run_independent_variant,
    simulate_portfolio,
    walk_forward_portfolio,
)
from titan_system.core.data_loader import SECTOR_MAP


STRICT_LATAM = sorted(SECTOR_MAP["latam"])
LEGACY_LATAM = ["MELI", "NU", "BABA", "VALE", "PBR", "GLOB", "STNE", "XP", "SBS", "ITUB"]


def metric_line(metrics: dict[str, float]) -> str:
    return (
        f"trades={int(metrics['trades']):3d} "
        f"wr={metrics['wr']:5.2f}% sh={metrics['sharpe']:5.2f} "
        f"avg={metrics.get('avg', metrics.get('avg_trade', 0.0)):+5.2f}% "
        f"mdd={metrics['mdd']:6.2f}%"
    )


def portfolio_metric_line(metrics: dict[str, float]) -> str:
    return (
        f"trades={int(metrics['trades']):3d} "
        f"wr={metrics['wr']:5.2f}% sh={metrics['sharpe']:5.2f} "
        f"avg_trade={metrics['avg_trade']:+5.2f}% total={metrics['total']:6.1f}% "
        f"mdd={metrics['mdd']:6.2f}%"
    )


def build_sets(prepared: dict[str, pd.DataFrame]) -> dict[str, list[str]]:
    available = set(prepared) - {"SPY"}
    base = [ticker for ticker in BROAD_UNIVERSE if ticker in available]
    strict_only = [ticker for ticker in STRICT_LATAM if ticker in available and ticker not in base]
    legacy_only = [ticker for ticker in LEGACY_LATAM if ticker in available and ticker not in base]
    combined_only = sorted(set(strict_only) | set(legacy_only))

    return {
        "BASE": base,
        "BASE+STRICT": base + strict_only,
        "BASE+LEGACY": base + legacy_only,
        "BASE+ALL": base + combined_only,
        "STRICT_ONLY": strict_only,
        "LEGACY_ONLY": legacy_only,
        "ALL_ADD_ONLY": combined_only,
    }


def align_to_spy(raw_data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    if "SPY" not in raw_data:
        return raw_data
    spy_index = raw_data["SPY"].index
    aligned: dict[str, pd.DataFrame] = {}
    for ticker, df in raw_data.items():
        aligned[ticker] = df.reindex(spy_index)
    return aligned


def evaluate_variant(
    prepared: dict[str, pd.DataFrame],
    tickers: list[str],
) -> dict[str, object]:
    dates = prepared["SPY"].index

    v10_ind_df = run_v10(prepared, tickers)
    v11_ind_df = run_independent_variant(prepared, tickers, POLICY_SCORE85_VOL4)
    pending, pressure = build_candidates(prepared, tickers)
    v10_port = simulate_portfolio(prepared, dates, pending, POLICY_RAW)
    v11_port = simulate_portfolio(prepared, dates, pending, POLICY_SCORE85_VOL4)
    wf_v10 = walk_forward_portfolio(prepared, dates, pending, POLICY_RAW, windows=5)
    wf_v11 = walk_forward_portfolio(prepared, dates, pending, POLICY_SCORE85_VOL4, windows=5)
    mc_v11 = monte_carlo(v11_ind_df, sims=1000) if not v11_ind_df.empty else None

    return {
        "v10_ind_df": v10_ind_df,
        "v11_ind_df": v11_ind_df,
        "v10_ind": calc_metrics(v10_ind_df),
        "v11_ind": calc_metrics(v11_ind_df),
        "v10_port": v10_port["metrics"],
        "v11_port": v11_port["metrics"],
        "wf_v10": wf_v10,
        "wf_v11": wf_v11,
        "mc_v11": mc_v11,
        "pressure": pressure,
    }


def print_variant(name: str, tickers: list[str], result: dict[str, object]) -> None:
    print("\n" + "=" * 100)
    print(f"  {name} | tickers={len(tickers)}")
    print("=" * 100)
    print(f"  V10 ind : {metric_line(result['v10_ind'])}")
    print(f"  V11 ind : {metric_line(result['v11_ind'])}")
    print(f"  V10 port: {portfolio_metric_line(result['v10_port'])}")
    print(f"  V11 port: {portfolio_metric_line(result['v11_port'])}")
    print(
        f"  WF5 V10={result['wf_v10']['pct']:5.1f}% avg_sh={result['wf_v10']['avg_sharpe']:.2f} | "
        f"V11={result['wf_v11']['pct']:5.1f}% avg_sh={result['wf_v11']['avg_sharpe']:.2f}"
    )
    pressure = result["pressure"]
    print(
        f"  Presion slots: dias_activos={int(pressure['days_with_candidates'])} | "
        f"dias_gt3={int(pressure['days_gt3'])} | max_dia={int(pressure['max_candidates_day'])} | "
        f"C_extremos={int(pressure['c_extreme_count'])}/{int(pressure['c_trades_total'])}"
    )
    mc_v11 = result["mc_v11"]
    if mc_v11:
        print(
            f"  MC V11  : P(Sh>0)={mc_v11['p_sharpe_pos']:5.1f}% | "
            f"median_sh={mc_v11['median_sharpe']:.2f} | worst1_sh={mc_v11['worst_1pct_sharpe']:.2f}"
        )


def print_delta(label: str, base: dict[str, object], other: dict[str, object]) -> None:
    print("\n" + "-" * 100)
    print(f"  Delta vs BASE - {label}")
    print("-" * 100)
    print(
        f"  V10 ind : sharpe {other['v10_ind']['sharpe'] - base['v10_ind']['sharpe']:+.2f} | "
        f"avg {other['v10_ind']['avg'] - base['v10_ind']['avg']:+.2f}% | "
        f"mdd {other['v10_ind']['mdd'] - base['v10_ind']['mdd']:+.2f}%"
    )
    print(
        f"  V11 ind : sharpe {other['v11_ind']['sharpe'] - base['v11_ind']['sharpe']:+.2f} | "
        f"avg {other['v11_ind']['avg'] - base['v11_ind']['avg']:+.2f}% | "
        f"mdd {other['v11_ind']['mdd'] - base['v11_ind']['mdd']:+.2f}%"
    )
    print(
        f"  V10 port: sharpe {other['v10_port']['sharpe'] - base['v10_port']['sharpe']:+.2f} | "
        f"total {other['v10_port']['total'] - base['v10_port']['total']:+.1f}% | "
        f"mdd {other['v10_port']['mdd'] - base['v10_port']['mdd']:+.2f}%"
    )
    print(
        f"  V11 port: sharpe {other['v11_port']['sharpe'] - base['v11_port']['sharpe']:+.2f} | "
        f"total {other['v11_port']['total'] - base['v11_port']['total']:+.1f}% | "
        f"mdd {other['v11_port']['mdd'] - base['v11_port']['mdd']:+.2f}%"
    )


def print_basket_contributors(name: str, df: pd.DataFrame) -> None:
    if df.empty:
        print(f"\n  {name}: sin trades")
        return
    grouped = (
        df.groupby("ticker")["return_pct"]
        .agg(["count", "mean", "sum"])
        .sort_values("sum")
    )
    print(f"\n  {name} - peores 5")
    print(grouped.head(5).round(2).to_string())
    print(f"\n  {name} - mejores 5")
    print(grouped.tail(5).sort_values("sum", ascending=False).round(2).to_string())


def main() -> None:
    universe_probe = sorted(set(BROAD_UNIVERSE) | set(STRICT_LATAM) | set(LEGACY_LATAM))
    raw_data, missing = load_db_data(universe_probe)
    raw_data = align_to_spy(raw_data)
    prepared = precompute(raw_data)
    sets = build_sets(prepared)

    print("=" * 100)
    print("  AUDITORIA LATAM SOBRE V10/V11")
    print("=" * 100)
    print(f"  DB coverage probe: {len(raw_data) - 1} tickers + SPY")
    print(f"  Missing probe: {missing}")
    print(f"  Strict LatAm add-back: {sets['STRICT_ONLY']}")
    print(f"  Legacy LatAm add-back: {sets['LEGACY_ONLY']}")

    results = {name: evaluate_variant(prepared, tickers) for name, tickers in sets.items()}

    for name in ["BASE", "BASE+STRICT", "BASE+LEGACY", "BASE+ALL", "STRICT_ONLY", "LEGACY_ONLY", "ALL_ADD_ONLY"]:
        print_variant(name, sets[name], results[name])

    base = results["BASE"]
    for name in ["BASE+STRICT", "BASE+LEGACY", "BASE+ALL"]:
        print_delta(name, base, results[name])

    print_basket_contributors("STRICT_ONLY V11", results["STRICT_ONLY"]["v11_ind_df"])
    print_basket_contributors("LEGACY_ONLY V11", results["LEGACY_ONLY"]["v11_ind_df"])
    print_basket_contributors("ALL_ADD_ONLY V11", results["ALL_ADD_ONLY"]["v11_ind_df"])


if __name__ == "__main__":
    main()
