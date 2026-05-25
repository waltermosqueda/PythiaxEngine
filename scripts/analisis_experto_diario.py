#!/usr/bin/env python3
"""
ANÁLISIS EXPERTO DIARIO — PythiaxEngine + Gemini 2.5 Pro
=========================================================

Complementa plan_inversion_diario.py con consulta a Gemini 2.5 Pro
(thinking mode) para análisis profundo y quirúrgico de los candidatos
más fuertes detectados por los modelos ML del sistema.

Pipeline:
  1. Carga snapshot (mismo que plan_inversion_diario.py)
  2. Enriquece con yfinance (mismo pipeline)
  3. Construye prompt estructurado con todos los datos enriquecidos
  4. Consulta Gemini 2.5 Pro → análisis experto con razonamiento profundo
  5. Guarda logs/analisis_experto/analisis_YYYY-MM-DD.md + .json
  6. Envía por Telegram: header estructurado (HTML) + análisis IA (texto)

Requiere en env:
  GEMINI_API_KEY         → GitHub Secret
  TELEGRAM_BOT_TOKEN     → GitHub Secret (opcional)
  TELEGRAM_CHAT_ID       → GitHub Secret (opcional)

Paquetes Python necesarios:
  pip install yfinance numpy pandas google-generativeai google-genai

Uso:
  py scripts/analisis_experto_diario.py
  py scripts/analisis_experto_diario.py --no-telegram
  py scripts/analisis_experto_diario.py --no-ai       # solo datos bot, sin Gemini
  py scripts/analisis_experto_diario.py --quiet
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

# ── Importar lógica compartida de plan_inversion_diario ─────────────────────
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import plan_inversion_diario as _plan  # noqa: E402

Candidate = _plan.Candidate
load_snapshot = _plan.load_snapshot
extract_candidates = _plan.extract_candidates
enrich_candidates = _plan.enrich_candidates
score_consensus = _plan.score_consensus
score_technical = _plan.score_technical
score_fundamental = _plan.score_fundamental
composite_probability = _plan.composite_probability
apply_quality_filters = _plan.apply_quality_filters
compute_adjusted_probability = _plan.compute_adjusted_probability
compute_sizing = _plan.compute_sizing
enforce_aggregate_capital_cap = _plan.enforce_aggregate_capital_cap
fetch_macro_context = _plan.fetch_macro_context
macro_label = _plan.macro_label

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = (
    ROOT / "dashboards" / "maquina_pensante" / "tablero_maquina_pensante_snapshot.json"
)
DEFAULT_OUTPUT_DIR = ROOT / "logs" / "analisis_experto"

# Modelos Gemini en orden de preferencia (mejor → más robusto)
# Nombres válidos verificados contra API v1beta (mayo 2026):
#   - gemini-2.5-pro-preview-05-06 → 404 (nombre incorrecto)
#   - gemini-2.5-pro-exp-03-25     → 404 (nombre incorrecto)
#   - gemini-2.5-pro               → existe, requiere billing
#   - gemini-2.5-flash             → existe, requiere billing
#   - gemini-2.0-flash             → existe, requiere billing
#   - gemini-1.5-pro               → existe, free tier funciona
GEMINI_MODELS = [
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_MAX = 4000


# ─────────────────────────────────────────────────────────────────────────────
# Construcción del prompt para Gemini
# ─────────────────────────────────────────────────────────────────────────────

def _fmt(v: Any, decimals: int = 2, prefix: str = "", suffix: str = "") -> str:
    """Formatea un float o retorna '—' si es None."""
    if v is None:
        return "—"
    try:
        return f"{prefix}{float(v):.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(v)


def build_analysis_prompt(
    meta: dict[str, Any],
    macro: dict[str, Any],
    candidates: list[Candidate],
    capital: float,
) -> str:
    today = date.today().isoformat()
    L: list[str] = []

    # ── Contexto del sistema ──────────────────────────────────────────────────
    regime = meta.get("regime", "?")
    breadth = meta.get("breadth_pct", "?")
    generated_at = meta.get("generated_at", "?")

    spy_d  = macro.get("spy") or {}
    qqq_d  = macro.get("qqq") or {}
    vix_d  = macro.get("vix") or {}

    spy_str = f"SPY {spy_d['last']} ({spy_d['chg_5d_pct']:+.2f}% 5d)" if spy_d else "SPY ?"
    qqq_str = f"QQQ {qqq_d['last']} ({qqq_d['chg_5d_pct']:+.2f}% 5d)" if qqq_d else "QQQ ?"
    vix_str = f"VIX {vix_d['last']:.1f} ({vix_d['chg_5d_pct']:+.1f}%)" if vix_d else "VIX ?"
    macro_one_line = f"{spy_str} | {qqq_str} | {vix_str}"

    # ── Candidatos ────────────────────────────────────────────────────────────
    actionable = [
        c for c in candidates
        if c.decision in ("COMPRAR", "WATCH-COMPRAR", "WATCH", "MAYOR_RIESGO")
    ][:10]
    descartados = [c for c in candidates if c.decision == "DESCARTAR"][:8]

    # ── Helpers de serialización ──────────────────────────────────────────────
    def _indicator_line(c: Candidate) -> str:
        parts: list[str] = []
        if c.consensus_score is not None:
            parts.append(f"Cons {c.consensus_score:.2f}")
        if c.rsi is not None:
            parts.append(f"RSI {c.rsi:.1f}")
        if c.obv_rising is not None:
            parts.append("OBV+" if c.obv_rising else "OBV-")
        if c.macd_pos is not None:
            parts.append("MACD+" if c.macd_pos else "MACD-")
        if c.ema_aligned is not None:
            parts.append("EMA alineada" if c.ema_aligned else "EMA NO alineada")
        elif c.ema20 and c.ema50:
            parts.append("EMA20>EMA50" if c.ema20 > c.ema50 else "EMA20<EMA50")
        if c.rr_ratio is not None:
            parts.append(f"R:R {c.rr_ratio:.2f}")
        if c.days_to_target is not None:
            parts.append(f"{c.days_to_target}d target")
        return " | ".join(parts)

    def _fund_line(c: Candidate) -> str:
        price = c.current or c.entry or 0.0
        parts: list[str] = []
        if c.sector:
            parts.append(c.sector)
        if c.pe is not None:
            parts.append(f"P/E {c.pe:.1f}")
        if c.beta is not None:
            parts.append(f"beta={c.beta:.2f}")
        if c.analyst_target and price:
            upside_a = (c.analyst_target - price) / price * 100
            parts.append(f"analistas {_fmt(c.analyst_target, 2, '$')} ({upside_a:+.1f}%)")
        if c.market_cap:
            mc = c.market_cap
            parts.append(
                "MegaCap" if mc >= 1e11 else
                "LargeCap" if mc >= 1e10 else
                "MidCap" if mc >= 2e9 else "SmallCap"
            )
        return " | ".join(parts)

    # ── Cuerpo del prompt ─────────────────────────────────────────────────────
    L.append(
        f"Sos un portfolio manager cuantitativo con 20 anos de experiencia en equity "
        f"NYSE/NASDAQ. Fecha: {today}. Tenes que entregar un analisis PROFUNDO y HONESTO, "
        f"respaldado por todo tu poder de razonamiento. Usa pensamiento critico, no frases genericas."
    )
    L.append("")

    L.append("── SISTEMA: PythiaxEngine ──")
    L.append("9 modelos ML ensemble que votan direccion de equity. Accuracy historica ~80%.")
    L.append(f"Snapshot: {generated_at}  |  Regimen: {regime}  |  Breadth: {breadth}%")
    L.append(f"Macro: {macro_one_line}")
    L.append(f"Capital a asignar: USD {capital:,.0f}")
    L.append("")

    L.append(f"── CANDIDATOS ACTIVOS ({len(actionable)}) ──")
    L.append("")
    for i, c in enumerate(actionable, 1):
        price = c.current or c.entry or 0.0
        avg_wr = sum(c.wrs) / max(1, len(c.wrs))
        mtm_str = f"{c.mtm_pct:+.2f}%" if c.mtm_pct is not None else "—"

        L.append(f"{i}. {c.ticker}  [{c.decision}]")
        L.append(
            f"   Prob ajustada: {c.prob_ajustada*100:.1f}%  (formula plana: {c.composite_prob*100:.1f}%)  "
            f"| {len(c.models)} modelos | WR medio: {avg_wr:.1f}%"
        )
        L.append(
            f"   Precio: {_fmt(price, 2, '$')}  | MTM: {mtm_str}  "
            f"| Entry: {_fmt(c.entry, 2, '$')}  "
            f"| Stop: {_fmt(c.stop_price, 2, '$')}  | Target: {_fmt(c.target_price, 2, '$')}"
        )
        ind = _indicator_line(c)
        if ind:
            L.append(f"   Indicadores: {ind}")
        if c.upside_52w is not None:
            L.append(f"   Upside 52w: {c.upside_52w:.1f}%  | Dist EMA200: {_fmt(c.dist_ema200_pct, 1, '', '%')}  | Vol rel 5d: {_fmt(c.rel_vol_5d, 2)}")
        fund = _fund_line(c)
        if fund:
            L.append(f"   Fundamental: {fund}")
        if c.earnings_in_days is not None and c.earnings_in_days >= 0:
            flag = " <- RIESGO BINARIO" if c.earnings_in_days <= 5 else ""
            L.append(f"   Earnings: en {c.earnings_in_days}d{flag}")
        if c.news_titles:
            for t in c.news_titles[:2]:
                L.append(f"   News: {t}")
        if c.prob_adjustments:
            L.append(f"   Ajustes: {' | '.join(c.prob_adjustments[:5])}")
        if c.why_up:
            L.append(f"   A favor: {' | '.join(c.why_up[:3])}")
        if c.why_risk:
            L.append(f"   En contra: {' | '.join(c.why_risk[:3])}")
        L.append("")

    if descartados:
        L.append("── DESCARTADOS (referencia) ──")
        for c in descartados:
            L.append(f"  {c.ticker}: {c.reject_reason or c.decision}  | comp={c.composite_prob*100:.0f}%")
        L.append("")

    bot_rank = [c.ticker for c in sorted(actionable, key=lambda x: -x.composite_prob)[:5]]

    L.append("=" * 70)
    L.append("INSTRUCCIONES DE SALIDA — SEGUIRLAS AL PIE DE LA LETRA")
    L.append("=" * 70)
    L.append("")
    L.append(
        "Produce EXACTAMENTE el siguiente formato. Sin introduccion. Sin conclusion. "
        "Directo al formato. Usa TODO tu poder de razonamiento antes de escribir cada linea."
    )
    L.append("")
    L.append("-" * 70)
    L.append(f"RANKING HONESTO — {today}")
    L.append("Ajustado por d2t, upside_52w, MTM extendido y confirmacion multiple")
    L.append("")
    L.append(f"Macro: {macro_one_line} -> regimen [describir en 5 palabras]")
    L.append("")
    L.append("TOP N — probabilidad real de suba (proximas 5-15 ruedas)")
    L.append("")
    L.append("[Para cada candidato que consideras accionable, en orden de conviccion TUYA:")
    L.append("  Nro TICKER XX-YY% — [descriptor corto de 3-5 palabras]")
    L.append("     [indicadores clave: Cons X.XX, OBV+/-, MACD+/-, EMA status, RSI XX.X, R:R X.X, Xd margen]")
    L.append("     [advertencia principal — exactamente 1 linea concisa]")
    L.append("]")
    L.append("")
    L.append(f"CARTERA HONESTA — USD {capital:,.0f}")
    L.append("[Para cada posicion:]")
    L.append("- TICKER XX% (USD X.XXX) — [razon de 3-5 palabras]")
    L.append("- CASH XX% (USD X.XXX) — reserva para [condicion especifica de deploy]")
    L.append("[La cartera DEBE sumar 100% siempre]")
    L.append("")
    L.append("NO TOMAR (aunque el bot los marque)")
    L.append("[Para cada ticker que rechazas, aunque el bot lo marque COMPRAR/WATCH:]")
    L.append("- TICKER — [razon directa y especifica en 1 linea]")
    L.append("")
    L.append("ESPERAR confirmacion")
    L.append("[Tickers en zona limitrofe que necesitan 1-2 ruedas mas:]")
    L.append("- TICKER — [que senal falta exactamente]")
    L.append("")
    L.append("Vs ranking del bot")
    L.append(f"Bot: {' > '.join(bot_rank)} (por composite_prob crudo)")
    L.append("Honesto: [tu ranking] ([razon de la diferencia principal en 1 linea])")
    L.append("-" * 70)
    L.append("")
    L.append("REGLAS CRITICAS — OBLIGATORIAS:")
    L.append("1. Probabilidades como RANGOS (ej: 65-68%), nunca numero unico")
    L.append("2. Mencionar EXPLICITAMENTE el estado de MACD, OBV y EMA para cada pick")
    L.append("3. La cartera SIEMPRE suma exactamente 100%")
    L.append("4. CASH siempre tiene condicion especifica de deploy (no generica)")
    L.append("5. NO TOMAR y ESPERAR son secciones obligatorias aunque esten vacias")
    L.append("6. El 'Vs bot' SIEMPRE muestra el ranking del algoritmo y el tuyo con diferencia explicada")
    L.append("7. CERO frases genericas. CERO disclaimers. CERO relleno.")
    L.append("8. Cada advertencia es exactamente 1 linea, directa y tecnica")
    L.append("9. Si un ticker tiene earnings en <=5d, marcarlo como RIESGO BINARIO en el ranking")
    L.append("10. Usa TODOS tus pasos de razonamiento antes de escribir. Este analisis va a un trader real.")

    return "\n".join(L)

def consult_gemini(prompt: str, api_key: str, log) -> tuple[str | None, str]:
    """
    Consulta a Gemini. Retorna (texto_respuesta, modelo_usado).
    SDK: google-genai (nuevo, thinking mode) → google-generativeai (legacy).
    Retry: 1 intento adicional con 65s de espera si recibe 429 (quota/min).
    Retorna (None, '') si todos los intentos fallan.
    """
    import time

    def _try_genai_new(model_id: str, retry: bool = False) -> str | None:
        """Prueba con google-genai SDK (thinking mode)."""
        try:
            from google import genai as genai_new  # type: ignore
            from google.genai import types as genai_types  # type: ignore
        except ImportError:
            return None

        try:
            client = genai_new.Client(api_key=api_key)
            label = f"{model_id} (thinking{'·retry' if retry else ''})"
            log(f"[gemini] {label}…")

            # Intentar con thinking_config primero; algunos modelos no lo soportan
            try:
                resp = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        thinking_config=genai_types.ThinkingConfig(thinking_budget=10000),
                        max_output_tokens=8192,
                        temperature=1.0,
                    ),
                )
            except Exception:
                # Fallback sin thinking (para modelos que no soportan thinking)
                resp = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        max_output_tokens=8192,
                        temperature=0.4,
                    ),
                )

            text = resp.text
            if text:
                log(f"[gemini] ✓ {model_id} SDK-nuevo ({len(text)} chars)")
                return text
            return None
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                log(f"[gemini]   {model_id}: 429 quota — {'reintentando en 65s' if not retry else 'sin más reintentos'}")
                if not retry:
                    time.sleep(65)
                    return _try_genai_new(model_id, retry=True)
            else:
                log(f"[gemini]   {model_id}: {exc_str[:200]}")
            return None

    def _try_genai_legacy(model_id: str, retry: bool = False) -> str | None:
        """Prueba con google-generativeai SDK (legacy)."""
        try:
            import google.generativeai as genai_legacy  # type: ignore
        except ImportError:
            return None

        try:
            genai_legacy.configure(api_key=api_key)
            label = f"{model_id} (legacy{'·retry' if retry else ''})"
            log(f"[gemini] {label}…")
            model = genai_legacy.GenerativeModel(
                model_name=model_id,
                generation_config=genai_legacy.types.GenerationConfig(
                    max_output_tokens=8192,
                    temperature=0.4,
                ),
            )
            resp = model.generate_content(prompt)
            text = resp.text
            if text:
                log(f"[gemini] ✓ {model_id} SDK-legacy ({len(text)} chars)")
                return text
            return None
        except Exception as exc:
            exc_str = str(exc)
            if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                log(f"[gemini]   {model_id}: 429 quota — {'reintentando en 65s' if not retry else 'sin más reintentos'}")
                if not retry:
                    time.sleep(65)
                    return _try_genai_legacy(model_id, retry=True)
            else:
                log(f"[gemini]   {model_id}: {exc_str[:200]}")
            return None

    # ── Intentar con SDK nuevo primero, luego legacy ────────────────────
    sdk_new_available = True
    try:
        from google import genai  # noqa: F401  # type: ignore
    except ImportError:
        sdk_new_available = False
        log("[gemini] google-genai no disponible, usando google-generativeai…")

    for model_id in GEMINI_MODELS:
        if sdk_new_available:
            text = _try_genai_new(model_id)
            if text:
                return text, model_id
        else:
            text = _try_genai_legacy(model_id)
            if text:
                return text, model_id

    # Si SDK nuevo falló en todos, probar legacy como segunda pasada
    if sdk_new_available:
        log("[gemini] SDK nuevo agotado, intentando con google-generativeai…")
        for model_id in GEMINI_MODELS:
            text = _try_genai_legacy(model_id)
            if text:
                return text, f"{model_id}-legacy"

    log("[gemini] ⚠️  todos los modelos fallaron")
    return None, ""


# ─────────────────────────────────────────────────────────────────────────────
# Render Markdown (archivo)
# ─────────────────────────────────────────────────────────────────────────────

def render_markdown_experto(
    meta: dict[str, Any],
    macro: dict[str, Any],
    candidates: list[Candidate],
    ai_text: str | None,
    model_used: str,
    capital: float,
) -> str:
    today = date.today().isoformat()
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L: list[str] = []

    L.append("# 🧠 Análisis Experto Diario — PythiaxEngine + Gemini")
    L.append("")
    L.append(f"**Fecha:** {today}  |  **Generado:** {now_utc}")
    L.append(
        f"**Snapshot:** {meta.get('generated_at')}  ·  "
        f"**Régimen:** `{meta.get('regime')}`  ·  "
        f"**Breadth:** {meta.get('breadth_pct')}%"
    )
    L.append(f"**Macro:** {macro_label(macro)}")
    L.append(f"**Modelo IA:** `{model_used or 'no disponible'}`")
    L.append("")
    L.append("> ⚠️ No es asesoramiento financiero. Hacé tu propia diligencia antes de operar.")
    L.append("")
    L.append("---")
    L.append("")

    # Tabla resumen de candidatos
    actionable = [c for c in candidates if c.decision != "DESCARTAR"]
    if actionable:
        L.append("## Candidatos procesados por el bot")
        L.append("")
        L.append("| Ticker | Decisión bot | Prob honesta | Formula | Consenso | Técnico | R:R | d2t |")
        L.append("|--------|-------------|--------------|---------|----------|---------|-----|-----|")
        for c in actionable[:12]:
            rr = f"{c.rr_ratio:.2f}" if c.rr_ratio else "—"
            L.append(
                f"| `{c.ticker}` | {c.decision} | **{c.prob_ajustada * 100:.0f}%** | "
                f"{c.composite_prob * 100:.0f}% | {c.consensus_score * 100:.0f}% | "
                f"{c.technical_score * 100:.0f}% | {rr} | {c.days_to_target}d |"
            )
        L.append("")
        L.append("---")
        L.append("")

    L.append("## Análisis Gemini")
    L.append("")
    if ai_text:
        L.append(ai_text)
    else:
        L.append("> ⚠️ La consulta a Gemini no estuvo disponible hoy.")
        L.append("> El análisis cuantitativo está en `logs/plan_diario/`.")
    L.append("")
    L.append("---")
    L.append(f"_Generado por `scripts/analisis_experto_diario.py` · PythiaxEngine_")
    return "\n".join(L)


# ─────────────────────────────────────────────────────────────────────────────
# Telegram — dos mensajes: header HTML + análisis IA en texto plano
# ─────────────────────────────────────────────────────────────────────────────

def _send_raw_telegram(
    text: str, parse_mode: str, token: str, chat_id: str, log
) -> bool:
    """Envía texto a Telegram con el parse_mode dado (HTML o vacío)."""
    chunks: list[str] = []
    remaining = text
    while len(remaining) > TELEGRAM_MAX:
        cut = remaining.rfind("\n", 0, TELEGRAM_MAX)
        if cut < 1:
            cut = TELEGRAM_MAX
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    chunks.append(remaining)

    ok_all = True
    for idx, chunk in enumerate(chunks, 1):
        suffix = f"\n(parte {idx}/{len(chunks)})" if len(chunks) > 1 else ""
        payload: dict[str, str] = {
            "chat_id": chat_id,
            "text": chunk + suffix,
            "disable_web_page_preview": "true",
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            TELEGRAM_API.format(token=token), data=data, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status != 200:
                    log(f"Telegram parte {idx}: HTTP {r.status}")
                    ok_all = False
                else:
                    log(f"✓ Telegram parte {idx}/{len(chunks)} enviada")
        except Exception as exc:
            log(f"Telegram parte {idx} FAIL: {exc}")
            ok_all = False
    return ok_all


def send_telegram_experto(
    meta: dict[str, Any],
    macro: dict[str, Any],
    candidates: list[Candidate],
    ai_text: str | None,
    model_used: str,
    today: str,
    log,
) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID no presentes → skip Telegram")
        return

    # ── Mensaje 1: header HTML estructurado ──────────────────────────────
    regime = meta.get("regime", "?")
    breadth = meta.get("breadth_pct", "?")
    macro_txt = macro_label(macro).replace("·", "|")

    H: list[str] = []
    H.append(f"🧠 <b>ANÁLISIS EXPERTO IA — {today}</b>")
    H.append(f"<i>Régimen: {regime}  ·  Breadth: {breadth}%</i>")
    if macro_txt and macro_txt != "macro no disponible":
        H.append(f"<i>{macro_txt}</i>")
    if model_used:
        H.append(f"<i>Modelo: {model_used}</i>")
    H.append("")

    actionable_buys = [c for c in candidates if c.decision in ("COMPRAR", "WATCH-COMPRAR")][:5]
    if actionable_buys:
        H.append("📊 <b>Top candidatos (bot):</b>")
        for c in actionable_buys:
            price_str = f"${c.current:.2f}" if c.current else "—"
            rr_str = f"  R:R {c.rr_ratio:.2f}" if c.rr_ratio else ""
            H.append(
                f"  <b>{c.ticker}</b> {c.prob_ajustada * 100:.0f}% "
                f"({c.decision})  {price_str}{rr_str}"
            )
        H.append("")

    if not ai_text:
        H.append("⚠️ <i>Consulta Gemini no disponible hoy.</i>")
    else:
        H.append(f"🤖 <i>Análisis completo abajo ({len(ai_text):,} chars)</i>")

    H.append("")
    H.append(f"<i>logs/analisis_experto/analisis_{today}.md</i>")
    H.append("⚠️ <i>No es asesoramiento financiero.</i>")

    header_msg = "\n".join(H)
    _send_raw_telegram(header_msg, "HTML", token, chat_id, log)

    # ── Mensaje 2: análisis IA en texto plano ─────────────────────────────
    if ai_text:
        _send_raw_telegram(ai_text, "", token, chat_id, log)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Análisis experto diario PythiaxEngine + Gemini 2.5 Pro"
    )
    p.add_argument("--snapshot-path", type=Path, default=DEFAULT_SNAPSHOT)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--capital", type=float, default=10_000.0)
    p.add_argument("--risk-pct", type=float, default=0.02)
    p.add_argument(
        "--max-candidates",
        type=int,
        default=10,
        help="Máx candidatos enviados a Gemini (los de mayor prob honesta)",
    )
    p.add_argument("--no-enrichment", action="store_true", help="Skip yfinance")
    p.add_argument("--no-telegram", action="store_true")
    p.add_argument("--no-ai", action="store_true", help="Skip consulta Gemini")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    def log(msg: str) -> None:
        if not args.quiet:
            print(f"[experto] {msg}", flush=True)

    # 1. Cargar snapshot
    log(f"snapshot: {args.snapshot_path}")
    try:
        snapshot = load_snapshot(args.snapshot_path)
    except FileNotFoundError as exc:
        print(f"[experto] FATAL: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"[experto] FATAL JSON: {exc}", file=sys.stderr)
        return 1

    # 2. Extraer candidatos vivos
    meta, candidates = extract_candidates(snapshot)
    log(f"candidatos vivos: {len(candidates)} (régimen: {meta['regime']})")

    # 3. Score consenso + ordenar
    for c in candidates:
        c.consensus_score = score_consensus(c)
    candidates.sort(key=lambda c: -c.consensus_score)

    # 4. Enriquecer con yfinance
    enrich_pool = candidates[: max(args.max_candidates, 15)]
    macro: dict[str, Any] = {}
    if not args.no_enrichment:
        log(f"enriqueciendo top {len(enrich_pool)} candidatos via yfinance…")
        enrich_candidates(enrich_pool, log)
        log("fetch macro context (SPY/QQQ/VIX)…")
        macro = fetch_macro_context(log)
    else:
        log("--no-enrichment → skip yfinance")

    # 5. Scoring completo + filtros + sizing
    for c in candidates:
        c.technical_score = score_technical(c)
        c.fundamental_score = score_fundamental(c)
        c.composite_prob = composite_probability(c)
        compute_sizing(c, args.capital, args.risk_pct)
        apply_quality_filters(c)
        compute_adjusted_probability(c)
    candidates.sort(key=lambda c: -c.prob_ajustada)
    enforce_aggregate_capital_cap(
        [c for c in candidates if c.decision == "COMPRAR"], args.capital
    )

    actionable = [c for c in candidates if c.decision != "DESCARTAR"]
    log(
        f"comprar: {sum(1 for c in candidates if c.decision=='COMPRAR')}  "
        f"watch: {sum(1 for c in candidates if 'WATCH' in c.decision)}  "
        f"mayor_riesgo: {sum(1 for c in candidates if c.decision=='MAYOR_RIESGO')}  "
        f"descartados: {sum(1 for c in candidates if c.decision=='DESCARTAR')}"
    )

    # 6. Consultar Gemini
    ai_text: str | None = None
    model_used = ""
    if not args.no_ai:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            log("GEMINI_API_KEY no presente en env → skip IA")
        else:
            prompt = build_analysis_prompt(
                meta, macro, candidates[: args.max_candidates], args.capital
            )
            log(f"prompt: {len(prompt):,} chars → enviando a Gemini…")
            ai_text, model_used = consult_gemini(prompt, api_key, log)
    else:
        log("--no-ai → skip Gemini")

    # 7. Guardar output
    today_iso = date.today().isoformat()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    md_content = render_markdown_experto(
        meta, macro, candidates, ai_text, model_used, args.capital
    )
    md_path = args.output_dir / f"analisis_{today_iso}.md"
    md_path.write_text(md_content, encoding="utf-8")
    log(f"✓ Escrito: {md_path}")

    json_out = {
        "date": today_iso,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_meta": meta,
        "model_used": model_used,
        "ai_analysis_chars": len(ai_text) if ai_text else 0,
        "candidates_summary": [
            {
                "ticker": c.ticker,
                "decision": c.decision,
                "prob_ajustada": c.prob_ajustada,
                "composite_prob": c.composite_prob,
                "rr_ratio": c.rr_ratio,
                "days_to_target": c.days_to_target,
            }
            for c in candidates[:15]
        ],
    }
    json_path = args.output_dir / f"analisis_{today_iso}.json"
    json_path.write_text(
        json.dumps(json_out, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    log(f"✓ Escrito: {json_path}")

    # 8. Telegram
    if not args.no_telegram:
        send_telegram_experto(
            meta, macro, candidates, ai_text, model_used, today_iso, log
        )
    else:
        log("--no-telegram → skip")

    # Resumen stdout
    print("=" * 70)
    print(
        f"ANÁLISIS EXPERTO {today_iso}  ·  "
        f"IA: {'✓ ' + model_used if model_used else '✗ no disponible'}  ·  "
        f"{len(actionable)} candidatos procesados"
    )
    for c in candidates[:5]:
        print(f"  {c.ticker:6s}  {c.decision:14s}  honesta {c.prob_ajustada * 100:.1f}%")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
