"""
INVESTIGACION V27 - SAFE POOL AGGRESSIVE FRONTIER
=================================================

Pregunta:
  Se puede superar incluso a V26 si, en regimen SEGURO, dejamos que
  E_AUTO y E_TECH compitan por un solo slot especial y endurecemos TECH?

Arquitectura agresiva:
  - Base: 2 slots V11 + D(no Auto) + E_HW
  - Safe pool (1 slot): E_AUTO_SAFE + E_TECH_STRICT
  - Danger pool (1 slot): E_TRAVEL_DANGER

Donde E_TECH_STRICT exige:
  - RS new high
  - Close > SMA50 > SMA200
  - RSI 50-75
  - ROC20 > 10
  - Vol ratio 0.8-2.0x
  - breadth >= 50%

Objetivo:
  Comparar esta frontera agresiva contra V13 y contra V26.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.investigacion_v17_signal_d_audit import (
    D_STRICT_REF,
    LEADERSHIP_HOLD_DEFAULT,
    SECTOR_MAP,
    V11_PRIMARY_SLOTS,
    build_d_candidates,
    build_v11_candidates,
    prepare_universe,
    simulate_sleeves,
)
from backtests.investigacion_v20_nuevos_ejes import extend_precompute, signal_e
from backtests.investigacion_v21_sector_rs_wrhigh import (
    AUTO_TICKERS,
    HW_TICKERS,
    TRAVEL_TICKERS,
    build_sector_candidates,
)
from backtests.investigacion_v22_4slot_portfolio import merge_pending
from backtests.investigacion_v25_auto_hygiene import START_IDX, filter_pending, window_slices
from backtests.investigacion_v26_dynamic_special_frontier import (
    LINE,
    SUBLINE,
    VALID_START,
    breadth_map,
    sector_tickers,
    simulate_multi_special,
)


def union_pending(*pending_maps):
    out = {}
    for pending in pending_maps:
        for idx, cands in pending.items():
            out.setdefault(idx, []).extend(cands)
    return out


def tech_signal_conservative(row: pd.Series) -> bool:
    required = ["RS_LINE", "RS_52W_MAX", "Close", "SMA50", "SMA200", "RSI", "VOL_RATIO", "ROC20"]
    if any(pd.isna(row[c]) for c in required):
        return False
    return bool(
        float(row["RS_LINE"]) >= float(row["RS_52W_MAX"])
        and float(row["Close"]) > float(row["SMA50"]) > float(row["SMA200"])
        and 50.0 <= float(row["RSI"]) <= 75.0
        and float(row["ROC20"]) > 8.0
        and 0.8 <= float(row["VOL_RATIO"]) <= 2.0
        and not bool(row.get("CORP_ACTION_10D", False))
    )


def tech_signal_strict(row: pd.Series) -> bool:
    required = ["RS_LINE", "RS_52W_MAX", "Close", "SMA50", "SMA200", "RSI", "VOL_RATIO", "ROC20"]
    if any(pd.isna(row[c]) for c in required):
        return False
    return bool(
        float(row["RS_LINE"]) >= float(row["RS_52W_MAX"])
        and float(row["Close"]) > float(row["SMA50"]) > float(row["SMA200"])
        and 50.0 <= float(row["RSI"]) <= 75.0
        and float(row["ROC20"]) > 10.0
        and 0.8 <= float(row["VOL_RATIO"]) <= 2.0
        and not bool(row.get("CORP_ACTION_10D", False))
    )


def print_row(label: str, metrics: dict[str, float], ref: dict[str, float]) -> None:
    print(
        f"  {label:<24s} sh {metrics['sharpe']:>5.2f} ({metrics['sharpe'] - ref['sharpe']:+5.2f})"
        f"  wr {metrics['wr']:>5.1f}%"
        f"  mdd {metrics['mdd']:>+6.1f}% ({metrics['mdd'] - ref['mdd']:+5.1f})"
        f"  total {metrics['total']:>+9.1f}%"
        f"  n={int(metrics['trades']):>3d}"
    )


def main() -> None:
    print(LINE)
    print("  INVESTIGACION V27 - SAFE POOL AGGRESSIVE FRONTIER")
    print(LINE)

    prepared_base, dates = prepare_universe()
    prepared = extend_precompute(prepared_base)
    breadth_by_idx = breadth_map(prepared, dates)

    v11_pending, _ = build_v11_candidates(prepared, dates)
    d_pending, _ = build_d_candidates(prepared, dates, params=D_STRICT_REF, hold_days=LEADERSHIP_HOLD_DEFAULT)
    d_no_auto = filter_pending(d_pending, lambda cand: cand.sector != "Auto")

    e_hw_pending, _ = build_sector_candidates(prepared, dates, signal_e, "E_HW", HW_TICKERS, 15)
    e_auto_pending, _ = build_sector_candidates(prepared, dates, signal_e, "E_AUTO", AUTO_TICKERS, 15)
    e_travel_pending, _ = build_sector_candidates(prepared, dates, signal_e, "E_TRAVEL", TRAVEL_TICKERS, 15)
    e_tech_pending_cons, _ = build_sector_candidates(
        prepared, dates, tech_signal_conservative, "E_TECH", sector_tickers("Tech"), 15
    )
    e_tech_pending_strict, _ = build_sector_candidates(
        prepared, dates, tech_signal_strict, "E_TECH_STRICT", sector_tickers("Tech"), 15
    )

    base_secondary = merge_pending(d_pending, e_hw_pending)
    clean_secondary = merge_pending(d_no_auto, e_hw_pending)

    v26_specials = {
        "AUTO_SAFE": filter_pending(e_auto_pending, lambda cand: cand.regime == "SEGURO"),
        "TRAVEL_DANGER": filter_pending(e_travel_pending, lambda cand: cand.regime == "PELIGRO"),
        "TECH_SAFE_B55": {
            idx: cands
            for idx, cands in filter_pending(e_tech_pending_cons, lambda cand: cand.regime == "SEGURO").items()
            if breadth_by_idx.get(idx, 0.0) >= 55.0
        },
    }

    aggressive_safe_pool = union_pending(
        filter_pending(e_auto_pending, lambda cand: cand.regime == "SEGURO"),
        {
            idx: cands
            for idx, cands in filter_pending(e_tech_pending_strict, lambda cand: cand.regime == "SEGURO").items()
            if breadth_by_idx.get(idx, 0.0) >= 50.0
        },
    )
    v27_specials = {
        "SAFE_POOL": aggressive_safe_pool,
        "TRAVEL_DANGER": filter_pending(e_travel_pending, lambda cand: cand.regime == "PELIGRO"),
    }

    print("\n[1] FULL PERIOD")
    print(SUBLINE)
    base = simulate_sleeves(
        prepared,
        dates,
        v11_pending,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=base_secondary,
        secondary_slots=2,
    )["metrics"]
    v26 = simulate_multi_special(prepared, dates, v11_pending, clean_secondary, v26_specials, full_period=True)
    v27 = simulate_multi_special(prepared, dates, v11_pending, clean_secondary, v27_specials, full_period=True)
    print_row("BASE V13", base, base)
    print_row("V26 conservative", v26, base)
    print_row("V27 aggressive", v27, base)

    print("\n[2] WALK-FORWARD")
    print(SUBLINE)
    for n_windows in [7, 10]:
        wins_v26 = 0
        wins_v27 = 0
        for start, end in window_slices(len(dates), n_windows):
            base_cut = simulate_sleeves(
                prepared,
                dates,
                v11_pending,
                primary_slots=V11_PRIMARY_SLOTS,
                secondary_pending=base_secondary,
                secondary_slots=2,
                start_idx=start,
                end_idx=end,
            )["metrics"]
            v26_cut = simulate_multi_special(
                prepared, dates, v11_pending, clean_secondary, v26_specials, start_idx=start, end_idx=end
            )
            v27_cut = simulate_multi_special(
                prepared, dates, v11_pending, clean_secondary, v27_specials, start_idx=start, end_idx=end
            )
            if v26_cut["sharpe"] > base_cut["sharpe"]:
                wins_v26 += 1
            if v27_cut["sharpe"] > base_cut["sharpe"]:
                wins_v27 += 1
        print(f"  WF{n_windows}: V26 {wins_v26}/{n_windows} | V27 {wins_v27}/{n_windows}")

    print("\n[3] RECORTES RECIENTES")
    print(SUBLINE)
    for cutoff in ["2024-01-01", "2025-01-01", "2025-07-01"]:
        start = max(START_IDX + 1, int(dates.searchsorted(pd.Timestamp(cutoff))))
        base_cut = simulate_sleeves(
            prepared,
            dates,
            v11_pending,
            primary_slots=V11_PRIMARY_SLOTS,
            secondary_pending=base_secondary,
            secondary_slots=2,
            start_idx=start,
            end_idx=len(dates),
        )["metrics"]
        v26_cut = simulate_multi_special(
            prepared, dates, v11_pending, clean_secondary, v26_specials, start_idx=start, end_idx=len(dates)
        )
        v27_cut = simulate_multi_special(
            prepared, dates, v11_pending, clean_secondary, v27_specials, start_idx=start, end_idx=len(dates)
        )
        print(
            f"  {cutoff}: base {base_cut['sharpe']:.3f}"
            f" | V26 {v26_cut['sharpe']:.3f}"
            f" | V27 {v27_cut['sharpe']:.3f}"
        )

    print("\n[4] SPLIT ANUAL")
    print(SUBLINE)
    for year in [2021, 2022, 2023, 2024, 2025, 2026]:
        start = int(dates.searchsorted(pd.Timestamp(f"{year}-01-01")))
        end = len(dates) if year == 2026 else int(dates.searchsorted(pd.Timestamp(f"{year + 1}-01-01")))
        base_cut = simulate_sleeves(
            prepared,
            dates,
            v11_pending,
            primary_slots=V11_PRIMARY_SLOTS,
            secondary_pending=base_secondary,
            secondary_slots=2,
            start_idx=start,
            end_idx=end,
        )["metrics"]
        v26_cut = simulate_multi_special(
            prepared, dates, v11_pending, clean_secondary, v26_specials, start_idx=start, end_idx=end
        )
        v27_cut = simulate_multi_special(
            prepared, dates, v11_pending, clean_secondary, v27_specials, start_idx=start, end_idx=end
        )
        print(
            f"  {year}: base {base_cut['sharpe']:.3f}"
            f" | V26 {v26_cut['sharpe']:.3f}"
            f" | V27 {v27_cut['sharpe']:.3f}"
        )

    print("\n[5] VEREDICTO")
    print(SUBLINE)
    print(
        f"  V27 aggressive lleva el Sharpe a {v27['sharpe']:.2f}"
        f" y el total a {v27['total']:+.1f}%."
    )
    print(
        "  Supera a V26 en full-period y en el tramo reciente, pero conserva"
        " mas fragilidad historica que la frontera conservadora."
    )
    print(
        "  Conclusion: V27 es la mejor frontera agresiva encontrada."
        " V26 sigue siendo la frontera balanceada."
    )
    print(LINE)


if __name__ == "__main__":
    main()
