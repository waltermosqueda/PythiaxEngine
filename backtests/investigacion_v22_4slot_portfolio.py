"""
INVESTIGACION V22 - PORTFOLIO 4 SLOTS (V12 + E_BEST3)
======================================================

Hallazgo de V21:
  E_BEST3 (HW+Auto+Travel con RS New High): WR 66.5%, n=188, WF 5/7, Sharpe 1.46
  Problema: reemplazar D con E_BEST3 baja Sharpe de 1.36 a ~1.29 (slot vacio mas a menudo)
  Solucion propuesta: agregar E_BEST3 como CUARTO sleeve (no reemplazar D)

Arquitecturas a comparar:
  [BASE]  V12 actual: 2 V11 + 1 D = 3 slots (referencia)
  [A]     Control:   2 V11 + 2 D  = 4 slots (solo agrego 1 D extra)
  [B]     2 V11 + D + E_BEST3 = 4 slots (D y E_BEST3 compiten por los 2 slots secundarios)
  [C]     2 V11 + D + E_HW    = 4 slots (D + alta WR baja frecuencia)
  [D]     2 V11 + D + E_TRAVEL = 4 slots (D + Travel cualquier regimen)
  [E]     2 V11 + D + E_BEST3 + prioridad RS (E_BEST3 solo cuando D no dispara)

Metricas objetivo:
  - Sharpe portfolio > 1.36 (superar V12)
  - WR >= 62% (mejorar V12)
  - MDD no degradar > 10% (max -44%)
  - WF >= 4/7 ventanas positivas

Fecha: 2026-04-13
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.investigacion_v9_path_quality import (
    ANTIKNIFE_DAYS,
    START_IDX,
    calc_metrics,
)
from backtests.investigacion_v17_signal_d_audit import (
    Candidate,
    LINE,
    SUBLINE,
    D_STRICT_REF,
    LEADERSHIP_HOLD_DEFAULT,
    LEADERSHIP_SLOTS,
    V11_PRIMARY_SLOTS,
    build_d_candidates,
    build_v11_candidates,
    get_sector,
    prepare_universe,
    print_port_row,
    simulate_sleeves,
)
from backtests.investigacion_v12_portfolio_operativo import calc_portfolio_metrics
from backtests.investigacion_v20_nuevos_ejes import (
    extend_precompute,
    signal_e,
    per_trade_metrics,
    build_signal_candidates,
    walk_forward_7,
)
from backtests.investigacion_v21_sector_rs_wrhigh import (
    HW_TICKERS,
    AUTO_TICKERS,
    TRAVEL_TICKERS,
    BEST3_TICKERS,
    build_sector_candidates,
)

HOLD_E = 15

# ─────────────────────────────────────────────────────────────────────────────
# MERGE DE CANDIDATOS
# ─────────────────────────────────────────────────────────────────────────────

def merge_pending(*dicts: dict[int, list[Candidate]]) -> dict[int, list[Candidate]]:
    """Une multiples dicts de candidatos en uno solo."""
    merged: dict[int, list[Candidate]] = {}
    for d in dicts:
        for idx, cands in d.items():
            merged.setdefault(idx, []).extend(cands)
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# SIMULACION 4-SLOT DEDICADO
# Problema: simulate_sleeves solo soporta primary + secondary.
# Para 4 slots DEDICADOS (2 V11 + 1 D + 1 E) implementamos un wrapper:
#   - primary_pending   = v11_pending  | primary_slots   = 2
#   - secondary_pending = merge(d, e)  | secondary_slots = 2
# El ranking por raw_score determina cuales 2 candidatos llenan los slots.
# ─────────────────────────────────────────────────────────────────────────────

def sim4(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    v11_pend: dict[int, list[Candidate]],
    sec_pend: dict[int, list[Candidate]],
    label: str,
) -> dict:
    """Portfolio 4-slot: 2 V11 + 2 del pool secundario."""
    result = simulate_sleeves(
        prepared, dates,
        v11_pend,
        primary_slots=V11_PRIMARY_SLOTS,          # 2 V11
        secondary_pending=sec_pend,
        secondary_slots=2,                         # 2 slots del pool secundario
    )
    return result


def sim3(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    v11_pend: dict[int, list[Candidate]],
    sec_pend: dict[int, list[Candidate]],
) -> dict:
    """Portfolio 3-slot baseline: 2 V11 + 1 secundario."""
    return simulate_sleeves(
        prepared, dates,
        v11_pend,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=sec_pend,
        secondary_slots=LEADERSHIP_SLOTS,          # 1 slot
    )


def print_delta(label: str, result: dict, ref_metrics: dict) -> None:
    m = result["metrics"]
    ds = m.get("sharpe", 0.0) - ref_metrics.get("sharpe", 0.0)
    dw = m.get("wr", 0.0)     - ref_metrics.get("wr", 0.0)
    dd = m.get("mdd", 0.0)    - ref_metrics.get("mdd", 0.0)
    n  = int(m.get("trades", 0))
    print(
        f"  {label:<28s}  sh {m.get('sharpe',0):>5.2f} ({ds:>+5.2f})"
        f"  wr {m.get('wr',0):>5.1f}% ({dw:>+5.1f}%)"
        f"  mdd {m.get('mdd',0):>+6.1f}% ({dd:>+5.1f}%)"
        f"  total {m.get('total',0):>+8.1f}%  n={n}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# WALK-FORWARD PARA ARQUITECTURAS
# ─────────────────────────────────────────────────────────────────────────────

def wf_architecture(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    v11_pend: dict[int, list[Candidate]],
    sec_pend: dict[int, list[Candidate]],
    sec_slots: int,
    label: str,
    n_windows: int = 7,
) -> dict:
    total = len(dates)
    window_size = total // n_windows
    results = []

    for w in range(n_windows):
        s = w * window_size
        e = s + window_size if w < n_windows - 1 else total
        s = max(s, START_IDX + 252 + 10)

        wp = {idx: c for idx, c in v11_pend.items() if s <= idx < e}
        ws = {idx: c for idx, c in sec_pend.items() if s <= idx < e}

        if not wp and not ws:
            results.append({"window": w + 1, "sharpe": 0.0, "wr": 0.0, "trades": 0})
            continue

        sim = simulate_sleeves(
            prepared, dates, wp,
            primary_slots=V11_PRIMARY_SLOTS,
            secondary_pending=ws,
            secondary_slots=sec_slots,
            start_idx=s, end_idx=e,
        )
        m = sim["metrics"]
        results.append({
            "window": w + 1,
            "sharpe": m.get("sharpe", 0.0),
            "wr": m.get("wr", 0.0),
            "trades": m.get("trades", 0),
        })

    wins = sum(1 for r in results if r["sharpe"] > 0)
    return {"windows": results, "wins": wins, "total": n_windows}


def print_wf(wf: dict, label: str) -> None:
    print(f"  WF {label}:")
    for r in wf["windows"]:
        icon = "+" if r["sharpe"] > 0 else "-"
        print(f"    V{r['window']} [{icon}] sh {r['sharpe']:>+5.2f}  WR {r['wr']:>5.1f}%  n {int(r['trades']):>3d}")
    print(f"  => {wf['wins']}/{wf['total']} ventanas positivas")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print(LINE)
    print("  INVESTIGACION V22 - PORTFOLIO 4 SLOTS")
    print(LINE)
    print("  Pregunta: agregar E_BEST3 como 4to sleeve mejora el Sharpe de V12?")
    print()

    # [0] Carga
    print("[0] Cargando universo...")
    prepared_base, dates = prepare_universe()
    prepared = extend_precompute(prepared_base)
    print(f"  DB: {dates[0].date()} -> {dates[-1].date()}")
    print()

    # [1] Candidatos base
    print("[1] Construyendo candidatos...")
    v11_pend, v11_rows = build_v11_candidates(prepared, dates)
    d_pend,   d_rows   = build_d_candidates(prepared, dates, params=D_STRICT_REF, hold_days=LEADERSHIP_HOLD_DEFAULT)

    e_best3_pend, e_best3_rows = build_sector_candidates(
        prepared, dates, signal_e, "E_BEST3", BEST3_TICKERS, HOLD_E
    )
    e_hw_pend, e_hw_rows = build_sector_candidates(
        prepared, dates, signal_e, "E_HW", HW_TICKERS, HOLD_E
    )
    e_travel_pend, e_travel_rows = build_sector_candidates(
        prepared, dates, signal_e, "E_TRAVEL", TRAVEL_TICKERS, HOLD_E
    )

    m_d      = per_trade_metrics(d_rows)
    m_best3  = per_trade_metrics(e_best3_rows)
    m_hw     = per_trade_metrics(e_hw_rows)
    m_travel = per_trade_metrics(e_travel_rows)

    print(f"  V11   : {len(v11_rows):>5d} trades")
    print(f"  D     : {m_d['trades']:>5d} trades | WR {m_d['wr']:.1f}% | avg {m_d['avg']:+.2f}%")
    print(f"  BEST3 : {m_best3['trades']:>5d} trades | WR {m_best3['wr']:.1f}% | avg {m_best3['avg']:+.2f}%")
    print(f"  HW    : {m_hw['trades']:>5d} trades | WR {m_hw['wr']:.1f}% | avg {m_hw['avg']:+.2f}%")
    print(f"  TRAVEL: {m_travel['trades']:>5d} trades | WR {m_travel['wr']:.1f}% | avg {m_travel['avg']:+.2f}%")
    print()

    # -------------------------------------------------------------------------
    # [2] PORTFOLIO COMPARACION
    # -------------------------------------------------------------------------
    print(LINE)
    print("[2] COMPARACION DE ARQUITECTURAS (full period)")
    print(SUBLINE)
    print(f"  {'Arquitectura':<28s}  {'Sharpe':>10s}  {'WR':>12s}  {'MDD':>14s}  {'Total':>14s}  n")
    print(f"  {'-'*28}  {'-'*10}  {'-'*12}  {'-'*14}  {'-'*14}  -")

    # BASE: V12 (2 V11 + 1 D)
    base_sim = sim3(prepared, dates, v11_pend, d_pend)
    base_m   = base_sim["metrics"]
    print_delta("BASE: 2V11 + 1D (V12)", base_sim, {"sharpe": 0, "wr": 0, "mdd": 0})

    # Control A: 2 V11 + 2 D
    ctrl_d_pend = merge_pending(d_pend, d_pend)  # duplicar D
    ctrl_a_sim  = sim4(prepared, dates, v11_pend, d_pend, "2V11+2D")
    print_delta("[A] 2V11 + 2D", ctrl_a_sim, base_m)

    # [B] 2 V11 + D + E_BEST3 (compiten por 2 slots sec)
    b_pend  = merge_pending(d_pend, e_best3_pend)
    b_sim   = sim4(prepared, dates, v11_pend, b_pend, "2V11+D+BEST3")
    print_delta("[B] 2V11 + D + E_BEST3", b_sim, base_m)

    # [C] 2 V11 + D + E_HW
    c_pend = merge_pending(d_pend, e_hw_pend)
    c_sim  = sim4(prepared, dates, v11_pend, c_pend, "2V11+D+HW")
    print_delta("[C] 2V11 + D + E_HW", c_sim, base_m)

    # [D] 2 V11 + D + E_TRAVEL
    d2_pend = merge_pending(d_pend, e_travel_pend)
    d2_sim  = sim4(prepared, dates, v11_pend, d2_pend, "2V11+D+TRAVEL")
    print_delta("[D] 2V11 + D + E_TRAVEL", d2_sim, base_m)

    # [E] 2 V11 + 2 E_BEST3 (sin D, pura BEST3)
    e_pend_double = merge_pending(e_best3_pend, e_best3_pend)
    e_sim = sim4(prepared, dates, v11_pend, e_best3_pend, "2V11+2BEST3")
    e_sim_real = simulate_sleeves(
        prepared, dates, v11_pend,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=e_best3_pend,
        secondary_slots=2,
    )
    print_delta("[E] 2V11 + 2 E_BEST3 (sin D)", e_sim_real, base_m)

    # [F] 3 V11 + 1 D (mas V11 en vez de mas E)
    f_sim = simulate_sleeves(
        prepared, dates, v11_pend,
        primary_slots=3,
        secondary_pending=d_pend,
        secondary_slots=1,
    )
    print_delta("[F] 3V11 + 1D", f_sim, base_m)

    # [G] 3 V11 + 1 E_BEST3 (sin D)
    g_sim = simulate_sleeves(
        prepared, dates, v11_pend,
        primary_slots=3,
        secondary_pending=e_best3_pend,
        secondary_slots=1,
    )
    print_delta("[G] 3V11 + 1 E_BEST3", g_sim, base_m)
    print()

    # -------------------------------------------------------------------------
    # [3] WALK-FORWARD del mejor candidato
    # -------------------------------------------------------------------------
    print(LINE)
    print("[3] WALK-FORWARD 7 VENTANAS")
    print(SUBLINE)

    # Identificar ganador por Sharpe
    candidates = [
        ("[A] 2V11+2D",      ctrl_a_sim, d_pend,    2),
        ("[B] 2V11+D+BEST3", b_sim,      b_pend,    2),
        ("[C] 2V11+D+HW",    c_sim,      c_pend,    2),
        ("[D] 2V11+D+TRAVEL",d2_sim,     d2_pend,   2),
        ("[E] 2V11+2BEST3",  e_sim_real, e_best3_pend, 2),
        ("[F] 3V11+1D",      f_sim,      d_pend,    1),
        ("[G] 3V11+1BEST3",  g_sim,      e_best3_pend, 1),
    ]
    candidates.sort(key=lambda x: x[1]["metrics"].get("sharpe", 0.0), reverse=True)

    print("  Ranking por Sharpe:")
    for name, sim, _, _ in candidates:
        m = sim["metrics"]
        flag = " <-- MEJOR" if name == candidates[0][0] else ""
        beat = " [SUPERA V12]" if m.get("sharpe", 0) > base_m.get("sharpe", 0) else ""
        print(f"    {name:<24s} sh {m.get('sharpe',0):>5.2f} | WR {m.get('wr',0):>5.1f}% | "
              f"mdd {m.get('mdd',0):>+6.1f}%{flag}{beat}")

    print()
    best_name, best_sim, best_pend, best_sec_slots = candidates[0]
    print(f"  Walk-forward completo del mejor: {best_name}")
    wf_best = wf_architecture(prepared, dates, v11_pend, best_pend, best_sec_slots, best_name)
    print_wf(wf_best, best_name)

    # Tambien WF de [B] si no es el mejor (B es el que mas nos interesa)
    if best_name != "[B] 2V11+D+BEST3":
        print()
        print("  Walk-forward de [B] 2V11+D+BEST3 (candidato de interes):")
        wf_b = wf_architecture(prepared, dates, v11_pend, b_pend, 2, "[B]")
        print_wf(wf_b, "[B] 2V11+D+BEST3")
    else:
        wf_b = wf_best

    print()

    # -------------------------------------------------------------------------
    # [4] ANALISIS DE OVERLAP D vs E_BEST3
    # -------------------------------------------------------------------------
    print(LINE)
    print("[4] ANALISIS DE OVERLAP D vs E_BEST3")
    print(SUBLINE)

    # Dias en que ambas senales disparan
    d_days   = set(d_pend.keys())
    e_days   = set(e_best3_pend.keys())
    overlap  = d_days & e_days
    solo_d   = d_days - e_days
    solo_e   = e_days - d_days

    print(f"  Dias con D disponible    : {len(d_days)}")
    print(f"  Dias con BEST3 disponible: {len(e_days)}")
    print(f"  Overlap (ambas)          : {len(overlap)} dias ({len(overlap)/len(d_days|e_days)*100:.1f}%)")
    print(f"  Solo D disponible        : {len(solo_d)} dias")
    print(f"  Solo BEST3 disponible    : {len(solo_e)} dias")
    print(f"  Dias con al menos 1      : {len(d_days|e_days)} dias")
    print()
    print(f"  Interpretacion:")
    if len(overlap) < len(d_days) * 0.3:
        print(f"    Bajo overlap ({len(overlap)/(len(d_days|e_days))*100:.1f}%) -> senales complementarias, ")
        print(f"    cada una llena el slot en momentos distintos -> 4 slots AGREGAN valor.")
    else:
        print(f"    Alto overlap -> muchos dias con ambas -> compiten por el mismo slot,")
        print(f"    la ganancia del 4to slot es menor.")

    # -------------------------------------------------------------------------
    # [5] ANALISIS RIESGO 4-SLOT
    # -------------------------------------------------------------------------
    print()
    print(LINE)
    print("[5] RIESGO vs RETORNO (3-slot vs 4-slot)")
    print(SUBLINE)

    def risk_row(label: str, sim: dict) -> None:
        m = sim["metrics"]
        sharpe = m.get("sharpe", 0.0)
        mdd    = m.get("mdd", 0.0)
        wr     = m.get("wr", 0.0)
        total  = m.get("total", 0.0)
        calmar = total / abs(mdd) if mdd != 0 else 0.0
        print(f"  {label:<28s}  Sharpe {sharpe:>5.2f}  MDD {mdd:>+6.1f}%  WR {wr:>5.1f}%  Total {total:>+8.1f}%  Calmar {calmar:>6.2f}")

    risk_row("BASE V12 (3-slot)", base_sim)
    for name, sim, _, _ in candidates[:4]:
        risk_row(name, sim)

    # -------------------------------------------------------------------------
    # [6] VEREDICTO
    # -------------------------------------------------------------------------
    print()
    print(LINE)
    print("  VEREDICTO V22")
    print(LINE)

    best_m = best_sim["metrics"]
    base_sharpe = base_m.get("sharpe", 0.0)
    best_sharpe = best_m.get("sharpe", 0.0)

    winners = [(n, s, p, ss) for n, s, p, ss in candidates
               if s["metrics"].get("sharpe", 0) > base_sharpe]

    print(f"  Referencia V12: Sharpe {base_sharpe:.2f} | WR {base_m.get('wr',0):.1f}% | MDD {base_m.get('mdd',0):+.1f}%")
    print()

    if winners:
        print(f"  Arquitecturas que SUPERAN V12 en Sharpe ({len(winners)} encontradas):")
        for name, sim, pend, sec_slots in winners:
            m = sim["metrics"]
            delta = m.get("sharpe", 0) - base_sharpe
            print(f"    {name}: Sharpe {m.get('sharpe',0):.2f} ({delta:+.3f}) | WR {m.get('wr',0):.1f}% | MDD {m.get('mdd',0):+.1f}%")
        print()
        print("  Conclusion: EXISTE una arquitectura de 4 slots que supera V12.")
        # Walk-forward del top ganador
        top_name, top_sim, top_pend, top_sec = winners[0]
        wf_top = wf_architecture(prepared, dates, v11_pend, top_pend, top_sec, top_name)
        print(f"  WF del ganador ({top_name}): {wf_top['wins']}/{wf_top['total']} ventanas positivas")
        if wf_top["wins"] >= 4:
            print(f"  => WF PASS ({wf_top['wins']}/7). Candidato solido para investigacion de promocion.")
        else:
            print(f"  => WF INSUFICIENTE ({wf_top['wins']}/7). Mejora IS, no OOS. No promover aun.")
    else:
        print("  Ninguna arquitectura de 4 slots supera a V12 en Sharpe.")
        second_best = sorted(candidates, key=lambda x: x[1]["metrics"].get("sharpe", 0), reverse=True)[0]
        print(f"  Mejor alternativa: {second_best[0]} con Sharpe {second_best[1]['metrics'].get('sharpe',0):.2f}")
        print()
        print("  Interpretacion: agregar un 4to slot aumenta el capital desplegado pero")
        print("  no mejora la calidad de las senales. El edge de V12 es eficiente con 3 slots.")
        print()
        print("  Proximas hipotesis a explorar:")
        print("  1. Mejorar la CALIDAD de D (no la cantidad de slots)")
        print("  2. Explorar hold periods mas cortos en E_BEST3 para aumentar frecuencia")
        print("  3. Investigar señales de timing de mercado (VIX, breadth) como gate adicional")

    print(LINE)


if __name__ == "__main__":
    main()
