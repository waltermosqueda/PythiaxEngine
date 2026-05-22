#!/usr/bin/env python3
"""
Monitor de cuota de egress Supabase.

Consulta la Platform API de Supabase (/platform/organizations/{slug}/usage)
para obtener el egress acumulado del ciclo de billing actual y envía alertas
por Telegram si se superan los umbrales.

Nota: usa Classic Token (sbp_) vía Authorization: Bearer.

Umbrales (sobre el límite del plan free = 5 GB):
  < 70%  (< 3.50 GB) — solo log, sin alerta
  70–89% (3.50–4.49 GB) — warning Telegram + GitHub warning annotation
  ≥ 90%  (≥ 4.50 GB) — critical Telegram + exit(1) → detiene el pipeline

Exit codes:
  0 — OK o warning (pipeline continúa)
  1 — cuota crítica (pipeline se detiene para conservar egress restante)
  2 — error de configuración (token faltante, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone


PLAN_LIMIT_GB: float = 5.0
WARN_PCT: float = 70.0
CRITICAL_PCT: float = 90.0


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _send_telegram(bot_token: str, chat_id: str, text: str) -> None:
    payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as exc:  # non-critical: don't break pipeline over Telegram
        print(f"::warning::Telegram notification failed: {exc}")


def _github_annotation(level: str, message: str) -> None:
    """Emite una anotación visible en el resumen del workflow de GitHub Actions."""
    print(f"::{level}::{message}")


def check_egress(org_slug: str, access_token: str) -> tuple[float, float]:
    """
    Retorna (egress_gb_used, egress_pct) del ciclo actual.
    Lanza en caso de error de API.
    """
    # Endpoint correcto: /platform/ (no /v1/). Requiere Classic Token (sbp_).
    url = f"https://api.supabase.com/platform/organizations/{org_slug}/usage"
    data = _get(url, access_token)

    # La respuesta tiene forma:
    # {"usages": [{"metric": "EGRESS", "usage": X.XX, "pricing_free_units": 5, ...}, ...]}
    # donde usage ya está en GB (no bytes).
    usages = data.get("usages") or []
    egress_gb: float | None = None
    for item in usages:
        metric = str(item.get("metric") or "").upper()
        if metric == "EGRESS":
            val = item.get("usage")
            if val is not None:
                egress_gb = float(val)
            break

    if egress_gb is None:
        raise ValueError(f"No se encontró métrica EGRESS en la respuesta: {[u.get('metric') for u in usages]}")

    egress_pct = egress_gb / PLAN_LIMIT_GB * 100.0
    return egress_gb, egress_pct


def main() -> int:
    parser = argparse.ArgumentParser(description="Verifica cuota de egress Supabase.")
    parser.add_argument("--org-slug", required=True, help="Slug de la organización Supabase.")
    parser.add_argument("--warn-pct", type=float, default=WARN_PCT,
                        help=f"% de uso para warning (default {WARN_PCT}).")
    parser.add_argument("--critical-pct", type=float, default=CRITICAL_PCT,
                        help=f"% de uso para critical/detener pipeline (default {CRITICAL_PCT}).")
    parser.add_argument("--limit-gb", type=float, default=PLAN_LIMIT_GB,
                        help=f"Límite del plan en GB (default {PLAN_LIMIT_GB}).")
    args = parser.parse_args()

    access_token = os.environ.get("SUPABASE_ACCESS_TOKEN", "").strip()
    telegram_bot = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    telegram_chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not access_token:
        print("::error::SUPABASE_ACCESS_TOKEN no está configurado. Saltando chequeo de egress.")
        return 2

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    try:
        egress_gb, egress_pct = check_egress(args.org_slug, access_token)
    except Exception as exc:
        print(f"::warning::No se pudo obtener egress de Supabase Platform API: {exc}")
        print("Continuando pipeline — chequeo de egress omitido.")
        return 0  # No bloquear el pipeline por falla de monitoreo

    remaining_gb = args.limit_gb - egress_gb
    bar_filled = int(egress_pct / 5)  # 1 bloque cada 5%
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    summary = (
        f"Supabase egress: {egress_gb:.3f} GB / {args.limit_gb:.1f} GB "
        f"({egress_pct:.1f}%) — restante: {remaining_gb:.3f} GB [{now_utc}]"
    )
    print(summary)
    print(f"[{bar}] {egress_pct:.1f}%")

    if egress_pct >= args.critical_pct:
        msg = (
            f"🚨 <b>PYTHIAX — EGRESS CRÍTICO</b>\n\n"
            f"Supabase egress al <b>{egress_pct:.1f}%</b> del límite free\n"
            f"Usado: <b>{egress_gb:.3f} GB</b> de {args.limit_gb:.1f} GB\n"
            f"Restante: <b>{remaining_gb:.3f} GB</b>\n\n"
            f"⛔ El pipeline cloud-daily fue DETENIDO para conservar egress.\n"
            f"Acción requerida: revisar https://supabase.com/dashboard/org/{args.org_slug}/usage\n\n"
            f"⏱ {now_utc}"
        )
        _github_annotation("error", f"EGRESS CRÍTICO: {egress_pct:.1f}% — pipeline detenido")
        if telegram_bot and telegram_chat:
            _send_telegram(telegram_bot, telegram_chat, msg)
        print(f"\n❌ EGRESS CRÍTICO ({egress_pct:.1f}% ≥ {args.critical_pct}%) — deteniendo pipeline.")
        return 1

    if egress_pct >= args.warn_pct:
        msg = (
            f"⚠️ <b>PYTHIAX — Egress warning</b>\n\n"
            f"Supabase egress al <b>{egress_pct:.1f}%</b> del límite free\n"
            f"Usado: <b>{egress_gb:.3f} GB</b> de {args.limit_gb:.1f} GB\n"
            f"Restante: <b>{remaining_gb:.3f} GB</b>\n\n"
            f"El pipeline continúa, pero considerá revisar el consumo.\n"
            f"🔗 https://supabase.com/dashboard/org/{args.org_slug}/usage\n\n"
            f"⏱ {now_utc}"
        )
        _github_annotation("warning", f"Egress al {egress_pct:.1f}% del límite — revisar consumo")
        if telegram_bot and telegram_chat:
            _send_telegram(telegram_bot, telegram_chat, msg)
        print(f"\n⚠️  Warning: egress al {egress_pct:.1f}% — pipeline continúa.")
        return 0

    print(f"\n✅ Egress OK ({egress_pct:.1f}% < {args.warn_pct}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
