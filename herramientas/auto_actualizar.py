#!/usr/bin/env python3
"""
AUTO-ACTUALIZADOR Y PIPELINE DIARIO PYTHIAXENGINE
================================================
Actualiza titan.db automaticamente cuando detecta dias bursatiles cerrados
sin datos y, cuando corresponde, ejecuta el flujo diario completo:

    actualizar_datos -> validate_market_data -> aprendizaje base/referencia/activo
    -> scanner activo -> gestor -> resumentes operativos -> auditoria fast

Esta pensado para correr todos los dias y tambien al iniciar sesion como
red de seguridad.

Ubicacion: herramientas/auto_actualizar.py
Registrar en Windows: ejecutar herramientas/setup_tarea_windows.bat

Nota:
  La carpeta local puede seguir llamandose `Claude/`, pero este pipeline
  pertenece a `PythiaxEngine` y debe priorizar siempre el flujo cloud-first.
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from sqlalchemy.engine import make_url

# Este script vive en el working copy historico `Claude/`, pero opera sobre la
# raiz canonica del repo PythiaxEngine.
BASE_DIR = Path(__file__).parent.parent
LOG_PATH = BASE_DIR / "bitacora" / "auto_actualizar.log"
RUN_REPORTS_DIR = BASE_DIR / "aprendizaje_operativo" / "v11_reports"
ALERTS_DIR = BASE_DIR / "aprendizaje_operativo" / "alerts"
VALIDATE_SCRIPT = BASE_DIR / "herramientas" / "validate_market_data.py"
GESTOR_SCRIPT = BASE_DIR / "herramientas" / "gestor_posiciones_v11.py"
AUDIT_SCRIPT = BASE_DIR / "herramientas" / "auditoria_integral_claude.py"
DASHBOARD_INTEGRITY_SCRIPT = BASE_DIR / "infra" / "cloud" / "audit_dashboard_integrity.py"
DASHBOARD_SCRIPT = BASE_DIR / "analisis" / "generar_tablero_maquina_pensante.py"
MODEL_FRESHNESS_REPORT = BASE_DIR / "docs" / "cloud" / "reports" / "model_snapshot_freshness.json"
MARKET_CLOSE_HOUR = 19
POST_CLOSE_RETRY_ATTEMPTS = 4
POST_CLOSE_RETRY_SLEEP_SECONDS = 20 * 60
DEFAULT_REQUIRED_TIMEOUT_SECONDS = 10 * 60
DEFAULT_OPTIONAL_TIMEOUT_SECONDS = 15 * 60
LEGACY_OPTIONAL_TIMEOUT_SECONDS = 30 * 60

sys.path.insert(0, str(BASE_DIR))

from herramientas.scanner_operativo_context import (
    learning_version_from_path,
    resolve_operational_scanner_context,
)
from herramientas.competencia_modelos import is_required_monitored_role, monitored_entries
from infra.db.config import get_database_url
from infra.db.model_run_snapshots import fetch_model_run_snapshots
from infra.db.runtime import (
    cloud_runtime_required as shared_cloud_runtime_required,
    connect_runtime_db,
    require_cloud_database_runtime as shared_require_cloud_database_runtime,
    runtime_backend_name as shared_runtime_backend_name,
)
from herramientas.legacy_ml_registry import load_enabled_legacy_ml_entries
from titan_system.core.database import TitanDB

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M",
    encoding="utf-8",
)
log = logging.getLogger()


def runtime_backend_name() -> str:
    return shared_runtime_backend_name(get_database_url())


def cloud_runtime_required() -> bool:
    return shared_cloud_runtime_required()


def runtime_sqlite_path() -> Path | None:
    url = make_url(get_database_url())
    if url.get_backend_name() == "sqlite" and url.database:
        return Path(url.database).resolve()
    return None


def runtime_is_cloud_backend() -> bool:
    return runtime_backend_name().startswith("postgres")


def runtime_db_details() -> dict[str, str]:
    backend = runtime_backend_name()
    details = {"db_backend": backend}
    sqlite_path = runtime_sqlite_path()
    if sqlite_path is not None:
        details["db_path"] = str(sqlite_path)
    return details


def require_cloud_database_runtime() -> None:
    shared_require_cloud_database_runtime(get_database_url())


def es_dia_bursatil(fecha: date) -> bool:
    """Lunes a viernes. No contempla feriados bursatiles."""
    return fecha.weekday() < 5


def dia_bursatil_anterior(fecha: date) -> date:
    """Devuelve el dia habil anterior."""
    cursor = fecha - timedelta(days=1)
    while not es_dia_bursatil(cursor):
        cursor -= timedelta(days=1)
    return cursor


def fecha_objetivo_mercado(ahora: datetime | None = None) -> date:
    """
    Fecha mas reciente que deberia estar cerrada en la DB.

    Antes del cierre local, apuntamos al ultimo dia habil anterior para evitar
    descargar una rueda parcial.
    """
    ahora = ahora or datetime.now()
    hoy = ahora.date()

    if not es_dia_bursatil(hoy):
        return dia_bursatil_anterior(hoy)

    if ahora.hour < MARKET_CLOSE_HOUR:
        return dia_bursatil_anterior(hoy)

    return hoy


def dias_bursatiles_faltantes(ultima_fecha: date, fecha_objetivo: date) -> int:
    """Cuenta dias habiles cerrados faltantes entre la DB y la fecha objetivo."""
    if ultima_fecha >= fecha_objetivo:
        return 0

    count = 0
    cursor = ultima_fecha + timedelta(days=1)
    while cursor <= fecha_objetivo:
        if es_dia_bursatil(cursor):
            count += 1
        cursor += timedelta(days=1)
    return count


def get_ultima_fecha_db() -> date | None:
    """Lee la fecha mas reciente en la base activa del runtime."""
    if runtime_backend_name() == "sqlite" and not runtime_sqlite_path().exists():
        return None

    try:
        with TitanDB() as db:
            frame = db.execute_raw("SELECT MAX(date) AS latest_date FROM prices")
        if not frame.empty and frame.iloc[0]["latest_date"]:
            latest_value = frame.iloc[0]["latest_date"]
            if isinstance(latest_value, datetime):
                return latest_value.date()
            if isinstance(latest_value, date):
                return latest_value
            return datetime.strptime(str(latest_value)[:10], "%Y-%m-%d").date()
    except Exception as exc:
        log.error(f"Error leyendo DB: {exc}")

    return None


def get_price_row_count() -> int | None:
    """Devuelve la cantidad de filas en prices para distinguir DB vacia de error de lectura."""
    if runtime_backend_name() == "sqlite" and not runtime_sqlite_path().exists():
        return 0

    try:
        with TitanDB() as db:
            frame = db.execute_raw("SELECT COUNT(*) AS total_rows FROM prices")
        if frame.empty:
            return 0
        total_rows = frame.iloc[0]["total_rows"]
        return int(total_rows or 0)
    except Exception as exc:
        log.error(f"Error contando filas en prices: {exc}")
        return None


def debe_correr_pipeline(ahora: datetime, faltantes: int, force_pipeline: bool = False) -> bool:
    """
    Decide si hay que ejecutar el flujo downstream.

    - La tarea diaria de las 19:15 SI debe correr el pipeline.
    - Un backup ONLOGON durante rueda abierta no necesita regenerar outputs.
    - Si hubo faltantes y se intento actualizar, tambien conviene correrlo.
    """
    if force_pipeline:
        return True
    if faltantes > 0:
        return True
    if not es_dia_bursatil(ahora.date()):
        return True
    return ahora.hour >= MARKET_CLOSE_HOUR


def should_retry_same_close(now: datetime, target_date: date, latest_after: date) -> bool:
    return (
        latest_after < target_date
        and es_dia_bursatil(target_date)
        and now.date() == target_date
        and now.hour >= MARKET_CLOSE_HOUR
    )


def guardar_salida(step_name: str, fecha_base: date, text: str) -> Path:
    RUN_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUN_REPORTS_DIR / f"{fecha_base.isoformat()}_{step_name}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def guardar_reporte_json(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def repair_recent_ohlcv_bounds(fecha_base: date) -> int:
    repair_start = (fecha_base - timedelta(days=45)).isoformat()
    with TitanDB() as db:
        repaired_rows = db.repair_ohlcv_bounds(
            start_date=repair_start,
            end_date=fecha_base.isoformat(),
        )
    repaired_rows = int(repaired_rows or 0)
    if repaired_rows:
        log.info(
            "[PIPELINE] Reconciliacion OHLCV conservadora aplicada a %s filas recientes antes del pipeline.",
            repaired_rows,
        )
        print(f"  Filas OHLCV reparadas previo al pipeline: {repaired_rows}")
    return repaired_rows


def repair_recent_invalid_ohlcv_rows(fecha_base: date) -> int:
    from titan_system.core.data_loader import DataLoader

    with TitanDB() as db:
        loader = DataLoader(db, years_history=2, max_workers=1)
        refresh_stats = loader.refresh_recent_invalid_rows(end_date=fecha_base.isoformat())

    invalid_rows = int(refresh_stats.get("invalid_rows", 0) or 0)
    remaining_rows = int(refresh_stats.get("remaining_rows", 0) or 0)
    resolved_rows = max(0, invalid_rows - remaining_rows)
    if invalid_rows:
        affected_tickers = ", ".join(refresh_stats.get("affected_tickers") or []) or "-"
        refreshed_tickers = ", ".join(refresh_stats.get("refreshed_tickers") or []) or "-"
        log.info(
            "[PIPELINE] Refetch OHLCV severo: detectadas=%s | resueltas=%s | restantes=%s | afectados=%s | refrescados=%s",
            invalid_rows,
            resolved_rows,
            remaining_rows,
            affected_tickers,
            refreshed_tickers,
        )
        print(f"  Filas OHLCV severas reconsultadas: {resolved_rows}/{invalid_rows}")
        if remaining_rows:
            remaining_tickers = ", ".join(refresh_stats.get("remaining_tickers") or []) or "-"
            print(
                "  [ALERTA] Persisten filas OHLCV severas: "
                f"{remaining_rows} ({remaining_tickers})"
            )
        for detail in (refresh_stats.get("errors") or [])[:5]:
            log.warning("[PIPELINE] Refetch OHLCV severo sin resolver: %s", detail)
            print(f"  [WARN] Refetch OHLCV severo: {detail}")
    return resolved_rows


def _timeout_seconds_for_step(step_name: str, optional: bool = False) -> int:
    if step_name == "validacion":
        return 10 * 60
    if step_name.startswith("aprendizaje_v"):
        return 15 * 60
    if step_name == "scanner":
        return 10 * 60
    if step_name == "gestor":
        return 10 * 60
    if step_name.startswith("resumen_v"):
        return 10 * 60
    if step_name.startswith("dashboard_maquina"):
        return 5 * 60
    if step_name == "auditoria_centinela":
        return 15 * 60
    if step_name.startswith("legacy_ml_") or step_name.startswith("resumen_legacy_ml_"):
        return LEGACY_OPTIONAL_TIMEOUT_SECONDS
    if step_name.startswith("observado_") or step_name.startswith("resumen_observado_"):
        return DEFAULT_OPTIONAL_TIMEOUT_SECONDS
    return DEFAULT_OPTIONAL_TIMEOUT_SECONDS if optional else DEFAULT_REQUIRED_TIMEOUT_SECONDS


def ejecutar_paso(step_name: str, command: list[str], fecha_base: date) -> bool:
    log.info(f"[PIPELINE] Iniciando paso {step_name}: {' '.join(command)}")
    timeout_seconds = _timeout_seconds_for_step(step_name, optional=False)
    try:
        result = subprocess.run(
            command,
            cwd=str(BASE_DIR),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        combined = []
        combined.append(f"Paso: {step_name}")
        combined.append(f"Fecha base DB: {fecha_base.isoformat()}")
        combined.append(f"Comando: {' '.join(command)}")
        combined.append("Return code: TIMEOUT")
        combined.append(f"Timeout seconds: {timeout_seconds}")
        combined.append("")
        combined.append("STDOUT")
        combined.append((exc.stdout or "").strip())
        combined.append("")
        combined.append("STDERR")
        combined.append((exc.stderr or "").strip())
        report_path = guardar_salida(step_name, fecha_base, "\n".join(combined).strip() + "\n")
        log.error(f"[PIPELINE] Paso {step_name} expiro tras {timeout_seconds}s. Ver {report_path}")
        emit_critical_alert(
            code=f"pipeline_step_timeout_{step_name}",
            summary=f"El paso {step_name} del pipeline diario expiro por timeout.",
            details={
                "fecha_base": fecha_base.isoformat(),
                "command": command,
                "report_path": str(report_path),
                "timeout_seconds": timeout_seconds,
            },
        )
        print(f"  [ERROR] Paso {step_name} expiro tras {timeout_seconds}s. Ver {report_path}")
        return False

    combined = []
    combined.append(f"Paso: {step_name}")
    combined.append(f"Fecha base DB: {fecha_base.isoformat()}")
    combined.append(f"Comando: {' '.join(command)}")
    combined.append(f"Return code: {result.returncode}")
    combined.append(f"Timeout seconds: {timeout_seconds}")
    combined.append("")
    combined.append("STDOUT")
    combined.append(result.stdout.strip())
    combined.append("")
    combined.append("STDERR")
    combined.append(result.stderr.strip())
    report_path = guardar_salida(step_name, fecha_base, "\n".join(combined).strip() + "\n")

    if result.returncode != 0:
        log.error(f"[PIPELINE] Paso {step_name} fallo. Ver {report_path}")
        if result.stderr.strip():
            log.error(result.stderr.strip())
        emit_critical_alert(
            code=f"pipeline_step_failed_{step_name}",
            summary=f"Fallo el paso {step_name} del pipeline diario.",
            details={
                "fecha_base": fecha_base.isoformat(),
                "command": command,
                "report_path": str(report_path),
                "return_code": result.returncode,
            },
        )
        print(f"  [ERROR] Paso {step_name} fallo. Ver {report_path}")
        return False

    log.info(f"[PIPELINE] Paso {step_name} OK. Reporte: {report_path}")
    print(f"  Paso {step_name}: OK")
    print(f"  Reporte {step_name}: {report_path}")
    return True


def build_learning_steps(command_name: str) -> list[tuple[str, Path]]:
    operational = resolve_operational_scanner_context()
    steps: list[tuple[str, Path]] = []
    for script in operational.learning_chain:
        version = learning_version_from_path(script)
        step_name = f"aprendizaje_v{version}" if command_name == "run" else f"resumen_v{version}"
        steps.append((step_name, script))
    return steps


def build_observed_steps(command_name: str) -> list[tuple[str, Path]]:
    operational = resolve_operational_scanner_context()
    steps: list[tuple[str, Path]] = []
    for script in operational.observed_learning_chain:
        version = learning_version_from_path(script)
        step_name = f"observado_v{version}" if command_name == "run" else f"resumen_observado_v{version}"
        steps.append((step_name, script))
    return steps


def build_legacy_ml_steps(command_name: str) -> list[tuple[str, Path]]:
    steps: list[tuple[str, Path]] = []
    for entry in load_enabled_legacy_ml_entries():
        runner_path = entry.runner_path
        if not runner_path.exists():
            continue
        step_name = entry.model_id if command_name == "run" else f"resumen_{entry.model_id}"
        steps.append((step_name, runner_path))
    return steps


def expected_monitored_snapshot_entries() -> list[dict[str, str]]:
    expected: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in monitored_entries():
        label = str(entry["label"])
        if label in seen:
            continue
        seen.add(label)
        expected.append(
            {
                "label": label,
                "role": str(entry.get("role") or ""),
                "prefix": str(entry.get("prefix") or label),
                "exact_model_name": "1" if bool(entry.get("exact_model_name", False)) else "0",
            }
        )
    return expected


def build_prediction_freshness_details(con, entry: dict[str, str]) -> dict[str, object]:
    exact_model_name = entry.get("exact_model_name") == "1"
    prefix = str(entry.get("prefix") or entry["label"])
    operator = "=" if exact_model_name else "LIKE"
    pattern = prefix if exact_model_name else f"{prefix}_%"

    row = con.execute(
        f"""
        SELECT
            MAX(prediction_date) AS latest_prediction_date,
            COUNT(*) AS total_prediction_rows,
            COUNT(DISTINCT prediction_date) AS prediction_days
        FROM predictions
        WHERE model_name {operator} ?
        """,
        (pattern,),
    ).fetchone()

    latest_prediction_date = str(row[0]) if row and row[0] else None
    latest_prediction_rows = 0
    if latest_prediction_date:
        latest_prediction_rows = int(
            con.scalar(
                f"""
                SELECT COUNT(*)
                FROM predictions
                WHERE model_name {operator} ? AND prediction_date = ?
                """,
                (pattern, latest_prediction_date),
            )
            or 0
        )

    return {
        "latest_prediction_date": latest_prediction_date,
        "latest_prediction_rows": latest_prediction_rows,
        "total_prediction_rows": int(row[1] or 0) if row else 0,
        "prediction_days": int(row[2] or 0) if row else 0,
    }


def build_model_snapshot_freshness_report(fecha_base: date) -> dict[str, object]:
    expected_entries = expected_monitored_snapshot_entries()
    expected_labels = [entry["label"] for entry in expected_entries]

    with connect_runtime_db() as con:
        snapshot_rows = fetch_model_run_snapshots(
            con,
            model_keys=expected_labels,
            analyzed_date_from=fecha_base.isoformat(),
            analyzed_date_to=fecha_base.isoformat(),
        )
        latest_prices_date = con.scalar("SELECT MAX(date) FROM prices")
        latest_prediction_date = con.scalar("SELECT MAX(prediction_date) FROM predictions")
        prediction_details_by_label = {
            entry["label"]: build_prediction_freshness_details(con, entry)
            for entry in expected_entries
        }

    row_by_label = {str(row.get("model_key")): row for row in snapshot_rows}
    models: list[dict[str, object]] = []
    missing_models: list[str] = []
    required_missing_models: list[str] = []
    optional_missing_models: list[str] = []
    zero_signal_models: list[str] = []

    for entry in expected_entries:
        label = entry["label"]
        role = str(entry["role"])
        row = row_by_label.get(label)
        prediction_details = prediction_details_by_label.get(label, {})
        if row is None:
            missing_models.append(label)
            if is_required_monitored_role(role):
                required_missing_models.append(label)
            else:
                optional_missing_models.append(label)
            models.append(
                {
                    "label": label,
                    "role": role,
                    "status": "missing_snapshot",
                    "analyzed_date": None,
                    "prediction_for": None,
                    "signal_count": None,
                    "latest_prediction_date": prediction_details.get("latest_prediction_date"),
                    "latest_prediction_rows": prediction_details.get("latest_prediction_rows"),
                    "total_prediction_rows": prediction_details.get("total_prediction_rows"),
                    "prediction_days": prediction_details.get("prediction_days"),
                }
            )
            continue

        signal_count = int(row.get("signal_count") or 0)
        if signal_count == 0:
            zero_signal_models.append(label)
        models.append(
            {
                "label": label,
                "role": role,
                "status": "ok_zero_signal" if signal_count == 0 else "ok",
                "analyzed_date": row.get("analyzed_date"),
                "prediction_for": row.get("prediction_for"),
                "signal_count": signal_count,
                "freshness": row.get("freshness"),
                "regime_label": row.get("regime_label"),
                "latest_prediction_date": prediction_details.get("latest_prediction_date"),
                "latest_prediction_rows": prediction_details.get("latest_prediction_rows"),
                "total_prediction_rows": prediction_details.get("total_prediction_rows"),
                "prediction_days": prediction_details.get("prediction_days"),
            }
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "fecha_base": fecha_base.isoformat(),
        "db_backend": runtime_backend_name(),
        "expected_models": len(expected_entries),
        "snapshot_rows_found": len(snapshot_rows),
        "fresh_models": len(expected_entries) - len(missing_models),
        "missing_models": missing_models,
        "required_missing_models": required_missing_models,
        "optional_missing_models": optional_missing_models,
        "zero_signal_models": zero_signal_models,
        "latest_prices_date": str(latest_prices_date) if latest_prices_date else None,
        "latest_prediction_date": str(latest_prediction_date) if latest_prediction_date else None,
        "models": models,
    }


def validate_model_snapshot_freshness(fecha_base: date) -> bool:
    report = build_model_snapshot_freshness_report(fecha_base)
    report_path = guardar_reporte_json(MODEL_FRESHNESS_REPORT, report)
    required_missing_models = list(
        report.get("required_missing_models")
        if report.get("required_missing_models") is not None
        else report.get("missing_models") or []
    )
    optional_missing_models = list(report.get("optional_missing_models") or [])

    if not required_missing_models:
        if optional_missing_models:
            optional_summary = (
                "Faltan snapshots opcionales en Postgres para modelos observados/legacy: "
                + ", ".join(optional_missing_models)
            )
            print(f"  [WARN] {optional_summary}. Ver {report_path}")
            log.warning("[PIPELINE] %s", optional_summary)
        print(f"  Cobertura de snapshots requeridos: OK ({report_path})")
        log.info(
            "[PIPELINE] Cobertura de snapshots requeridos OK para %s. Reporte: %s",
            fecha_base.isoformat(),
            report_path,
        )
        return True

    summary = (
        "Faltan snapshots diarios requeridos en Postgres para modelos monitoreados: "
        + ", ".join(required_missing_models)
    )
    emit_critical_alert(
        code="missing_model_run_snapshots",
        summary=summary,
        details={
            "fecha_base": fecha_base.isoformat(),
            "missing_models": required_missing_models,
            "optional_missing_models": optional_missing_models,
            "report_path": str(report_path),
        },
    )
    print(f"  [ERROR] {summary}. Ver {report_path}")
    log.error("[PIPELINE] %s", summary)
    return False


def model_snapshot_coverage_is_current(report: dict[str, object], fecha_base: date) -> bool:
    fecha_iso = fecha_base.isoformat()
    required_missing_models = list(
        report.get("required_missing_models")
        if report.get("required_missing_models") is not None
        else report.get("missing_models") or []
    )
    if required_missing_models:
        return False
    if report.get("latest_prices_date") != fecha_iso:
        return False
    latest_prediction_date = report.get("latest_prediction_date")
    if latest_prediction_date not in (None, fecha_iso):
        return False
    return True


def monitored_snapshots_already_current(fecha_base: date) -> bool:
    report = build_model_snapshot_freshness_report(fecha_base)
    return model_snapshot_coverage_is_current(report, fecha_base)


def ejecutar_paso_opcional(
    step_name: str,
    command: list[str],
    fecha_base: date,
    timeout_seconds: int | None = None,
) -> bool:
    log.info(f"[PIPELINE][OPTIONAL] Iniciando paso {step_name}: {' '.join(command)}")
    timeout_seconds = timeout_seconds or _timeout_seconds_for_step(step_name, optional=True)
    try:
        result = subprocess.run(
            command,
            cwd=str(BASE_DIR),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        combined = []
        combined.append(f"Paso: {step_name}")
        combined.append(f"Fecha base DB: {fecha_base.isoformat()}")
        combined.append(f"Comando: {' '.join(command)}")
        combined.append("Return code: TIMEOUT")
        combined.append(f"Timeout seconds: {timeout_seconds}")
        combined.append("")
        combined.append("STDOUT")
        combined.append((exc.stdout or "").strip())
        combined.append("")
        combined.append("STDERR")
        combined.append((exc.stderr or "").strip())
        report_path = guardar_salida(step_name, fecha_base, "\n".join(combined).strip() + "\n")
        log.warning(
            f"[PIPELINE][OPTIONAL] Paso {step_name} expiro tras {timeout_seconds}s. Ver {report_path}"
        )
        print(f"  [WARN] Paso opcional {step_name} expiro tras {timeout_seconds}s. Ver {report_path}")
        return False

    combined = []
    combined.append(f"Paso: {step_name}")
    combined.append(f"Fecha base DB: {fecha_base.isoformat()}")
    combined.append(f"Comando: {' '.join(command)}")
    combined.append(f"Return code: {result.returncode}")
    combined.append(f"Timeout seconds: {timeout_seconds}")
    combined.append("")
    combined.append("STDOUT")
    combined.append(result.stdout.strip())
    combined.append("")
    combined.append("STDERR")
    combined.append(result.stderr.strip())
    report_path = guardar_salida(step_name, fecha_base, "\n".join(combined).strip() + "\n")

    if result.returncode != 0:
        log.warning(f"[PIPELINE][OPTIONAL] Paso {step_name} fallo. Ver {report_path}")
        if result.stderr.strip():
            log.warning(result.stderr.strip())
        print(f"  [WARN] Paso opcional {step_name} fallo. Ver {report_path}")
        return False

    log.info(f"[PIPELINE][OPTIONAL] Paso {step_name} OK. Reporte: {report_path}")
    print(f"  Paso opcional {step_name}: OK")
    print(f"  Reporte {step_name}: {report_path}")
    return True


def refrescar_dashboard(fecha_base: date) -> bool:
    if not DASHBOARD_SCRIPT.exists():
        emit_critical_alert(
            code="dashboard_script_missing",
            summary="No se encontro el generador canonico del dashboard.",
            details={"dashboard_script": str(DASHBOARD_SCRIPT)},
        )
        print(f"  [ERROR] No existe el generador del dashboard: {DASHBOARD_SCRIPT}")
        return False
    return ejecutar_paso(
        "dashboard_maquina",
        [sys.executable, str(DASHBOARD_SCRIPT)],
        fecha_base,
    )


def auditar_integridad_dashboard(fecha_base: date) -> bool:
    if not DASHBOARD_INTEGRITY_SCRIPT.exists():
        emit_critical_alert(
            code="dashboard_integrity_script_missing",
            summary="No se encontro la auditoria canonica del dashboard.",
            details={"dashboard_integrity_script": str(DASHBOARD_INTEGRITY_SCRIPT)},
        )
        print(f"  [ERROR] No existe la auditoria canonica del dashboard: {DASHBOARD_INTEGRITY_SCRIPT}")
        return False
    return ejecutar_paso(
        "dashboard_integrity",
        [sys.executable, str(DASHBOARD_INTEGRITY_SCRIPT)],
        fecha_base,
    )


def ejecutar_publicacion_liviana(fecha_base: date) -> bool:
    print("\n  Reusando snapshots vigentes; se omite recomputo pesado y se refresca publicacion.\n")
    log.info(
        "[PIPELINE] Snapshots vigentes para %s. Se omite recomputo pesado y solo se refresca dashboard/publicacion.",
        fecha_base.isoformat(),
    )

    if not validate_model_snapshot_freshness(fecha_base):
        return False

    if not refrescar_dashboard(fecha_base):
        return False

    if not auditar_integridad_dashboard(fecha_base):
        return False

    auditoria_ok = ejecutar_paso_opcional(
        "auditoria_centinela",
        [sys.executable, str(AUDIT_SCRIPT), "--mode", "fast"],
        fecha_base,
    )
    if not auditoria_ok:
        log.warning("[PIPELINE] Auditoria centinela fallo durante publicacion liviana.")
        print("  [WARN] Auditoria centinela fallo. El dashboard ya quedo regenerado con evidencia vigente.")
    return True


def log_dashboard_refresh_deferred(fecha_base: date) -> None:
    log.info(
        "[PIPELINE] Refresh de dashboard diferido para %s. El workflow cloud solo lo ejecutara si detecta publicacion necesaria.",
        fecha_base.isoformat(),
    )
    print("  Refresh de dashboard diferido. El workflow cloud lo ejecutara solo si hace falta publicar.")


def ejecutar_pipeline_diario(
    fecha_base: date,
    ahora: datetime,
    *,
    skip_dashboard_refresh: bool = False,
) -> bool:
    operational = resolve_operational_scanner_context()
    active_scanner_label = operational.active_scanner.stem

    print(f"\n  Ejecutando pipeline diario {active_scanner_label}...\n")
    log.info(
        f"[PIPELINE] Inicio pipeline diario para {fecha_base} ({ahora:%Y-%m-%d %H:%M}) | "
        f"scanner_activo={active_scanner_label}"
    )

    if operational.active_learning is None:
        emit_critical_alert(
            code="active_learning_missing",
            summary="El scanner activo no tiene aprendizaje operativo propio.",
            details={
                "scanner_activo": str(operational.active_scanner.relative_to(BASE_DIR)),
                "active_version": operational.active_version,
            },
        )
        print("  [ERROR] Falta el aprendizaje operativo del scanner activo.\n")
        return False

    validate_ok = ejecutar_paso(
        "validacion",
        [sys.executable, str(VALIDATE_SCRIPT), "--expected-date", fecha_base.isoformat()],
        fecha_base,
    )
    if not validate_ok:
        return False

    for step_name, script_path in build_learning_steps("run"):
        learning_ok = ejecutar_paso(
            step_name,
            [sys.executable, str(script_path), "run", "--date", fecha_base.isoformat()],
            fecha_base,
        )
        if not learning_ok:
            return False

    scanner_ok = ejecutar_paso(
        "scanner",
        [sys.executable, str(operational.active_scanner)],
        fecha_base,
    )
    if not scanner_ok:
        return False

    gestor_ok = ejecutar_paso(
        "gestor",
        [sys.executable, str(GESTOR_SCRIPT), "daily-report"],
        fecha_base,
    )
    if not gestor_ok:
        return False

    for step_name, script_path in build_learning_steps("daily-summary"):
        resumen_ok = ejecutar_paso(
            step_name,
            [sys.executable, str(script_path), "daily-summary", "--date", fecha_base.isoformat()],
            fecha_base,
        )
        if not resumen_ok:
            return False

    # Repetimos el sync despues de observados/legacy para que el refresh final
    # capture tambien ese material en Postgres antes de publicar el dashboard.

    # Segundo refresh para incorporar tambien lo que hayan agregado los modelos
    # observados/legacy si llegaron a completarse en esta misma corrida.

    if not validate_model_snapshot_freshness(fecha_base):
        return False

    if skip_dashboard_refresh:
        log_dashboard_refresh_deferred(fecha_base)
        return True

    # Antes del dashboard core, alineamos Postgres cloud con la SQLite local
    # para que el bundle visible y GitHub Pages salgan del mismo corte operativo.

    # Refrescamos el dashboard core antes de los opcionales lentos para que el
    # tablero operativo y el heatmap queden alineados con la rueda cerrada.

    # La auditoría centinela es una verificación de calidad de CÓDIGO, no de
    # frescura de datos. Un fallo (ej. proyecto stale) NO debe bloquear los
    # pasos opcionales de datos (legacy ML, observados). Solo se avisa en log.

    if operational.observed_versions and len(operational.observed_versions) != len(operational.observed_learning_chain):
        log.error("[PIPELINE] Hay versiones observadas habilitadas sin script de aprendizaje resoluble.")
        print("  [ERROR] Hay modelos observados habilitados sin script resoluble.")
        emit_critical_alert(
            code="observed_learning_missing",
            summary="Hay modelos observados habilitados sin script de aprendizaje resoluble.",
            details={
                "observed_versions": list(operational.observed_versions),
                "resolved_learning_chain": [str(path) for path in operational.observed_learning_chain],
            },
        )
        return False

    for step_name, script_path in build_observed_steps("run"):
        ok = ejecutar_paso_opcional(
            step_name,
            [sys.executable, str(script_path), "run", "--date", fecha_base.isoformat()],
            fecha_base,
        )
        if not ok:
            log.warning("[PIPELINE] Paso observado opcional no bloqueante: %s", step_name)

    for step_name, script_path in build_observed_steps("daily-summary"):
        ok = ejecutar_paso_opcional(
            step_name,
            [sys.executable, str(script_path), "daily-summary", "--date", fecha_base.isoformat()],
            fecha_base,
        )
        if not ok:
            log.warning("[PIPELINE] Resumen observado opcional no bloqueante: %s", step_name)

    for step_name, script_path in build_legacy_ml_steps("run"):
        ok = ejecutar_paso_opcional(
            step_name,
            [sys.executable, str(script_path), "run", "--date", fecha_base.isoformat()],
            fecha_base,
        )
        if not ok:
            log.warning("[PIPELINE] Paso legacy ML opcional no bloqueante: %s", step_name)

    for step_name, script_path in build_legacy_ml_steps("daily-summary"):
        ok = ejecutar_paso_opcional(
            step_name,
            [sys.executable, str(script_path), "daily-summary", "--date", fecha_base.isoformat()],
            fecha_base,
        )
        if not ok:
            log.warning("[PIPELINE] Resumen legacy ML opcional no bloqueante: %s", step_name)

    # Refresco de datos dinamicos en la plantilla canonica C1 Pro (heatmap + liga)

    if not refrescar_dashboard(fecha_base):
        return False

    if not auditar_integridad_dashboard(fecha_base):
        return False

    auditoria_ok = ejecutar_paso_opcional(
        "auditoria_centinela",
        [sys.executable, str(AUDIT_SCRIPT), "--mode", "fast"],
        fecha_base,
    )
    if not auditoria_ok:
        log.warning("[PIPELINE] Auditoria centinela fallo. Se registra como warning post-dashboard.")
        print("  [WARN] Auditoria centinela fallo. El dashboard ya quedo generado con datos validados.")

    log.info(f"[PIPELINE] Pipeline diario completado para {fecha_base}")
    print("\n  Pipeline diario completado.\n")
    return True


def emit_critical_alert(code: str, summary: str, details: dict[str, object] | None = None) -> Path:
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    payload = {
        "level": "CRITICAL",
        "code": code,
        "summary": summary,
        "created_at": now.isoformat(timespec="seconds"),
        "details": details or {},
    }
    latest_path = ALERTS_DIR / "latest_critical_alert.json"
    stamped_path = ALERTS_DIR / f"{now.strftime('%Y-%m-%d_%H-%M-%S')}_{code}.json"
    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    latest_path.write_text(content, encoding="utf-8")
    stamped_path.write_text(content, encoding="utf-8")
    log.error(f"[CRITICAL ALERT] {code} | {summary}")
    return stamped_path


def main() -> int:
    now = datetime.now()
    force_pipeline = "--force-pipeline" in sys.argv
    skip_dashboard_refresh = "--skip-dashboard-refresh" in sys.argv
    log.info(f"-- Auto-actualizador iniciado ({now:%Y-%m-%d %H:%M}) --")

    try:
        require_cloud_database_runtime()
    except Exception as exc:
        log.error(str(exc))
        print(f"[ERROR] {exc}")
        emit_critical_alert(
            code="cloud_db_required",
            summary=str(exc),
            details=runtime_db_details(),
        )
        return 1

    sqlite_path = runtime_sqlite_path()
    if runtime_backend_name() == "sqlite" and sqlite_path is not None and not sqlite_path.exists():
        db_path = sqlite_path
        log.error(f"DB no encontrada: {db_path}")
        print(f"[ERROR] DB no encontrada: {db_path}")
        emit_critical_alert(
            code="db_missing",
            summary="No se encontro titan.db para correr el auto-actualizador.",
            details=runtime_db_details(),
        )
        return 1

    target_date = fecha_objetivo_mercado(now)
    ultima = get_ultima_fecha_db()
    bootstrap_prices = False
    if ultima is None:
        price_rows = get_price_row_count()
        if price_rows == 0:
            bootstrap_prices = True
            log.warning(
                "[PIPELINE] La DB activa no tiene historial en prices. Se inicia bootstrap cloud hasta %s.",
                target_date.isoformat(),
            )
        else:
            log.error("No se pudo leer fecha de la DB.")
            print("[ERROR] No se pudo leer fecha de la DB.")
            emit_critical_alert(
                code="db_date_unreadable",
                summary="No se pudo leer la ultima fecha de la DB.",
                details=runtime_db_details(),
            )
            return 1

    faltantes = 1 if bootstrap_prices else dias_bursatiles_faltantes(ultima, target_date)

    log.info(
        f"Ultima fecha en DB: {ultima} | Objetivo: {target_date} | Dias faltantes: {faltantes}"
    )

    print("\n  TITAN Auto-Actualizador")
    print(f"  Ultima fecha DB : {ultima or 'SIN DATOS'}")
    print(f"  Fecha objetivo  : {target_date}")
    print(f"  Dias faltantes  : {'bootstrap' if bootstrap_prices else faltantes}")

    if faltantes == 0:
        log.info("DB al dia - sin accion.")
        print("  DB al dia. No es necesario actualizar.\n")
        if not debe_correr_pipeline(now, faltantes, force_pipeline=force_pipeline):
            log.info("[PIPELINE] Backup pre-cierre: no se ejecuta flujo downstream.")
            return 0

        latest_after = get_ultima_fecha_db()
        if latest_after is None:
            log.error("[PIPELINE] No se pudo revalidar la fecha de la DB.")
            print("  [ERROR] No se pudo revalidar la fecha de la DB.")
            emit_critical_alert(
                code="db_revalidation_failed",
                summary="No se pudo revalidar la ultima fecha de la DB antes del pipeline.",
                details={},
            )
            return 1
        with TitanDB() as db:
            market_status = db.get_market_data_status()
            needs_metadata = (
                market_status.get("latest_prices_date") != latest_after.isoformat()
                or not market_status.get("market_data_updated_at")
            )
            if needs_metadata:
                db.save_market_data_update(latest_after.isoformat())
                log.info(f"[PIPELINE] Metadata de mercado reconciliada para {latest_after}")

        repair_recent_invalid_ohlcv_rows(latest_after)
        repair_recent_ohlcv_bounds(latest_after)

        if latest_after < target_date:
            log.warning(
                f"[PIPELINE] DB sin alcanzar objetivo. Ultima={latest_after} | objetivo={target_date}. Se omite pipeline."
            )
            print("  [ALERTA] La DB no llego a la fecha objetivo. Se omite pipeline downstream.\n")
            emit_critical_alert(
                code="pipeline_blocked_stale_db",
                summary="La DB no llego a la fecha objetivo y el pipeline fue bloqueado.",
                details={
                    "latest_after": latest_after.isoformat(),
                    "target_date": target_date.isoformat(),
                    "force_pipeline": force_pipeline,
                },
            )
            return 2

        if monitored_snapshots_already_current(latest_after):
            if skip_dashboard_refresh:
                log.info(
                    "[PIPELINE] Snapshot coverage al dia. Se omite el recomputo cloud y el workflow continua con el build/publicacion."
                )
                print(
                    "  Snapshots requeridos al dia. Se omite recomputo cloud y el workflow continua con el build/publicacion.\n"
                )
                return 0
            return 0 if ejecutar_publicacion_liviana(latest_after) else 1

        return 0 if ejecutar_pipeline_diario(
            latest_after,
            now,
            skip_dashboard_refresh=skip_dashboard_refresh,
        ) else 1

    if bootstrap_prices:
        print("\n  DB sin historial de precios. Iniciando bootstrap desde el proveedor de mercado...\n")
        log.info(f"Iniciando bootstrap historico hasta {target_date}...")
    else:
        print(f"\n  Actualizando {faltantes} dia(s)...\n")
        log.info(f"Iniciando actualizacion ({faltantes} dias) hasta {target_date}...")

    from titan_system.core.data_loader import DataLoader

    try:
        latest_after = ultima
        max_attempts = POST_CLOSE_RETRY_ATTEMPTS if now.date() == target_date and now.hour >= MARKET_CLOSE_HOUR else 1

        for attempt in range(1, max_attempts + 1):
            if attempt > 1:
                log.warning(f"[RETRY] Reintentando actualizacion post-cierre ({attempt}/{max_attempts}).")
                print(f"\n  Reintento post-cierre {attempt}/{max_attempts}...\n")

            with TitanDB() as db:
                loader = DataLoader(db, years_history=2, max_workers=10)
                results = loader.update_daily(end_date=target_date.isoformat())
                refresh_stats = loader.refresh_recent_invalid_rows(end_date=target_date.isoformat())
                repair_start = (target_date - timedelta(days=45)).isoformat()
                repaired_rows = db.repair_ohlcv_bounds(
                    start_date=repair_start,
                    end_date=target_date.isoformat(),
                )

            filas = results.get("total_rows", 0)
            errores = results.get("failed", 0)
            sin_datos = results.get("empty", 0)
            log.info(
                f"Actualizacion OK - {filas:,} filas nuevas, {errores} errores, {sin_datos} sin datos."
            )
            invalid_rows = int(refresh_stats.get("invalid_rows", 0) or 0)
            remaining_invalid_rows = int(refresh_stats.get("remaining_rows", 0) or 0)
            if invalid_rows:
                resolved_invalid_rows = max(0, invalid_rows - remaining_invalid_rows)
                log.info(
                    "Refetch OHLCV severo post-update: detectadas=%s | resueltas=%s | restantes=%s",
                    invalid_rows,
                    resolved_invalid_rows,
                    remaining_invalid_rows,
                )
            if repaired_rows:
                log.info(f"Reparacion OHLCV conservadora aplicada a {repaired_rows} filas recientes.")
            print(f"  Actualizacion completada: {filas:,} filas nuevas.")
            if invalid_rows:
                resolved_invalid_rows = max(0, invalid_rows - remaining_invalid_rows)
                print(
                    "  Filas OHLCV severas reconsultadas: "
                    f"{resolved_invalid_rows}/{invalid_rows}"
                )
                if remaining_invalid_rows:
                    remaining_tickers = ", ".join(refresh_stats.get("remaining_tickers") or []) or "-"
                    print(
                        "  [ALERTA] Persisten filas OHLCV severas: "
                        f"{remaining_invalid_rows} ({remaining_tickers})"
                    )
                for detail in (refresh_stats.get("errors") or [])[:5]:
                    print(f"  [WARN] Refetch OHLCV severo: {detail}")
            if repaired_rows:
                print(f"  Filas OHLCV reparadas: {repaired_rows}")
            if errores:
                print(f"  Tickers con error: {errores}")
            if sin_datos:
                print(f"  Tickers sin datos: {sin_datos}")
            if filas == 0 and faltantes > 0:
                log.warning(
                    "Sin avance real en la DB pese a dias faltantes. Revisar conectividad, proxy y simbolos sin datos."
                )
                print("  [ALERTA] No hubo avance real en la DB pese a que faltaban ruedas cerradas.")

            latest_after = get_ultima_fecha_db()
            if latest_after is None:
                log.error("[PIPELINE] No se pudo leer la fecha final de la DB tras actualizar.")
                print("  [ERROR] No se pudo leer la fecha final de la DB tras actualizar.")
                emit_critical_alert(
                    code="db_post_update_unreadable",
                    summary="No se pudo leer la fecha final de la DB tras actualizar.",
                    details={"target_date": target_date.isoformat()},
                )
                return 1

            if latest_after >= target_date:
                break

            if attempt >= max_attempts or not should_retry_same_close(now, target_date, latest_after):
                break

            retry_minutes = POST_CLOSE_RETRY_SLEEP_SECONDS // 60
            log.warning(
                f"[RETRY] DB sigue en {latest_after}; objetivo {target_date}. Nuevo intento en {retry_minutes} min."
            )
            print(
                f"  [ALERTA] DB sigue en {latest_after} con objetivo {target_date}. "
                f"Reintentando en {retry_minutes} minutos..."
            )
            time.sleep(POST_CLOSE_RETRY_SLEEP_SECONDS)
            now = datetime.now()

        if latest_after < target_date:
            log.warning(
                f"[PIPELINE] DB sigue atrasada tras update. Ultima={latest_after} | objetivo={target_date}. Se omite pipeline."
            )
            print("  [ALERTA] La DB sigue atrasada tras actualizar. Se omite pipeline downstream.\n")
            emit_critical_alert(
                code="update_finished_without_target",
                summary="La actualizacion termino sin alcanzar la fecha objetivo de mercado.",
                details={
                    "latest_after": latest_after.isoformat(),
                    "target_date": target_date.isoformat(),
                    "attempted_after_close": now.hour >= MARKET_CLOSE_HOUR,
                },
            )
            return 2

        with TitanDB() as db:
            market_status = db.get_market_data_status()
            needs_metadata = (
                market_status.get("latest_prices_date") != latest_after.isoformat()
                or not market_status.get("market_data_updated_at")
            )
            if ultima is None or latest_after > ultima or needs_metadata:
                db.save_market_data_update(latest_after.isoformat())
                log.info(f"[PIPELINE] Metadata de mercado actualizada para {latest_after}")

        return 0 if ejecutar_pipeline_diario(
            latest_after,
            now,
            skip_dashboard_refresh=skip_dashboard_refresh,
        ) else 1

    except Exception as exc:
        log.error(f"Error durante actualizacion: {exc}")
        print(f"  [ERROR] {exc}")
        emit_critical_alert(
            code="auto_update_exception",
            summary="Se produjo una excepcion durante el auto-actualizador.",
            details={"error": str(exc)},
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
