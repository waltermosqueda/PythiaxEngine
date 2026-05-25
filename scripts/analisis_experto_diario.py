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
GEMINI_MODELS = [
    "gemini-2.5-pro-preview-05-06",
    "gemini-2.5-pro",
    "gemini-2.5-pro-exp-03-25",
    "gemini-2.0-flash",
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

    L.append(
        f"Sos un analista de trading cuantitativo experto con 20 años de experiencia "
        f"en mercados de equity NYSE/NASDAQ. Fecha de hoy: {today}."
    )
    L.append(
        "Tu misión: análisis de trading PROFUNDO, QUIRÚRGICO y HONESTO de los "
        "candidatos detectados por PythiaxEngine (sistema algorítmico ML ensemble)."
    )
    L.append("")

    L.append("═══ CONTEXTO DEL SISTEMA ═══")
    L.append("PythiaxEngine: 9 modelos ML ensemble, predice dirección de equity NYSE/NASDAQ.")
    L.append(f"Régimen de mercado: {meta.get('regime')} | Breadth del mercado: {meta.get('breadth_pct')}%")
    L.append(f"Snapshot generado: {meta.get('generated_at')}")
    macro_txt = macro_label(macro)
    if macro_txt and macro_txt != "macro no disponible":
        L.append(f"Contexto macro actual: {macro_txt}")
    L.append(f"Capital del inversor: USD {capital:,.0f}")
    L.append("")

    # Solo candidatos que superaron o están cerca del threshold del bot
    actionable = [
        c for c in candidates
        if c.decision in ("COMPRAR", "WATCH-COMPRAR", "WATCH", "MAYOR_RIESGO")
    ][:10]

    L.append(f"═══ CANDIDATOS A ANALIZAR ({len(actionable)}) ═══")
    L.append("")

    for i, c in enumerate(actionable, 1):
        price = c.current or c.entry or 0.0
        avg_wr = sum(c.wrs) / max(1, len(c.wrs))

        L.append(f"┌── CANDIDATO {i}: {c.ticker} | Decisión bot: {c.decision} ──")
        L.append(
            f"│ Prob honesta ajustada: {c.prob_ajustada * 100:.1f}%  "
            f"│  Formula plana: {c.composite_prob * 100:.1f}%"
        )
        L.append(
            f"│ Modelos que votan: {len(c.models)} ({', '.join(c.models[:5])})  "
            f"│  WR promedio: {avg_wr:.1f}%"
        )
        L.append(
            f"│ Entry modelo: {_fmt(c.entry, 2, '$')}  "
            f"│  Close actual: {_fmt(price, 2, '$')}  "
            f"│  MTM abierto: {c.mtm_pct:+.2f}%"
        )
        L.append(
            f"│ Target modelo: {c.target_date} ({c.days_to_target}d)  "
            f"│  Stop sugerido: {_fmt(c.stop_price, 2, '$')}  "
            f"│  Target precio: {_fmt(c.target_price, 2, '$')}  "
            f"│  R:R: {_fmt(c.rr_ratio, 2)}"
        )

        # Técnico
        if c.rsi is not None:
            if c.ema_aligned:
                ema_str = "EMA20>EMA50>EMA200 (tendencia alcista)"
            elif c.ema20 and c.ema50 and c.ema20 > c.ema50:
                ema_str = "EMA20>EMA50 (sin confirmación EMA200)"
            else:
                ema_str = "EMA desordenada (sin tendencia)"
            L.append(
                f"│ Técnico: RSI {c.rsi:.1f}  │  {ema_str}  │  "
                f"MACD+ {'SÍ' if c.macd_pos else 'NO'}  │  "
                f"OBV subiendo {'SÍ' if c.obv_rising else 'NO'}"
            )
            L.append(
                f"│   ATR: {_fmt(c.atr, 3)}  │  "
                f"Distancia EMA200: {_fmt(c.dist_ema200_pct, 1, '', '%')}  │  "
                f"Upside 52w: {_fmt(c.upside_52w, 1, '', '%')}  │  "
                f"Vol relativo 5d: {_fmt(c.rel_vol_5d, 2)}"
            )

        # Fundamental
        fund_parts: list[str] = []
        if c.sector:
            fund_parts.append(f"Sector: {c.sector}")
        if c.pe is not None:
            fund_parts.append(f"P/E: {c.pe:.1f}")
        if c.analyst_target and price:
            upside_a = (c.analyst_target - price) / price * 100
            fund_parts.append(f"Target analistas: {_fmt(c.analyst_target, 2, '$')} ({upside_a:+.1f}%)")
        if c.beta is not None:
            fund_parts.append(f"Beta: {c.beta:.2f}")
        if c.market_cap:
            mc = c.market_cap
            cap_label = (
                "MegaCap" if mc >= 1e11 else
                "LargeCap" if mc >= 1e10 else
                "MidCap" if mc >= 2e9 else
                "SmallCap"
            )
            fund_parts.append(cap_label)
        if fund_parts:
            L.append(f"│ Fundamental: {' | '.join(fund_parts)}")

        # Earnings
        if c.earnings_in_days is not None and c.earnings_in_days >= 0:
            flag = " ⚠️ RIESGO BINARIO" if c.earnings_in_days <= 5 else ""
            L.append(f"│ Earnings próximos: en {c.earnings_in_days}d{flag}")

        # News
        if c.news_titles:
            L.append(f"│ News recientes ({c.news_count_14d} en últimos 14d):")
            for t in c.news_titles[:3]:
                L.append(f"│   - {t}")

        # Ajustes heurísticos
        if c.prob_adjustments:
            L.append(f"│ Heurísticas aplicadas: {' · '.join(c.prob_adjustments[:6])}")

        # Narrativa del bot
        if c.why_up:
            L.append(f"│ Bot favor: {' | '.join(c.why_up[:3])}")
        if c.why_risk:
            L.append(f"│ Bot riesgos: {' | '.join(c.why_risk[:3])}")
        if c.reject_reason and c.decision == "MAYOR_RIESGO":
            L.append(f"│ Motivo degradación: {c.reject_reason}")

        L.append("└" + "─" * 60)
        L.append("")

    L.append("═══ INSTRUCCIONES PARA TU ANÁLISIS ═══")
    L.append("")
    L.append("Para cada candidato, producí el siguiente bloque:")
    L.append("")
    L.append("### [TICKER] — Convicción: [0-100] | Timing: [ENTRAR AHORA / ESPERAR / EVITAR]")
    L.append("**Setup técnico**: ¿Es un setup limpio o forzado? ¿Qué patrón técnico domina?")
    L.append("**Catalizadores**: Drivers específicos para los próximos 5-10 días.")
    L.append("**Tesis bear**: Escenario específico que invalidaría la tesis. Nivel técnico de invalidación.")
    L.append("**Timing de entrada**: ¿Ahora al open, o esperar un nivel? ¿Cuál?")
    L.append("**Vs bot**: ¿Coincidís con la decisión del bot? Si diferís, explicá por qué.")
    L.append("")
    L.append("Al final, una única sección de síntesis:")
    L.append("")
    L.append("## CARTERA HONESTA DEL ANALISTA")
    L.append("- Los 2-3 picks que VOS elegirías, con sizing relativo (% del capital)")
    L.append("- Los que evitarías aunque el bot los marque")
    L.append("- Riesgo de la cartera en el contexto del régimen actual")
    L.append("- Una línea sobre cómo el macro condiciona la convicción")
    L.append("")
    L.append("REGLAS:")
    L.append("- NO repetir los números ya dados. INTERPRETARLOS, agregar valor.")
    L.append("- Sé directo y técnico. Sin frases genéricas ni disclaimers de relleno.")
    L.append("- Si un candidato no tiene setup claro, decirlo sin rodeos.")
    L.append("- Máxima densidad informativa.")

    return "\n".join(L)


# ─────────────────────────────────────────────────────────────────────────────
# Consulta a Gemini (SDK nuevo google-genai + fallback google-generativeai)
# ─────────────────────────────────────────────────────────────────────────────

def consult_gemini(prompt: str, api_key: str, log) -> tuple[str | None, str]:
    """
    Consulta a Gemini 2.5 Pro. Retorna (texto_respuesta, modelo_usado).
    Prueba google-genai (nuevo, thinking mode) → google-generativeai (legacy).
    Retorna (None, '') si todos los intentos fallan.
    """
    # Intento 1: google-genai (SDK nuevo, soporta thinking_config nativo)
    try:
        from google import genai as genai_new  # type: ignore
        from google.genai import types as genai_types  # type: ignore

        client = genai_new.Client(api_key=api_key)
        for model_id in GEMINI_MODELS:
            try:
                log(f"[gemini] {model_id} (SDK nuevo + thinking)…")
                resp = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        thinking_config=genai_types.ThinkingConfig(thinking_budget=8000),
                        max_output_tokens=8192,
                        temperature=1.0,  # Requerido para thinking mode
                    ),
                )
                text = resp.text
                if text:
                    log(f"[gemini] ✓ respuesta de {model_id} ({len(text)} chars)")
                    return text, model_id
            except Exception as exc:
                log(f"[gemini]   {model_id}: {exc}")
                continue
    except ImportError:
        log("[gemini] google-genai no disponible, probando google-generativeai…")

    # Intento 2: google-generativeai (SDK clásico)
    try:
        import google.generativeai as genai_legacy  # type: ignore

        genai_legacy.configure(api_key=api_key)
        for model_id in GEMINI_MODELS:
            try:
                log(f"[gemini] {model_id} (SDK clásico)…")
                model = genai_legacy.GenerativeModel(
                    model_name=model_id,
                    generation_config=genai_legacy.types.GenerationConfig(
                        max_output_tokens=4096,
                        temperature=0.3,
                    ),
                )
                resp = model.generate_content(prompt)
                text = resp.text
                if text:
                    log(f"[gemini] ✓ respuesta de {model_id} ({len(text)} chars)")
                    return text, model_id
            except Exception as exc:
                log(f"[gemini]   {model_id}: {exc}")
                continue
    except ImportError:
        log("[gemini] google-generativeai tampoco disponible")

    log("[gemini] todos los intentos fallaron")
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
