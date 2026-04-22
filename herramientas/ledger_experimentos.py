#!/usr/bin/env python3
"""
LEDGER DE EXPERIMENTOS - CLAUDE
===============================

Registro liviano de champion/fronteras candidatas y mejoras aplicadas al scanner activo.

Uso:
  python herramientas/ledger_experimentos.py status
  python herramientas/ledger_experimentos.py list
  python herramientas/ledger_experimentos.py show --id SCN-V11-CAP-OPERATIVO
  python herramientas/ledger_experimentos.py validate
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LEDGER_PATH = ROOT / "experimentos" / "scanner_ledger.json"
LINE = "=" * 100
SUBLINE = "-" * 100

VALID_STATUSES = {
    "historical_baseline",
    "active_champion",
    "retired_champion",
    "rejected",
    "applied_in_place",
    "promotion_candidate",
}

VALID_SCOPES = {
    "reference",
    "new_scanner",
    "in_place_enhancement",
}


def load_ledger() -> dict[str, Any]:
    with LEDGER_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def index_entries(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["entry_id"]: entry for entry in payload.get("entries", [])}


def fmt_metric_block(name: str, metrics: dict[str, Any]) -> str:
    parts: list[str] = []
    if "sharpe" in metrics:
        parts.append(f"Sharpe {metrics['sharpe']}")
    if "win_rate_pct" in metrics:
        parts.append(f"WR {metrics['win_rate_pct']}%")
    if "total_return_pct" in metrics:
        parts.append(f"Total {metrics['total_return_pct']}%")
    if "mdd_pct" in metrics:
        parts.append(f"MDD {metrics['mdd_pct']}%")
    if "message" in metrics:
        parts.append(str(metrics["message"]))
    if not parts:
        parts.append(str(metrics))
    return f"  - {name}: " + " | ".join(parts)


def print_status(payload: dict[str, Any]) -> int:
    entries = index_entries(payload)
    active_state = payload["active_state"]
    champion = entries[active_state["scanner_entry_id"]]

    print(LINE)
    print("  LEDGER DE EXPERIMENTOS - ESTADO ACTUAL")
    print(LINE)
    print(f"  Scanner champion : {champion['entry_id']} | {champion['candidate']}")
    print(f"  Archivo canonico : {active_state['scanner_file']}")
    print(f"  Desde            : {champion['date']}")
    print(f"  Decision         : {champion['decision_summary']}")

    metrics = champion.get("metrics", {})
    if metrics:
        print(SUBLINE)
        print("  Metricas champion")
        for key in ("independent_broad", "independent_core", "portfolio_broad", "portfolio_core"):
            if key in metrics:
                print(fmt_metric_block(key, metrics[key]))

    applied_ids = active_state.get("applied_entry_ids", [])
    if applied_ids:
        print(SUBLINE)
        print("  Mejoras aplicadas in place")
        for entry_id in applied_ids:
            entry = entries[entry_id]
            print(f"  - {entry_id} | {entry['candidate']} | {entry['date']}")
            print(f"    {entry['decision_summary']}")

    next_frontier_id = active_state.get("next_frontier_entry_id")
    if next_frontier_id:
        frontier = entries.get(next_frontier_id)
        if frontier is not None:
            print(SUBLINE)
            print("  Frontera aprobada")
            print(f"  - {frontier['entry_id']} | {frontier['candidate']} | {frontier['date']}")
            print(f"    {frontier['decision_summary']}")

    champions = [
        entry for entry in payload["entries"]
        if entry["status"] in {"historical_baseline", "retired_champion", "active_champion"}
    ]
    champions.sort(key=lambda item: item["date"])
    print(SUBLINE)
    print("  Cadena de champion")
    print("  " + " -> ".join(entry["entry_id"] for entry in champions))

    rejected = [entry for entry in payload["entries"] if entry["status"] == "rejected"]
    rejected.sort(key=lambda item: item["date"], reverse=True)
    if rejected:
        print(SUBLINE)
        print("  Rechazos relevantes")
        for entry in rejected[:5]:
            print(f"  - {entry['entry_id']} | {entry['candidate']} | {entry['date']}")
            print(f"    {entry['decision_summary']}")

    print(LINE)
    return 0


def print_list(payload: dict[str, Any]) -> int:
    entries = sorted(payload.get("entries", []), key=lambda item: (item["date"], item["entry_id"]))
    print(LINE)
    print("  LEDGER DE EXPERIMENTOS - LISTA")
    print(LINE)
    for entry in entries:
        print(
            f"  {entry['date']} | {entry['entry_id']} | {entry['status']} | "
            f"{entry['candidate']}"
        )
    print(LINE)
    return 0


def print_show(payload: dict[str, Any], entry_id: str) -> int:
    entries = index_entries(payload)
    entry = entries.get(entry_id)
    if entry is None:
        print(f"[ERROR] No existe entry_id={entry_id}")
        return 1

    print(LINE)
    print(f"  {entry['entry_id']} - {entry['candidate']}")
    print(LINE)
    print(f"  Fecha            : {entry['date']}")
    print(f"  Scope            : {entry['change_scope']}")
    print(f"  Status           : {entry['status']}")
    print(f"  Scanner file     : {entry.get('scanner_file') or '-'}")
    print(f"  Replaces         : {entry.get('replaces') or '-'}")
    print(f"  Applies to       : {entry.get('applies_to') or '-'}")
    print(f"  Hypothesis       : {entry['hypothesis']}")
    print(f"  Decision         : {entry['decision_summary']}")
    print(f"  Source sessions  : {', '.join(entry.get('source_sessions', [])) or '-'}")
    print("  Evidence")
    for path in entry.get("evidence_paths", []):
        print(f"  - {path}")
    metrics = entry.get("metrics", {})
    if metrics:
        print(SUBLINE)
        print("  Metricas")
        for name, metric_values in metrics.items():
            if isinstance(metric_values, dict):
                print(fmt_metric_block(name, metric_values))
            else:
                print(f"  - {name}: {metric_values}")
    notes = entry.get("notes")
    if notes:
        print(SUBLINE)
        print(f"  Notes            : {notes}")
    print(LINE)
    return 0


def validate_ledger(payload: dict[str, Any]) -> int:
    errors: list[str] = []
    entries = payload.get("entries", [])
    entry_index = index_entries(payload)

    if payload.get("schema_version") != 1:
        errors.append("schema_version debe ser 1")

    if not isinstance(entries, list) or not entries:
        errors.append("entries debe ser una lista no vacia")

    if len(entry_index) != len(entries):
        errors.append("entry_id duplicado detectado")

    active_state = payload.get("active_state", {})
    active_id = active_state.get("scanner_entry_id")
    if active_id not in entry_index:
        errors.append("active_state.scanner_entry_id no existe en entries")

    active_champions = [entry for entry in entries if entry.get("status") == "active_champion"]
    if len(active_champions) != 1:
        errors.append("debe existir exactamente un active_champion")
    elif active_champions[0]["entry_id"] != active_id:
        errors.append("active_state.scanner_entry_id no coincide con active_champion")

    for applied_id in active_state.get("applied_entry_ids", []):
        entry = entry_index.get(applied_id)
        if entry is None:
            errors.append(f"applied_entry_id inexistente: {applied_id}")
            continue
        if entry.get("status") != "applied_in_place":
            errors.append(f"{applied_id} esta en applied_entry_ids pero no tiene status applied_in_place")

    next_frontier_id = active_state.get("next_frontier_entry_id")
    if next_frontier_id is not None:
        entry = entry_index.get(next_frontier_id)
        if entry is None:
            errors.append(f"next_frontier_entry_id inexistente: {next_frontier_id}")
        elif entry.get("status") != "promotion_candidate":
            errors.append(
                f"{next_frontier_id} esta en next_frontier_entry_id pero no tiene status promotion_candidate"
            )

    for entry in entries:
        entry_id = entry["entry_id"]
        if entry.get("status") not in VALID_STATUSES:
            errors.append(f"{entry_id}: status invalido")
        if entry.get("change_scope") not in VALID_SCOPES:
            errors.append(f"{entry_id}: change_scope invalido")

        for ref_key in ("replaces", "applies_to"):
            ref = entry.get(ref_key)
            if ref is not None and ref not in entry_index:
                errors.append(f"{entry_id}: {ref_key} apunta a un id inexistente ({ref})")

        scanner_file = entry.get("scanner_file")
        if scanner_file:
            path = ROOT / scanner_file
            if not path.exists():
                errors.append(f"{entry_id}: scanner_file no existe ({scanner_file})")

        for rel_path in entry.get("evidence_paths", []):
            path = ROOT / rel_path
            if not path.exists():
                errors.append(f"{entry_id}: evidence_path no existe ({rel_path})")

        if not isinstance(entry.get("metrics", {}), dict):
            errors.append(f"{entry_id}: metrics debe ser un objeto")

    print(LINE)
    print("  LEDGER DE EXPERIMENTOS - VALIDACION")
    print(LINE)
    if errors:
        for error in errors:
            print(f"  [FAIL] {error}")
        print(SUBLINE)
        print(f"  Resultado final : FAIL | {len(errors)} problema(s)")
        print(LINE)
        return 1

    print("  [PASS] schema_version")
    print("  [PASS] ids unicos")
    print("  [PASS] champion activo consistente")
    print("  [PASS] applied entries consistentes")
    print("  [PASS] referencias internas")
    print("  [PASS] rutas de evidencia")
    print(SUBLINE)
    print(f"  Resultado final : PASS | {len(entries)} entradas validas")
    print(LINE)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ledger liviano de experimentos de Claude")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Ver champion actual y rechazos relevantes")
    subparsers.add_parser("list", help="Listar todas las entradas del ledger")
    subparsers.add_parser("validate", help="Validar integridad del ledger")

    show_parser = subparsers.add_parser("show", help="Ver una entrada puntual")
    show_parser.add_argument("--id", required=True, dest="entry_id", help="ID de la entrada")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    command = args.command or "status"
    payload = load_ledger()

    if command == "status":
        return print_status(payload)
    if command == "list":
        return print_list(payload)
    if command == "show":
        return print_show(payload, args.entry_id)
    if command == "validate":
        return validate_ledger(payload)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
