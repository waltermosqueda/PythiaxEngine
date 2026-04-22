#!/usr/bin/env python3
"""
Tablero textual de competencia entre scanners.

No decide el champion. Solo observa y resume:
  - quien viene acertando mas
  - que modelos predijeron en una fecha
  - que memoria tienen cargada
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.scanner_operativo_context import resolve_operational_scanner_context
from herramientas.legacy_ml_registry import load_enabled_legacy_ml_entries


DB_PATH = ROOT / "titan_system" / "data" / "titan.db"


def monitored_entries() -> list[dict[str, object]]:
    operational = resolve_operational_scanner_context()
    entries: list[dict[str, object]] = []

    version_roles = []
    for version in [operational.active_version, operational.reference_version, 11, *operational.observed_versions]:
        if version is None or version in version_roles:
            continue
        version_roles.append(version)
        role = "seguimiento"
        if version == operational.active_version:
            role = "activo"
        elif operational.reference_version is not None and version == operational.reference_version:
            role = "referencia"
        elif version == 11:
            role = "base"
        elif version in operational.observed_versions:
            role = "observado"
        entries.append(
            {
                "key": f"V{version}",
                "label": f"V{version}",
                "role": role,
                "prefix": f"INVERTIR_V{version}",
            }
        )

    for entry in load_enabled_legacy_ml_entries():
        entries.append(
            {
                "key": entry.model_id,
                "label": entry.label,
                "role": "legacy_ml",
                "prefix": entry.model_name,
                "exact_model_name": True,
            }
        )
    return entries


def monitored_versions() -> list[int]:
    return [
        int(entry["label"].replace("V", ""))
        for entry in monitored_entries()
        if str(entry["label"]).startswith("V")
    ]


def role_for_version(version: int) -> str:
    for entry in monitored_entries():
        if entry["label"] == f"V{version}":
            return str(entry["role"])
    return "seguimiento"


def prefix_for_version(version: int) -> str:
    return f"INVERTIR_V{version}"


def standings_df(con: sqlite3.Connection) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for entry in monitored_entries():
        prefix = str(entry["prefix"])
        exact_model_name = bool(entry.get("exact_model_name", False))
        pattern = prefix if exact_model_name else f"{prefix}_%"
        summary = con.execute(
            """
            SELECT
                COUNT(*) AS total_predictions,
                COUNT(DISTINCT p.prediction_date) AS prediction_days,
                COUNT(o.id) AS evaluated,
                AVG(o.hit) * 100.0 AS accuracy_pct,
                AVG(o.actual_return) * 100.0 AS avg_return_pct,
                MIN(p.prediction_date) AS first_prediction_date,
                MAX(p.prediction_date) AS last_prediction_date
            FROM predictions p
            LEFT JOIN outcomes o ON p.id = o.prediction_id
            WHERE p.model_name LIKE ?
            """,
            (pattern,),
        ).fetchone()

        latest_prediction_date = summary[6]
        latest_picks = 0
        latest_tickers: list[str] = []
        if latest_prediction_date:
            latest_rows = con.execute(
                """
                SELECT DISTINCT ticker
                FROM predictions
                WHERE model_name LIKE ? AND prediction_date = ?
                ORDER BY ticker
                """,
                (pattern, latest_prediction_date),
            ).fetchall()
            latest_tickers = [row[0] for row in latest_rows]
            latest_picks = len(latest_tickers)

        rows.append(
            {
                "version": str(entry["label"]),
                "rol": str(entry["role"]),
                "pred_days": int(summary[1] or 0),
                "total_preds": int(summary[0] or 0),
                "evaluated": int(summary[2] or 0),
                "accuracy_pct": round(float(summary[3]), 2) if summary[3] is not None else None,
                "avg_return_pct": round(float(summary[4]), 3) if summary[4] is not None else None,
                "first_date": summary[5] or "-",
                "last_date": summary[6] or "-",
                "latest_picks": latest_picks,
                "latest_tickers": ", ".join(latest_tickers[:8]) if latest_tickers else "-",
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(by=["accuracy_pct", "avg_return_pct", "version"], ascending=[False, False, True], na_position="last")


def compare_day_df(con: sqlite3.Connection, date_text: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for entry in monitored_entries():
        prefix = str(entry["prefix"])
        exact_model_name = bool(entry.get("exact_model_name", False))
        pattern = prefix if exact_model_name else f"{prefix}_%"
        tickers = [
            row[0]
            for row in con.execute(
                """
                SELECT DISTINCT ticker
                FROM predictions
                WHERE model_name LIKE ? AND prediction_date = ?
                ORDER BY ticker
                """,
                (pattern, date_text),
            ).fetchall()
        ]
        rows.append(
            {
                "version": str(entry["label"]),
                "rol": str(entry["role"]),
                "picks": len(tickers),
                "tickers": ", ".join(tickers) if tickers else "-",
            }
        )
    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tablero textual de competencia entre scanners")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("standings", help="Ver posiciones acumuladas de los modelos monitoreados")
    compare_parser = sub.add_parser("compare-day", help="Comparar predicciones de una fecha")
    compare_parser.add_argument("--date", required=True, help="Fecha prediction_date (YYYY-MM-DD)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    con = sqlite3.connect(str(DB_PATH))
    try:
        if args.command == "standings":
            df = standings_df(con)
            print("=" * 120)
            print("  TABLERO DE COMPETENCIA DE MODELOS")
            print("=" * 120)
            if df.empty:
                print("  Sin datos de competencia todavia.")
                return 0
            print(df.to_string(index=False))
            return 0

        if args.command == "compare-day":
            df = compare_day_df(con, args.date)
            print("=" * 120)
            print(f"  COMPARACION DE PREDICCIONES | {args.date}")
            print("=" * 120)
            print(df.to_string(index=False))
            return 0
    finally:
        con.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
