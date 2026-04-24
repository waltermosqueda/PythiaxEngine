#!/usr/bin/env python3
"""
AUTO-ACTUALIZADOR Y PIPELINE DIARIO V13
======================================
Actualiza titan.db automaticamente cuando detecta dias bursatiles cerrados
sin datos y, cuando corresponde, ejecuta el flujo diario completo:

    actualizar_datos -> validate_market_data -> aprendizaje base/referencia/activo
    -> scanner activo -> gestor -> resumentes operativos -> auditoria fast

Esta pensado para correr todos los dias y tambien al iniciar sesion como
red de seguridad.

Ubicacion: herramientas/auto_actualizar.py
Registrar en Windows: ejecutar herramientas/setup_tarea_windows.bat
"""

import json
import logging
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# Este script esta en Claude/herramientas/ y sube un nivel a la raiz.
BASE_DIR = Path(__file__).parent.parent
LOG_PATH = BASE_DIR / "bitacora" / "auto_actualizar.log"
RUN_REPORTS_DIR = BASE_DIR / "aprendizaje_operativo" / "v11_reports"
ALERTS_DIR = BASE_DIR / "aprendizaje_operativo" / "alerts"
VALIDATE_SCRIPT = BASE_DIR / "herramientas" / "validate_market_data.py"
GESTOR_SCRIPT = BASE_DIR / "herramientas" / "gestor_posiciones_v11.py"
AUDIT_SCRIPT = BASE_DIR / "herramientas" / "auditoria_integral_claude.py"
DASHBOARD_SCRIPT = BASE_DIR / "analisis" / "generar_tablero_maquina_pensante.py"
CLOUD_SYNC_SCRIPT = BASE_DIR / "infra" / "db" / "sync_sqlite_delta_to_target.py"
CLOUD_SYNC_REPORT = BASE_DIR / "docs" / "cloud" / "reports" / "sqlite_to_target_incremental_sync.json"
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
from infra.db.config import get_database_url
from infra.db.sqlite_compat import connect_sqlite, get_sqlite_db_path
from herramientas.legacy_ml_registry import load_enabled_legacy_ml_entries
from titan_system.core.database import TitanDB

DB_PATH = get_sqlite_db_path()

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M",
    encoding="utf-8",
)
log = logging.getLogger()


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
    """Lee la fecha mas reciente en titan.db."""
    if not DB_PATH.exists():
        return None

    try:
        con = connect_sqlite(DB_PATH)
        row = con.execute("SELECT MAX(date) FROM prices").fetchone()
        con.close()
        if row and row[0]:
            return datetime.strptime(row[0], "%Y-%m-%d").date()
    except Exception as exc:
        log.error(f"Error leyendo DB: {exc}")

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


def ejecutar_paso_opcional(step_name: str, command: list[str], fecha_base: date) -> bool:
    log.info(f"[PIPELINE][OPTIONAL] Iniciando paso {step_name}: {' '.join(command)}")
    timeout_seconds = _timeout_seconds_for_step(step_name, optional=True)
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


def refrescar_dashboard(step_name: str, fecha_base: date, observed_failures: list[str]) -> None:
    if not DASHBOARD_SCRIPT.exists():
        return
    ok = ejecutar_paso_opcional(
        step_name,
        [sys.executable, str(DASHBOARD_SCRIPT)],
        fecha_base,
    )
    if not ok:
        observed_failures.append(step_name)


def sync_target_incremental(step_name: str, fecha_base: date, observed_failures: list[str]) -> None:
    if not CLOUD_SYNC_SCRIPT.exists():
        return
    try:
        target_url = get_database_url()
    except Exception as exc:
        log.warning(f"[PIPELINE][OPTIONAL] No se pudo resolver DATABASE_URL para sync incremental: {exc}")
        return
    if not target_url or target_url.startswith("sqlite:"):
        return
    ok = ejecutar_paso_opcional(
        step_name,
        [
            sys.executable,
            str(CLOUD_SYNC_SCRIPT),
            "--report-path",
            str(CLOUD_SYNC_REPORT),
        ],
        fecha_base,
        timeout_seconds=30 * 60,
    )
    if not ok:
        observed_failures.append(step_name)


def ejecutar_pipeline_diario(fecha_base: date, ahora: datetime) -> bool:
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

    observed_failures: list[str] = []

    # Antes del dashboard core, alineamos Neon/Postgres con la SQLite local para
    # que el bundle visible y GitHub Pages salgan del mismo corte operativo.
    sync_target_incremental("sync_target_incremental_core", fecha_base, observed_failures)

    # Refrescamos el dashboard core antes de los opcionales lentos para que el
    # tablero operativo y el heatmap queden alineados con la rueda cerrada.
    refrescar_dashboard("dashboard_maquina_core", fecha_base, observed_failures)

    # La auditoría centinela es una verificación de calidad de CÓDIGO, no de
    # frescura de datos. Un fallo (ej. proyecto stale) NO debe bloquear los
    # pasos opcionales de datos (legacy ML, observados). Solo se avisa en log.
    auditoria_ok = ejecutar_paso_opcional(
        "auditoria_centinela",
        [sys.executable, str(AUDIT_SCRIPT), "--mode", "fast"],
        fecha_base,
    )
    if not auditoria_ok:
        log.warning("[PIPELINE] Auditoria centinela fallo (posible estado stale). "
                    "Los pasos opcionales de datos continuaran de todas formas.")
        observed_failures.append("auditoria_centinela")

    if operational.observed_versions and len(operational.observed_versions) != len(operational.observed_learning_chain):
        log.warning(
            "[PIPELINE][OPTIONAL] Hay versiones observadas habilitadas sin script de aprendizaje resoluble."
        )
        print("  [WARN] Hay modelos observados habilitados sin script resoluble.")

    for step_name, script_path in build_observed_steps("run"):
        ok = ejecutar_paso_opcional(
            step_name,
            [sys.executable, str(script_path), "run", "--date", fecha_base.isoformat()],
            fecha_base,
        )
        if not ok:
            observed_failures.append(step_name)

    for step_name, script_path in build_observed_steps("daily-summary"):
        ok = ejecutar_paso_opcional(
            step_name,
            [sys.executable, str(script_path), "daily-summary", "--date", fecha_base.isoformat()],
            fecha_base,
        )
        if not ok:
            observed_failures.append(step_name)

    for step_name, script_path in build_legacy_ml_steps("run"):
        ok = ejecutar_paso_opcional(
            step_name,
            [sys.executable, str(script_path), "run", "--date", fecha_base.isoformat()],
            fecha_base,
        )
        if not ok:
            observed_failures.append(step_name)

    for step_name, script_path in build_legacy_ml_steps("daily-summary"):
        ok = ejecutar_paso_opcional(
            step_name,
            [sys.executable, str(script_path), "daily-summary", "--date", fecha_base.isoformat()],
            fecha_base,
        )
        if not ok:
            observed_failures.append(step_name)

    # Repetimos el sync despues de observados/legacy para que el refresh final
    # capture tambien ese material en Postgres antes de publicar el dashboard.
    sync_target_incremental("sync_target_incremental_final", fecha_base, observed_failures)

    # Segundo refresh para incorporar tambien lo que hayan agregado los modelos
    # observados/legacy si llegaron a completarse en esta misma corrida.
    refrescar_dashboard("dashboard_maquina_final", fecha_base, observed_failures)

    # Refresco de datos dinámicos en dashboard_operativo_aurora_pro.html (heatmap + liga)
    ejecutar_paso_opcional(
        "refrescar_preview_dashboard",
        [sys.executable, str(BASE_DIR / "herramientas" / "refrescar_datos_dashboard.py")],
        fecha_base,
    )

    if observed_failures:
        log.warning(f"[PIPELINE][OPTIONAL] Fallaron pasos observados: {sorted(set(observed_failures))}")
        print(f"  [WARN] Fallaron pasos observados: {', '.join(sorted(set(observed_failures)))}")

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
    log.info(f"-- Auto-actualizador iniciado ({now:%Y-%m-%d %H:%M}) --")

    if not DB_PATH.exists():
        log.error(f"DB no encontrada: {DB_PATH}")
        print(f"[ERROR] DB no encontrada: {DB_PATH}")
        emit_critical_alert(
            code="db_missing",
            summary="No se encontro titan.db para correr el auto-actualizador.",
            details={"db_path": str(DB_PATH)},
        )
        return 1

    ultima = get_ultima_fecha_db()
    if ultima is None:
        log.error("No se pudo leer fecha de la DB.")
        print("[ERROR] No se pudo leer fecha de la DB.")
        emit_critical_alert(
            code="db_date_unreadable",
            summary="No se pudo leer la ultima fecha de la DB.",
            details={"db_path": str(DB_PATH)},
        )
        return 1

    target_date = fecha_objetivo_mercado(now)
    faltantes = dias_bursatiles_faltantes(ultima, target_date)

    log.info(
        f"Ultima fecha en DB: {ultima} | Objetivo: {target_date} | Dias faltantes: {faltantes}"
    )

    print("\n  TITAN Auto-Actualizador")
    print(f"  Ultima fecha DB : {ultima}")
    print(f"  Fecha objetivo  : {target_date}")
    print(f"  Dias faltantes  : {faltantes}")

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

        return 0 if ejecutar_pipeline_diario(latest_after, now) else 1

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
            if repaired_rows:
                log.info(f"Reparacion OHLCV conservadora aplicada a {repaired_rows} filas recientes.")
            print(f"  Actualizacion completada: {filas:,} filas nuevas.")
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
            if latest_after > ultima or needs_metadata:
                db.save_market_data_update(latest_after.isoformat())
                log.info(f"[PIPELINE] Metadata de mercado actualizada para {latest_after}")

        return 0 if ejecutar_pipeline_diario(latest_after, now) else 1

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
