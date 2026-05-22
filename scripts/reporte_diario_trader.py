#!/usr/bin/env python3
"""
Reporte diario de trading para el trader.
Lee el snapshot del dashboard, detecta convergencias entre modelos,
consulta precios actuales via yfinance y envia el reporte por Telegram.

Uso local (solo imprime, sin enviar):
    py scripts/reporte_diario_trader.py

Uso en CI (necesita TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID como env vars / secrets):
    python scripts/reporte_diario_trader.py
"""

from __future__ import annotations

import json
import os
import sys
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
    # Acortar "2026-05-22 -> 2026-05-28" a "22->28/05"
    if " -> " in text:
        parts = text.split(" -> ")
        try:
            d1 = parts[0][8:10] + "/" + parts[0][5:7]
            d2 = parts[1][8:10] + "/" + parts[1][5:7]
            return f"{d1}→{d2}"
        except Exception:
            return text
    try:
        return text[8:10] + "/" + text[5:7]
    except Exception:
        return text


def _tickers_str(tickers: list[str], limit: int = 6) -> str:
    if not tickers:
        return "sin picks"
    preview = ", ".join(tickers[:limit])
    if len(tickers) > limit:
        preview += f" +{len(tickers) - limit}"
    return preview


# ──────────────────────────────────────────────────────────────────────────────
# Extraccion de datos del snapshot
# ──────────────────────────────────────────────────────────────────────────────

def _latest_mtm(row: dict[str, Any]) -> float | None:
    """Retorna el MTM provisional mas reciente de recent_30.calendar."""
    recent_30 = row.get("recent_30") or {}
    calendar = recent_30.get("calendar") or []
    for entry in reversed(calendar):
        if entry.get("picks", 0) > 0:
            return entry.get("avg_return_pct")
    return None


def _load_snapshot() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        raise FileNotFoundError(
            f"Snapshot no encontrado: {SNAPSHOT_PATH}\n"
            "Asegurate de correr generar_tablero_maquina_pensante.py antes."
        )
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _extract_report_data(snapshot: dict[str, Any]) -> dict[str, Any]:
    generated_at: str = snapshot.get("generated_at", "")
    active_run: dict[str, Any] = (snapshot.get("active") or {}).get("active_run") or {}
    regime_label: str = active_run.get("regime_label") or "DESCONOCIDO"
    breadth_pct: float | None = active_run.get("breadth_pct")

    # Rows del dashboard (equalized, por WR)
    competition_recent = snapshot.get("competition_recent") or {}
    league_rows: list[dict[str, Any]] = list(
        competition_recent.get("dashboard_league_equalized")
        or competition_recent.get("league_equalized")
        or snapshot.get("competition")
        or []
    )

    # Overlap matrix para calcular Jaccard entre pares de modelos
    overlap = snapshot.get("overlap") or {}
    overlap_labels: list[str] = overlap.get("labels") or []
    overlap_matrix: list[list[float | None]] = overlap.get("matrix") or []

    def _jaccard(a: str, b: str) -> float | None:
        if a not in overlap_labels or b not in overlap_labels:
            return None
        i = overlap_labels.index(a)
        j = overlap_labels.index(b)
        try:
            return overlap_matrix[i][j]
        except (IndexError, TypeError):
            return None

    # Modelos activos con picks
    models_with_picks: list[dict[str, Any]] = []
    for row in league_rows:
        tickers = row.get("latest_tickers") or []
        if not tickers:
            continue
        eq = row.get("equalized_recent") or row.get("window") or {}
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

    # Convergencias: tickers en ≥2 modelos con Jaccard < 0.10 entre al menos un par
    ticker_to_models: dict[str, list[str]] = {}
    for m in models_with_picks:
        for t in m["tickers"]:
            ticker_to_models.setdefault(t, []).append(m["version"])

    convergences: list[dict[str, Any]] = []
    for ticker, versions in ticker_to_models.items():
        if len(versions) < 2:
            continue
        best_jaccard: float | None = None
        best_pair: tuple[str, str] | None = None
        for i in range(len(versions)):
            for j in range(i + 1, len(versions)):
                j_val = _jaccard(versions[i], versions[j])
                if j_val is not None and (best_jaccard is None or j_val < best_jaccard):
                    best_jaccard = j_val
                    best_pair = (versions[i], versions[j])
        if best_jaccard is not None and best_jaccard < 0.10:
            convergences.append({
                "ticker": ticker,
                "models": versions,
                "jaccard": best_jaccard,
                "pair": best_pair,
            })

    convergences.sort(key=lambda x: x["jaccard"])

    # Todos los tickers activos unicos
    all_active_tickers: list[str] = sorted(
        {t for m in models_with_picks for t in m["tickers"]}
    )

    return {
        "generated_at": generated_at,
        "regime": regime_label,
        "breadth_pct": breadth_pct,
        "models": models_with_picks,
        "convergences": convergences,
        "all_active_tickers": all_active_tickers,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Precios via yfinance
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_prices(tickers: list[str]) -> dict[str, dict[str, Any]]:
    """Retorna {ticker: {price, change_pct, prev_close}} para la lista dada."""
    if not tickers:
        return {}
    try:
        import yfinance as yf  # noqa: PLC0415

        result: dict[str, dict[str, Any]] = {}
        data = yf.download(
            tickers,
            period="2d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if data.empty:
            return {}

        # yfinance devuelve MultiIndex cuando son varios tickers
        close = data["Close"] if "Close" in data.columns else data.get("close")
        if close is None:
            return {}

        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    series = close
                else:
                    series = close[ticker]
                series = series.dropna()
                if len(series) < 1:
                    continue
                price = float(series.iloc[-1])
                prev = float(series.iloc[-2]) if len(series) >= 2 else None
                change_pct = ((price - prev) / prev * 100.0) if prev and prev != 0 else None
                result[ticker] = {
                    "price": price,
                    "prev_close": prev,
                    "change_pct": change_pct,
                }
            except Exception:
                continue

        return result
    except Exception as exc:
        print(f"[reporte_diario] WARN: yfinance fallo: {exc}", file=sys.stderr)
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# Formateo del mensaje Telegram (HTML)
# ──────────────────────────────────────────────────────────────────────────────

def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _regime_emoji(regime: str) -> str:
    r = regime.upper()
    if "SEGURO" in r or "SAFE" in r or "BULL" in r:
        return "🟢"
    if "PRECAUCION" in r or "WARN" in r or "NEUTRAL" in r:
        return "🟡"
    if "RIESGO" in r or "BEAR" in r or "RISK" in r:
        return "🔴"
    return "⚪"


def _build_message(
    data: dict[str, Any],
    prices: dict[str, dict[str, Any]],
) -> str:
    lines: list[str] = []

    # ── Encabezado ──────────────────────────────────────────────────────────
    gen = data["generated_at"][:16].replace("T", " ") if data["generated_at"] else "—"
    regime = data["regime"]
    breadth = data["breadth_pct"]
    breadth_str = f"{breadth:.1f}%" if breadth is not None else "—"
    regime_icon = _regime_emoji(regime)

    lines.append("🧠 <b>PythiaxEngine · Reporte Diario</b>")
    lines.append(f"📅 {_escape(gen)} UTC")
    lines.append(
        f"{regime_icon} Régimen: <b>{_escape(regime)}</b>  |  "
        f"Breadth: <b>{breadth_str}</b>"
    )
    lines.append("")

    # ── Modelos activos ──────────────────────────────────────────────────────
    models = data["models"]
    if models:
        lines.append(f"<b>📊 Modelos con picks activos ({len(models)})</b>")
        for m in models:
            wr_str = _pct(m["wr"], 1, signed=False)
            mtm_str = _pct(m["mtm"]) if m["mtm"] is not None else "—"
            target_str = _fmt_date(m["target"])
            tickers_str = _tickers_str(m["tickers"])
            mtm_marker = ""
            if m["mtm"] is not None:
                mtm_marker = "🟢 " if m["mtm"] >= 0 else "🔴 "
            lines.append(
                f"  • <b>{_escape(m['version'])}</b>  "
                f"WR {wr_str}  |  {mtm_marker}MTM {mtm_str}"
            )
            lines.append(f"    📌 {_escape(tickers_str)}  →  {_escape(target_str)}")
        lines.append("")
    else:
        lines.append("⚠️ <i>Ningún modelo tiene picks activos hoy.</i>")
        lines.append("")

    # ── Convergencias ────────────────────────────────────────────────────────
    convergences = data["convergences"]
    if convergences:
        lines.append(
            f"<b>⚡ Convergencias detectadas ({len(convergences)}) "
            f"— Jaccard &lt; 0.10</b>"
        )
        for c in convergences[:5]:  # max 5 para no llenar el mensaje
            ticker = c["ticker"]
            pair = c["pair"]
            jaccard = c["jaccard"]
            price_info = prices.get(ticker)
            price_str = ""
            if price_info:
                p = price_info["price"]
                chg = price_info.get("change_pct")
                chg_str = f" ({_pct(chg)})" if chg is not None else ""
                price_str = f"  💵 ${p:.2f}{chg_str}"
            models_str = ", ".join(c["models"])
            pair_str = (
                f"{_escape(pair[0])} + {_escape(pair[1])}"
                if pair
                else _escape(models_str)
            )
            lines.append(
                f"  🎯 <b>{_escape(ticker)}</b>{price_str}"
            )
            lines.append(
                f"     {pair_str}  |  Jaccard: {jaccard:.3f}"
            )
        lines.append("")
    else:
        lines.append("ℹ️ <i>Sin convergencias ortogonales hoy.</i>")
        lines.append("")

    # ── Resumen de precios para tickers convergentes ─────────────────────────
    convergent_tickers = [c["ticker"] for c in convergences[:5]]
    non_convergent_tickers = [
        t for t in data["all_active_tickers"] if t not in convergent_tickers
    ][:8]

    if non_convergent_tickers:
        lines.append("<b>📈 Otros picks activos (precio actual)</b>")
        for ticker in non_convergent_tickers:
            price_info = prices.get(ticker)
            if price_info:
                p = price_info["price"]
                chg = price_info.get("change_pct")
                chg_str = f" ({_pct(chg)})" if chg is not None else ""
                lines.append(f"  {_escape(ticker)} ${p:.2f}{chg_str}")
        lines.append("")

    # ── Totales ──────────────────────────────────────────────────────────────
    total_tickers = len(data["all_active_tickers"])
    total_models = len(models)
    lines.append(
        f"<i>📦 {total_tickers} tickers activos en {total_models} modelos  |  "
        f"gen. {_escape(gen)} UTC</i>"
    )

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Envio por Telegram
# ──────────────────────────────────────────────────────────────────────────────

def _send_telegram(text: str, token: str, chat_id: str) -> bool:
    """Envia el mensaje via Telegram Bot API. Retorna True si OK."""
    import urllib.request  # stdlib, sin dependencias externas  # noqa: PLC0415

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("ok"):
                return True
            print(
                f"[reporte_diario] ERROR Telegram: {body.get('description')}",
                file=sys.stderr,
            )
            return False
    except Exception as exc:
        print(f"[reporte_diario] ERROR al enviar Telegram: {exc}", file=sys.stderr)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    # 1. Cargar snapshot
    try:
        snapshot = _load_snapshot()
    except FileNotFoundError as exc:
        print(f"[reporte_diario] SKIP: {exc}", file=sys.stderr)
        return 0  # No es error critico — pipeline no debe fallar por esto

    # 2. Extraer datos del reporte
    data = _extract_report_data(snapshot)

    # 3. Obtener precios actuales para tickers activos (max 20 para no saturar)
    tickers_to_fetch = data["all_active_tickers"][:20]
    prices = _fetch_prices(tickers_to_fetch) if tickers_to_fetch else {}

    # 4. Construir mensaje
    message = _build_message(data, prices)

    # 5. Enviar o imprimir
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if token and chat_id:
        print("[reporte_diario] Enviando reporte por Telegram...", flush=True)
        ok = _send_telegram(message, token, chat_id)
        if ok:
            print("[reporte_diario] ✓ Reporte enviado.", flush=True)
            return 0
        else:
            print("[reporte_diario] ✗ Envio fallido.", file=sys.stderr)
            return 1
    else:
        # Modo local: solo imprimir (util para testing)
        print("[reporte_diario] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID no configurados.")
        print("=" * 70)
        # Strip HTML tags para lectura en consola
        import re  # noqa: PLC0415
        plain = re.sub(r"<[^>]+>", "", message)
        print(plain)
        print("=" * 70)
        return 0


if __name__ == "__main__":
    sys.exit(main())
