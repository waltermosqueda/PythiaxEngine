#!/usr/bin/env python3
"""
Recolector de errores graves del pipeline.

Lee los logs del pipeline y el health check, extrae errores serios
y los persiste en logs/errores_criticos.json.

Ese archivo es la fuente de verdad que Copilot chequea al inicio
de cada sesion para corregir problemas sin que el usuario lo pida.

Corre sin dependencias externas (solo stdlib).
Exit code: 0 = OK o errores ya conocidos, 1 = errores nuevos registrados.
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_LOG   = ROOT / "logs" / "pipeline_run.log"
HEALTH_LOG     = ROOT / "logs" / "dashboard_health.log"
ERRORS_FILE    = ROOT / "logs" / "errores_criticos.json"

# Patrones que clasifican como error grave
CRITICAL_PATTERNS = [
    (r"\[CRITICAL ALERT\]",             "pipeline_critical_alert"),
    (r"ModuleNotFoundError",             "module_not_found"),
    (r"ImportError",                     "import_error"),
    (r"Exception.*Traceback",            "unhandled_exception"),
    (r"TimeoutExpired|TimeoutError",     "timeout"),
    (r"OperationalError|ProgrammingError", "database_error"),
    (r"STALE:.*snapshot",               "dashboard_stale"),
    (r"ALERTA:.*health check",          "dashboard_health_alert"),
    (r"pipeline fallo|Paso.*fallo",     "pipeline_step_failed"),
    (r"ERROR:.*No se pudo",             "script_error"),
]

def local_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=-3)))


def read_log(path: Path) -> str:
    if not path.exists():
        return ""
    raw = path.read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def load_errors() -> list[dict]:
    if not ERRORS_FILE.exists():
        return []
    try:
        return json.loads(ERRORS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_errors(errors: list[dict]) -> None:
    ERRORS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ERRORS_FILE.write_text(
        json.dumps(errors, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def scan_log_for_errors(log_text: str, source: str) -> list[dict]:
    """Extrae lineas de error del log y las clasifica."""
    found = []
    today = local_now().strftime("%Y-%m-%d")

    for line in log_text.splitlines():
        # Solo lineas de hoy (los logs incluyen fecha al inicio)
        if not line.startswith(today):
            continue
        for pattern, category in CRITICAL_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                found.append({
                    "timestamp": local_now().isoformat(),
                    "source": source,
                    "category": category,
                    "line": line.strip(),
                    "status": "pendiente",
                    "resolved_at": None,
                    "resolution": None,
                })
                break  # una categoria por linea

    return found


def deduplicate(existing: list[dict], new_entries: list[dict]) -> tuple[list[dict], int]:
    """Agrega solo errores que no existen ya (misma linea + categoria)."""
    existing_keys = {(e["category"], e["line"]) for e in existing}
    added = 0
    for entry in new_entries:
        key = (entry["category"], entry["line"])
        if key not in existing_keys:
            existing.append(entry)
            existing_keys.add(key)
            added += 1
    return existing, added


def main() -> int:
    pipeline_text = read_log(PIPELINE_LOG)
    health_text   = read_log(HEALTH_LOG)

    new_from_pipeline = scan_log_for_errors(pipeline_text, "pipeline_run.log")
    new_from_health   = scan_log_for_errors(health_text, "dashboard_health.log")
    all_new = new_from_pipeline + new_from_health

    existing = load_errors()
    updated, added = deduplicate(existing, all_new)

    # Mantener solo los ultimos 90 dias (limpiar historico viejo)
    cutoff = (local_now() - timedelta(days=90)).isoformat()
    updated = [e for e in updated if e.get("timestamp", "") >= cutoff or e.get("status") == "pendiente"]

    save_errors(updated)

    pending = [e for e in updated if e.get("status") == "pendiente"]

    if added > 0:
        print(f"[collect_errors] {added} error(es) nuevo(s) registrado(s). Total pendientes: {len(pending)}")
        for e in all_new[:added]:
            print(f"  [{e['category']}] {e['line'][:120]}")
        return 1

    print(f"[collect_errors] Sin errores nuevos. Pendientes existentes: {len(pending)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
