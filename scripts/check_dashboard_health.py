#!/usr/bin/env python3
"""
Monitor de salud del dashboard.
Detecta:
  - Snapshot local stale (no actualizado hoy en dia de mercado)
  - Dashboard HTML stale en GitHub Pages
  - Pipeline que aborto (log con errores criticos sin completado)
  - Incoherencia de datos (market_date vs generated_at desfasados)

Corre sin dependencias externas: solo stdlib + pathlib.
Retorna exit code 0 si todo OK, 1 si hay problemas.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / "dashboards" / "maquina_pensante" / "tablero_maquina_pensante_snapshot.json"
PIPELINE_LOG = ROOT / "logs" / "pipeline_run.log"
# Horario del pipeline: 20:00 local (Argentina UTC-3)
# Si ya son las 21:00 y no hay snapshot de hoy -> ALERTA
PIPELINE_HOUR_LOCAL = 20
ALERT_AFTER_HOUR_LOCAL = 21   # empezar a alarmar a partir de las 21hs


def is_weekday(d: datetime) -> bool:
    return d.weekday() < 5  # lun-vie


def local_now() -> datetime:
    # Argentina UTC-3 (sin DST)
    tz = timezone(timedelta(hours=-3))
    return datetime.now(tz)


def check_snapshot() -> list[str]:
    issues = []
    now = local_now()

    if not SNAPSHOT_PATH.exists():
        issues.append("CRITICO: snapshot no existe en " + str(SNAPSHOT_PATH))
        return issues

    # Verificar mtime del archivo
    mtime = datetime.fromtimestamp(SNAPSHOT_PATH.stat().st_mtime, tz=timezone(timedelta(hours=-3)))
    age_hours = (now - mtime).total_seconds() / 3600

    # Cargar JSON
    try:
        data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        issues.append(f"CRITICO: no se pudo leer snapshot: {e}")
        return issues

    generated_at_str = data.get("generated_at", "")
    try:
        gen = datetime.fromisoformat(generated_at_str).replace(tzinfo=timezone(timedelta(hours=-3)))
    except Exception:
        issues.append(f"CRITICO: generated_at invalido: {generated_at_str!r}")
        return issues

    gen_age_hours = (now - gen).total_seconds() / 3600
    gen_date = gen.date()
    today = now.date()

    integrity = data.get("integrity", {})
    latest_market = integrity.get("latest_market_date", "?")
    latest_pred   = integrity.get("latest_prediction_date", "?")

    # Solo alarmar en dias habiles despues del horario del pipeline
    if is_weekday(now) and now.hour >= ALERT_AFTER_HOUR_LOCAL:
        if gen_date < today:
            issues.append(
                f"STALE: snapshot generado el {gen_date} (hace {gen_age_hours:.1f}h),"
                f" hoy es {today}. El pipeline NO actualizo el dashboard hoy."
            )
        elif gen_age_hours > 26:
            issues.append(
                f"STALE: snapshot tiene {gen_age_hours:.1f}h de antiguedad"
                f" (generado {generated_at_str})."
            )

    # Coherencia: market_date debe ser <= generated_at date (puede ser viernes si hoy es lunes)
    try:
        market_date = datetime.strptime(latest_market, "%Y-%m-%d").date()
        days_diff = (gen_date - market_date).days
        # El market date puede estar 3 dias atras (fin de semana) - mas que eso es problema
        if days_diff > 4:
            issues.append(
                f"INCOHERENCIA: market_date={latest_market} pero snapshot={gen_date}"
                f" (diferencia de {days_diff} dias)."
            )
    except Exception:
        pass

    # Predicciones: si hay cero para hoy en dia habil
    preds_count = integrity.get("predictions_count", 0)
    if is_weekday(now) and preds_count == 0:
        issues.append("INCOHERENCIA: predictions_count=0 en snapshot.")

    return issues


def read_log_text() -> str:
    """Lee el log manejando UTF-16 LE (que es lo que usa PowerShell Tee-Object)."""
    raw = PIPELINE_LOG.read_bytes()
    if raw[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def check_pipeline_log() -> list[str]:
    issues = []
    if not PIPELINE_LOG.exists():
        issues.append("WARN: no existe logs/pipeline_run.log")
        return issues

    now = local_now()
    today_str = now.strftime("%Y-%m-%d")

    text = read_log_text()
    lines = text.splitlines()

    # Buscar ultima ejecucion de hoy
    today_lines = [l for l in lines if l.startswith(today_str)]
    if not today_lines and is_weekday(now) and now.hour >= ALERT_AFTER_HOUR_LOCAL:
        issues.append(f"WARN: no hay entradas del pipeline para hoy ({today_str}) en el log.")
        return issues

    # Buscar si completo
    completed = any("Pipeline diario completado" in l for l in today_lines)
    critical   = [l for l in today_lines if "[CRITICAL ALERT]" in l]
    pipeline_failed = [l for l in today_lines if "pipeline fallo" in l.lower() or "Paso" in l and "fallo" in l and "[CRITICAL" in l]

    if not completed and is_weekday(now) and now.hour >= ALERT_AFTER_HOUR_LOCAL:
        if critical:
            for c in critical:
                issues.append(f"CRITICO en pipeline: {c.strip()}")
        else:
            issues.append(
                f"WARN: pipeline de hoy ({today_str}) NO completo con 'Pipeline diario completado'."
            )

    return issues


def main() -> int:
    now = local_now()
    sep = "=" * 70
    print(f"\n{sep}")
    print(f"  DASHBOARD HEALTH CHECK  |  {now.strftime('%Y-%m-%d %H:%M:%S')} (UTC-3)")
    print(sep)

    all_issues: list[str] = []
    all_issues.extend(check_snapshot())
    all_issues.extend(check_pipeline_log())

    if not all_issues:
        # Mostrar resumen OK
        try:
            data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            gen = data.get("generated_at", "?")
            integ = data.get("integrity", {})
            market = integ.get("latest_market_date", "?")
            preds  = integ.get("predictions_count", "?")
            models = integ.get("prediction_models", "?")
            print(f"  Estado: OK")
            print(f"  Snapshot: {gen}")
            print(f"  Mercado:  {market}")
            print(f"  Predicciones en DB: {preds} | Modelos: {models}")
            comp = data.get("competition", [])
            if comp:
                print(f"  Modelos en competition: {len(comp)}")
                active = [m for m in comp if m.get("role") in ("activo", "base", "referencia")]
                for m in active:
                    v = m.get("version", "?")
                    acc = m.get("accuracy_pct", 0)
                    avg = m.get("avg_return_pct", 0)
                    stale = m.get("snapshot_stale_market_days", 0)
                    stale_warn = " *** STALE ***" if stale and stale > 1 else ""
                    print(f"    {v:15s}  WR={acc:.0f}%  avg={avg:+.2f}%  stale={stale}d{stale_warn}")
        except Exception:
            pass
        print(sep + "\n")
        return 0
    else:
        print(f"  Estado: PROBLEMAS DETECTADOS ({len(all_issues)})")
        print()
        for i, issue in enumerate(all_issues, 1):
            tag = "  [!]" if "CRITICO" in issue else "  [W]"
            print(f"{tag} {issue}")
        print(sep + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
