"""
INVESTIGACION V18 - CRISTALIZACION DE V12 CON SIGNAL D
======================================================

Objetivo:
  Convertir la frontera aprobada en V17 en un candidato V12 concreto y
  reproducible, manteniendo la tesis valida:

    - V11 sigue siendo el champion productivo actual
    - V12 es el challenger canonico que agrega Signal D como tercer eje
    - la arquitectura validada es 2 slots V11 + 1 slot D

Esta investigacion no vuelve a inventar Signal D desde cero. Toma la
auditoria dura de V17 como referencia y la cristaliza en el siguiente paso:
  1. Reproducir el diferencial V11 vs V12
  2. Confirmar que el promotion gate de V17 sigue vivo
  3. Mostrar el snapshot live mas reciente de candidatos D

Fecha: 2026-04-10
"""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.investigacion_v17_signal_d_audit import (
    D_STRICT_REF,
    LEADERSHIP_HOLD_DEFAULT,
    LEADERSHIP_SLOTS,
    LINE,
    SUBLINE,
    V11_PRIMARY_SLOTS,
    build_d_candidates,
    build_v11_candidates,
    evaluate_promotion_gate,
    run_concentration_analysis,
    run_hold_sensitivity,
    run_monte_carlo,
    run_walk_forward_10,
    prepare_universe,
    print_ind_row,
    print_port_row,
    signal_d_leadership,
    simulate_sleeves,
)


def latest_d_snapshot(prepared: dict[str, pd.DataFrame], dates: pd.DatetimeIndex) -> pd.DataFrame:
    idx = len(dates) - 1
    rows: list[dict[str, object]] = []
    spy = prepared["SPY"]
    regime = "SEGURO" if bool(spy["REGIME_SAFE"].iloc[idx]) else "PELIGRO"

    for ticker, df in prepared.items():
        if ticker == "SPY":
            continue
        row = df.iloc[idx]
        if not signal_d_leadership(row, **D_STRICT_REF):
            continue
        rows.append(
            {
                "ticker": ticker,
                "date": str(dates[idx].date()),
                "regime": regime,
                "close": round(float(row["Close"]), 2),
                "roc20": round(float(row["ROC20"]), 1),
                "rel20": round(float(row["REL20"]), 1),
                "rsi": round(float(row["RSI"]), 1),
                "vol_ratio": round(float(row["VOL_RATIO"]), 2),
                "score": round(float(row["ROC20"] + row["REL20"]), 1),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["ticker", "date", "regime", "close", "roc20", "rel20", "rsi", "vol_ratio", "score"])
    return pd.DataFrame(rows).sort_values(["score", "rel20", "roc20"], ascending=[False, False, False])


def main() -> None:
    print(LINE)
    print("  INVESTIGACION V18 - CRISTALIZACION DE V12")
    print(LINE)
    print("  Objetivo: convertir la tesis validada en V17 en un challenger canonico V12.")
    print()

    prepared, dates = prepare_universe()
    print(f"  Rango DB       : {dates[0].date()} -> {dates[-1].date()}")
    print(f"  Parametros D   : {D_STRICT_REF} | hold={LEADERSHIP_HOLD_DEFAULT}d")
    print(f"  Arquitectura   : {V11_PRIMARY_SLOTS} slots V11 + {LEADERSHIP_SLOTS} slot D")
    print()

    print("[1] Construyendo base V11")
    v11_pending, v11_rows = build_v11_candidates(prepared, dates)
    print_ind_row("V11_BASE", v11_rows)
    base_result = simulate_sleeves(
        prepared,
        dates,
        v11_pending,
        primary_slots=V11_PRIMARY_SLOTS + LEADERSHIP_SLOTS,
    )
    print_port_row("V11_3SLOTS_PORT", base_result)
    print()

    print("[2] Construyendo sleeve D para V12")
    d_pending, d_rows = build_d_candidates(
        prepared,
        dates,
        params=D_STRICT_REF,
        hold_days=LEADERSHIP_HOLD_DEFAULT,
    )
    print_ind_row("D_STRICT_IND", d_rows)
    hybrid_result = simulate_sleeves(
        prepared,
        dates,
        v11_pending,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=d_pending,
        secondary_slots=LEADERSHIP_SLOTS,
    )
    print_port_row("V12_CANDIDATO", hybrid_result)
    print()

    print("[3] Revalidando promotion gate")
    wf_df = run_walk_forward_10(prepared, dates, v11_pending, d_pending)
    hold_df = run_hold_sensitivity(prepared, dates, v11_pending, D_STRICT_REF)
    conc_stats = run_concentration_analysis(d_rows)
    mc_stats = run_monte_carlo(base_result, hybrid_result)
    passed, veredicto = evaluate_promotion_gate(
        wf_df,
        base_result["metrics"],
        hybrid_result["metrics"],
        mc_stats,
        conc_stats,
        hold_df,
        d_rows,
    )
    print()

    print("[4] Snapshot live mas reciente de Signal D")
    latest_df = latest_d_snapshot(prepared, dates)
    if latest_df.empty:
        print("  No hay candidatos D hoy en la ultima fecha de la DB.")
    else:
        print(latest_df.head(12).to_string(index=False))
    print()

    print(LINE)
    print("  RESUMEN EJECUTIVO V18")
    print(LINE)
    print(
        "  V11 base : "
        f"Sharpe={float(base_result['metrics']['sharpe']):.2f} | "
        f"Total={float(base_result['metrics']['total']):.1f}% | "
        f"MDD={float(base_result['metrics']['mdd']):.1f}%"
    )
    print(
        "  V12 cand : "
        f"Sharpe={float(hybrid_result['metrics']['sharpe']):.2f} | "
        f"Total={float(hybrid_result['metrics']['total']):.1f}% | "
        f"MDD={float(hybrid_result['metrics']['mdd']):.1f}%"
    )
    print(f"  Gates V17: {passed}/7 | {veredicto}")
    print("  Conclusión: si V18 reproduce V17, ya existe base honesta para construir invertir_v12.py.")
    print(LINE)


if __name__ == "__main__":
    main()
