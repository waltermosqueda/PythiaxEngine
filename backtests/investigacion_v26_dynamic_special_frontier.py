"""
INVESTIGACION V26 - DYNAMIC SPECIAL FRONTIER
============================================

Pregunta:
  Existe una arquitectura claramente superior a V13/V15 si tratamos ciertos
  sleeves RS por sector y por regimen como slots especiales dinamicos?

Frontera testeada:
  - Base core: 2 slots V11 + D(no Auto) + E_HW
  - Specials:
      E_AUTO   solo en SEGURO
      E_TRAVEL solo en PELIGRO
      E_TECH   solo en SEGURO y solo si breadth >= 55%

Idea economica:
  - Auto recupera edge solo cuando el mercado esta sano.
  - Travel muestra mejor perfil en contexto defensivo.
  - Tech RS necesita viento de cola broad; sin breadth suficiente se vuelve ruido.

Fecha: 2026-04-13
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.investigacion_v9_path_quality import ANTIKNIFE_DAYS, START_IDX
from backtests.investigacion_v12_portfolio_operativo import INITIAL_EQUITY, calc_portfolio_metrics
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
from backtests.investigacion_v25_auto_hygiene import VALID_START, filter_pending, window_slices


LINE = "=" * 100
SUBLINE = "-" * 100


def sector_tickers(sector_name: str) -> set[str]:
    return {ticker for ticker, sector in SECTOR_MAP.items() if sector == sector_name}


def breadth_map(prepared: dict[str, pd.DataFrame], dates: pd.DatetimeIndex) -> dict[int, float]:
    tickers = [ticker for ticker in prepared.keys() if ticker != "SPY"]
    out: dict[int, float] = {}
    for idx in range(len(dates)):
        vals: list[bool] = []
        for ticker in tickers:
            df = prepared[ticker]
            sma50 = df["SMA50"].iloc[idx]
            price = df["Close"].iloc[idx]
            if pd.isna(sma50):
                continue
            vals.append(bool(price > sma50))
        out[idx] = float(sum(vals) / len(vals) * 100.0) if vals else 0.0
    return out


def tech_signal(row: pd.Series) -> bool:
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


def filter_pending_with_breadth(
    pending: dict[int, list[Any]],
    breadth_by_idx: dict[int, float],
    minimum_breadth: float,
) -> dict[int, list[Any]]:
    out: dict[int, list[Any]] = {}
    for idx, cands in pending.items():
        if breadth_by_idx.get(idx, 0.0) < minimum_breadth:
            continue
        out[idx] = list(cands)
    return out


def simulate_multi_special(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    primary_pending: dict[int, list[Any]],
    secondary_pending: dict[int, list[Any]],
    special_map: dict[str, dict[int, list[Any]]],
    *,
    start_idx: int | None = None,
    end_idx: int | None = None,
    full_period: bool = False,
) -> dict[str, float]:
    start = (START_IDX + 1 if full_period else VALID_START) if start_idx is None else start_idx
    end = len(dates) if end_idx is None else end_idx

    cash = INITIAL_EQUITY
    cooldown_until: dict[str, int] = {}
    primary_positions: list[dict[str, Any]] = []
    secondary_positions: list[dict[str, Any]] = []
    special_positions: dict[str, list[dict[str, Any]]] = {name: [] for name in special_map}
    equity_rows: list[dict[str, float]] = []
    closed_rows: list[dict[str, Any]] = []

    def flat_special_positions() -> list[dict[str, Any]]:
        return [position for bucket in special_positions.values() for position in bucket]

    for idx in range(start, end):
        equity = cash
        for pos in primary_positions + secondary_positions + flat_special_positions():
            px = float(prepared[pos["ticker"]]["Close"].iloc[idx])
            equity += float(pos["shares"]) * px
        equity_rows.append(
            {
                "equity": equity,
                "open_positions": float(
                    len(primary_positions) + len(secondary_positions) + sum(len(bucket) for bucket in special_positions.values())
                ),
            }
        )

        next_primary: list[dict[str, Any]] = []
        next_secondary: list[dict[str, Any]] = []
        next_special: dict[str, list[dict[str, Any]]] = {name: [] for name in special_positions}

        for current, target in [(primary_positions, next_primary), (secondary_positions, next_secondary)]:
            for pos in current:
                if int(pos["exit_idx"]) == idx:
                    px = float(prepared[pos["ticker"]]["Close"].iloc[idx])
                    cash += float(pos["shares"]) * px
                    closed_rows.append({"return_pct": (px / float(pos["entry_price"]) - 1.0) * 100.0})
                else:
                    target.append(pos)

        for name, current in special_positions.items():
            for pos in current:
                if int(pos["exit_idx"]) == idx:
                    px = float(prepared[pos["ticker"]]["Close"].iloc[idx])
                    cash += float(pos["shares"]) * px
                    closed_rows.append({"return_pct": (px / float(pos["entry_price"]) - 1.0) * 100.0})
                else:
                    next_special[name].append(pos)

        primary_positions = next_primary
        secondary_positions = next_secondary
        special_positions = next_special

        active_special_slots = sum(1 for name, pending in special_map.items() if pending.get(idx) or special_positions[name])
        total_slots = 4 + active_special_slots

        total_equity = cash
        for pos in primary_positions + secondary_positions + flat_special_positions():
            px = float(prepared[pos["ticker"]]["Close"].iloc[idx])
            total_equity += float(pos["shares"]) * px
        slot_budget = total_equity / float(total_slots)

        def occupied_tickers() -> set[str]:
            return {pos["ticker"] for pos in primary_positions + secondary_positions + flat_special_positions()}

        def open_pool(candidates: list[Any], container: list[dict[str, Any]], limit: int) -> None:
            nonlocal cash
            free = limit - len(container)
            for cand in sorted(candidates, key=lambda item: item.raw_score, reverse=True):
                if free <= 0:
                    break
                if cand.ticker in occupied_tickers():
                    continue
                if idx <= cooldown_until.get(cand.ticker, -999):
                    continue
                px = float(prepared[cand.ticker]["Close"].iloc[idx])
                invested = min(slot_budget, cash)
                if invested <= 0:
                    break
                container.append(
                    {
                        "ticker": cand.ticker,
                        "entry_price": px,
                        "shares": invested / px,
                        "exit_idx": cand.exit_idx,
                    }
                )
                cash -= invested
                cooldown_until[cand.ticker] = idx + ANTIKNIFE_DAYS
                free -= 1

        open_pool(primary_pending.get(idx, []), primary_positions, 2)
        open_pool(secondary_pending.get(idx, []), secondary_positions, 2)
        for name, pending in special_map.items():
            open_pool(pending.get(idx, []), special_positions[name], 1)

    return calc_portfolio_metrics(pd.DataFrame(equity_rows), pd.DataFrame(closed_rows))


def print_row(label: str, metrics: dict[str, float], ref: dict[str, float]) -> None:
    print(
        f"  {label:<22s} sh {metrics['sharpe']:>5.2f} ({metrics['sharpe'] - ref['sharpe']:+5.2f})"
        f"  wr {metrics['wr']:>5.1f}%"
        f"  mdd {metrics['mdd']:>+6.1f}% ({metrics['mdd'] - ref['mdd']:+5.1f})"
        f"  total {metrics['total']:>+8.1f}%"
        f"  n={int(metrics['trades']):>3d}"
    )


def main() -> None:
    print(LINE)
    print("  INVESTIGACION V26 - DYNAMIC SPECIAL FRONTIER")
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
    e_tech_pending, tech_rows = build_sector_candidates(prepared, dates, tech_signal, "E_TECH", sector_tickers("Tech"), 15)

    base_secondary = merge_pending(d_pending, e_hw_pending)
    clean_secondary = merge_pending(d_no_auto, e_hw_pending)

    v15_specials = {
        "AUTO_SAFE": filter_pending(e_auto_pending, lambda cand: cand.regime == "SEGURO")
    }
    v26_specials = {
        "AUTO_SAFE": filter_pending(e_auto_pending, lambda cand: cand.regime == "SEGURO"),
        "TRAVEL_DANGER": filter_pending(e_travel_pending, lambda cand: cand.regime == "PELIGRO"),
        "TECH_SAFE_B55": filter_pending_with_breadth(
            filter_pending(e_tech_pending, lambda cand: cand.regime == "SEGURO"),
            breadth_by_idx,
            55.0,
        ),
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
    v15 = simulate_multi_special(prepared, dates, v11_pending, clean_secondary, v15_specials, full_period=True)
    v26 = simulate_multi_special(prepared, dates, v11_pending, clean_secondary, v26_specials, full_period=True)
    print_row("BASE V13", base, base)
    print_row("V15", v15, base)
    print_row("V26 frontier", v26, base)

    print("\n[2] WALK-FORWARD")
    print(SUBLINE)
    for n_windows in [7, 10]:
        wins = 0
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
                prepared,
                dates,
                v11_pending,
                clean_secondary,
                v26_specials,
                start_idx=start,
                end_idx=end,
            )
            if v26_cut["sharpe"] > base_cut["sharpe"]:
                wins += 1
        print(f"  WF{n_windows}: {wins}/{n_windows}")

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
            prepared,
            dates,
            v11_pending,
            clean_secondary,
            v26_specials,
            start_idx=start,
            end_idx=len(dates),
        )
        print(
            f"  {cutoff}: sh {base_cut['sharpe']:.3f}->{v26_cut['sharpe']:.3f}"
            f" | mdd {base_cut['mdd']:+.1f}%->{v26_cut['mdd']:+.1f}%"
            f" | wr {base_cut['wr']:.1f}%->{v26_cut['wr']:.1f}%"
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
            prepared,
            dates,
            v11_pending,
            clean_secondary,
            v26_specials,
            start_idx=start,
            end_idx=end,
        )
        print(
            f"  {year}: sh {base_cut['sharpe']:.3f}->{v26_cut['sharpe']:.3f}"
            f" | wr {base_cut['wr']:.1f}%->{v26_cut['wr']:.1f}%"
            f" | mdd {base_cut['mdd']:+.1f}%->{v26_cut['mdd']:+.1f}%"
        )

    tech_df = pd.DataFrame(tech_rows)
    tech_safe_n = int((tech_df["regime"] == "SEGURO").sum())
    print("\n[5] SANITY CHECK TECH SAFE")
    print(SUBLINE)
    print(f"  Tech trades totales: {len(tech_df)}")
    print(f"  Tech safe antes de breadth gate: {tech_safe_n}")
    print(
        f"  Tech safe despues de breadth>=55: "
        f"{sum(len(v) for v in v26_specials['TECH_SAFE_B55'].values())}"
    )

    print("\n[6] VEREDICTO")
    print(SUBLINE)
    print(
        f"  V26 frontier sube Sharpe de {base['sharpe']:.2f} a {v26['sharpe']:.2f}"
        f" y mejora MDD de {base['mdd']:+.1f}% a {v26['mdd']:+.1f}%."
    )
    print(
        "  Es una frontera mas amplia que V15, pero sigue teniendo debilidad puntual"
        " en 2021 y en el tramo parcial 2026."
    )
    print(
        "  Conclusion: challenger MUY serio. Merece cristalizacion como scanner de sombra"
        " y monitoreo live antes de reemplazar a V13."
    )
    print(LINE)


if __name__ == "__main__":
    main()
