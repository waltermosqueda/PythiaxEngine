#!/usr/bin/env python3
"""
INVERTIR V10 REBOUND CAPTURE - DB-Integrated Scanner
====================================================

Objetivo:
  Mantener la entrada robusta de V9 y superar a V7/V9 desde la ejecucion.

Hallazgo:
  Muchos crashes validos hacen un snapback fuerte en los primeros dias.
  El hold fijo a 7d puede devolver parte del rebote antes del cierre.

V10:
  - Signal A: igual a V9
  - Signal C4: misma entrada que V9
  - Exit overlay para C4:
      si cualquier cierre en los primeros 4 dias queda >= +6% vs entry,
      cerrar ahi; si no, cerrar en day 7

Evidencia local sobre titan.db:
  Broad:
    V7  : Sharpe 2.89 | MDD -26.9%
    V9  : Sharpe 3.08 | MDD -19.0%
    V10 : Sharpe 3.85 | MDD -19.0%
  Core:
    V7  : Sharpe 3.87 | MDD -9.8%
    V9  : Sharpe 3.92 | MDD -9.8%
    V10 : Sharpe 5.60 | MDD -7.3%

Estado:
  CANDIDATO FUERTE. Supera a V7 sin complicar la entrada.

Uso:
  python scanner_variantes/invertir_v10_rebound_capture.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import SCANNER.invertir_v9 as v9


MODEL_NAME = "INVERTIR_V10_REBOUND_CAPTURE"
C_EARLY_TP_PCT = 6.0
C_EARLY_TP_DAYS = 4


def enrich_c_signal(result: v9.ScanResult) -> v9.ScanResult:
    note = result.note
    if note:
        note += " | "
    note += f"exit: close +{C_EARLY_TP_PCT:.0f}% <= day {C_EARLY_TP_DAYS}; sino day {v9.V7_HOLDING_DAYS}"
    return replace(result, signal="C4 (Crash+Rebound)", note=note)


def main() -> None:
    today = date.today()

    with v9.TitanDB() as db:
        universe_data, missing = v9.load_universe_data(db, v9.UNIVERSE)
        prepared = v9.precompute_indicators(universe_data)

        if "SPY" not in prepared:
            print("ERROR: SPY no esta en titan.db. No se puede evaluar el regimen.")
            return

        latest_date_str = db.get_latest_date("SPY")
        latest_dt = datetime.strptime(latest_date_str, "%Y-%m-%d").date() if latest_date_str else None
        staleness = v9.business_days_between(latest_dt, today) if latest_dt else None
        regime_safe, regime_info = v9.check_regime(prepared["SPY"])
        breadth = v9.compute_breadth(universe_data)
        quality_alerts = v9.recent_quality_alerts(prepared)

        results_a: list[v9.ScanResult] = []
        results_c4: list[v9.ScanResult] = []

        for ticker in sorted(t for t in prepared.keys() if t != "SPY"):
            df = prepared[ticker]

            if regime_safe:
                sig_a = v9.signal_a_mean_reversion(ticker, df)
                if sig_a is not None:
                    results_a.append(sig_a)

            sig_c3 = v9.signal_c3_crash_path_quality(ticker, df)
            if sig_c3 is not None and not any(existing.ticker == ticker for existing in results_a):
                results_c4.append(enrich_c_signal(sig_c3))

        all_results = results_a + results_c4
        all_results.sort(key=lambda item: item.score, reverse=True)

        print("=" * 88)
        print(f"  {MODEL_NAME} - {today.isoformat()}")
        print("=" * 88)
        print("  Fuente datos     : titan.db")
        print(f"  Ultima fecha DB  : {latest_date_str}")
        if staleness is not None:
            freshness = "AL DIA" if staleness <= 1 else f"STALE ({staleness} dias habiles)"
            print(f"  Frescura DB      : {freshness}")
        print(f"  Universo V7      : {len(v9.UNIVERSE)} tickers esperados")
        print(f"  Cobertura DB     : {len(prepared) - 1} tickers + SPY")
        if missing:
            print(f"  Tickers faltantes: {len(missing)}")

        print("\n" + "=" * 88)
        print("  PASO 1: REGIMEN, BREADTH Y CALIDAD")
        print("=" * 88)
        if "safe" in regime_info:
            regime_label = "SEGURO" if regime_info["safe"] else "PELIGRO"
            print(
                f"  SPY ${regime_info['spy_price']:.2f} | dist SMA50 {regime_info['spy_dist']:+.2f}% | "
                f"vol20 {regime_info['spy_vol20d']:.2f}% | regimen {regime_label}"
            )
        else:
            print(f"  Regimen: {regime_info.get('reason', 'sin informacion')}")
        print(f"  Breadth > SMA50  : {breadth['pct_above_sma50']:.1f}% ({breadth['count']} tickers evaluables)")
        if quality_alerts:
            print("  Alertas calidad  :")
            for alert in quality_alerts[:5]:
                print(
                    f"    - {alert['ticker']} | {alert['date']} | ret1 {alert['ret1']:+.1f}% | "
                    f"intraday {alert['intraday']:+.1f}% | rango {alert['range_pct']:.1f}%"
                )

        print("\n" + "=" * 88)
        print("  PASO 2: SENALES V10")
        print("=" * 88)
        print("  Signal A         : igual a V9 / V7, con quality guard")
        print(
            "  Signal C4        : entrada V9 + exit adaptativo: +6% al cierre <= 4d; si no, 7d"
        )
        print(f"  Total senales    : {len(all_results)} ({len(results_a)} tipo A + {len(results_c4)} tipo C4)")

        if all_results:
            df_show = v9.format_signal_rows(all_results)
            print()
            print(df_show.to_string(index=False))
        else:
            print("\n  Sin senales hoy en la ultima fecha de la DB.")

        print("\n" + "=" * 88)
        print("  PASO 3: LECTURA OPERATIVA")
        print("=" * 88)

        if staleness and staleness > 1:
            print("  AVISO: la DB no esta fresca. Actualiza antes de tomar una decision real.")

        if quality_alerts:
            print("  V10 mantiene el bloqueo de corporate actions para evitar falsos crashes.")

        if all_results:
            top = all_results[:3]
            print("  Top oportunidades:")
            for idx, signal in enumerate(top, start=1):
                print(
                    f"  {idx}. {signal.ticker:<6} | {signal.signal:<18} | ${signal.price:>8.2f} | "
                    f"Sector {signal.sector:<10} | Score {signal.score:>6.1f}"
                )
            print("\n  Reglas:")
            print("  - Maximo 3 posiciones simultaneas")
            print("  - Signal A: hold de referencia 7 dias habiles")
            print(f"  - Signal C4: si cierre >= +{C_EARLY_TP_PCT:.0f}% antes de day {C_EARLY_TP_DAYS}, tomar ganancia")
            print("  - Si C4 no activa early TP, cerrar en day 7")
            print(f"  - Anti-knife conceptual: no repetir ticker en {v9.V7_ANTIKNIFE_DAYS} dias")
            print("  - Corporate-action guard bloquea splits y repricings sospechosos")
        elif regime_safe:
            print("  Regimen seguro, pero sin setups de calidad. Esperar tambien es edge.")
        else:
            print("  Regimen peligroso y sin crashes de calidad suficientes. Mejor esperar.")

        print("\n" + "=" * 88)
        print("  VEREDICTO")
        print("=" * 88)
        print("  V10 supera a V9 no por entrar mas, sino por ejecutar mejor el rebote de crashes.")
        print("  Mantiene la robustez live de V9 y agrega una salida simple, operable y mas ganadora.")
        print("  Ejecutar: python scanner_variantes/invertir_v10_rebound_capture.py")
        print("  Referencias: V9 path-quality y V7 arquitectura original")


if __name__ == "__main__":
    main()
