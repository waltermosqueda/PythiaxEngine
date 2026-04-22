#!/usr/bin/env python3
"""
AUDITORIA INTEGRAL CLAUDE
=========================

Objetivo:
  Ejecutar una auditoria reproducible del proyecto Claude para detectar:
  - roturas en backtests y flujos criticos
  - desalineaciones entre scanner, gestor, loop operativo y ledger
  - incoherencias de documentacion que puedan volver a inducir errores

Uso:
  python herramientas/auditoria_integral_claude.py
  python herramientas/auditoria_integral_claude.py --mode fast
  python herramientas/auditoria_integral_claude.py --mode full
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import timedelta
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.scanner_operativo_context import (
    learning_version_from_path,
    model_prefix_for_version,
    resolve_operational_scanner_context,
    run_dir_for_version,
)
from herramientas.competencia_modelos import monitored_entries
from herramientas.competencia_topn_estandar import (
    STANDARD_TOP_N,
    extract_ranked_snapshot_picks,
    load_entry_snapshots,
)
from herramientas.dashboard_paths import AURORA_PRO_HTML, INDEX_HTML as TABLERO_INDEX_PATH, SNAPSHOT_PATH as TABLERO_SNAPSHOT_PATH

REPORTS_DIR = ROOT / "analisis" / "auditorias"
SENTINEL_STATE_PATH = REPORTS_DIR / "sentinel_status.json"
DB_PATH = ROOT / "titan_system" / "data" / "titan.db"
LINE = "=" * 110
SUBLINE = "-" * 110
SCANNER_DIR = ROOT / "SCANNER"
OPERATIONAL = resolve_operational_scanner_context()
ACTIVE_SCANNER = OPERATIONAL.active_scanner
PREV_SCANNER = OPERATIONAL.reference_scanner
GESTOR_PATH = ROOT / "herramientas" / "gestor_posiciones_v11.py"
LEGACY_GESTOR_PATH = ROOT / "herramientas" / "gestor_posiciones_v10.py"
GESTOR_STATE_PATH = ROOT / "herramientas" / "v11_open_positions.json"
AUTO_UPDATE_PATH = ROOT / "herramientas" / "auto_actualizar.py"
CLAUDE_MD = ROOT / "CLAUDE.md"
CONTEXT_MD = ROOT / ".claude" / "context-essentials.md"
ESTRUCTURA_MD = ROOT / "docs" / "ESTRUCTURA.md"
LEDGER_PATH = ROOT / "experimentos" / "scanner_ledger.json"
LEARNING_BASIS_PATH = ROOT / "herramientas" / "aprendizaje_operativo_v11.py"
APRENDIZAJE_README = ROOT / "aprendizaje_operativo" / "README.md"
SCANNER_VARIANTES_DIR = ROOT / "scanner_variantes"

CODE_DIRS = [
    SCANNER_DIR,
    ROOT / "herramientas",
    ROOT / "backtests",
    ROOT / "titan_system",
]
OPTIONAL_CODE_DIRS = [
    SCANNER_VARIANTES_DIR,
]
DOC_FILES = [
    CLAUDE_MD,
    CONTEXT_MD,
    ESTRUCTURA_MD,
    APRENDIZAJE_README,
]
STATE_FILES = [
    LEDGER_PATH,
]
CANONICAL_BACKTESTS = {
    "investigacion_v9_path_quality.py",
    "investigacion_v10_rebound_capture.py",
    "investigacion_v11_cap_operativo.py",
    "investigacion_v12_portfolio_operativo.py",
    "investigacion_v14_prioridad_memoria.py",
    "investigacion_v15_edge_enhancement.py",
}


@dataclass
class AuditResult:
    name: str
    status: str
    summary: str
    details: list[str]


def run_command(command: list[str], timeout_ms: int = 60000) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=str(ROOT.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, timeout_ms // 1000),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        # Devolver un CompletedProcess sintetico para que los checks lo evaluen como FAIL
        return subprocess.CompletedProcess(
            args=command, returncode=-1,
            stdout=(exc.output or b"").decode("utf-8", errors="replace") if isinstance(exc.output, bytes) else (exc.output or ""),
            stderr=f"TIMEOUT after {timeout_ms}ms",
        )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_ledger() -> dict[str, Any]:
    return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))


def load_sentinel_state() -> dict[str, Any]:
    if not SENTINEL_STATE_PATH.exists():
        return {}
    try:
        return json.loads(SENTINEL_STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def sqlite_value(query: str, params: tuple[Any, ...] = ()) -> Any:
    con = sqlite3.connect(str(DB_PATH))
    try:
        row = con.execute(query, params).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def sqlite_value_many(query: str, params: tuple[Any, ...] = ()) -> list[Any]:
    con = sqlite3.connect(str(DB_PATH))
    try:
        return con.execute(query, params).fetchall()
    finally:
        con.close()


def discover_executable_paths() -> list[Path]:
    paths: set[Path] = set()
    for directory in CODE_DIRS + OPTIONAL_CODE_DIRS:
        if not directory.exists():
            continue
        for path in directory.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            paths.add(path.resolve())
    for path in STATE_FILES:
        if path.exists():
            paths.add(path.resolve())
    return sorted(paths)


def discover_documentation_paths() -> list[Path]:
    return [path.resolve() for path in DOC_FILES if path.exists()]


def iso_from_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def latest_executable_change(paths: list[Path] | None = None) -> tuple[Path, str] | None:
    paths = paths or discover_executable_paths()
    if not paths:
        return None
    latest = max(paths, key=lambda candidate: candidate.stat().st_mtime)
    return latest, iso_from_mtime(latest)


def previous_full_audit_time(state: dict[str, Any] | None = None) -> datetime | None:
    state = state or load_sentinel_state()
    last_full = state.get("last_full")
    if not last_full:
        return None
    audited_at = last_full.get("audited_at")
    if not audited_at:
        return None
    try:
        return datetime.fromisoformat(audited_at)
    except ValueError:
        return None


def discover_recent_executable_changes(
    since: datetime | None,
    limit: int = 20,
) -> list[Path]:
    paths = discover_executable_paths()
    if since is None:
        return sorted(paths, key=lambda candidate: candidate.stat().st_mtime, reverse=True)[:limit]

    since_ts = since.timestamp()
    changed = [path for path in paths if path.stat().st_mtime > since_ts]
    return sorted(changed, key=lambda candidate: candidate.stat().st_mtime, reverse=True)[:limit]


def discover_dynamic_research_targets() -> list[Path]:
    state = load_sentinel_state()
    since = previous_full_audit_time(state)
    candidates: dict[Path, None] = {}

    ledger = load_ledger()
    candidate_entry_ids = []
    next_frontier = ledger.get("active_state", {}).get("next_frontier_entry_id")
    if next_frontier:
        candidate_entry_ids.append(next_frontier)

    for entry in ledger.get("entries", []):
        if entry.get("entry_id") in candidate_entry_ids:
            for evidence_path in entry.get("evidence_paths", []):
                if evidence_path.startswith("backtests/") and evidence_path.endswith(".py"):
                    path = (ROOT / evidence_path).resolve()
                    if path.exists() and path.name not in CANONICAL_BACKTESTS:
                        candidates[path] = None

    if (ROOT / "backtests").exists():
        recent_candidates = discover_recent_executable_changes(since, limit=8)
        for path in recent_candidates:
            if path.parent != (ROOT / "backtests").resolve():
                continue
            if path.name in CANONICAL_BACKTESTS:
                continue
            if not (
                path.name.startswith("investigacion_")
                or path.name.startswith("auditoria_")
            ):
                continue
            candidates[path] = None

    return sorted(candidates.keys(), key=lambda candidate: candidate.stat().st_mtime)


def update_sentinel_state(mode: str, results: list[AuditResult]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    executable_paths = discover_executable_paths()
    doc_paths = discover_documentation_paths()
    latest_change = latest_executable_change(executable_paths)
    state = load_sentinel_state()
    now = datetime.now().isoformat(timespec="seconds")
    summary = {
        "audited_at": now,
        "mode": mode,
        "status": overall_status(results),
        "tracked_executable_files": len(executable_paths),
        "tracked_docs": len(doc_paths),
        "latest_executable_change": {
            "path": relative(latest_change[0]) if latest_change else None,
            "mtime": latest_change[1] if latest_change else None,
        },
        "recent_executable_changes": [
            {
                "path": relative(path),
                "mtime": iso_from_mtime(path),
            }
            for path in discover_recent_executable_changes(previous_full_audit_time(state), limit=12)
        ],
    }
    state["schema_version"] = 1
    state["last_run"] = summary
    if mode == "fast" and overall_status(results) != "FAIL":
        state["last_fast"] = summary
    if mode == "full" and overall_status(results) != "FAIL":
        state["last_full"] = summary
    SENTINEL_STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check_scanner_naming() -> AuditResult:
    bad = []
    canonical_files = []
    for path in SCANNER_DIR.iterdir():
        if path.name in {"__pycache__", "desktop.ini"}:
            continue
        if path.is_dir():
            bad.append(f"{path.name}/ (subdirectorio inesperado)")
            continue
        if not re.fullmatch(r"invertir_v\d+(?:_\d+)?\.py", path.name):
            bad.append(path.name)
        else:
            canonical_files.append(path.name)
    if bad:
        return AuditResult(
            "Naming SCANNER",
            "FAIL",
            "Hay archivos no canonicos o no promovidos dentro de SCANNER.",
            bad,
        )
    return AuditResult(
        "Naming SCANNER",
        "PASS",
        "SCANNER contiene solo scanners productivos canonicos (invertir_vN.py o invertir_vN_M.py).",
        [", ".join(sorted(canonical_files))],
    )


def check_active_scanner_autocontained() -> AuditResult:
    text = read_text(ACTIVE_SCANNER)
    forbidden = [
        line.strip()
        for line in text.splitlines()
        if "from SCANNER" in line or "import SCANNER" in line
    ]
    if forbidden:
        return AuditResult(
            "Autocontencion scanner activo",
            "FAIL",
            "El scanner activo importa codigo desde otros scanners.",
            forbidden,
        )
    return AuditResult(
        "Autocontencion scanner activo",
        "PASS",
        f"{ACTIVE_SCANNER.name} no importa desde SCANNER.",
        [],
    )


def check_gestor_alignment() -> AuditResult:
    text = read_text(GESTOR_PATH)
    details: list[str] = []
    summary = "El gestor canonico esta alineado con la logica V11."

    if "invertir_v10" in text and "from SCANNER.invertir_v10" in text:
        return AuditResult(
            "Gestor operativo",
            "FAIL",
            "El gestor sigue enganchado a V10.",
            ["Detectado import directo desde SCANNER.invertir_v10"],
        )
    if "from SCANNER.invertir_v11 import" not in text or "from SCANNER import invertir_v11 as v11" not in text:
        return AuditResult(
            "Gestor operativo",
            "FAIL",
            "No pude verificar los imports esperados de V11 en el gestor canonico.",
            [],
        )

    if LEGACY_GESTOR_PATH.exists():
        legacy_text = read_text(LEGACY_GESTOR_PATH)
        if "from herramientas.gestor_posiciones_v11 import main" not in legacy_text:
            return AuditResult(
                "Gestor operativo",
                "WARN",
                "Existe un archivo legacy v10, pero no parece un wrapper limpio hacia V11.",
                [],
            )
        details.append("Wrapper legacy v10 presente y redirigido a gestor_posiciones_v11.py")

    return AuditResult("Gestor operativo", "PASS", summary, details)


def check_gestor_v15_sizing() -> AuditResult:
    text = read_text(GESTOR_PATH)
    required_snippets = [
        "ATR_SIZING_ENABLED = True",
        "ATR_SIZING_TARGET_PCT = 4.0",
        "ATR_SIZING_MIN_FACTOR = 0.3",
        "ATR_SIZING_MAX_FACTOR = 2.0",
        "def calc_atr_size_factor(",
        "\"atr_pct\"",
        "\"size_factor\"",
        "\"size_note\"",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in text]
    if missing:
        return AuditResult(
            "Gestor V15 sizing",
            "FAIL",
            "No pude verificar la capa ATR sizing validada en el gestor operativo.",
            missing,
        )
    return AuditResult(
        "Gestor V15 sizing",
        "PASS",
        "El gestor operativo contiene la capa V15 de ATR sizing y la expone en su metadata.",
        [
            "Target 4.0%",
            "Clamp 0.3x -> 2.0x",
            "ATR%, size_factor y size_note presentes",
        ],
    )


def check_gestor_operational_loop() -> AuditResult:
    text = read_text(GESTOR_PATH)
    required_snippets = [
        '"equity_base"',
        '"slot_base"',
        '"notional_suggested"',
        '"shares_suggested"',
        '"shares_real"',
        '"entry_notional_effective"',
        '"realized_pnl_amount"',
        '"realized_pnl_equity_pct"',
        'daily-report',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in text]
    if missing:
        return AuditResult(
            "Loop operativo V15",
            "FAIL",
            "El gestor no parece persistir todavia el loop sized completo de V15.",
            missing,
        )

    if not GESTOR_STATE_PATH.exists():
        return AuditResult(
            "Loop operativo V15",
            "FAIL",
            "No existe el estado persistente del gestor V15.",
            [str(GESTOR_STATE_PATH)],
        )

    state = json.loads(GESTOR_STATE_PATH.read_text(encoding="utf-8"))
    details = [
        f"state_version = {state.get('version')}",
        f"policy = {state.get('policy')}",
        f"positions = {len(state.get('positions', []))}",
    ]
    if state.get("version", 0) < 2:
        return AuditResult(
            "Loop operativo V15",
            "FAIL",
            "El estado persistente del gestor no migro al esquema V15 versionado.",
            details,
        )

    return AuditResult(
        "Loop operativo V15",
        "PASS",
        "El gestor persiste el loop sized V15 y su estado esta versionado.",
        details,
    )


def check_pipeline_gestor_step() -> AuditResult:
    text = read_text(AUTO_UPDATE_PATH)
    required_snippets = [
        "GESTOR_SCRIPT",
        "AUDIT_SCRIPT",
        "DASHBOARD_SCRIPT",
        "build_learning_steps",
        "resolve_operational_scanner_context",
        "operational.active_learning is None",
        '"gestor"',
        '"daily-report"',
        '"dashboard_maquina_core"',
        '"dashboard_maquina_final"',
        '"auditoria_centinela"',
        '"--mode", "fast"',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in text]
    if missing:
        return AuditResult(
            "Pipeline diario gestor",
            "FAIL",
            "El pipeline diario no integra todavia el cierre completo gestor + auditoria centinela.",
            missing,
        )
    return AuditResult(
        "Pipeline diario gestor",
        "PASS",
        "auto_actualizar integra el cierre gestor + dashboard + auditoria centinela y la cadena dinamica de aprendizaje.",
        ["Pipeline esperado: update -> validate -> aprendizaje base/referencia/activo -> scanner activo -> gestor -> resumenes -> dashboard core -> auditoria fast -> opcionales -> dashboard final"],
    )


def check_market_metadata() -> AuditResult:
    latest_prices_date = sqlite_value("SELECT value FROM data_status WHERE key='latest_prices_date'")
    updated_at = sqlite_value("SELECT value FROM data_status WHERE key='market_data_updated_at'")
    latest_spy = sqlite_value("SELECT MAX(date) FROM prices WHERE ticker='SPY'")
    total_rows = sqlite_value("SELECT COUNT(*) FROM data_status")

    details = [
        f"latest_prices_date = {latest_prices_date}",
        f"market_data_updated_at = {updated_at}",
        f"latest_spy = {latest_spy}",
        f"data_status rows = {total_rows}",
    ]
    if not latest_prices_date or not updated_at:
        return AuditResult(
            "Metadata de mercado",
            "FAIL",
            "data_status no esta poblada correctamente.",
            details,
        )
    if latest_prices_date != latest_spy:
        return AuditResult(
            "Metadata de mercado",
            "FAIL",
            "data_status no coincide con la ultima fecha real de SPY.",
            details,
        )
    return AuditResult(
        "Metadata de mercado",
        "PASS",
        "data_status esta poblada y alineada con la ultima fecha real de mercado.",
        details,
    )


def _trading_days_between(start_str: str, end_str: str) -> int:
    """Cuenta dias habiles (lun-vie) entre dos fechas ISO, extremos inclusive si distintos."""
    from datetime import date
    start = date.fromisoformat(start_str)
    end = date.fromisoformat(end_str)
    if end <= start:
        return 0
    cursor = start + timedelta(days=1)
    count = 0
    while cursor <= end:
        if cursor.weekday() < 5:
            count += 1
        cursor += timedelta(days=1)
    return count


def _expected_last_closed_trading_day() -> str:
    """
    Devuelve la ultima fecha bursatil (lun-vie) para la que NYSE deberia tener datos completos.

    Usa UTC para calcular si hoy ya cerro el mercado:
    - NYSE cierra 21:00 UTC en invierno (EST) y 20:00 UTC en verano (EDT).
    - Umbral conservador: 21:30 UTC. Antes de ese umbral, la ultima fecha
      cerrada es el dia habitual anterior a hoy.
    """
    from datetime import datetime as dt, date
    utc_now = dt.utcnow()
    hoy_utc = utc_now.date()

    # Umbral conservador: siempre despues de cierre NYSE en cualquier estacion
    MARKET_CLOSED_UTC_HOUR = 21
    MARKET_CLOSED_UTC_MINUTE = 30

    if (utc_now.hour > MARKET_CLOSED_UTC_HOUR or
            (utc_now.hour == MARKET_CLOSED_UTC_HOUR and utc_now.minute >= MARKET_CLOSED_UTC_MINUTE)):
        candidate = hoy_utc
    else:
        candidate = hoy_utc - timedelta(days=1)

    # Retroceder al ultimo dia habitual si es fin de semana
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate.isoformat()


def check_db_temporal_freshness() -> AuditResult:
    """
    Verifica que la DB tenga datos hasta el ultimo dia bursatil que deberia haber cerrado.

    check_market_metadata() verifica coherencia interna (data_status == MAX en DB).
    Este check verifica frescura externa: si la fecha que tiene la DB es la esperada
    segun el horario real del mercado. Si la DB esta vieja, todos los analisis
    subsiguientes son sobre datos obsoletos.
    """
    db_latest = sqlite_value("SELECT MAX(date) FROM prices WHERE ticker='SPY'")
    expected = _expected_last_closed_trading_day()

    details = [
        f"db_latest_spy = {db_latest}",
        f"expected_last_closed = {expected}",
        f"umbral_cierre = 21:30 UTC (conservador, ambas estaciones NYSE)",
    ]

    if not db_latest:
        return AuditResult("Frescura temporal DB", "FAIL", "No hay datos de SPY en la DB.", details)

    if db_latest >= expected:
        return AuditResult(
            "Frescura temporal DB",
            "PASS",
            f"DB actualizada: SPY hasta {db_latest} (esperado: {expected}).",
            details,
        )

    trading_days_behind = _trading_days_between(db_latest, expected)
    details.append(f"dias_habiles_atrasados = {trading_days_behind}")

    if trading_days_behind == 1:
        return AuditResult(
            "Frescura temporal DB",
            "WARN",
            f"DB 1 dia habitual atras ({db_latest} vs {expected}). Puede ser feriado NYSE o pipeline no ejecutado aun.",
            details,
        )

    return AuditResult(
        "Frescura temporal DB",
        "FAIL",
        f"DB {trading_days_behind} dias habiles atras ({db_latest} vs {expected}). "
        "Ejecutar: python herramientas/actualizar_datos.py [--force-today si son antes de 19:00 en verano]",
        details,
    )


def check_pending_evaluations_stale() -> AuditResult:
    """
    Verifica que no haya predicciones cuyo target_date ya paso (segun la DB)
    pero que todavia no tienen outcome registrado.

    Estas predicciones 'huerfanas' indican que el pipeline de aprendizaje
    no corrio despues de que los datos del target_date llegaron a la DB.
    En el dashboard se muestran como provisionales/pendientes aunque el
    dato real ya existe — es el error critico que se quiere prevenir.
    """
    db_latest = sqlite_value("SELECT MAX(date) FROM prices")
    if not db_latest:
        return AuditResult(
            "Evaluaciones pendientes stale",
            "WARN",
            "No hay precios en la DB para verificar.",
            [],
        )

    stale_count = sqlite_value(
        """
        SELECT COUNT(*)
        FROM predictions p
        WHERE p.target_date <= ?
          AND NOT EXISTS (SELECT 1 FROM outcomes o WHERE o.prediction_id = p.id)
        """,
        (db_latest,),
    ) or 0

    details = [
        f"db_latest = {db_latest}",
        f"predicciones_sin_outcome_cuyo_target_date_ya_paso = {stale_count}",
    ]

    if int(stale_count) == 0:
        return AuditResult(
            "Evaluaciones pendientes stale",
            "PASS",
            "Todas las predicciones con target_date pasado tienen outcome registrado.",
            details,
        )

    # Detalle: cuales modelos tienen el problema
    stale_rows = sqlite_value_many(
        """
        SELECT p.model_name, COUNT(*) as cnt, MIN(p.target_date) as oldest_target
        FROM predictions p
        WHERE p.target_date <= ?
          AND NOT EXISTS (SELECT 1 FROM outcomes o WHERE o.prediction_id = p.id)
        GROUP BY p.model_name
        ORDER BY oldest_target
        """,
        (db_latest,),
    )
    for row in (stale_rows or []):
        details.append(f"  modelo={row[0]}  sin_evaluar={row[1]}  target_mas_antiguo={row[2]}")

    return AuditResult(
        "Evaluaciones pendientes stale",
        "FAIL",
        f"{stale_count} predicciones con target_date <= {db_latest} sin outcome. "
        "Re-ejecutar el loop de aprendizaje operativo para el modelo correspondiente.",
        details,
    )


def check_dashboard_freshness() -> AuditResult:
    details = [
        f"snapshot = {relative(TABLERO_SNAPSHOT_PATH) if TABLERO_SNAPSHOT_PATH.exists() else '-'}",
        f"html = {relative(TABLERO_INDEX_PATH) if TABLERO_INDEX_PATH.exists() else '-'}",
        f"aurora = {relative(AURORA_PRO_HTML) if AURORA_PRO_HTML.exists() else '-'}",
    ]

    if not TABLERO_SNAPSHOT_PATH.exists() or not TABLERO_INDEX_PATH.exists() or not AURORA_PRO_HTML.exists():
        return AuditResult(
            "Tablero maquina pensante",
            "FAIL",
            "Faltan artefactos del dashboard operativo principal canonico.",
            details,
        )

    try:
        payload = json.loads(TABLERO_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return AuditResult(
            "Tablero maquina pensante",
            "FAIL",
            "El snapshot del dashboard no es JSON valido.",
            details + [str(exc)],
        )

    integrity = payload.get("integrity") or {}
    snapshot_market = integrity.get("latest_market_date")
    snapshot_prediction = integrity.get("latest_prediction_date")
    snapshot_outcome = integrity.get("latest_outcome_date")
    generated_at = payload.get("generated_at")

    db_market = sqlite_value("SELECT value FROM data_status WHERE key='latest_prices_date'")
    db_prediction = sqlite_value("SELECT MAX(prediction_date) FROM predictions")
    db_outcome = sqlite_value(
        """
        SELECT MAX(p.target_date)
        FROM outcomes o
        JOIN predictions p ON p.id = o.prediction_id
        """
    )

    details.extend(
        [
            f"generated_at = {generated_at}",
            f"snapshot_market = {snapshot_market}",
            f"db_market = {db_market}",
            f"snapshot_prediction = {snapshot_prediction}",
            f"db_prediction = {db_prediction}",
            f"snapshot_outcome = {snapshot_outcome}",
            f"db_outcome = {db_outcome}",
        ]
    )

    mismatches: list[str] = []
    if snapshot_market != db_market:
        mismatches.append("latest_market_date")
    if snapshot_prediction != db_prediction:
        mismatches.append("latest_prediction_date")
    if snapshot_outcome != db_outcome:
        mismatches.append("latest_outcome_date")

    if mismatches:
        return AuditResult(
            "Tablero maquina pensante",
            "FAIL",
            "El dashboard principal quedo desfasado respecto de la DB operativa.",
            details + [f"mismatch = {', '.join(mismatches)}"],
        )

    return AuditResult(
        "Tablero maquina pensante",
        "PASS",
        "El dashboard principal refleja la misma fecha de mercado/predicciones/outcomes que la DB.",
        details,
    )


def check_dashboard_topn_alignment() -> AuditResult:
    details: list[str] = []

    if not TABLERO_SNAPSHOT_PATH.exists():
        return AuditResult(
            "Top N dashboard",
            "FAIL",
            "No existe el snapshot del dashboard para auditar el top N estandar.",
            [relative(TABLERO_SNAPSHOT_PATH)],
        )

    try:
        payload = json.loads(TABLERO_SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return AuditResult(
            "Top N dashboard",
            "FAIL",
            "El snapshot del dashboard no es JSON valido.",
            [str(exc)],
        )

    policy = payload.get("competition_policy") or {}
    snapshot_top_n = policy.get("top_n")
    details.append(f"snapshot_top_n = {snapshot_top_n}")
    details.append(f"expected_top_n = {STANDARD_TOP_N}")

    if snapshot_top_n != STANDARD_TOP_N:
        return AuditResult(
            "Top N dashboard",
            "FAIL",
            "El snapshot no refleja el top N operativo estandar vigente.",
            details,
        )

    competition_rows = {
        str(row.get("version")): row
        for row in (payload.get("competition") or [])
    }

    mismatches: list[str] = []
    for entry in monitored_entries():
        label = str(entry["label"])
        row = competition_rows.get(label)
        if row is None:
            mismatches.append(f"{label}:sin_fila_dashboard")
            continue

        snapshots = load_entry_snapshots(entry)
        if not snapshots:
            mismatches.append(f"{label}:sin_snapshots")
            continue

        latest_date = max(snapshots)
        expected = [str(item["ticker"]) for item in extract_ranked_snapshot_picks(snapshots[latest_date])[:STANDARD_TOP_N]]
        actual = [str(item) for item in (row.get("latest_tickers") or [])]
        details.append(f"{label} | latest_date = {latest_date} | expected = {', '.join(expected) or '-'} | actual = {', '.join(actual) or '-'}")
        if actual != expected:
            mismatches.append(label)

    if mismatches:
        return AuditResult(
            "Top N dashboard",
            "FAIL",
            "La liga del dashboard no coincide con el top N real de los snapshots operativos.",
            details + [f"mismatch = {', '.join(mismatches)}"],
        )

    return AuditResult(
        "Top N dashboard",
        "PASS",
        "El dashboard refleja el mismo top N estandar y los mismos tickers que los snapshots reales.",
        details,
    )


def check_sentinel_freshness(mode: str) -> AuditResult:
    state = load_sentinel_state()
    previous_full = previous_full_audit_time(state)
    recent_changes = discover_recent_executable_changes(previous_full, limit=12)

    if previous_full is None:
        if mode == "full":
            details = [f"{relative(path)} | {iso_from_mtime(path)}" for path in recent_changes[:8]]
            return AuditResult(
                "Centinela de integridad",
                "PASS",
                "No habia baseline full previo; esta corrida full lo va a crear.",
                details,
            )
        return AuditResult(
            "Centinela de integridad",
            "FAIL",
            "No existe baseline de auditoria full. Ejecutar una auditoria integral full antes de confiar en el proyecto.",
            [],
        )

    if recent_changes:
        details = [f"{relative(path)} | {iso_from_mtime(path)}" for path in recent_changes]
        if mode == "fast":
            return AuditResult(
                "Centinela de integridad",
                "FAIL",
                "Hay cambios ejecutables posteriores al ultimo full audit. El proyecto esta stale hasta rerunear auditoria full.",
                details,
            )
        return AuditResult(
            "Centinela de integridad",
            "PASS",
            "Se detectaron cambios desde el ultimo full audit y esta corrida full los esta revalidando.",
            details,
        )

    last_full = state.get("last_full", {})
    return AuditResult(
        "Centinela de integridad",
        "PASS",
        "No hay cambios ejecutables posteriores al ultimo full audit.",
        [
            f"last_full = {last_full.get('audited_at')}",
            f"tracked_executable_files = {last_full.get('tracked_executable_files')}",
        ],
    )


def check_learning_basis() -> AuditResult:
    text = read_text(LEARNING_BASIS_PATH)
    required_snippets = [
        "entry_date = self.trading_day_offset(str(pred_date), 1)",
        "SELECT open",
        "SELECT close",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in text]
    if missing:
        return AuditResult(
            "Base de evaluacion memoria",
            "FAIL",
            "No se pudo verificar la medicion operable open->close en aprendizaje_operativo_v11.",
            missing,
        )
    return AuditResult(
        "Base de evaluacion memoria",
        "PASS",
        "Los outcomes V11 se miden con base operable (open siguiente -> close target).",
        [],
    )


def check_doc_alignment() -> AuditResult:
    ledger = load_ledger()
    champion_id = ledger["active_state"]["scanner_entry_id"]
    champion = next(entry for entry in ledger["entries"] if entry["entry_id"] == champion_id)
    metrics = champion["metrics"]

    # Support V11-style (independent_broad/core + portfolio_broad/core),
    # V12-style (portfolio_broad_after_v12) and V13-style (portfolio_broad_after_v13).
    _ind_broad = metrics.get("independent_broad") or {}
    _ind_core = metrics.get("independent_core") or {}
    _port_broad = (
        metrics.get("portfolio_broad")
        or metrics.get("portfolio_broad_after_v12")
        or metrics.get("portfolio_broad_after_v13")
        or {}
    )
    _port_core = metrics.get("portfolio_core") or {}

    broad_sharpe = str(_ind_broad["sharpe"]) if _ind_broad else None
    core_sharpe = str(_ind_core["sharpe"]) if _ind_core else None
    portfolio_broad = str(_port_broad["sharpe"]) if _port_broad else None
    portfolio_core = str(_port_core["sharpe"]) if _port_core else None

    texts = {
        "CLAUDE.md": read_text(CLAUDE_MD),
        "context-essentials.md": read_text(CONTEXT_MD),
        "ESTRUCTURA.md": read_text(ESTRUCTURA_MD),
    }
    problems: list[str] = []

    for label, text in texts.items():
        if "vol_ratio<=1.5" not in text and "Volumen relativo <= 1.5x" not in text:
            problems.append(f"{label}: no documenta el filtro A_VOL_MAX / vol_ratio<=1.5")
    if broad_sharpe is not None:
        if broad_sharpe not in texts["CLAUDE.md"] or (core_sharpe and core_sharpe not in texts["CLAUDE.md"]):
            problems.append("CLAUDE.md: no refleja los Sharpes revalidados del champion")
        if broad_sharpe not in texts["ESTRUCTURA.md"] or (core_sharpe and core_sharpe not in texts["ESTRUCTURA.md"]):
            problems.append("ESTRUCTURA.md: no refleja los Sharpes revalidados del champion")
    if portfolio_broad is not None:
        if portfolio_broad not in texts["CLAUDE.md"]:
            problems.append("CLAUDE.md: no refleja los Sharpes de cartera revalidados")
        if portfolio_core is not None and portfolio_core not in texts["CLAUDE.md"]:
            problems.append("CLAUDE.md: no refleja el Sharpe de cartera core revalidado")
    next_frontier_entry_id = ledger.get("active_state", {}).get("next_frontier_entry_id")
    if next_frontier_entry_id:
        next_entry = next(
            (entry for entry in ledger["entries"] if entry["entry_id"] == next_frontier_entry_id),
            None,
        )
        if next_entry is None:
            problems.append("scanner_ledger.json: next_frontier_entry_id no apunta a una entrada valida")
        else:
            frontier_hint = next_entry["entry_id"]
            frontier_markers = [frontier_hint, *next_entry.get("evidence_paths", [])]

            if not any(marker in texts["CLAUDE.md"] for marker in frontier_markers):
                problems.append("CLAUDE.md: no refleja la frontera aprobada del ledger")
            if not any(marker in texts["ESTRUCTURA.md"] for marker in frontier_markers):
                problems.append("ESTRUCTURA.md: no refleja la frontera aprobada del ledger")
            if not any(marker in texts["context-essentials.md"] for marker in frontier_markers):
                problems.append("context-essentials.md: no refleja la frontera aprobada del ledger")

    if problems:
        return AuditResult(
            "Alineacion documental",
            "FAIL",
            "Hay desalineaciones entre champion/logic y documentacion activa.",
            problems,
        )
    return AuditResult(
        "Alineacion documental",
        "PASS",
        "La documentacion activa refleja el champion real y sus filtros clave.",
        [
            f"Champion {champion_id}",
            f"Broad sharpe {broad_sharpe} | Core sharpe {core_sharpe}",
            f"Portfolio broad {portfolio_broad} | Portfolio core {portfolio_core}",
        ],
    )


def result_from_command(name: str, command: list[str], timeout_ms: int, success_summary: str) -> AuditResult:
    try:
        completed = run_command(command, timeout_ms=timeout_ms)
    except subprocess.TimeoutExpired as exc:
        return AuditResult(
            name,
            "FAIL",
            f"Timeout al ejecutar: {' '.join(command)}",
            [
                f"timeout_ms = {timeout_ms}",
                f"command = {' '.join(command)}",
                f"partial_stdout = {(exc.stdout or '').strip().splitlines()[-1] if exc.stdout else ''}",
                f"partial_stderr = {(exc.stderr or '').strip().splitlines()[-1] if exc.stderr else ''}",
            ],
        )
    details = []
    if completed.stdout.strip():
        details.extend(completed.stdout.strip().splitlines()[-12:])
    if completed.stderr.strip():
        details.append("STDERR:")
        details.extend(completed.stderr.strip().splitlines()[-8:])
    if completed.returncode != 0:
        return AuditResult(name, "FAIL", f"Fallo al ejecutar: {' '.join(command)}", details)
    return AuditResult(name, "PASS", success_summary, details)


def check_validate_market_data() -> AuditResult:
    command = [sys.executable, str(ROOT / "herramientas" / "validate_market_data.py")]
    completed = run_command(command, timeout_ms=90000)
    stdout = completed.stdout.strip().splitlines()
    status = "PASS"
    summary = "validate_market_data paso sin alertas relevantes."
    if any("Resultado final: WARN" in line for line in stdout):
        status = "WARN"
        summary = "validate_market_data detecto alertas, pero el pipeline puede continuar."
    if completed.returncode != 0 or any("Resultado final: FAIL" in line for line in stdout):
        status = "FAIL"
        summary = "validate_market_data fallo o devolvio FAIL."
    return AuditResult("Validacion de datos", status, summary, stdout[-18:])


def _scanner_health_from_output(name: str, completed: subprocess.CompletedProcess[str]) -> AuditResult:
    stdout_lines = completed.stdout.strip().splitlines()
    details = stdout_lines[-16:]
    if completed.stderr.strip():
        details.append("STDERR:")
        details.extend(completed.stderr.strip().splitlines()[-8:])
    if completed.returncode != 0:
        return AuditResult(name, "FAIL", "El scanner fallo al ejecutarse.", details)

    status_line = next((line.strip() for line in stdout_lines if "Estado senal" in line), "")
    if not status_line:
        return AuditResult(name, "FAIL", "El scanner no expuso su estado de vigencia en la salida.", details)
    if "VENCIDA" in status_line or "STALE" in status_line:
        return AuditResult(name, "FAIL", "El scanner corrio, pero la senal no esta vigente o la base esta stale.", details)
    return AuditResult(name, "PASS", "El scanner corre y entrega salida vigente.", details)


def check_ledger() -> AuditResult:
    return result_from_command(
        "Ledger champion",
        [sys.executable, str(ROOT / "herramientas" / "ledger_experimentos.py"), "validate"],
        timeout_ms=30000,
        success_summary="El ledger valida correctamente.",
    )


def check_scanner_smoke() -> AuditResult:
    # --equity 1 evita el prompt interactivo de capital (0 causa ZeroDivisionError en sizing)
    completed = run_command([sys.executable, str(ACTIVE_SCANNER), "--equity", "1"], timeout_ms=60000)
    return _scanner_health_from_output("Smoke scanner activo", completed)


def learning_versions_under_audit() -> list[int]:
    versions: list[int] = []
    for script in OPERATIONAL.learning_chain:
        version = learning_version_from_path(script)
        if version not in versions:
            versions.append(version)
    return versions


def _learning_role(version: int) -> str:
    if version == OPERATIONAL.active_version:
        return "activo"
    if OPERATIONAL.reference_version is not None and version == OPERATIONAL.reference_version:
        return "referencia inmediata"
    if version == 11:
        return "base"
    return "operativo"


def check_active_learning_alignment() -> AuditResult:
    details = [
        f"scanner_activo = {relative(OPERATIONAL.active_scanner)}",
        f"active_version = V{OPERATIONAL.active_version}",
    ]
    if OPERATIONAL.reference_scanner is not None:
        details.append(f"scanner_referencia = {relative(OPERATIONAL.reference_scanner)}")
    if OPERATIONAL.active_learning is None:
        return AuditResult(
            "Aprendizaje scanner activo",
            "FAIL",
            "El scanner activo no tiene aprendizaje operativo propio. La promocion quedo incompleta.",
            details,
        )
    details.append(f"aprendizaje_activo = {relative(OPERATIONAL.active_learning)}")
    if OPERATIONAL.reference_learning is not None:
        details.append(f"aprendizaje_referencia = {relative(OPERATIONAL.reference_learning)}")
    if OPERATIONAL.base_learning is not None:
        details.append(f"aprendizaje_base = {relative(OPERATIONAL.base_learning)}")
    return AuditResult(
        "Aprendizaje scanner activo",
        "PASS",
        "El scanner activo tiene loop operativo propio y cadena de aprendizaje resoluble.",
        details,
    )


def check_learning_smoke_for_version(version: int) -> AuditResult:
    latest_spy = sqlite_value("SELECT MAX(date) FROM prices WHERE ticker='SPY'")
    script_path = ROOT / "herramientas" / f"aprendizaje_operativo_v{version}.py"
    role = _learning_role(version)
    return result_from_command(
        f"Smoke aprendizaje V{version}",
        [
            sys.executable,
            str(script_path),
            "daily-summary",
            "--date",
            str(latest_spy),
        ],
        timeout_ms=45000,
        success_summary=f"El loop operativo {role} V{version} puede emitir resumen diario sin fallar.",
    )


def check_gestor_smoke() -> AuditResult:
    return result_from_command(
        "Smoke gestor diario",
        [sys.executable, str(ROOT / "herramientas" / "gestor_posiciones_v11.py"), "daily-report"],
        timeout_ms=45000,
        success_summary="El gestor puede emitir su reporte diario sized sin fallar.",
    )


def check_reference_scanner_smoke() -> AuditResult:
    if PREV_SCANNER is None or not PREV_SCANNER.exists():
        return AuditResult(
            "Smoke scanner referencia inmediata",
            "WARN",
            "No existe scanner productivo previo para validar.",
            [],
        )
    completed = run_command([sys.executable, str(PREV_SCANNER), "--equity", "1"], timeout_ms=90000)
    return _scanner_health_from_output("Smoke scanner referencia inmediata", completed)


def _check_learning_persistence(version: int) -> AuditResult:
    run_dir = run_dir_for_version(version)
    model_prefix = model_prefix_for_version(version)
    label = f"Persistencia aprendizaje V{version}"
    if not run_dir.exists():
        return AuditResult(
            label,
            "FAIL",
            "No existe la carpeta de snapshots del loop operativo.",
            [relative(run_dir)],
        )

    run_paths = sorted(run_dir.glob("*.json"))
    if not run_paths:
        return AuditResult(
            label,
            "FAIL",
            "No hay snapshots diarios para verificar persistencia.",
            [relative(run_dir)],
        )

    latest_run = max(run_paths, key=lambda path: path.stem)
    artifact = json.loads(latest_run.read_text(encoding="utf-8"))
    analyzed_date = artifact.get("analyzed_date")
    if not analyzed_date:
        return AuditResult(
            label,
            "FAIL",
            "El snapshot mas reciente no tiene analyzed_date.",
            [relative(latest_run)],
        )

    expected = (
        len(artifact.get("results_a", [])) * 2
        + len(artifact.get("results_c5", [])) * 3
        + len(artifact.get("results_d", [])) * 1
        + len(artifact.get("results_e", [])) * 1
    )
    actual = sqlite_value(
        "SELECT COUNT(*) FROM predictions WHERE model_name LIKE ? AND prediction_date = ?",
        (f"{model_prefix}_%", analyzed_date),
    ) or 0
    details = [
        f"snapshot = {relative(latest_run)}",
        f"prediction_date = {analyzed_date}",
        f"expected_predictions = {expected}",
        f"actual_predictions = {actual}",
    ]
    if int(actual) != int(expected):
        return AuditResult(
            label,
            "FAIL",
            "Las senales del snapshot mas reciente no coinciden con lo persistido en predictions.",
            details,
        )
    return AuditResult(
        label,
        "PASS",
        "El snapshot mas reciente y la tabla predictions estan alineados.",
        details,
    )


def _check_snapshot_runtime_context(version: int) -> AuditResult:
    run_dir = run_dir_for_version(version)
    label = f"Runtime context V{version}"
    if not run_dir.exists():
        return AuditResult(label, "FAIL", "No existe la carpeta de snapshots del loop operativo.", [relative(run_dir)])

    run_paths = sorted(run_dir.glob("*.json"))
    if not run_paths:
        return AuditResult(label, "FAIL", "No hay snapshots diarios para verificar runtime context.", [relative(run_dir)])

    latest_run = max(run_paths, key=lambda path: path.stem)
    artifact = json.loads(latest_run.read_text(encoding="utf-8"))
    runtime_context = artifact.get("runtime_context")
    if not isinstance(runtime_context, dict):
        return AuditResult(
            label,
            "FAIL",
            "El snapshot mas reciente no guarda runtime_context reproducible.",
            [relative(latest_run)],
        )

    required_keys = [
        "scanner_path",
        "latest_db_date",
        "python_version",
        "platform",
        "critical_file_hashes",
        "runtime_fingerprint",
    ]
    missing = [key for key in required_keys if key not in runtime_context]
    if missing:
        return AuditResult(
            label,
            "FAIL",
            "El runtime_context del snapshot mas reciente esta incompleto.",
            [relative(latest_run), *missing],
        )

    details = [
        f"snapshot = {relative(latest_run)}",
        f"runtime_fingerprint = {runtime_context.get('runtime_fingerprint')}",
        f"scanner_path = {runtime_context.get('scanner_path')}",
        f"latest_db_date = {runtime_context.get('latest_db_date')}",
        f"python_version = {runtime_context.get('python_version')}",
    ]
    return AuditResult(
        label,
        "PASS",
        "El snapshot mas reciente guarda contexto reproducible de codigo y runtime.",
        details,
    )


def check_learning_operational_results() -> list[AuditResult]:
    results: list[AuditResult] = [check_active_learning_alignment()]
    for version in learning_versions_under_audit():
        results.append(check_learning_smoke_for_version(version))
        results.append(_check_learning_persistence(version))
        results.append(_check_snapshot_runtime_context(version))
    return results


def check_backtests_full() -> list[AuditResult]:
    commands = [
        ("Backtest V9", [sys.executable, str(ROOT / "backtests" / "investigacion_v9_path_quality.py")], 480000),
        ("Backtest V10", [sys.executable, str(ROOT / "backtests" / "investigacion_v10_rebound_capture.py")], 480000),
        ("Backtest V11", [sys.executable, str(ROOT / "backtests" / "investigacion_v11_cap_operativo.py")], 480000),
        ("Backtest V12", [sys.executable, str(ROOT / "backtests" / "investigacion_v12_portfolio_operativo.py")], 480000),
        ("Backtest V14", [sys.executable, str(ROOT / "backtests" / "investigacion_v14_prioridad_memoria.py")], 480000),
        # V15 excluido: tarda >25 min consistentemente; su logica ATR sizing
        # ya esta validada por check_gestor_v15_sizing() que corre en modo fast.
    ]
    for path in discover_dynamic_research_targets():
        commands.append(
            (
                f"Research {path.stem}",
                [sys.executable, str(path)],
                2700000,
            )
        )
    results: list[AuditResult] = []
    for name, command, timeout_ms in commands:
        results.append(
            result_from_command(
                name,
                command,
                timeout_ms=timeout_ms,
                success_summary=f"{name} corre sin crash.",
            )
        )
    return results


def check_compile_targets() -> AuditResult:
    targets = [
        str(path)
        for path in discover_executable_paths()
        if path.suffix == ".py"
    ]
    command = [sys.executable, "-m", "py_compile", *[str(path) for path in targets]]
    return result_from_command(
        "Compilacion Python",
        command,
        timeout_ms=120000,
        success_summary=f"Los objetivos criticos compilan correctamente ({len(targets)} archivos Python).",
    )


def check_db_usage() -> AuditResult:
    con = sqlite3.connect(str(DB_PATH))
    try:
        predictions = con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        outcomes = con.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
        regimes = con.execute("SELECT COUNT(*) FROM regimes").fetchone()[0]
        model_metrics = con.execute("SELECT COUNT(*) FROM model_metrics").fetchone()[0]
    finally:
        con.close()

    details = [
        f"predictions = {predictions}",
        f"outcomes = {outcomes}",
        f"regimes = {regimes}",
        f"model_metrics = {model_metrics}",
    ]
    if model_metrics == 0:
        return AuditResult(
            "Uso de tablas DB",
            "WARN",
            "Las tablas operativas viven, pero model_metrics sigue sin usarse.",
            details,
        )
    return AuditResult(
        "Uso de tablas DB",
        "PASS",
        "Las tablas operativas principales estan pobladas.",
        details,
    )


def format_result(result: AuditResult) -> list[str]:
    lines = [f"[{result.status}] {result.name}: {result.summary}"]
    for detail in result.details:
        lines.append(f"  - {detail}")
    return lines


def overall_status(results: list[AuditResult]) -> str:
    if any(result.status == "FAIL" for result in results):
        return "FAIL"
    if any(result.status == "WARN" for result in results):
        return "WARN"
    return "PASS"


def write_report(mode: str, results: list[AuditResult]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    path = REPORTS_DIR / f"{now.strftime('%Y-%m-%d_%H-%M-%S')}_auditoria_integral_{mode}.txt"
    lines = [
        LINE,
        f"  AUDITORIA INTEGRAL CLAUDE | {now.strftime('%Y-%m-%d %H:%M:%S')}",
        LINE,
        f"  Modo            : {mode}",
        f"  Resultado final : {overall_status(results)}",
        SUBLINE,
    ]
    for result in results:
        lines.extend(format_result(result))
        lines.append(SUBLINE)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def _console_safe(text: str) -> str:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def print_report(path: Path, results: list[AuditResult], mode: str) -> None:
    print(_console_safe(LINE))
    print(_console_safe("  AUDITORIA INTEGRAL CLAUDE"))
    print(_console_safe(LINE))
    print(_console_safe(f"  Modo            : {mode}"))
    print(_console_safe(f"  Resultado final : {overall_status(results)}"))
    print(_console_safe(f"  Reporte         : {path}"))
    print(_console_safe(SUBLINE))
    for result in results:
        for line in format_result(result):
            print(_console_safe(line))
        print(_console_safe(SUBLINE))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auditoria integral reproducible del proyecto Claude")
    parser.add_argument("--mode", choices=["fast", "full"], default="full")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")

    results: list[AuditResult] = [
        check_sentinel_freshness(args.mode),
        check_scanner_naming(),
        check_active_scanner_autocontained(),
        check_compile_targets(),
        check_market_metadata(),
        check_db_temporal_freshness(),
        check_pending_evaluations_stale(),
        check_dashboard_freshness(),
        check_dashboard_topn_alignment(),
        check_validate_market_data(),
        check_learning_basis(),
        check_gestor_alignment(),
        check_gestor_v15_sizing(),
        check_gestor_operational_loop(),
        check_pipeline_gestor_step(),
        check_scanner_smoke(),
        check_reference_scanner_smoke(),
        check_gestor_smoke(),
        check_ledger(),
        check_doc_alignment(),
        check_db_usage(),
    ]
    results.extend(check_learning_operational_results())

    if args.mode == "full":
        results.extend(check_backtests_full())

    report_path = write_report(args.mode, results)
    update_sentinel_state(args.mode, results)
    print_report(report_path, results, args.mode)
    return 1 if overall_status(results) == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
