"""
INVESTIGACION V21 - SECTOR RS + WR ALTA (SEGUIMIENTO DE V20)
=============================================================

Hallazgo de V20: Signal E (RS New High) tiene WR global 55.5%, pero por sector:
  HW (hardware/industriales tech): WR 75.0% con 64 trades
  Travel:                          WR 61.8% con 68 trades
  Auto:                            WR 62.5% con 56 trades

V21 investiga si este diferencial sectorial es robusto o es overfitting.

Estrategias:
  [E_HW]     Signal E restringida a sector HW
  [E_AUTO]   Signal E restringida a sector Auto
  [E_TRAVEL] Signal E restringida a sector Travel
  [E_BEST3]  Union de los 3 mejores sectores de E
  [TIGHTER]  Signal E con parametros mas estrictos (ROC20>15%, RSI 55-70) en todo el universo
  [SEMIS_E]  RS New High solo para semiconductores (NVDA, AMD, AMAT, LRCX, MU, AVGO, TSM, QCOM)

Hipotesis:
  - Si HW/Auto/Travel mantienen 65%+ WR en WF → hay un edge real de sector
  - Si colapsa en WF → era noise del periodo IS

Protocolo: per-trade + walk-forward 7 ventanas por cada variante.

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
    BROAD_UNIVERSE,
    START_IDX,
    calc_metrics,
)
from backtests.investigacion_v17_signal_d_audit import (
    Candidate,
    LINE,
    SUBLINE,
    get_sector,
    prepare_universe,
    simulate_sleeves,
    V11_PRIMARY_SLOTS,
    LEADERSHIP_SLOTS,
    build_v11_candidates,
    build_d_candidates,
    D_STRICT_REF,
    LEADERSHIP_HOLD_DEFAULT,
    print_port_row,
)
from backtests.investigacion_v20_nuevos_ejes import (
    extend_precompute,
    signal_e,
    per_trade_metrics,
    print_perf_row,
    walk_forward_7,
    build_signal_candidates,
    print_regime_split,
    print_antioverfit_checklist,
)

# Sectores de interes de V20
HW_TICKERS     = {"GLW", "GRMN", "HPQ", "MSI", "SWKS", "TXN", "EA", "ASTS", "RKLB", "ERIC", "BB"}
AUTO_TICKERS   = {"F", "GM", "HMC", "HOG", "NIO", "RACE", "STLA", "TM", "TSLA"}
TRAVEL_TICKERS = {"AAL", "ABNB", "CAR", "CCL", "DAL", "LVS", "SPCE", "TCOM", "TRIP", "UAL"}
SEMIS_TICKERS  = {"NVDA", "AMD", "AMAT", "LRCX", "MU", "AVGO", "TSM", "QCOM", "INTC", "ADI",
                   "MRVL", "ASML", "ARM", "SWKS", "TXN"}

BEST3_TICKERS = HW_TICKERS | AUTO_TICKERS | TRAVEL_TICKERS

HOLD_DEFAULT = 15


def signal_e_hw(row: pd.Series) -> bool:
    """Signal E solo para tickers HW."""
    # El filtro de sector lo aplicamos en build_sector_candidates
    return signal_e(row)


def signal_e_tighter(row: pd.Series) -> bool:
    """Signal E con filtros mas estrictos: ROC20>15%, RSI 55-70, Vol 1.0-2.0x."""
    required = ["RS_LINE", "RS_52W_MAX", "Close", "SMA50", "SMA200", "RSI", "VOL_RATIO", "ROC20"]
    if any(pd.isna(row[c]) for c in required):
        return False
    return (
        float(row["RS_LINE"])  >= float(row["RS_52W_MAX"])
        and float(row["Close"]) > float(row["SMA50"]) > float(row["SMA200"])
        and 55.0 <= float(row["RSI"]) <= 70.0
        and float(row["ROC20"]) > 15.0
        and 1.0 <= float(row["VOL_RATIO"]) <= 2.0
    )


def signal_e_ultra(row: pd.Series) -> bool:
    """Signal E ultra-estricta: RS high + ROC20>20% + RSI 58-68."""
    required = ["RS_LINE", "RS_52W_MAX", "Close", "SMA50", "SMA200", "RSI", "VOL_RATIO",
                "ROC20", "ROC60"]
    if any(pd.isna(row[c]) for c in required):
        return False
    return (
        float(row["RS_LINE"])  >= float(row["RS_52W_MAX"])
        and float(row["Close"]) > float(row["SMA50"]) > float(row["SMA200"])
        and 58.0 <= float(row["RSI"]) <= 68.0
        and float(row["ROC20"]) > 20.0
        and float(row["ROC60"]) > 30.0
        and 0.9 <= float(row["VOL_RATIO"]) <= 2.0
    )


def build_sector_candidates(
    prepared: dict[str, pd.DataFrame],
    dates: pd.DatetimeIndex,
    signal_fn,
    signal_name: str,
    allowed_tickers: set[str],
    hold_days: int = HOLD_DEFAULT,
) -> tuple[dict[int, list[Candidate]], list[dict]]:
    """Igual que build_signal_candidates pero restringe al subset de tickers."""
    start = START_IDX + 252 + 10
    pending: dict[int, list[Candidate]] = {}
    rows: list[dict] = []
    spy_df = prepared["SPY"]

    for ticker, df in prepared.items():
        if ticker == "SPY":
            continue
        if ticker not in allowed_tickers:
            continue
        n = len(dates)
        for idx in range(start, n - hold_days - 1):
            row = df.iloc[idx]
            if not signal_fn(row):
                continue
            if bool(row.get("CORP_ACTION_10D", False)):
                continue
            exit_idx = min(idx + hold_days, n - 1)
            entry_px = float(df["Close"].iloc[idx])
            exit_px  = float(df["Close"].iloc[exit_idx])
            if entry_px <= 0:
                continue
            score  = float(row.get("ROC20", 0.0)) if not pd.isna(row.get("ROC20", np.nan)) else 0.0
            regime = "SEGURO" if bool(spy_df["REGIME_SAFE"].iloc[idx]) else "PELIGRO"
            cand = Candidate(
                ticker=ticker, signal=signal_name,
                entry_idx=idx, exit_idx=exit_idx,
                raw_score=score, signal_date=dates[idx],
                regime=regime, sector=get_sector(ticker),
            )
            pending.setdefault(idx, []).append(cand)
            rows.append({
                "return_pct": (exit_px / entry_px - 1.0) * 100.0,
                "signal": signal_name, "ticker": ticker,
                "sector": get_sector(ticker), "regime": regime,
            })
    return pending, rows


def print_wf(wf: dict, label: str) -> None:
    print(f"  Walk-forward 7v ({label}):")
    for r in wf["windows"]:
        print(f"    V{r['window']} | sh {r['sharpe']:>+5.2f} | WR {r['wr']:>5.1f}% | n {int(r['trades']):>3d}")
    print(f"  => {wf['wins']}/{wf['total']} ventanas sharpe>0")


def main() -> None:
    print(LINE)
    print("  INVESTIGACION V21 — SECTOR RS + WR ALTA")
    print(LINE)
    print("  Hipotesis: el edge de WR=75% de HW en Signal E es real (no noise).")
    print()

    print("[0] Cargando y extendiendo universo...")
    prepared_base, dates = prepare_universe()
    prepared = extend_precompute(prepared_base)
    print(f"  DB: {dates[0].date()} -> {dates[-1].date()} | {len([t for t in prepared if t!='SPY'])} tickers")
    print()

    # Baseline V12
    print(LINE)
    print("[1] BASELINE V12 (referencia)")
    print(SUBLINE)
    v11_pend, v11_rows = build_v11_candidates(prepared, dates)
    d_pend, d_rows     = build_d_candidates(prepared, dates, params=D_STRICT_REF, hold_days=LEADERSHIP_HOLD_DEFAULT)
    v12_sim = simulate_sleeves(prepared, dates, v11_pend,
                               primary_slots=V11_PRIMARY_SLOTS,
                               secondary_pending=d_pend, secondary_slots=LEADERSHIP_SLOTS)
    print_port_row("V12_PORT", v12_sim)
    v12_sharpe = v12_sim["metrics"].get("sharpe", 0.0)
    print()

    results_summary = []

    # -------------------------------------------------------------------------
    # [2] Signal E por sectores especificos
    # -------------------------------------------------------------------------
    print(LINE)
    print("[2] SIGNAL E POR SECTORES — HW / Auto / Travel / Semis")
    print(SUBLINE)

    sector_configs = [
        ("E_HW",     HW_TICKERS,     "Hardware/IndustrialTech"),
        ("E_AUTO",   AUTO_TICKERS,   "Automotive"),
        ("E_TRAVEL", TRAVEL_TICKERS, "Travel/Airlines"),
        ("E_SEMIS",  SEMIS_TICKERS,  "Semiconductores"),
        ("E_BEST3",  BEST3_TICKERS,  "HW+Auto+Travel combined"),
    ]

    for label, tickers, desc in sector_configs:
        pend, rows = build_sector_candidates(
            prepared, dates, signal_e, label, tickers, HOLD_DEFAULT
        )
        m = per_trade_metrics(rows)
        print(f"\n  [{label}] {desc}")
        print_perf_row(label, m)
        print_regime_split(label, rows)

        if m["trades"] >= 20:
            wf = walk_forward_7(pend, prepared, dates, hold_days=HOLD_DEFAULT)
            print_wf(wf, label)
            results_summary.append((label, m, wf))
        else:
            print(f"  SKIP WF: solo {m['trades']} trades (min 20)")
            results_summary.append((label, m, {"wins": 0, "total": 7}))

    # -------------------------------------------------------------------------
    # [3] Signal E mas estricta (todo el universo)
    # -------------------------------------------------------------------------
    print()
    print(LINE)
    print("[3] SIGNAL E CON FILTROS MAS ESTRICTOS (universo completo)")
    print(SUBLINE)

    tight_configs = [
        ("E_TIGHTER", signal_e_tighter, "ROC20>15%, RSI 55-70, Vol 1-2x"),
        ("E_ULTRA",   signal_e_ultra,   "ROC20>20%, ROC60>30%, RSI 58-68"),
    ]

    for label, fn, desc in tight_configs:
        pend, rows = build_signal_candidates(
            prepared, dates, fn, label, HOLD_DEFAULT
        )
        m = per_trade_metrics(rows)
        print(f"\n  [{label}] {desc}")
        print_perf_row(label, m)
        print_regime_split(label, rows)

        if m["trades"] >= 30:
            # Hold sensitivity rapida
            best_wr = 0.0
            best_hold = HOLD_DEFAULT
            for h in [8, 10, 12, 15, 21]:
                _, rr = build_signal_candidates(prepared, dates, fn, label, h)
                mm = per_trade_metrics(rr)
                flag = ""
                if mm["wr"] > best_wr:
                    best_wr = mm["wr"]
                    best_hold = h
                    flag = " <--"
                print(f"    hold {h:>3d}d | n={mm['trades']:>4d} | WR {mm['wr']:>5.1f}% | avg {mm['avg']:>+6.2f}%{flag}")

            pend_best, rows_best = build_signal_candidates(
                prepared, dates, fn, label, best_hold
            )
            wf = walk_forward_7(pend_best, prepared, dates, hold_days=best_hold)
            print_wf(wf, f"{label} hold={best_hold}d")
            results_summary.append((label, per_trade_metrics(rows_best), wf))
        else:
            print(f"  SKIP WF: solo {m['trades']} trades")
            results_summary.append((label, m, {"wins": 0, "total": 7}))

    # -------------------------------------------------------------------------
    # [4] Portfolio: mejor sector + V11 (reemplazando D)
    # -------------------------------------------------------------------------
    print()
    print(LINE)
    print("[4] PORTFOLIO: mejor variante sectorial reemplazando slot D")
    print(SUBLINE)

    # Ordenar por WR
    results_summary.sort(key=lambda x: x[1]["wr"], reverse=True)

    print("  Ranking final por WR:")
    for name, m, wf in results_summary:
        wf_w = wf.get("wins", 0)
        flag = " *** WR>70!" if m["wr"] >= 70 else (" ** WR>65" if m["wr"] >= 65 else "")
        print(f"    {name:<14s} WR {m['wr']:>5.1f}% | n {m['trades']:>4d} | WF {wf_w}/7{flag}")

    print()
    # Portfolio con el top-1
    best_name, best_m, best_wf = results_summary[0]
    print(f"  Construyendo portfolio con {best_name} (WR={best_m['wr']:.1f}%)...")

    best_sector_map = {
        "E_HW": HW_TICKERS, "E_AUTO": AUTO_TICKERS,
        "E_TRAVEL": TRAVEL_TICKERS, "E_SEMIS": SEMIS_TICKERS,
        "E_BEST3": BEST3_TICKERS,
    }
    fn_map = {"E_TIGHTER": signal_e_tighter, "E_ULTRA": signal_e_ultra}

    if best_name in best_sector_map:
        bp, _ = build_sector_candidates(
            prepared, dates, signal_e, best_name,
            best_sector_map[best_name], HOLD_DEFAULT
        )
    else:
        fn = fn_map.get(best_name, signal_e_tighter)
        bp, _ = build_signal_candidates(prepared, dates, fn, best_name, HOLD_DEFAULT)

    port_sim = simulate_sleeves(
        prepared, dates, v11_pend,
        primary_slots=V11_PRIMARY_SLOTS,
        secondary_pending=bp,
        secondary_slots=LEADERSHIP_SLOTS,
    )
    print_port_row(f"V12_replace_D_{best_name}", port_sim)
    delta_sharpe = port_sim["metrics"].get("sharpe", 0.0) - v12_sharpe
    print(f"  Delta vs V12: {delta_sharpe:+.3f} Sharpe")

    # -------------------------------------------------------------------------
    # [5] VEREDICTO
    # -------------------------------------------------------------------------
    print()
    print(LINE)
    print("  VEREDICTO V21")
    print(LINE)

    winners_70 = [(n, m, wf) for n, m, wf in results_summary if m["wr"] >= 70.0 and m["trades"] >= 30]
    winners_65 = [(n, m, wf) for n, m, wf in results_summary if m["wr"] >= 65.0 and m["trades"] >= 30]

    if winners_70:
        print(f"  SENALES CON WR >= 70% y n >= 30:")
        for n, m, wf in winners_70:
            print(f"    {n}: WR {m['wr']:.1f}% | n={m['trades']} | WF {wf.get('wins',0)}/7")
        print()
        print("  Proximos pasos:")
        print("  1. Aplicar la mejor como sleeve adicional en V13")
        print("  2. Correr gate de promocion formal (7 criterios)")
    elif winners_65:
        print("  Ninguna senial supera 70%, pero estas superan 65%:")
        for n, m, wf in winners_65:
            print(f"    {n}: WR {m['wr']:.1f}% | n={m['trades']} | WF {wf.get('wins',0)}/7")
        print()
        print("  Proximos pasos:")
        print("  1. Endurecer filtros hasta llegar a 70%")
        print("  2. Verificar si el sector edge persiste en OOS")
    else:
        best = results_summary[0]
        print(f"  Mejor encontrada: {best[0]} con WR {best[1]['wr']:.1f}%")
        print("  Interpretacion: el edge sectorial de V20 (HW 75%) no se replica con suficientes trades.")
        print("  Conclusion: WR 70%+ requiere condiciones de mercado muy especificas (panic, extremos).")
        print("  El sistema actual (V12 WR 60.8%) esta cerca del optimo realista para un universo broad.")
    print(LINE)


if __name__ == "__main__":
    main()
