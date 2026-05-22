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


def _compute_technicals(h: "pd.DataFrame") -> dict:
    """Calcula indicadores técnicos sobre un DataFrame OHLCV diario (1y)."""
    import numpy as np  # noqa: PLC0415

    def _rsi(s, n=14):
        delta = s.diff()
        up = delta.clip(lower=0)
        dn = (-delta).clip(lower=0)
        rs = up.ewm(com=n - 1, adjust=False).mean() / dn.ewm(com=n - 1, adjust=False).mean()
        return 100 - (100 / (1 + rs))

    h = h.copy()
    h["RSI"] = _rsi(h["Close"])
    h["EMA20"] = h["Close"].ewm(span=20).mean()
    h["EMA50"] = h["Close"].ewm(span=50).mean()
    h["EMA200"] = h["Close"].ewm(span=200).mean()
    macd_fast = h["Close"].ewm(span=12).mean()
    macd_slow = h["Close"].ewm(span=26).mean()
    h["MACD"] = macd_fast - macd_slow
    h["MACD_sig"] = h["MACD"].ewm(span=9).mean()
    h["MACD_hist"] = h["MACD"] - h["MACD_sig"]
    h["BB_mid"] = h["Close"].rolling(20).mean()
    h["BB_std"] = h["Close"].rolling(20).std()
    h["BB_upper"] = h["BB_mid"] + 2 * h["BB_std"]
    h["BB_lower"] = h["BB_mid"] - 2 * h["BB_std"]
    h["BB_pct"] = (h["Close"] - h["BB_lower"]) / (h["BB_upper"] - h["BB_lower"])
    hl = h["High"] - h["Low"]
    hpc = (h["High"] - h["Close"].shift()).abs()
    lpc = (h["Low"] - h["Close"].shift()).abs()
    tr = hl.combine(hpc, max).combine(lpc, max)
    h["ATR14"] = tr.ewm(span=14).mean()
    h["Vol_MA20"] = h["Volume"].rolling(20).mean()
    h["OBV"] = (np.sign(h["Close"].diff()) * h["Volume"]).fillna(0).cumsum()
    low14 = h["Low"].rolling(14).min()
    high14 = h["High"].rolling(14).max()
    h["Stoch_K"] = 100 * (h["Close"] - low14) / (high14 - low14)

    last = h.iloc[-1]
    prev = h.iloc[-2] if len(h) >= 2 else last
    high52 = h["High"].tail(252).max()
    low52 = h["Low"].tail(252).min()
    obv_slope = float(h["OBV"].tail(20).iloc[-1] - h["OBV"].tail(20).iloc[0])

    # Señal de tendencia EMA
    if last["EMA20"] > last["EMA50"] > last["EMA200"]:
        ema_signal = "Golden Cross ✅"
    elif last["EMA20"] < last["EMA50"] < last["EMA200"]:
        ema_signal = "Death Stack 🔴"
    else:
        ema_signal = "Mixtas ⚠️"

    return {
        "price": float(last["Close"]),
        "change_pct": float((last["Close"] - prev["Close"]) / prev["Close"] * 100),
        "rsi": float(last["RSI"]),
        "stoch_k": float(last["Stoch_K"]),
        "ema20": float(last["EMA20"]),
        "ema50": float(last["EMA50"]),
        "ema200": float(last["EMA200"]),
        "ema_signal": ema_signal,
        "macd_hist": float(last["MACD_hist"]),
        "bb_pct": float(last["BB_pct"]) if last["BB_pct"] == last["BB_pct"] else 0.5,
        "atr_pct": float(last["ATR14"] / last["Close"] * 100),
        "vol_ratio": float(last["Volume"] / last["Vol_MA20"]) if last["Vol_MA20"] > 0 else 1.0,
        "obv_slope": obv_slope,        "high52": float(high52),
        "low52": float(low52),
        "vs_high52": float((last["Close"] - high52) / high52 * 100),
        "vs_low52": float((last["Close"] - low52) / low52 * 100),
    }


def _fetch_deep_analysis(tickers: list[str], max_n: int = 5) -> dict[str, dict]:
    """
    Para los top N tickers: descarga 1y historia + info fundamental vía yfinance.
    Retorna dict ticker -> {tech: {...}, fund: {...}}.
    """
    if not tickers:
        return {}
    try:
        import yfinance as yf  # noqa: PLC0415
        import pandas as pd    # noqa: PLC0415

        result: dict[str, dict] = {}
        targets = tickers[:max_n]

        for tkr in targets:
            try:
                t = yf.Ticker(tkr)
                h = t.history(period="1y", interval="1d", auto_adjust=True)
                if h is None or len(h) < 30:
                    continue
                tech = _compute_technicals(h)

                info = t.info or {}
                fund: dict = {}
                for k, label in [
                    ("forwardPE",   "pe_fwd"),
                    ("trailingPE",  "pe_trail"),
                    ("pegRatio",    "peg"),
                    ("freeCashflow","fcf"),
                    ("revenueGrowth","rev_growth"),
                    ("earningsGrowth","earn_growth"),
                    ("grossMargins","gm"),
                    ("returnOnEquity","roe"),
                    ("debtToEquity","de"),
                    ("beta",        "beta"),
                    ("shortRatio",  "short_ratio"),
                    ("marketCap",   "mktcap"),
                ]:
                    v = info.get(k)
                    if v is not None:
                        fund[label] = v

                # Próximo earnings
                try:
                    cal = t.calendar
                    if cal and "Earnings Date" in cal:
                        earn_dates = cal["Earnings Date"]
                        if isinstance(earn_dates, list) and earn_dates:
                            fund["next_earnings"] = str(earn_dates[0])
                except Exception:
                    pass

                result[tkr] = {"tech": tech, "fund": fund}
            except Exception as exc:
                print(f"[reporte_diario] WARN deep {tkr}: {exc}", file=sys.stderr)
                continue

        return result
    except Exception as exc:
        print(f"[reporte_diario] WARN deep analysis: {exc}", file=sys.stderr)
        return {}


def _tech_verdict(tech: dict, fund: dict) -> str:
    """Genera un veredicto conciso de 1 línea combinando técnico + fundamental."""
    bullets: list[str] = []

    # Técnico
    rsi = tech.get("rsi", 50)
    macd_hist = tech.get("macd_hist", 0)
    ema_sig = tech.get("ema_signal", "")
    obv = tech.get("obv_slope", 0)
    bb_pct = tech.get("bb_pct", 0.5)
    vs_high = tech.get("vs_high52", 0)

    if "Golden" in ema_sig:
        bullets.append("tendencia alcista")
    elif "Death" in ema_sig:
        bullets.append("tendencia bajista")

    if rsi > 70:
        bullets.append("RSI sobrecomprado")
    elif rsi < 35:
        bullets.append("RSI sobrevendido — posible rebote")
    elif rsi > 55:
        bullets.append("momentum positivo")

    if macd_hist > 0:
        bullets.append("MACD acelerando")
    else:
        bullets.append("MACD desacelerando")

    if bb_pct > 1.0:
        bullets.append("Bollinger sobrecomprado")
    elif bb_pct < 0.0:
        bullets.append("Bollinger sobrevendido — posible piso")

    if obv > 0:
        bullets.append("acumulación institucional")
    else:
        bullets.append("distribución")

    # Fundamental
    peg = fund.get("peg")
    pe_fwd = fund.get("pe_fwd")
    fcf = fund.get("fcf")
    earn_gr = fund.get("earn_growth")

    if peg is not None and peg < 1.0:
        bullets.append(f"PEG {peg:.2f} infravalorado")
    elif peg is not None and peg > 2.5:
        bullets.append(f"PEG {peg:.1f} caro")

    if fcf is not None and fcf > 2e9:
        bullets.append(f"FCF solido")

    return " · ".join(bullets[:4]) if bullets else "señal mixta"


def _build_tech_section(deep_data: dict, prices: dict) -> str:
    """Construye la sección de análisis técnico+fundamental para Telegram."""
    if not deep_data:
        return ""

    lines: list[str] = ["", "🔬 <b>ANÁLISIS TÉCNICO — TOP POSICIONES</b>"]

    for tkr, d in deep_data.items():
        tech = d.get("tech", {})
        fund = d.get("fund", {})

        price = tech.get("price", 0)
        chg = tech.get("change_pct", 0)
        rsi = tech.get("rsi", 0)
        ema_sig = tech.get("ema_signal", "—")
        macd_h = tech.get("macd_hist", 0)
        bb_pct = tech.get("bb_pct", 0.5)
        atr_pct = tech.get("atr_pct", 0)
        vol_r = tech.get("vol_ratio", 1)
        obv = tech.get("obv_slope", 0)
        vs_high = tech.get("vs_high52", 0)
        ema20 = tech.get("ema20", 0)
        ema200 = tech.get("ema200", 0)

        chg_sign = "+" if chg >= 0 else ""
        macd_icon = "↑" if macd_h > 0 else "↓"
        obv_tag = "Acumulación ↑" if obv > 0 else "Distribución ↓"
        vol_tag = f"{vol_r:.1f}x vol" if vol_r > 1.3 else ("vol normal" if vol_r > 0.7 else "vol bajo")

        # Fundamentales
        pe_fwd = fund.get("pe_fwd")
        peg = fund.get("peg")
        fcf = fund.get("fcf")
        rev_gr = fund.get("rev_growth")
        earn_gr = fund.get("earn_growth")
        beta = fund.get("beta")
        next_earn = fund.get("next_earnings", "")

        fund_parts: list[str] = []
        if pe_fwd:
            fund_parts.append(f"P/E fwd {pe_fwd:.1f}x")
        if peg is not None:
            peg_icon = "✅" if peg < 1.0 else ("⚠️" if peg > 2.5 else "")
            fund_parts.append(f"PEG {peg:.2f}{peg_icon}")
        if fcf is not None:
            fund_parts.append(f"FCF ${fcf/1e9:.1f}B")
        if rev_gr is not None:
            fund_parts.append(f"Rev {'+' if rev_gr >= 0 else ''}{rev_gr*100:.1f}%")
        if earn_gr is not None and abs(earn_gr) < 50:
            fund_parts.append(f"EPS {'+' if earn_gr >= 0 else ''}{earn_gr*100:.0f}%")
        if beta is not None:
            fund_parts.append(f"β {beta:.2f}")

        verdict = _tech_verdict(tech, fund)
        earn_tag = f" · earnings {next_earn[:10]}" if next_earn else ""

        lines.append(f"\n<b>{_escape(tkr)}</b> ${price:.2f} ({chg_sign}{chg:.1f}%)")
        lines.append(
            f"  RSI {rsi:.0f} · EMA {_escape(ema_sig)} · MACD {macd_icon} · %B {bb_pct:.2f} · ATR {atr_pct:.1f}%"
        )
        lines.append(
            f"  OBV: {_escape(obv_tag)} · {_escape(vol_tag)} · vs 52w max {vs_high:+.1f}%"
        )
        if fund_parts:
            lines.append(f"  {_escape(' | '.join(fund_parts))}{_escape(earn_tag)}")
        lines.append(f"  <i>→ {_escape(verdict)}</i>")

    lines.append("")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Construcción del mensaje de análisis profundo
# ──────────────────────────────────────────────────────────────────────────────

def _build_message(data: dict, prices: dict, deep_data: dict | None = None) -> str:
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

    # ── 8. ANÁLISIS TÉCNICO + FUNDAMENTAL (top tickers) ──────────────────────
    if deep_data:
        tech_section = _build_tech_section(deep_data, prices)
        if tech_section:
            lines.append(tech_section)

    # ── 9. PIE ────────────────────────────────────────────────────────────────
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

    # Top tickers por convicción → análisis técnico + fundamental profundo
    conviction = _conviction_map(data["models"])
    top_tickers = [t for t, _ in sorted(conviction.items(), key=lambda x: -x[1]["score"])[:5]]
    deep_data = _fetch_deep_analysis(top_tickers, max_n=5)

    message = _build_message(data, prices, deep_data=deep_data)

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
