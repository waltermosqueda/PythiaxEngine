#!/usr/bin/env python3
"""
Reporte diario de trading — análisis ejecutivo profundo.
Lee el snapshot del dashboard, analiza con reglas cuantitativas,
detecta señales de convicción y envía el reporte por Telegram.

Uso local (imprime en consola sin enviar):
    py scripts/reporte_diario_trader.py

Uso en CI (requiere TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID):
    python scripts/reporte_diario_trader.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.dashboard_paths import SNAPSHOT_PATH


# ──────────────────────────────────────────────────────────────────────────────
# Helpers de formato
# ──────────────────────────────────────────────────────────────────────────────

def _pct(value: float | None, digits: int = 1, signed: bool = True) -> str:
    if value is None:
        return "—"
    sign = "+" if signed and value >= 0 else ""
    return f"{sign}{value:.{digits}f}%"


def _fmt_date(value: Any) -> str:
    if not value:
        return "—"
    text = str(value)
    try:
        return text[8:10] + "/" + text[5:7]
    except Exception:
        return text


def _tickers_str(tickers: list[str], limit: int = 10) -> str:
    if not tickers:
        return "sin picks"
    preview = ", ".join(tickers[:limit])
    if len(tickers) > limit:
        preview += f" +{len(tickers) - limit}"
    return preview


def _escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _regime_emoji(regime: str) -> str:
    r = regime.upper()
    if "SEGURO" in r or "SAFE" in r or "BULL" in r:
        return "🟢"
    if "PRECAUCION" in r or "WARN" in r or "NEUTRAL" in r:
        return "🟡"
    if "RIESGO" in r or "BEAR" in r or "RISK" in r:
        return "🔴"
    return "⚪"


# ──────────────────────────────────────────────────────────────────────────────
# Carga y extracción del snapshot
# ──────────────────────────────────────────────────────────────────────────────

def _latest_mtm(row: dict[str, Any]) -> float | None:
    for key in ("recent_30", "recent_10"):
        calendar = (row.get(key) or {}).get("calendar") or []
        for entry in reversed(calendar):
            if entry.get("picks", 0) > 0:
                return entry.get("avg_return_pct")
    return None


def _load_snapshot() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        raise FileNotFoundError(f"Snapshot no encontrado: {SNAPSHOT_PATH}")
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _extract_report_data(snapshot: dict[str, Any]) -> dict[str, Any]:
    generated_at: str = snapshot.get("generated_at", "")
    active_run = (snapshot.get("active") or {}).get("active_run") or {}
    regime_label: str = active_run.get("regime_label") or "DESCONOCIDO"
    breadth_pct: float | None = active_run.get("breadth_pct")

    competition_recent = snapshot.get("competition_recent") or {}
    league_rows: list[dict] = list(
        competition_recent.get("dashboard_league_equalized")
        or competition_recent.get("league_equalized")
        or snapshot.get("competition")
        or []
    )

    overlap = snapshot.get("overlap") or {}
    overlap_labels: list[str] = overlap.get("labels") or []
    overlap_matrix: list[list] = overlap.get("matrix") or []

    def _jaccard(a: str, b: str) -> float | None:
        if a not in overlap_labels or b not in overlap_labels:
            return None
        i, j = overlap_labels.index(a), overlap_labels.index(b)
        try:
            return overlap_matrix[i][j]
        except (IndexError, TypeError):
            return None

    models_with_picks: list[dict] = []
    for row in league_rows:
        tickers = row.get("latest_tickers") or []
        if not tickers:
            continue
        eq = row.get("equalized_recent") or {}
        models_with_picks.append({
            "version": str(row.get("version") or ""),
            "role": str(row.get("role") or ""),
            "wr": eq.get("accuracy_pct"),
            "avg_ret": eq.get("avg_return_pct"),
            "mtm": _latest_mtm(row),
            "tickers": list(tickers),
            "target": row.get("latest_target_date"),
            "stale": row.get("stale_market_days"),
            "rank": row.get("rank"),
        })

    # Convergencias ortogonales (Jaccard < 0.10)
    ticker_to_models: dict[str, list[str]] = {}
    for m in models_with_picks:
        for t in m["tickers"]:
            ticker_to_models.setdefault(t, []).append(m["version"])

    convergences: list[dict] = []
    for ticker, versions in ticker_to_models.items():
        if len(versions) < 2:
            continue
        best_j: float | None = None
        best_pair: tuple | None = None
        for i in range(len(versions)):
            for j in range(i + 1, len(versions)):
                jv = _jaccard(versions[i], versions[j])
                if jv is not None and (best_j is None or jv < best_j):
                    best_j, best_pair = jv, (versions[i], versions[j])
        if best_j is not None and best_j < 0.10:
            convergences.append({"ticker": ticker, "models": versions, "jaccard": best_j, "pair": best_pair})

    # Multi-modelo simple (mismo ticker en ≥2 modelos, sin filtro Jaccard)
    multi_model: list[dict] = []
    for ticker, versions in ticker_to_models.items():
        if len(versions) >= 2:
            wr_sum = sum((m["wr"] or 0) for m in models_with_picks if m["version"] in versions)
            multi_model.append({"ticker": ticker, "models": versions, "wr_sum": wr_sum})
    multi_model.sort(key=lambda x: (-len(x["models"]), -x["wr_sum"]))

    convergences.sort(key=lambda x: x["jaccard"])

    return {
        "generated_at": generated_at,
        "regime": regime_label,
        "breadth_pct": breadth_pct,
        "models": models_with_picks,
        "convergences": convergences,
        "multi_model": multi_model,
        "all_active_tickers": sorted({t for m in models_with_picks for t in m["tickers"]}),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Análisis cuantitativo
# ──────────────────────────────────────────────────────────────────────────────

def _conviction_map(models: list[dict]) -> dict[str, dict]:
    """Score de convicción por ticker = suma de WR de cada modelo que lo tiene."""
    result: dict[str, dict] = {}
    for m in models:
        wr = m["wr"] or 0.0
        for t in m["tickers"]:
            if t not in result:
                result[t] = {"score": 0.0, "models": [], "mtm_vals": []}
            result[t]["score"] += wr / 100.0
            result[t]["models"].append(m["version"])
            if m["mtm"] is not None:
                result[t]["mtm_vals"].append(m["mtm"])
    for t, d in result.items():
        d["avg_mtm"] = sum(d["mtm_vals"]) / len(d["mtm_vals"]) if d["mtm_vals"] else None
    return result


def _expiring_models(models: list[dict], today_str: str, days_ahead: int = 1) -> list[dict]:
    cutoff = (date.fromisoformat(today_str) + timedelta(days=days_ahead)).isoformat()
    return [m for m in models if m.get("target") and str(m["target"]) <= cutoff]


def _portfolio_summary(models: list[dict]) -> dict:
    mtm_vals = [m["mtm"] for m in models if m["mtm"] is not None]
    wr_vals = [m["wr"] for m in models if m["wr"] is not None]
    pos = sum(1 for v in mtm_vals if v > 0)
    neg = sum(1 for v in mtm_vals if v < 0)
    total_wr = sum(m["wr"] or 0 for m in models if m["mtm"] is not None) or 1
    weighted_mtm = sum(m["mtm"] * (m["wr"] or 0) for m in models if m["mtm"] is not None) / total_wr
    return {
        "positive": pos,
        "negative": neg,
        "total_mtm": len(mtm_vals),
        "weighted_mtm": weighted_mtm,
        "avg_wr": sum(wr_vals) / len(wr_vals) if wr_vals else None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Precios via yfinance
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_prices(tickers: list[str]) -> dict[str, dict]:
    if not tickers:
        return {}
    try:
        import yfinance as yf  # noqa: PLC0415
        result: dict[str, dict] = {}
        data = yf.download(tickers, period="2d", interval="1d", progress=False, auto_adjust=True)
        if data.empty:
            return {}
        close = data["Close"] if "Close" in data.columns else data.get("close")
        if close is None:
            return {}
        for ticker in tickers:
            try:
                series = (close if len(tickers) == 1 else close[ticker]).dropna()
                if len(series) < 1:
                    continue
                price = float(series.iloc[-1])
                prev = float(series.iloc[-2]) if len(series) >= 2 else None
                chg = ((price - prev) / prev * 100.0) if prev and prev != 0 else None
                result[ticker] = {"price": price, "prev_close": prev, "change_pct": chg}
            except Exception:
                continue
        return result
    except Exception as exc:
        print(f"[reporte_diario] WARN yfinance: {exc}", file=sys.stderr)
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# Construcción del mensaje de análisis profundo
# ──────────────────────────────────────────────────────────────────────────────

def _build_message(data: dict, prices: dict) -> str:
    today = date.today().isoformat()
    gen = data["generated_at"][:10] if data["generated_at"] else "—"
    regime = data["regime"]
    breadth = data["breadth_pct"]
    models = data["models"]
    convergences = data["convergences"]
    multi_model = data["multi_model"]

    conviction = _conviction_map(models)
    summary = _portfolio_summary(models)
    expiring = _expiring_models(models, today, days_ahead=1)
    models_with_mtm = [m for m in models if m["mtm"] is not None]
    best_mtm = max(models_with_mtm, key=lambda m: m["mtm"]) if models_with_mtm else None
    worst_mtm = min(models_with_mtm, key=lambda m: m["mtm"]) if models_with_mtm else None
    best_wr = models[0] if models else None

    big_movers = sorted(
        [(t, p) for t, p in prices.items() if p.get("change_pct") is not None and abs(p["change_pct"]) >= 4.0],
        key=lambda x: -abs(x[1]["change_pct"]),
    )

    top_conviction = sorted(conviction.items(), key=lambda x: -x[1]["score"])

    lines: list[str] = []

    # ── 1. ENCABEZADO ────────────────────────────────────────────────────────
    re_icon = _regime_emoji(regime)
    breadth_str = f"{breadth:.1f}%" if breadth is not None else "—"
    lines.append(f"🧠 <b>PythiaxEngine · Análisis {gen}</b>")
    lines.append(f"{re_icon} <b>{_escape(regime)}</b> · Breadth {breadth_str} · {len(models)} modelos activos")
    lines.append("")

    # ── 2. CONTEXTO DE MERCADO ───────────────────────────────────────────────
    if breadth is not None:
        if breadth >= 60:
            ctx = "Mercado en expansión amplia. Condición favorable para posiciones largas."
        elif breadth >= 45:
            ctx = "Mercado neutral. Selectividad elevada — solo señales de alta convicción."
        else:
            ctx = "Mercado estrecho. Cautela: reducir exposición y priorizar stops."
        lines.append(f"<i>{_escape(ctx)}</i>")

    wmtm_str = _pct(summary["weighted_mtm"])
    lines.append(
        f"<i>Portfolio MTM ponderado por WR: <b>{wmtm_str}</b> · "
        f"{summary['positive']}✅ {summary['negative']}🔴 de {summary['total_mtm']} modelos</i>"
    )
    lines.append("")

    # ── 3. SEÑALES TOP (mayor convicción) ────────────────────────────────────
    # Primero convergencias ortogonales (Jaccard), luego multi-modelo simple
    shown_tickers: set[str] = set()

    if convergences:
        lines.append("⚡ <b>CONVERGENCIAS ORTOGONALES</b> <i>(señal independiente verificada)</i>")
        for c in convergences[:3]:
            t = c["ticker"]
            shown_tickers.add(t)
            p = prices.get(t)
            price_str = f" ${p['price']:.2f} ({_pct(p['change_pct'])})" if p and p.get("change_pct") is not None else (f" ${p['price']:.2f}" if p else "")
            models_str = " + ".join(c["models"])
            conv_d = conviction.get(t, {})
            avg_mtm_str = _pct(conv_d.get("avg_mtm")) if conv_d.get("avg_mtm") is not None else "—"
            lines.append(f"  🎯 <b>{_escape(t)}</b>{_escape(price_str)}")
            lines.append(f"     {_escape(models_str)} · Jaccard {c['jaccard']:.3f} · MTM prom {avg_mtm_str}")
        lines.append("")

    # Multi-modelo (mismo ticker en ≥2 modelos, aunque sean correlacionados)
    mm_new = [m for m in multi_model if m["ticker"] not in shown_tickers]
    if mm_new:
        lines.append("🔗 <b>SEÑALES MULTI-MODELO</b>")
        for item in mm_new[:4]:
            t = item["ticker"]
            shown_tickers.add(t)
            p = prices.get(t)
            price_str = f" ${p['price']:.2f} ({_pct(p['change_pct'])})" if p and p.get("change_pct") is not None else (f" ${p['price']:.2f}" if p else "")
            conv_d = conviction.get(t, {})
            avg_mtm_str = _pct(conv_d.get("avg_mtm")) if conv_d.get("avg_mtm") is not None else "—"
            models_str = " + ".join(item["models"])
            lines.append(f"  📌 <b>{_escape(t)}</b>{_escape(price_str)} — {_escape(models_str)} · MTM {avg_mtm_str}")
        lines.append("")

    # ── 4. ANÁLISIS POR MODELO (todos, ordenados por WR) ────────────────────
    lines.append("━━━ <b>MODELOS — ANÁLISIS DETALLADO</b> ━━━")
    for m in models:
        wr_str = _pct(m["wr"], 1, signed=False)
        mtm = m["mtm"]
        mtm_str = _pct(mtm)
        mtm_icon = "🟢" if mtm is not None and mtm >= 0 else "🔴"
        tgt = _fmt_date(m["target"])
        freshness = "✅" if m["stale"] == 0 else (f"⚠️ {m['stale']}d" if m["stale"] is not None else "❓")
        tickers_with_prices = []
        for t in m["tickers"]:
            p = prices.get(t)
            if p:
                chg_str = f" ({_pct(p['change_pct'])})" if p.get("change_pct") is not None else ""
                tickers_with_prices.append(f"{t} ${p['price']:.2f}{chg_str}")
            else:
                tickers_with_prices.append(t)

        lines.append(
            f"\n{freshness} <b>{_escape(m['version'])}</b> · WR {wr_str} · {mtm_icon} MTM {mtm_str} · → {_escape(tgt)}"
        )
        # Picks con precios
        picks_str = " · ".join(tickers_with_prices)
        lines.append(f"   <code>{_escape(picks_str)}</code>")

        # Notas contextuales
        notes: list[str] = []
        if m == best_wr:
            notes.append("⭐ mayor WR del día")
        if m == best_mtm:
            notes.append(f"🏆 mejor MTM ({mtm_str})")
        if m == worst_mtm and mtm is not None and mtm < -1.5:
            notes.append(f"⚠️ mayor drawdown ({mtm_str})")
        if m in expiring:
            notes.append(f"⏰ <b>VENCE {_escape(tgt)}</b>")
        if notes:
            lines.append(f"   <i>{' · '.join(notes)}</i>")

    lines.append("")

    # ── 5. MOVIMIENTOS DESTACADOS ─────────────────────────────────────────────
    if big_movers:
        lines.append("📈 <b>MOVIMIENTOS DESTACADOS HOY (&gt;4%)</b>")
        for t, p in big_movers[:5]:
            holding = [m["version"] for m in models if t in m["tickers"]]
            model_tag = f"← {', '.join(holding)}" if holding else ""
            chg_icon = "🚀" if p["change_pct"] >= 8 else ("📈" if p["change_pct"] > 0 else "📉")
            lines.append(
                f"  {chg_icon} <b>{_escape(t)}</b> {_pct(p['change_pct'])} "
                f"${p['price']:.2f}  <i>{_escape(model_tag)}</i>"
            )
        lines.append("")

    # ── 6. ALERTAS ────────────────────────────────────────────────────────────
    alerts: list[str] = []
    if expiring:
        for m in expiring:
            alerts.append(f"⏰ <b>{_escape(m['version'])}</b>: picks vencen {_escape(_fmt_date(m['target']))} — evaluar salida · MTM {_pct(m['mtm'])}")
    stale_models = [m for m in models if m["stale"] is not None and m["stale"] >= 3]
    for m in stale_models:
        alerts.append(f"⚠️ <b>{_escape(m['version'])}</b>: sin actualización hace {m['stale']} ruedas")
    if worst_mtm and worst_mtm["mtm"] is not None and worst_mtm["mtm"] < -2.0:
        alerts.append(f"🔴 <b>{_escape(worst_mtm['version'])}</b>: drawdown {_pct(worst_mtm['mtm'])} · {_escape(_tickers_str(worst_mtm['tickers'], 5))}")

    if alerts:
        lines.append("⚠️ <b>ALERTAS</b>")
        for a in alerts[:4]:
            lines.append(f"  {a}")
        lines.append("")

    # ── 7. TOP CONVICCIÓN GLOBAL ──────────────────────────────────────────────
    top3 = [(t, d) for t, d in top_conviction[:3] if d["score"] >= 0.4]
    if top3:
        lines.append("🏅 <b>TOP CONVICCIÓN GLOBAL</b>")
        for t, d in top3:
            p = prices.get(t)
            price_str = f" ${p['price']:.2f}" if p else ""
            lines.append(
                f"  {_escape(t)}{_escape(price_str)} · conv {d['score']:.2f} · "
                f"{_escape(', '.join(d['models']))} · MTM {_pct(d.get('avg_mtm'))}"
            )
        lines.append("")

    # ── 8. PIE ────────────────────────────────────────────────────────────────
    total = len(data["all_active_tickers"])
    lines.append(
        f"<i>📦 {total} tickers · {len(models)} modelos · snapshot {gen}</i>"
    )

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Envío por Telegram (con soporte de mensajes largos)
# ──────────────────────────────────────────────────────────────────────────────

_TG_LIMIT = 4000  # margen bajo el límite de 4096


def _split_message(text: str) -> list[str]:
    """Divide el texto en partes de máx _TG_LIMIT chars, cortando en saltos de línea."""
    if len(text) <= _TG_LIMIT:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = current + ("\n" if current else "") + line
        if len(candidate) > _TG_LIMIT:
            if current:
                parts.append(current)
            current = line
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _send_telegram(text: str, token: str, chat_id: str) -> bool:
    import urllib.request  # noqa: PLC0415
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i, part in enumerate(_split_message(text)):
        payload = json.dumps({
            "chat_id": chat_id,
            "text": part,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if not body.get("ok"):
                    print(f"[reporte_diario] ERROR parte {i+1}: {body.get('description')}", file=sys.stderr)
                    return False
        except Exception as exc:
            print(f"[reporte_diario] ERROR al enviar parte {i+1}: {exc}", file=sys.stderr)
            return False
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        snapshot = _load_snapshot()
    except FileNotFoundError as exc:
        print(f"[reporte_diario] SKIP: {exc}", file=sys.stderr)
        return 0

    data = _extract_report_data(snapshot)
    prices = _fetch_prices(data["all_active_tickers"][:25])
    message = _build_message(data, prices)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if token and chat_id:
        print("[reporte_diario] Enviando análisis por Telegram...", flush=True)
        ok = _send_telegram(message, token, chat_id)
        if ok:
            print("[reporte_diario] ✓ Enviado.", flush=True)
            return 0
        print("[reporte_diario] ✗ Envío fallido.", file=sys.stderr)
        return 1
    else:
        print("[reporte_diario] Sin token — imprimiendo en consola:")
        print("=" * 70)
        print(re.sub(r"<[^>]+>", "", message))
        print("=" * 70)
        return 0


if __name__ == "__main__":
    sys.exit(main())
