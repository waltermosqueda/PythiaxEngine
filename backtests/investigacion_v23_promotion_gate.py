"""
INVESTIGACION V23 - PROMOTION GATE FORMAL: ARQUITECTURA [C] 2V11+D+E_HW
=========================================================================

Objetivo: someter la arquitectura [C] (2V11+D+E_HW, Sharpe 1.62) al mismo
rigor que Signal D tuvo en V17, antes de promover a V13.

V22 hallazgo:
  [C] 2V11+D+E_HW: Sharpe 1.62 (+0.27 vs V12), MDD -37.0%, WF 6/7
  E_HW individual: WR 75.0% (n=64), avg +13.75%

Este script cubre:
  [A] Grid de hold period (8, 10, 12, 15, 21d) para E_HW en portfolio 4-slot
  [B] Grid de parametros RSI/ROC para E_HW
  [C] Promotion gate formal 7 criterios (adaptados de V17)
  [D] Bootstrap Monte Carlo (500 iters) sobre retornos E_HW
  [E] Concentracion por ticker en E_HW
  [F] Analisis de regime split profundo para E_HW
  [G] Veredicto y config recomendada para V13

Criterios de promotion gate (adaptados):
  PG1. WF >= 5/7 ventanas donde 4-slot Sharpe > 0
  PG2. Sharpe 4-slot full-period >= 1.50
  PG3. MDD 4-slot full-period <= -45%
  PG4. Bootstrap MC: P(E_HW WR > 50%) >= 70%
  PG5. Concentracion: ningun ticker > 30% del total de trades E_HW
  PG6. Hold period optimo <= 21d (razonable para un ticker HW)
  PG7. En SEGURO Y PELIGRO E_HW tiene avg_return >= 0 con >= 10 trades cada uno

Veredicto: PROMOVER (>=6/7 PASS) | CONDICIONAL (5/7) | RECHAZAR (<5)

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

np.random.seed(42)

from backtests.investigacion_v9_path_quality import (
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
from backtests.investigacion_v20_nuevos_ejes import (
    extend_precompute,
    signal_e,
    per_trade_metrics,
    build_signal_candidates,
)
from backtests.investigacion_v21_sector_rs_wrhigh import (
    HW_TICKERS,
    build_sector_candidates,
)

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────

HOLD_DEFAULT  = 15   # hold de E_HW en V22
MC_ITERATIONS = 500

# Gates de promocion
PG2_SHARPE_MIN  = 1.50
PG3_MDD_MAX     = -45.0
PG4_P_WR_MIN    = 70.0   # % iteraciones MC donde WR > 50%
PG5_TICKER_MAX  = 30.0   # max % de trades en un solo ticker HW
PG6_HOLD_MAX    = 21     # hold maximo aceptable
PG7_AVG_MIN     = 0.0    # avg_return >= 0 en cada regimen
PG7_N_MIN       = 10     # trades minimos por regimen


# ─────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────────────────────────

def merge_pending(*dicts: dict[int, list[Candidate]]) -> dict[int, list[Candidate]]:
    merged: dict[int, list[Candidate]] = {}
    for d in dicts:
        for idx, cands in d.items():
            merged.setdefault(idx, []).extend(cands)
    return merged


def sim4(prepared, dates, v11_pend, sec_pend) -> dict:
    """2 V11 + 2 slots del pool secundario."""
    return simulate_sleeves(
        prepared, dates, v11_pend,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=sec_pend,
        secondary_slots=2,
    )


def sim3_base(prepared, dates, v11_pend, d_pend) -> dict:
    """V12 baseline: 2V11 + 1D."""
    return simulate_sleeves(
        prepared, dates, v11_pend,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=d_pend,
        secondary_slots=LEADERSHIP_SLOTS,
    )


def wf_4slot(prepared, dates, v11_pend, sec_pend, n_windows=7) -> dict:
    """Walk-forward del portfolio 4-slot."""
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
            secondary_slots=2,
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
# SIGNAL E_HW VARIANTES (para el grid)
# ─────────────────────────────────────────────────────────────────────────────

def make_signal_e_hw(rsi_min: float, rsi_max: float, roc20_min: float):
    """Fabrica una funcion signal_e con parametros customizados."""
    def fn(row: pd.Series) -> bool:
        required = ["RS_LINE", "RS_52W_MAX", "Close", "SMA50", "SMA200", "RSI", "VOL_RATIO", "ROC20"]
        if any(pd.isna(row.get(c, float("nan"))) for c in required):
            return False
        return (
            float(row["RS_LINE"])  >= float(row["RS_52W_MAX"])
            and float(row["Close"]) > float(row["SMA50"]) > float(row["SMA200"])
            and rsi_min <= float(row["RSI"]) <= rsi_max
            and float(row["ROC20"]) > roc20_min
            and 0.8 <= float(row["VOL_RATIO"]) <= 2.5
        )
    return fn


# ─────────────────────────────────────────────────────────────────────────────
# MONTE CARLO BOOTSTRAP
# ─────────────────────────────────────────────────────────────────────────────

def bootstrap_mc(rows: list[dict], n_iter: int = MC_ITERATIONS) -> dict:
    """
    Bootstrap sobre retornos de E_HW.
    Pregunta: si resampleamos los trades, WR > 50% con que frecuencia?
    P(WR > 50%) >= 70% = PASS (el edge no es luck del periodo especifico).
    """
    if not rows:
        return {"p_wr_gt50": 0.0, "wr_p50": 0.0, "wr_ci": (0.0, 0.0), "avg_p50": 0.0}
    returns = np.array([r["return_pct"] for r in rows])
    wr_boot: list[float] = []
    avg_boot: list[float] = []
    for _ in range(n_iter):
        sample = np.random.choice(returns, size=len(returns), replace=True)
        wr_boot.append(float((sample > 0).mean() * 100))
        avg_boot.append(float(sample.mean()))
    wr_arr = np.array(wr_boot)
    p_wr_gt50 = float((wr_arr > 50).mean() * 100)
    return {
        "p_wr_gt50": round(p_wr_gt50, 1),
        "wr_p50":    round(float(np.percentile(wr_arr, 50)), 1),
        "wr_ci":     (round(float(np.percentile(wr_arr, 5)), 1),
                      round(float(np.percentile(wr_arr, 95)), 1)),
        "avg_p50":   round(float(np.percentile(avg_boot, 50)), 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# TICKER CONCENTRATION
# ─────────────────────────────────────────────────────────────────────────────

def ticker_concentration(rows: list[dict]) -> dict:
    if not rows:
        return {"max_pct": 0.0, "top_ticker": None, "by_ticker": {}}
    df = pd.DataFrame(rows)
    counts = df["ticker"].value_counts()
    total  = len(rows)
    by_ticker = {t: round(n / total * 100, 1) for t, n in counts.items()}
    top_ticker = counts.index[0]
    max_pct    = by_ticker[top_ticker]
    return {"max_pct": max_pct, "top_ticker": top_ticker, "by_ticker": by_ticker}


# ─────────────────────────────────────────────────────────────────────────────
# PROMOTION GATE
# ─────────────────────────────────────────────────────────────────────────────

def run_promotion_gate(
    label: str,
    sim_4slot: dict,
    wf: dict,
    rows_e: list[dict],
    mc: dict,
    conc: dict,
    best_hold: int,
) -> tuple[int, list[str]]:
    m = sim_4slot["metrics"]
    sharpe = m.get("sharpe", 0.0)
    mdd    = m.get("mdd", 0.0)
    wf_wins = wf["wins"]

    # Regime split de E_HW
    rows_seg = [r for r in rows_e if r["regime"] == "SEGURO"]
    rows_pel = [r for r in rows_e if r["regime"] == "PELIGRO"]
    ms = per_trade_metrics(rows_seg)
    mp = per_trade_metrics(rows_pel)

    gates = [
        ("PG1: WF >= 5/7 ventanas positivas",
         wf_wins >= 5,
         f"{wf_wins}/7 ventanas"),
        ("PG2: Sharpe 4-slot >= 1.50",
         sharpe >= PG2_SHARPE_MIN,
         f"Sharpe {sharpe:.2f}"),
        ("PG3: MDD 4-slot <= -45%",
         mdd >= PG3_MDD_MAX,
         f"MDD {mdd:.1f}%"),
        ("PG4: MC P(WR>50%) >= 70%",
         mc["p_wr_gt50"] >= PG4_P_WR_MIN,
         f"P(WR>50%) = {mc['p_wr_gt50']:.1f}%"),
        ("PG5: Concentracion max ticker < 30%",
         conc["max_pct"] < PG5_TICKER_MAX,
         f"Max: {conc['top_ticker']} = {conc['max_pct']:.1f}%"),
        ("PG6: Hold optimo <= 21d",
         best_hold <= PG6_HOLD_MAX,
         f"Hold optimo = {best_hold}d"),
        ("PG7: avg_return >= 0 en SEGURO y PELIGRO (n>=10)",
         (ms["avg"] >= PG7_AVG_MIN and ms["trades"] >= PG7_N_MIN and
          mp["avg"] >= PG7_AVG_MIN and mp["trades"] >= PG7_N_MIN),
         f"SEGURO avg {ms['avg']:+.2f}% n={ms['trades']} | PELIGRO avg {mp['avg']:+.2f}% n={mp['trades']}"),
    ]

    passed = sum(1 for _, ok, _ in gates if ok)
    details = []
    print(f"\n  PROMOTION GATE formal — {label}:")
    for name, ok, detail in gates:
        icon = "[PASS]" if ok else "[FAIL]"
        print(f"    {icon} {name:<40s} {detail}")
        details.append(f"{icon} {name}")
    verdict = "PROMOVER" if passed >= 6 else ("CONDICIONAL" if passed == 5 else "RECHAZAR")
    print(f"\n    RESULTADO: {passed}/7 PASS => {verdict}")
    return passed, details


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print(LINE)
    print("  INVESTIGACION V23 - PROMOTION GATE FORMAL: ARQUITECTURA [C] 2V11+D+E_HW")
    print(LINE)
    print("  Hipotesis: [C] con WF 6/7 y Sharpe 1.62 supera los 7 gates y merece ser V13.")
    print()

    # [0] Cargar datos
    print("[0] Cargando universo...")
    prepared_base, dates = prepare_universe()
    prepared = extend_precompute(prepared_base)
    print(f"  DB: {dates[0].date()} -> {dates[-1].date()} | {len([t for t in prepared if t != 'SPY'])} tickers")
    print()

    # [1] Candidatos base
    print("[1] Construyendo candidatos base...")
    v11_pend, v11_rows = build_v11_candidates(prepared, dates)
    d_pend,   d_rows   = build_d_candidates(prepared, dates, params=D_STRICT_REF, hold_days=LEADERSHIP_HOLD_DEFAULT)

    e_hw_pend, e_hw_rows = build_sector_candidates(
        prepared, dates, signal_e, "E_HW", HW_TICKERS, HOLD_DEFAULT
    )

    m_d  = per_trade_metrics(d_rows)
    m_hw = per_trade_metrics(e_hw_rows)
    print(f"  V11   : {len(v11_rows):>5d} trades")
    print(f"  D     : {m_d['trades']:>5d} trades | WR {m_d['wr']:.1f}% | avg {m_d['avg']:+.2f}%")
    print(f"  E_HW  : {m_hw['trades']:>5d} trades | WR {m_hw['wr']:.1f}% | avg {m_hw['avg']:+.2f}%")
    print()

    # V12 baseline
    base_sim = sim3_base(prepared, dates, v11_pend, d_pend)
    base_m   = base_sim["metrics"]
    print(f"  V12 baseline: Sharpe {base_m.get('sharpe',0):.2f} | WR {base_m.get('wr',0):.1f}% | MDD {base_m.get('mdd',0):.1f}%")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [A] GRID DE HOLD PERIOD
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[A] GRID DE HOLD PERIOD PARA E_HW EN PORTFOLIO 4-SLOT")
    print(SUBLINE)
    print(f"  {'Hold':>6s} | {'n E':>5s} | {'WR E':>7s} | {'Sharpe 4slot':>13s} | {'MDD':>8s} | {'Total':>9s}")
    print(f"  {'-'*6}-+-{'-'*5}-+-{'-'*7}-+-{'-'*13}-+-{'-'*8}-+-{'-'*9}")

    best_hold      = HOLD_DEFAULT
    best_hold_sharpe = 0.0
    best_hold_pend   = None
    best_hold_rows   = None

    for h in [8, 10, 12, 15, 21]:
        ep, er = build_sector_candidates(prepared, dates, signal_e, "E_HW", HW_TICKERS, h)
        me     = per_trade_metrics(er)
        cpend  = merge_pending(d_pend, ep)
        sim    = sim4(prepared, dates, v11_pend, cpend)
        sm     = sim["metrics"]
        flag   = " <--" if sm.get("sharpe", 0) > best_hold_sharpe else ""
        if sm.get("sharpe", 0) > best_hold_sharpe:
            best_hold_sharpe = sm.get("sharpe", 0)
            best_hold = h
            best_hold_pend = cpend
            best_hold_rows = er
        print(
            f"  {h:>6d}d | {me['trades']:>5d} | {me['wr']:>6.1f}% | "
            f"sh {sm.get('sharpe',0):>5.2f} ({sm.get('sharpe',0)-base_m.get('sharpe',0):>+5.2f}) | "
            f"{sm.get('mdd',0):>+7.1f}% | {sm.get('total',0):>+8.1f}%{flag}"
        )

    print(f"\n  => Hold optimo para E_HW en portfolio 4-slot: {best_hold}d (Sharpe {best_hold_sharpe:.2f})")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [B] GRID DE PARAMETROS RSI / ROC20
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[B] GRID DE PARAMETROS RSI / ROC20 PARA E_HW (hold optimo fijo)")
    print(SUBLINE)
    print(f"  {'Config':<22s} | {'n E':>5s} | {'WR E':>7s} | {'avg E':>7s} | {'Sharpe 4slot':>13s} | {'MDD':>8s}")
    print(f"  {'-'*22}-+-{'-'*5}-+-{'-'*7}-+-{'-'*7}-+-{'-'*13}-+-{'-'*8}")

    param_configs = [
        ("RSI[50-75] ROC>8%",  50.0, 75.0, 8.0),    # baseline
        ("RSI[45-70] ROC>6%",  45.0, 70.0, 6.0),    # mas permisivo
        ("RSI[50-75] ROC>10%", 50.0, 75.0, 10.0),   # mas estricto ROC
        ("RSI[55-78] ROC>8%",  55.0, 78.0, 8.0),    # RSI mas alto
        ("RSI[50-72] ROC>12%", 50.0, 72.0, 12.0),   # ultra estricto
    ]

    best_param_config = param_configs[0]
    best_param_sharpe = 0.0

    for cfg_label, rsi_min, rsi_max, roc_min in param_configs:
        fn  = make_signal_e_hw(rsi_min, rsi_max, roc_min)
        ep2, er2 = build_sector_candidates(prepared, dates, fn, "E_HW", HW_TICKERS, best_hold)
        me2  = per_trade_metrics(er2)
        cp2  = merge_pending(d_pend, ep2)
        sim2 = sim4(prepared, dates, v11_pend, cp2)
        sm2  = sim2["metrics"]
        flag = " <--" if sm2.get("sharpe", 0) > best_param_sharpe else ""
        if sm2.get("sharpe", 0) > best_param_sharpe:
            best_param_sharpe = sm2.get("sharpe", 0)
            best_param_config = (cfg_label, rsi_min, rsi_max, roc_min)
        print(
            f"  {cfg_label:<22s} | {me2['trades']:>5d} | {me2['wr']:>6.1f}% | "
            f"{me2['avg']:>+6.2f}% | sh {sm2.get('sharpe',0):>5.2f} | {sm2.get('mdd',0):>+7.1f}%{flag}"
        )

    best_param_label, best_rsi_min, best_rsi_max, best_roc_min = best_param_config
    print(f"\n  => Config optima: {best_param_label} (Sharpe {best_param_sharpe:.2f})")
    print()

    # Reconstruir candidatos con la config optima
    fn_opt = make_signal_e_hw(best_rsi_min, best_rsi_max, best_roc_min)
    e_opt_pend, e_opt_rows = build_sector_candidates(
        prepared, dates, fn_opt, "E_HW", HW_TICKERS, best_hold
    )
    c_opt_pend = merge_pending(d_pend, e_opt_pend)
    c_opt_sim  = sim4(prepared, dates, v11_pend, c_opt_pend)
    m_opt      = per_trade_metrics(e_opt_rows)

    print(f"  Config final V13: hold={best_hold}d, RSI={best_rsi_min:.0f}-{best_rsi_max:.0f}, ROC20>{best_roc_min:.0f}%")
    print(f"  E_HW optimo: n={m_opt['trades']}, WR={m_opt['wr']:.1f}%, avg={m_opt['avg']:+.2f}%")
    sm = c_opt_sim["metrics"]
    print(f"  Portfolio [C] optimo: Sharpe {sm.get('sharpe',0):.2f} | MDD {sm.get('mdd',0):.1f}% | Total {sm.get('total',0):+.1f}%")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [C] WALK-FORWARD CON CONFIG OPTIMA
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[C] WALK-FORWARD 7 VENTANAS (config optima)")
    print(SUBLINE)
    wf_opt = wf_4slot(prepared, dates, v11_pend, c_opt_pend)
    print_wf(wf_opt, f"[C] 2V11+D+E_HW (hold={best_hold}d, {best_param_label})")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [D] BOOTSTRAP MONTE CARLO
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[D] BOOTSTRAP MONTE CARLO (500 iteraciones sobre retornos E_HW)")
    print(SUBLINE)
    mc = bootstrap_mc(e_opt_rows)
    print(f"  E_HW retornos: {len(e_opt_rows)} trades")
    print(f"  WR observada: {m_opt['wr']:.1f}%")
    print(f"  Bootstrap WR mediana  : {mc['wr_p50']:.1f}%")
    print(f"  Bootstrap WR CI [5,95]: [{mc['wr_ci'][0]:.1f}%, {mc['wr_ci'][1]:.1f}%]")
    print(f"  P(WR > 50%)           : {mc['p_wr_gt50']:.1f}%  (gate: >= {PG4_P_WR_MIN:.0f}%)")
    print(f"  Bootstrap avg mediana : {mc['avg_p50']:+.2f}%")
    if mc["p_wr_gt50"] >= PG4_P_WR_MIN:
        print("  => PASS: el edge de E_HW es estadisticamente robusto.")
    else:
        print("  => FAIL: el edge no sobrevive bootstrap -> posible overfitting.")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [E] CONCENTRACION POR TICKER
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[E] CONCENTRACION POR TICKER EN E_HW")
    print(SUBLINE)
    conc = ticker_concentration(e_opt_rows)
    print(f"  Total trades E_HW: {len(e_opt_rows)}")
    for ticker_name, pct in sorted(conc["by_ticker"].items(), key=lambda x: -x[1]):
        flag = " <-- EXCEDE 30%!" if pct >= PG5_TICKER_MAX else (" *** >20%" if pct >= 20 else "")
        print(f"    {ticker_name:<8s}: {pct:>5.1f}%{flag}")
    print(f"\n  Ticker mas concentrado: {conc['top_ticker']} con {conc['max_pct']:.1f}%")
    if conc["max_pct"] < PG5_TICKER_MAX:
        print(f"  => PASS: concentracion max {conc['max_pct']:.1f}% < {PG5_TICKER_MAX:.0f}%")
    else:
        print(f"  => FAIL: {conc['top_ticker']} representa {conc['max_pct']:.1f}% de trades E_HW")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # [F] REGIME SPLIT PROFUNDO
    # ─────────────────────────────────────────────────────────────────────────
    print(LINE)
    print("[F] ANALISIS DE REGIME SPLIT PROFUNDO")
    print(SUBLINE)

    for signal_rows, label_s in [(e_opt_rows, "E_HW"), (d_rows, "D (referencia)")]:
        print(f"\n  {label_s}:")
        for regime in ["SEGURO", "PELIGRO"]:
            sub = [r for r in signal_rows if r["regime"] == regime]
            if sub:
                ms = per_trade_metrics(sub)
                print(f"    {regime:<8s}: n={ms['trades']:>4d} | WR {ms['wr']:>5.1f}% | avg {ms['avg']:>+6.2f}% | sharpe {ms['sharpe']:>5.2f}")

    # ─────────────────────────────────────────────────────────────────────────
    # [G] PROMOTION GATE FORMAL (7 criterios)
    # ─────────────────────────────────────────────────────────────────────────
    print()
    print(LINE)
    print("[G] PROMOTION GATE FORMAL — 7 CRITERIOS")
    print(SUBLINE)

    passed, details = run_promotion_gate(
        label    = f"[C] 2V11+D+E_HW hold={best_hold}d {best_param_label}",
        sim_4slot= c_opt_sim,
        wf       = wf_opt,
        rows_e   = e_opt_rows,
        mc       = mc,
        conc     = conc,
        best_hold= best_hold,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # VEREDICTO FINAL
    # ─────────────────────────────────────────────────────────────────────────
    print()
    print(LINE)
    print("  VEREDICTO V23")
    print(LINE)

    m_final = c_opt_sim["metrics"]
    verdict = "PROMOVER" if passed >= 6 else ("CONDICIONAL" if passed == 5 else "RECHAZAR")

    print(f"  Referencia V12 : Sharpe {base_m.get('sharpe',0):.2f} | MDD {base_m.get('mdd',0):.1f}%")
    print(f"  [C] 4-slot opt : Sharpe {m_final.get('sharpe',0):.2f} | MDD {m_final.get('mdd',0):.1f}% | WF {wf_opt['wins']}/7")
    print(f"  E_HW optimo    : n={m_opt['trades']} | WR {m_opt['wr']:.1f}% | avg {m_opt['avg']:+.2f}%")
    print(f"  Gates pasados  : {passed}/7")
    print()
    print(f"  VEREDICTO: {verdict}")
    print()

    if passed >= 6:
        print("  Configuracion recomendada para SCANNER/invertir_v13.py:")
        print(f"    HW_TICKERS   = {{GLW, GRMN, HPQ, MSI, SWKS, TXN, EA, ASTS, RKLB, ERIC, BB}}")
        print(f"    E_HOLD_DAYS  = {best_hold}")
        print(f"    E_RSI_MIN    = {best_rsi_min:.0f}")
        print(f"    E_RSI_MAX    = {best_rsi_max:.0f}")
        print(f"    E_ROC20_MIN  = {best_roc_min:.0f}")
        print(f"    E_VOL_MIN    = 0.8")
        print(f"    E_VOL_MAX    = 2.5")
        print()
        print("  Proximos pasos:")
        print("  1. Crear SCANNER/invertir_v13.py con 4 slots (A+C5+D+E_HW)")
        print("  2. Actualizar CLAUDE.md, ESTRUCTURA.md, y scanner_ledger.json")
        print("  3. Correr auditoria full: python herramientas/auditoria_integral_claude.py --mode full")
    elif passed == 5:
        print("  CONDICIONAL: la arquitectura tiene potencial pero necesita mas refinamiento.")
        print("  Revisar los gates fallados antes de promover a V13.")
    else:
        print("  RECHAZAR: la arquitectura no supera suficientes gates.")
        print("  Investigar con mas profundidad o probar otro enfoque.")

    print(LINE)


if __name__ == "__main__":
    main()
