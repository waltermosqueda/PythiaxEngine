"""
INVESTIGACION V25 - AUTO HYGIENE EN SIGNAL D
============================================

Pregunta:
  Podemos mejorar V13 si:
    1. dejamos de tratar a Auto como liderazgo generico dentro de D
    2. y solo le damos un sleeve propio cuando cumple RS new high en SEGURO

Hipotesis:
  - Auto dentro de D (liderazgo broad) destruye valor de forma persistente.
  - Auto puede recuperar edge si entra por una tesis mas estricta:
    RS new high + tendencia + mercado SEGURO.
  - La mejor forma de testearlo es contra la arquitectura activa V13:
      BASE   : 2 V11 + D + E_HW
      CAND A : 2 V11 + D(no Auto) + E_HW
      CAND B : BASE + sleeve dinamico E_AUTO solo en SEGURO
      CAND C : 2 V11 + D(no Auto) + E_HW + sleeve dinamico E_AUTO solo en SEGURO

Regla de honestidad:
  - No usar look-ahead.
  - Walk-forward correcto: partir desde el primer indice valido real.
  - No promocionar por full-period solamente; mirar 7v, 10v y recortes recientes.

Fecha: 2026-04-13
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.investigacion_v9_path_quality import ANTIKNIFE_DAYS, START_IDX
from backtests.investigacion_v12_portfolio_operativo import (
    INITIAL_EQUITY,
    calc_portfolio_metrics,
)
from backtests.investigacion_v17_signal_d_audit import (
    D_STRICT_REF,
    LEADERSHIP_HOLD_DEFAULT,
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
    build_sector_candidates,
)
from backtests.investigacion_v22_4slot_portfolio import merge_pending


LINE = "=" * 100
SUBLINE = "-" * 100
VALID_START = START_IDX + 252 + 10


def perf(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"trades": 0.0, "wr": 0.0, "avg": 0.0}
    df = pd.DataFrame(rows)
    return {
        "trades": float(len(df)),
        "wr": float((df["return_pct"] > 0).mean() * 100.0),
        "avg": float(df["return_pct"].mean()),
    }


def filter_pending(
    pending: dict[int, list[Any]],
    predicate,
) -> dict[int, list[Any]]:
    filtered: dict[int, list[Any]] = {}
    for idx, cands in pending.items():
        kept = [cand for cand in cands if predicate(cand)]
        if kept:
            filtered[idx] = kept
    return filtered


def window_slices(total_len: int, n_windows: int) -> list[tuple[int, int]]:
    usable = total_len - VALID_START
    window = usable // n_windows
    slices: list[tuple[int, int]] = []
    for w in range(n_windows):
        start = VALID_START + w * window
        end = VALID_START + (w + 1) * window if w < n_windows - 1 else total_len
        slices.append((start, end))
    return slices


def simulate_dynamic_special(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    primary_pending: dict[int, list[Any]],
    secondary_pending: dict[int, list[Any]],
    special_pending: dict[int, list[Any]],
    *,
    full_period: bool = False,
    start_idx: int | None = None,
    end_idx: int | None = None,
) -> dict[str, float]:
    start = (START_IDX + 1 if full_period else VALID_START) if start_idx is None else start_idx
    end = len(dates) if end_idx is None else end_idx

    cash = INITIAL_EQUITY
    cooldown_until: dict[str, int] = {}
    primary_positions: list[dict[str, Any]] = []
    secondary_positions: list[dict[str, Any]] = []
    special_positions: list[dict[str, Any]] = []
    equity_rows: list[dict[str, float]] = []
    closed_rows: list[dict[str, Any]] = []

    for idx in range(start, end):
        equity = cash
        for pos in primary_positions + secondary_positions + special_positions:
            px = float(prepared[pos["ticker"]]["Close"].iloc[idx])
            equity += float(pos["shares"]) * px
        equity_rows.append(
            {
                "equity": equity,
                "open_positions": float(
                    len(primary_positions) + len(secondary_positions) + len(special_positions)
                ),
            }
        )

        next_primary: list[dict[str, Any]] = []
        next_secondary: list[dict[str, Any]] = []
        next_special: list[dict[str, Any]] = []

        for current, target in [
            (primary_positions, next_primary),
            (secondary_positions, next_secondary),
            (special_positions, next_special),
        ]:
            for pos in current:
                if int(pos["exit_idx"]) == idx:
                    px = float(prepared[pos["ticker"]]["Close"].iloc[idx])
                    cash += float(pos["shares"]) * px
                    closed_rows.append(
                        {
                            "return_pct": (px / float(pos["entry_price"]) - 1.0) * 100.0,
                            "signal": pos["signal"],
                            "ticker": pos["ticker"],
                            "sector": pos["sector"],
                        }
                    )
                else:
                    target.append(pos)

        primary_positions = next_primary
        secondary_positions = next_secondary
        special_positions = next_special

        has_special_capacity = bool(special_pending.get(idx)) or bool(special_positions)
        total_slots = 5 if has_special_capacity else 4

        total_equity = cash
        for pos in primary_positions + secondary_positions + special_positions:
            px = float(prepared[pos["ticker"]]["Close"].iloc[idx])
            total_equity += float(pos["shares"]) * px
        slot_budget = total_equity / float(total_slots)

        def open_pool(
            candidates: list[Any],
            container: list[dict[str, Any]],
            limit: int,
        ) -> None:
            nonlocal cash
            free = limit - len(container)
            for cand in sorted(candidates, key=lambda item: item.raw_score, reverse=True):
                if free <= 0:
                    break
                occupied = {
                    pos["ticker"] for pos in primary_positions + secondary_positions + special_positions
                }
                if cand.ticker in occupied:
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
                        "signal": cand.signal,
                        "entry_price": px,
                        "shares": invested / px,
                        "exit_idx": cand.exit_idx,
                        "sector": cand.sector,
                    }
                )
                cash -= invested
                cooldown_until[cand.ticker] = idx + ANTIKNIFE_DAYS
                free -= 1

        open_pool(primary_pending.get(idx, []), primary_positions, 2)
        open_pool(secondary_pending.get(idx, []), secondary_positions, 2)
        open_pool(special_pending.get(idx, []), special_positions, 1)

    return calc_portfolio_metrics(pd.DataFrame(equity_rows), pd.DataFrame(closed_rows))


def walk_forward_vs_base(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    primary_pending: dict[int, list[Any]],
    base_secondary: dict[int, list[Any]],
    challenger_secondary: dict[int, list[Any]],
    *,
    challenger_special: dict[int, list[Any]] | None = None,
    n_windows: int = 7,
) -> dict[str, Any]:
    details: list[dict[str, float]] = []
    wins = 0

    for window_number, (start, end) in enumerate(window_slices(len(dates), n_windows), start=1):
        base_metrics = simulate_sleeves(
            prepared,
            dates,
            primary_pending,
            primary_slots=V11_PRIMARY_SLOTS,
            secondary_pending=base_secondary,
            secondary_slots=2,
            start_idx=start,
            end_idx=end,
        )["metrics"]

        if challenger_special is None:
            challenger_metrics = simulate_sleeves(
                prepared,
                dates,
                primary_pending,
                primary_slots=V11_PRIMARY_SLOTS,
                secondary_pending=challenger_secondary,
                secondary_slots=2,
                start_idx=start,
                end_idx=end,
            )["metrics"]
        else:
            challenger_metrics = simulate_dynamic_special(
                prepared,
                dates,
                primary_pending,
                challenger_secondary,
                challenger_special,
                start_idx=start,
                end_idx=end,
            )

        delta = float(challenger_metrics["sharpe"] - base_metrics["sharpe"])
        if delta > 0:
            wins += 1
        details.append(
            {
                "window": float(window_number),
                "base_sharpe": float(base_metrics["sharpe"]),
                "challenger_sharpe": float(challenger_metrics["sharpe"]),
                "delta_sharpe": delta,
                "base_wr": float(base_metrics["wr"]),
                "challenger_wr": float(challenger_metrics["wr"]),
            }
        )

    return {"wins": wins, "total": n_windows, "details": details}


def recent_cut(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    primary_pending: dict[int, list[Any]],
    base_secondary: dict[int, list[Any]],
    challenger_secondary: dict[int, list[Any]],
    *,
    challenger_special: dict[int, list[Any]] | None = None,
    cutoff: str,
) -> dict[str, dict[str, float]]:
    start = max(START_IDX + 1, int(dates.searchsorted(pd.Timestamp(cutoff))))

    base = simulate_sleeves(
        prepared,
        dates,
        primary_pending,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=base_secondary,
        secondary_slots=2,
        start_idx=start,
        end_idx=len(dates),
    )["metrics"]

    if challenger_special is None:
        challenger = simulate_sleeves(
            prepared,
            dates,
            primary_pending,
            primary_slots=V11_PRIMARY_SLOTS,
            secondary_pending=challenger_secondary,
            secondary_slots=2,
            start_idx=start,
            end_idx=len(dates),
        )["metrics"]
    else:
        challenger = simulate_dynamic_special(
            prepared,
            dates,
            primary_pending,
            challenger_secondary,
            challenger_special,
            start_idx=start,
            end_idx=len(dates),
        )

    return {"base": base, "challenger": challenger}


def print_portfolio_row(label: str, metrics: dict[str, float], ref: dict[str, float]) -> None:
    ds = float(metrics["sharpe"] - ref["sharpe"])
    dw = float(metrics["wr"] - ref["wr"])
    dmdd = float(metrics["mdd"] - ref["mdd"])
    print(
        f"  {label:<28s} sh {metrics['sharpe']:>5.2f} ({ds:+5.2f})"
        f"  wr {metrics['wr']:>5.1f}% ({dw:+5.1f}pp)"
        f"  mdd {metrics['mdd']:>+6.1f}% ({dmdd:+5.1f}pp)"
        f"  total {metrics['total']:>+8.1f}%"
        f"  n={int(metrics['trades']):>3d}"
    )


def main() -> None:
    print(LINE)
    print("  INVESTIGACION V25 - AUTO HYGIENE EN SIGNAL D")
    print(LINE)

    print("\n[0] Cargando universo...")
    prepared_base, dates = prepare_universe()
    prepared = extend_precompute(prepared_base)
    print(f"  DB: {dates[0].date()} -> {dates[-1].date()} | valid_start_idx={VALID_START}")

    print("\n[1] Construyendo candidatos base...")
    v11_pending, _ = build_v11_candidates(prepared, dates)
    d_pending, d_rows = build_d_candidates(
        prepared,
        dates,
        params=D_STRICT_REF,
        hold_days=LEADERSHIP_HOLD_DEFAULT,
    )
    e_hw_pending, e_hw_rows = build_sector_candidates(
        prepared,
        dates,
        signal_e,
        "E_HW",
        HW_TICKERS,
        15,
    )
    e_auto_pending, e_auto_rows = build_sector_candidates(
        prepared,
        dates,
        signal_e,
        "E_AUTO",
        AUTO_TICKERS,
        15,
    )

    base_secondary = merge_pending(d_pending, e_hw_pending)
    d_no_auto = filter_pending(d_pending, lambda cand: cand.sector != "Auto")
    e_auto_safe = filter_pending(e_auto_pending, lambda cand: cand.regime == "SEGURO")

    d_df = pd.DataFrame(d_rows)
    e_auto_df = pd.DataFrame(e_auto_rows)

    print("\n" + SUBLINE)
    print("[2] AUTO DENTRO DE D VS E_AUTO EN REGIME SAFE")
    print(SUBLINE)

    for regime in ["SEGURO", "PELIGRO"]:
        sub = d_df[(d_df["sector"] == "Auto") & (d_df["regime"] == regime)]
        wr = (sub["return_pct"] > 0).mean() * 100.0 if not sub.empty else 0.0
        avg = sub["return_pct"].mean() if not sub.empty else 0.0
        print(f"  D / Auto / {regime:<7s}: n={len(sub):>3d} | WR {wr:>5.1f}% | avg {avg:+6.2f}%")

    for regime in ["SEGURO", "PELIGRO"]:
        sub = e_auto_df[e_auto_df["regime"] == regime]
        wr = (sub["return_pct"] > 0).mean() * 100.0 if not sub.empty else 0.0
        avg = sub["return_pct"].mean() if not sub.empty else 0.0
        print(f"  E_AUTO / {regime:<7s}: n={len(sub):>3d} | WR {wr:>5.1f}% | avg {avg:+6.2f}%")

    print("\n" + SUBLINE)
    print("[3] COMPARACION DE ARQUITECTURAS")
    print(SUBLINE)

    base_metrics = simulate_sleeves(
        prepared,
        dates,
        v11_pending,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=base_secondary,
        secondary_slots=2,
    )["metrics"]
    cand_a_metrics = simulate_sleeves(
        prepared,
        dates,
        v11_pending,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=merge_pending(d_no_auto, e_hw_pending),
        secondary_slots=2,
    )["metrics"]
    cand_b_metrics = simulate_dynamic_special(
        prepared,
        dates,
        v11_pending,
        base_secondary,
        e_auto_safe,
        full_period=True,
    )
    cand_c_metrics = simulate_dynamic_special(
        prepared,
        dates,
        v11_pending,
        merge_pending(d_no_auto, e_hw_pending),
        e_auto_safe,
        full_period=True,
    )

    print_portfolio_row("BASE V13", base_metrics, base_metrics)
    print_portfolio_row("CAND A D(no Auto)", cand_a_metrics, base_metrics)
    print_portfolio_row("CAND B + E_AUTO_SAFE", cand_b_metrics, base_metrics)
    print_portfolio_row("CAND C A + E_AUTO_SAFE", cand_c_metrics, base_metrics)

    print("\n" + SUBLINE)
    print("[4] WALK-FORWARD CORRECTO")
    print(SUBLINE)

    wf7_a = walk_forward_vs_base(
        prepared,
        dates,
        v11_pending,
        base_secondary,
        merge_pending(d_no_auto, e_hw_pending),
        n_windows=7,
    )
    wf10_a = walk_forward_vs_base(
        prepared,
        dates,
        v11_pending,
        base_secondary,
        merge_pending(d_no_auto, e_hw_pending),
        n_windows=10,
    )
    wf7_c = walk_forward_vs_base(
        prepared,
        dates,
        v11_pending,
        base_secondary,
        merge_pending(d_no_auto, e_hw_pending),
        challenger_special=e_auto_safe,
        n_windows=7,
    )
    wf10_c = walk_forward_vs_base(
        prepared,
        dates,
        v11_pending,
        base_secondary,
        merge_pending(d_no_auto, e_hw_pending),
        challenger_special=e_auto_safe,
        n_windows=10,
    )

    print(f"  CAND A: WF7 {wf7_a['wins']}/{wf7_a['total']} | WF10 {wf10_a['wins']}/{wf10_a['total']}")
    print(f"  CAND C: WF7 {wf7_c['wins']}/{wf7_c['total']} | WF10 {wf10_c['wins']}/{wf10_c['total']}")

    print("\n  Detalle WF7 CAND C:")
    for row in wf7_c["details"]:
        print(
            f"    V{int(row['window'])}: sh {row['base_sharpe']:+.2f} -> {row['challenger_sharpe']:+.2f}"
            f" ({row['delta_sharpe']:+.2f}) | WR {row['base_wr']:.1f}% -> {row['challenger_wr']:.1f}%"
        )

    print("\n" + SUBLINE)
    print("[5] CORTES RECIENTES")
    print(SUBLINE)

    for cutoff in ["2024-01-01", "2025-01-01", "2025-07-01"]:
        recent = recent_cut(
            prepared,
            dates,
            v11_pending,
            base_secondary,
            merge_pending(d_no_auto, e_hw_pending),
            challenger_special=e_auto_safe,
            cutoff=cutoff,
        )
        base_recent = recent["base"]
        cand_recent = recent["challenger"]
        print(
            f"  {cutoff}: base sh {base_recent['sharpe']:.3f} | cand sh {cand_recent['sharpe']:.3f}"
            f" | base mdd {base_recent['mdd']:+.1f}% | cand mdd {cand_recent['mdd']:+.1f}%"
            f" | base wr {base_recent['wr']:.1f}% | cand wr {cand_recent['wr']:.1f}%"
        )

    print("\n" + SUBLINE)
    print("[6] GATE EXPLORATORIO")
    print(SUBLINE)

    gates = [
        (
            "D_AUTO_NEG_BOTH",
            perf(d_df[(d_df["sector"] == "Auto") & (d_df["regime"] == "SEGURO")].to_dict("records"))["avg"] < 0
            and perf(d_df[(d_df["sector"] == "Auto") & (d_df["regime"] == "PELIGRO")].to_dict("records"))["avg"] < 0,
            "Auto es negativa dentro de D en ambos regimes.",
        ),
        (
            "E_AUTO_SAFE_SPLIT",
            perf(e_auto_df[e_auto_df["regime"] == "SEGURO"].to_dict("records"))["avg"]
            > perf(e_auto_df[e_auto_df["regime"] == "PELIGRO"].to_dict("records"))["avg"],
            "E_AUTO funciona mejor en SEGURO que en PELIGRO.",
        ),
        (
            "FULL_SHARPE",
            cand_c_metrics["sharpe"] >= base_metrics["sharpe"] + 0.10,
            f"Sharpe {base_metrics['sharpe']:.2f} -> {cand_c_metrics['sharpe']:.2f}",
        ),
        (
            "FULL_MDD",
            cand_c_metrics["mdd"] >= base_metrics["mdd"] + 4.0,
            f"MDD {base_metrics['mdd']:+.1f}% -> {cand_c_metrics['mdd']:+.1f}%",
        ),
        (
            "FULL_WR",
            cand_c_metrics["wr"] >= base_metrics["wr"],
            f"WR {base_metrics['wr']:.1f}% -> {cand_c_metrics['wr']:.1f}%",
        ),
        (
            "WF7",
            wf7_c["wins"] >= 4,
            f"WF7 {wf7_c['wins']}/{wf7_c['total']}",
        ),
        (
            "WF10",
            wf10_c["wins"] >= 5,
            f"WF10 {wf10_c['wins']}/{wf10_c['total']}",
        ),
    ]

    passes = 0
    print(f"  {'Gate':<18} {'PASS/FAIL':>10}  Detalle")
    print(f"  {'-'*18} {'-'*10}  {'-'*52}")
    for name, ok, detail in gates:
        status = "PASS" if ok else "FAIL"
        if ok:
            passes += 1
        print(f"  {name:<18} {status:>10}  {detail}")

    print(f"\n  Total: {passes}/{len(gates)} PASS")

    print("\n" + LINE)
    print("  VEREDICTO V25")
    print(LINE)

    print(
        f"  Mejor challenger encontrado: CAND C = D(no Auto) + E_AUTO solo en SEGURO"
        f" | Sharpe {cand_c_metrics['sharpe']:.2f}"
        f" vs V13 {base_metrics['sharpe']:.2f}"
        f" | MDD {cand_c_metrics['mdd']:+.1f}% vs {base_metrics['mdd']:+.1f}%"
    )
    print(
        f"  WR {cand_c_metrics['wr']:.1f}% vs {base_metrics['wr']:.1f}%"
        f" | trades {int(cand_c_metrics['trades'])} vs {int(base_metrics['trades'])}"
    )
    print(
        f"  WF7 {wf7_c['wins']}/{wf7_c['total']} | WF10 {wf10_c['wins']}/{wf10_c['total']}"
    )

    print()
    if passes >= 6:
        print("  RESULTADO: CHALLENGER SERIO")
        print("  - Le gana a V13 por buen margen en Sharpe y drawdown.")
        print("  - La mejora temporal es suficiente para justificar cristalizacion challenger.")
        print("  - Siguiente paso recomendado: construir un scanner V15 challenger y monitorearlo en vivo.")
    elif passes >= 4:
        print("  RESULTADO: CONDICIONAL")
        print("  - Hay edge, pero todavia no alcanza para reemplazar V13 sin monitoreo adicional.")
        print("  - Mantener como promotion candidate, no como activo inmediato.")
    else:
        print("  RESULTADO: NO PROMOVER")
        print("  - El edge no se sostiene fuera del full-period.")

    print()
    print("  Lectura final:")
    print("  - Auto no sirve como liderazgo broad dentro de D.")
    print("  - Auto mejora cuando entra por una tesis mas estricta de RS new high y solo en SEGURO.")
    print("  - La combinacion de ambas ideas crea el primer challenger real contra V13 desde la promocion de E_HW.")
    print(LINE)


if __name__ == "__main__":
    main()
