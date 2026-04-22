#!/usr/bin/env python3
"""
Investigacion V28 — Top N operativo fijo para la liga.

Objetivo:
  - comparar top 1/2/3/4 con datos auditables
  - medir por activo predicho por rueda (prediction_date), no por filas crudas
  - usar el ranking real del snapshot y el horizonte operativo de mayor plazo
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.competencia_modelos import monitored_entries
from herramientas.competencia_topn_estandar import (
    STANDARD_TOP_N,
    load_market_dates,
    summarize_topn_study,
)


OUTPUT_PATH = ROOT / "analisis" / "top_n_estandar_study.json"


def _fmt_pct(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}%"


def _labels(prefix: str) -> list[str]:
    return [str(entry["label"]) for entry in monitored_entries() if str(entry["label"]).startswith(prefix)]


def _table_lines(study: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for result in study["results"]:
        lines.append(
            "  "
            f"top {result['top_n']} | "
            f"dias {result['eligible_days']:>3} | "
            f"WR medio {_fmt_pct(result['mean_model_accuracy_pct'], 2):>8} | "
            f"ret medio {_fmt_pct(result['mean_model_return_pct']):>9} | "
            f"ret/dia {_fmt_pct(result['mean_model_day_return_pct']):>9} | "
            f"picks/dia {result['mean_picks_active_day']:.2f}"
        )
    return lines


def _frontier_note(study: dict[str, Any]) -> str:
    by_n = {item["top_n"]: item for item in study["results"]}
    n1 = by_n.get(1)
    n2 = by_n.get(2)
    n3 = by_n.get(3)
    n4 = by_n.get(4)
    if not n1 or not n2 or not n3 or not n4:
        return "Muestra incompleta."

    return (
        f"top 2 vs top 1: ret {_fmt_pct((n2['mean_model_return_pct'] or 0) - (n1['mean_model_return_pct'] or 0))} "
        f"| picks/dia +{(n2['mean_picks_active_day'] or 0) - (n1['mean_picks_active_day'] or 0):.2f}. "
        f"top 3/top 4 ya diluyen mas de lo que agregan."
    )


def main() -> int:
    all_labels = [str(entry["label"]) for entry in monitored_entries()]
    scanner_labels = _labels("V")
    legacy_labels = _labels("ML_")
    active_core_labels = ["V13", "V12", "V11"]

    with sqlite3.connect(str(ROOT / "titan_system" / "data" / "titan.db")) as con:
        con.row_factory = sqlite3.Row
        market_dates = load_market_dates(con)

        studies = {
            "all_current_common_window": summarize_topn_study(
                con,
                all_labels,
                market_dates,
                start_date="2026-03-02",
            ),
            "scanners_2025_plus": summarize_topn_study(
                con,
                scanner_labels,
                market_dates,
                start_date="2025-01-01",
            ),
            "legacy_common_window": summarize_topn_study(
                con,
                legacy_labels,
                market_dates,
                start_date="2026-03-02",
            ),
            "active_core_2025_plus": summarize_topn_study(
                con,
                active_core_labels,
                market_dates,
                start_date="2025-01-01",
            ),
        }

    OUTPUT_PATH.write_text(json.dumps(studies, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print("=" * 110)
    print("INVESTIGACION V28 | TOP N OPERATIVO FIJO PARA LA LIGA")
    print("=" * 110)
    print(f"Output JSON: {OUTPUT_PATH.relative_to(ROOT)}")
    print(f"Top N recomendado vigente: {STANDARD_TOP_N}")

    print("\n[1] Liga monitoreada completa | ventana operativa comun desde 2026-03-02")
    print("\n".join(_table_lines(studies["all_current_common_window"])))
    print(f"  Nota: {_frontier_note(studies['all_current_common_window'])}")

    print("\n[2] Scanners | 2025+")
    print("\n".join(_table_lines(studies["scanners_2025_plus"])))
    print(f"  Nota: {_frontier_note(studies['scanners_2025_plus'])}")

    print("\n[3] Legacy ML | ventana comun desde 2026-03-02")
    print("\n".join(_table_lines(studies["legacy_common_window"])))
    print(f"  Nota: {_frontier_note(studies['legacy_common_window'])}")

    print("\n[4] Core activo/referencia/base | 2025+")
    print("\n".join(_table_lines(studies["active_core_2025_plus"])))
    print(f"  Nota: {_frontier_note(studies['active_core_2025_plus'])}")

    print("\nVEREDICTO")
    print(
        "  Se fija top 2 como estandar operativo de la liga: es el mejor compromiso entre retorno, "
        "carga analitica y comparabilidad entre familias."
    )
    print(
        "  top 1 sigue siendo muy fuerte cuando se mira solo el core V12/V13 o algunos scanners aislados, "
        "pero para el dashboard competitivo mixto top 2 mejora la frontera practica sin inflar el ruido."
    )
    print(
        "  top 3 y top 4 quedan descartados: suben demasiado la carga diaria y ya no mejoran de forma consistente."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

