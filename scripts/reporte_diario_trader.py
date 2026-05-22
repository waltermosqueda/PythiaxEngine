#!/usr/bin/env python3
"""
Reporte diario de acción — PythiaxEngine.

Responde exactamente: qué picks tienen más chances de subir, cuáles cerrar hoy,
con precio de entrada real vs precio actual y señales técnicas por ticker.

Uso local (sin token → imprime en consola):
    py scripts/reporte_diario_trader.py

Uso en CI (requiere TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID):
    python scripts/reporte_diario_trader.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.dashboard_paths import SNAPSHOT_PATH


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _pct(v: float | None, signed: bool = True, digits: int = 1) -> str:
    if v is None:
        return "—"
    s = "+" if signed and v >= 0 else ""
    return f"{s}{v:.{digits}f}%"


def _fmt_date(v: Any) -> str:
    if not v:
        return "—"
    s = str(v)
    try:
        return s[8:10] + "/" + s[5:7]
    except Exception:
        return s


def _days_left(target_str: Any, today: str) -> int:
    if not target_str:
        return 99
    try:
        return (date.fromisoformat(str(target_str)) - date.fromisoformat(today)).days
    except Exception:
        return 99


def _e(t: Any) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _regime_icon(r: str) -> str:
    r = r.upper()
    if "SEGURO" in r or "BULL" in r:
        return "🟢"
    if "PRECAUC" in r or "NEUTRAL" in r:
        return "🟡"
    return "🔴"


# ──────────────────────────────────────────────────────────────────────────────
# Carga del snapshot y extracción de picks
# ──────────────────────────────────────────────────────────────────────────────

def _load_snapshot() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        raise FileNotFoundError(f"Snapshot no encontrado: {SNAPSHOT_PATH}")
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def _extract_picks(snapshot: dict) -> tuple[dict, list[dict]]:
    active_run = (snapshot.get("active") or {}).get("active_run") or {}
    meta = {
        "generated_at": snapshot.get("generated_at", "")[:10] or "—",
        "regime":       active_run.get("regime_label", "DESCONOCIDO"),
        "breadth_pct":  active_run.get("breadth_pct"),
    }

    comp = snapshot.get("competition_recent") or {}
    rows = list(
        comp.get("dashboard_league_equalized")
        or comp.get("league_equalized")
        or snapshot.get("competition")
        or []
    )

    picks: list[dict] = []
    for row in rows:
        tickers = row.get("latest_tickers") or []
        if not tickers:
            continue
        eq      = row.get("equalized_recent") or {}
        wr      = eq.get("accuracy_pct")
        version = str(row.get("version", ""))
        target  = row.get("latest_target_date")
        stale   = row.get("stale_market_days")

        r30 = row.get("recent_30") or {}
        cal = r30.get("calendar") or []
        mtm_assets: list[dict] = []
        entry_date: str | None = None
        for c in reversed(cal):
            ct = c.get("tickers") or []
            if set(ct) == set(tickers) or (ct and all(t in tickers for t in ct)):
                mtm_assets = c.get("mtm_assets") or []
                entry_date = c.get("date")
                break

        for asset in mtm_assets:
            tkr = asset.get("ticker")
            if not tkr or tkr not in tickers:
                continue
            picks.append({
                "ticker":     tkr,
                "model":      version,
                "wr":         wr,
                "entry":      asset.get("entry_close"),
                "current":    asset.get("latest_close"),
                "mtm_pct":    (asset.get("mtm_return") or 0) * 100,
                "confidence": asset.get("confidence") or 0.5,
                "target":     target,
                "entry_date": entry_date,
                "stale":      stale,
            })

    return meta, picks


# ──────────────────────────────────────────────────────────────────────────────
# Análisis técnico
# ──────────────────────────────────────────────────────────────────────────────

def _rsi(series: Any, n: int = 14) -> Any:
    delta = series.diff()
    up = delta.clip(lower=0)
    dn = (-delta).clip(lower=0)
    rs = up.ewm(com=n - 1, adjust=False).mean() / dn.ewm(com=n - 1, adjust=False).mean()
    return 100 - (100 / (1 + rs))


def _fetch_technicals(tickers: list[str]) -> dict[str, dict]:
    if not tickers:
        return {}
    try:
        import yfinance as yf  # noqa: PLC0415
        import numpy as np     # noqa: PLC0415

        result: dict[str, dict] = {}
        for tkr in tickers:
            try:
                h = yf.Ticker(tkr).history(period="1y", interval="1d", auto_adjust=True)
                if h is None or len(h) < 30:
                    continue
                h = h.copy()
                h["RSI"]    = _rsi(h["Close"])
                h["EMA20"]  = h["Close"].ewm(span=20).mean()
                h["EMA50"]  = h["Close"].ewm(span=50).mean()
                h["EMA200"] = h["Close"].ewm(span=200).mean()
                mf = h["Close"].ewm(span=12).mean()
                ms = h["Close"].ewm(span=26).mean()
                macd = mf - ms
                h["MACD_h"] = macd - macd.ewm(span=9).mean()
                h["OBV"]    = (np.sign(h["Close"].diff()) * h["Volume"]).fillna(0).cumsum()
                last    = h.iloc[-1]
                high52  = float(h["High"].tail(252).max())
                ema_ok  = bool(last["EMA20"] > last["EMA50"] > last["EMA200"])
                obv_up  = float(h["OBV"].tail(20).iloc[-1] - h["OBV"].tail(20).iloc[0]) > 0
                macd_pos= float(last["MACD_h"]) > 0
                rsi_val = float(last["RSI"])
                price   = float(last["Close"])
                upside  = min((high52 - price) / price * 100, 120.0)
                result[tkr] = {
                    "rsi":        rsi_val,
                    "ema_ok":     ema_ok,
                    "macd_up":    macd_pos,
                    "obv_up":     obv_up,
                    "upside_52w": upside,
                    "price":      price,
                }
            except Exception as exc:
                print(f"[reporte] WARN tech {tkr}: {exc}", file=sys.stderr)
        return result
    except Exception as exc:
        print(f"[reporte] WARN yfinance: {exc}", file=sys.stderr)
        return {}


def _tech_score(t: dict | None) -> float:
    if not t:
        return 0.5
    score = 0.0
    rsi = t.get("rsi", 50)
    if 38 < rsi < 70:
        score += 0.25
    if t.get("ema_ok"):
        score += 0.30
    if t.get("macd_up"):
        score += 0.25
    if t.get("obv_up"):
        score += 0.20
    return round(score, 2)


def _tech_label(t: dict | None) -> str:
    if not t:
        return "sin datos técnicos"
    rsi = t.get("rsi", 50)
    if rsi > 70:
        rsi_s = f"RSI {rsi:.0f} ⚠️sobrecomprado"
    elif rsi < 35:
        rsi_s = f"RSI {rsi:.0f} 🔄muy bajo"
    else:
        rsi_s = f"RSI {rsi:.0f}"
    # EMA = tendencia (¿las medias móviles apuntan para arriba?)
    ema_s  = "tendencia ✅" if t.get("ema_ok") else "tendencia ⚠️"
    # MACD = momentum (¿el movimiento reciente es alcista?)
    macd_s = "momentum ↑" if t.get("macd_up") else "momentum ↓"
    # OBV = volumen (¿el volumen respalda el movimiento?)
    obv_s  = "volumen ↑" if t.get("obv_up") else "volumen ↓"
    return f"{rsi_s} · {ema_s} · {macd_s} · {obv_s}"


def _conviction(wr: float | None, confidence: float, ts: float) -> float:
    return round((wr or 0) / 100 * 0.4 + confidence * 0.3 + ts * 0.3, 3)


def _verdict(conv: float, mtm_pct: float, ema_ok: bool) -> str:
    if conv >= 0.55 and mtm_pct >= 0 and ema_ok:
        return "COMPRAR / MANTENER — tesis técnica alineada"
    if conv >= 0.45 and mtm_pct >= 0:
        return "MANTENER — momentum positivo"
    if mtm_pct < -1.5:
        return "REVISAR — considerar reducir si no mejora"
    return "WATCH — señal mixta, esperar confirmación"


# ──────────────────────────────────────────────────────────────────────────────
# Análisis fundamental
# ──────────────────────────────────────────────────────────────────────────────

_SECTOR_ABBR = {
    "Technology": "Tech",
    "Healthcare": "Health",
    "Financial Services": "Finance",
    "Consumer Cyclical": "ConsumC",
    "Consumer Defensive": "ConsumD",
    "Communication Services": "Comms",
    "Basic Materials": "Materials",
    "Real Estate": "RE",
    "Industrials": "Indus",
    "Energy": "Energy",
    "Utilities": "Util",
}


def _fetch_fundamentals(tickers: list[str]) -> dict[str, dict]:
    """PE (forward/trailing), analyst target, sector, market-cap tier."""
    if not tickers:
        return {}
    try:
        import yfinance as yf  # noqa: PLC0415

        result: dict[str, dict] = {}
        for tkr in tickers:
            try:
                info = yf.Ticker(tkr).info or {}
                pe_raw = info.get("forwardPE") or info.get("trailingPE")
                try:
                    pe: float | None = round(pe_raw, 1) if pe_raw and 0 < pe_raw < 999 else None
                except (TypeError, OverflowError):
                    pe = None
                target  = info.get("targetMeanPrice")
                sector  = info.get("sector") or ""
                mktcap  = info.get("marketCap") or 0
                if mktcap >= 10e9:
                    cap = "LargeCap"
                elif mktcap >= 2e9:
                    cap = "MidCap"
                elif mktcap > 0:
                    cap = "SmallCap"
                else:
                    cap = ""
                result[tkr] = {
                    "pe": pe,
                    "analyst_target": round(target, 2) if target else None,
                    "sector": _SECTOR_ABBR.get(sector, sector),
                    "cap": cap,
                }
            except Exception as exc:
                print(f"[reporte] WARN fund {tkr}: {exc}", file=sys.stderr)
        return result
    except Exception as exc:
        print(f"[reporte] WARN yfinance fund: {exc}", file=sys.stderr)
        return {}


def _fund_label(f: dict | None, current: float | None) -> str:
    if not f:
        return ""
    parts: list[str] = []
    pe = f.get("pe")
    if pe:
        parts.append(f"P/E {pe:.0f}x")   # precio/ganancia (valuación)
    target = f.get("analyst_target")
    if target and current and current > 0:
        upside_pct = (target - current) / current * 100
        parts.append(f"obj. analistas ${target:.2f} ({_pct(upside_pct, digits=0)})")
    sector = f.get("sector") or ""
    if sector:
        parts.append(sector)
    cap = f.get("cap") or ""
    if cap:
        parts.append(cap)
    return " · ".join(parts)


def _strength(v: float) -> str:
    """Icon showing how strong a normalized [0-1] score component is."""
    if v >= 0.75: return "▲▲▲"
    if v >= 0.55: return "▲▲"
    if v >= 0.35: return "▲"
    if v >= 0.18: return "◆"
    return "▼"


def _rank_why(
    wr: float | None,
    confidence: float,
    ts: float,
    t: dict | None,
    mtm_pct: float = 0.0,
    days: int = 99,
) -> str:
    """
    Razonamiento multi-factor cruzado: qué confirma la suba, qué la amenaza,
    qué contradicciones existen entre los datos del modelo y la realidad actual.
    """
    wr_n = (wr or 0) / 100
    rsi  = (t or {}).get("rsi", 50) or 50
    ups:   list[str] = []
    downs: list[str] = []

    # F1 — Historial del modelo (¿cuando apuesta, suele acertar?)
    if wr_n >= 0.65:
        ups.append(f"WR {wr:.0f}% histórico")
    elif wr_n < 0.42:
        downs.append(f"WR bajo ({wr:.0f}%)")

    # F2 — Conviccion ML (¿cuánto cree el modelo en este pick ahora?)
    if confidence >= 0.72:
        ups.append(f"ML {confidence*100:.0f}% convencido")
    elif confidence < 0.52:
        downs.append(f"ML poco convencido ({confidence*100:.0f}%)")

    # F3 — Estructura técnica (¿las medias y momentum confirman alza?)
    if ts >= 0.75 and t:
        if t.get("ema_ok") and t.get("macd_up"):
            ups.append("tendencia + momentum alcista")
        else:
            ups.append("técnico fuerte")
    elif ts >= 0.50 and t and t.get("ema_ok"):
        ups.append("tendencia alcista activa")
    elif ts <= 0.25 and t:
        downs.append("sin tendencia" if not t.get("ema_ok") else "momentum bajista")

    # F4 — Honestidad tiempo/P&L (¿hay margen real para que funcione?)
    if mtm_pct < -3.0 and days <= 4:
        downs.append(f"⚡ solo {days}d para recuperar {abs(mtm_pct):.1f}%")
    elif mtm_pct < -1.5 and days <= 3:
        downs.append(f"tiempo ajustado: {days}d con {mtm_pct:.1f}%")
    elif mtm_pct >= 7:
        ups.append(f"+{mtm_pct:.1f}% ya ejecutado")
    elif mtm_pct >= 3:
        ups.append(f"+{mtm_pct:.1f}% de margen")

    # F5 — Contradicciones cruzadas (¿lo que dice el modelo vs lo que pasa en el precio?)
    if mtm_pct < -2.0 and confidence >= 0.75:
        # ML sígue muy confiado a pesar de la caída → puede ser oportunidad real
        ups.append("ML mantiene conviccion alta en el drawdown")
    if mtm_pct < 0 and t and t.get("ema_ok") and t.get("macd_up") and ts >= 0.65:
        # Precio cayó pero estructura técnica alcista intacta → soporta rebote
        ups.append("técnico soporta rebote")
    if mtm_pct > 5 and t and not t.get("ema_ok"):
        # Subió pero sin tendencia estructural → sostenibilidad dudosa
        downs.append("subió sin estructura de tendencia")
    if rsi > 72 and mtm_pct > 3:
        # RSI sobrecomprado con ganancia abierta → posible correción cercana
        downs.append(f"RSI {rsi:.0f} sobrecomprado con ganancia abierta")

    parts: list[str] = []
    if ups:   parts.append("↑ " + " + ".join(ups))
    if downs: parts.append("⚠️ " + " · ".join(downs))
    return "  |  ".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# Construcción del mensaje
# ──────────────────────────────────────────────────────────────────────────────

def _build_message(
    meta: dict,
    picks: list[dict],
    tech: dict[str, dict],
    fund: dict[str, dict],
) -> str:
    today   = date.today().isoformat()
    regime  = meta["regime"]
    breadth = meta["breadth_pct"]
    gen     = meta["generated_at"]
    gen_d   = (gen[8:10] + "/" + gen[5:7]) if len(gen) >= 10 else gen

    for p in picks:
        p["days"]   = _days_left(p["target"], today)
        t           = tech.get(p["ticker"])
        p["ts"]     = _tech_score(t)
        p["conv"]   = _conviction(p["wr"], p["confidence"], p["ts"])
        p["ema_ok"] = (t or {}).get("ema_ok", False)

    exiting = sorted([p for p in picks if p["days"] <= 0], key=lambda x: -x["mtm_pct"])
    active  = sorted([p for p in picks if p["days"] > 0],  key=lambda x: -x["conv"])

    pos_count = sum(1 for p in picks if p["mtm_pct"] > 0)
    neg_count = sum(1 for p in picks if p["mtm_pct"] < 0)

    ri = _regime_icon(regime)
    br = f"{breadth:.1f}%" if breadth is not None else "—"
    lines: list[str] = [
        f"🧠 <b>PythiaxEngine · {_e(gen_d)}</b>",
        f"{ri} <b>{_e(regime)}</b> · Breadth {_e(br)} · {pos_count}✅ {neg_count}🔴",
        "",
    ]

    # ── CONSENSO — tickers en 2+ modelos ─────────────────────────────────────
    ticker_models: dict[str, set[str]] = defaultdict(set)
    for p in picks:
        ticker_models[p["ticker"]].add(p["model"])
    active_tickers = {p["ticker"] for p in active}
    consensus = sorted(
        [tkr for tkr, mods in ticker_models.items() if len(mods) >= 2 and tkr in active_tickers],
        key=lambda t: -(next((p["conv"] for p in active if p["ticker"] == t), 0.0)),
    )
    if consensus:
        lines.append("🔁 <b>CONSENSO</b> — detectado en 2+ modelos")
        for tkr in consensus:
            t      = tech.get(tkr)
            f      = fund.get(tkr) or {}
            pk     = next((p for p in active if p["ticker"] == tkr), None)
            conv   = pk["conv"] if pk else 0.0
            mods   = sorted(ticker_models[tkr])
            cp     = (t or {}).get("price") or (pk.get("current") if pk else None)
            tech_s = _tech_label(t)
            upside = (t or {}).get("upside_52w")
            up_s   = f" · +{upside:.0f}% 52w" if upside and upside > 5 else ""
            entry_s = f"${pk['entry']:.2f}" if pk and pk.get("entry") else "—"
            curr_s  = f"${pk['current']:.2f}" if pk and pk.get("current") else "—"
            mtm_pct = pk["mtm_pct"] if pk else 0.0
            tgt_s   = _fmt_date(pk["target"]) if pk else "—"
            days    = pk.get("days", 0) if pk else 0
            mi      = "✅" if mtm_pct >= 0 else "🔴"
            obj_c    = f.get("analyst_target")
            entry_pc = pk.get("entry") if pk else None
            if obj_c and cp and cp > 0:
                if obj_c > cp:
                    obj_s = f"  ·  obj. analistas ${obj_c:.2f} ({_pct((obj_c - cp) / cp * 100, digits=0)})"
                elif entry_pc and obj_c > entry_pc:
                    obj_s = f"  ·  analistas: obj. alcanzado (${obj_c:.2f})"
                else:
                    obj_s = ""  # target below entry = no relevante como señal alcista
            else:
                obj_s = "  ·  sin cobertura analistas"
            extra_s = (f"  ·  {f['sector']}" if f.get("sector") else "") + \
                      (f"  ·  P/E {f['pe']:.0f}x" if f.get("pe") else "")
            lines.append(f"  <b>{_e(tkr)}</b>  prob. suba {conv*100:.0f}%  ·  {_e(' + '.join(mods))}")
            lines.append(
                f"   entrada {_e(entry_s)}  ›  actual {_e(curr_s)}"
                f"  {mi}<b>{_pct(mtm_pct)}</b>{_e(obj_s)}  ·  vence {_e(tgt_s)} ({days}d)"
            )
            lines.append(f"   📊 {_e(tech_s)}{_e(up_s)}{_e(extra_s)}")
        lines.append("")

    # ── RANKING ───────────────────────────────────────────────────────────────
    lines.append("🎯 <b>TOP 6 — mayor convicción</b>")
    lines.append("")

    shown: set[str] = set()
    rank = 1
    for p in active:
        tkr = p["ticker"]
        if tkr in shown:
            continue
        shown.add(tkr)

        t        = tech.get(tkr)
        f        = fund.get(tkr) or {}
        entry_s  = f"${p['entry']:.2f}" if p["entry"] else "—"
        curr_s   = f"${p['current']:.2f}" if p["current"] else "—"
        mtm_pct  = p["mtm_pct"]
        mtm_icon = "✅" if mtm_pct >= 0 else "🔴"
        tgt_s    = _fmt_date(p["target"])
        conv     = p["conv"]
        tech_s   = _tech_label(t)
        cp       = (t or {}).get("price") or p.get("current")
        upside   = (t or {}).get("upside_52w")
        upside_s = f" · +{upside:.0f}% 52w" if upside and upside > 5 else ""
        why_s    = _rank_why(p["wr"], p["confidence"], p["ts"], t, p["mtm_pct"], p["days"])
        obj_r    = f.get("analyst_target")
        entry_p  = p.get("entry")
        if obj_r and cp and cp > 0:
            if obj_r > cp:
                obj_s = f"  ·  obj. analistas ${obj_r:.2f} ({_pct((obj_r - cp) / cp * 100, digits=0)})"
            elif entry_p and obj_r > entry_p:
                obj_s = f"  ·  analistas: obj. alcanzado (${obj_r:.2f})"
            else:
                obj_s = ""  # target below entry = ML compró contra analistas, no mostrar
        else:
            obj_s = "  ·  sin cobertura analistas"
        extra_s  = (f"  ·  {f['sector']}" if f.get("sector") else "") + \
                   (f"  ·  P/E {f['pe']:.0f}x" if f.get("pe") else "")

        wr_c  = round((p['wr'] or 0) / 100 * 0.4 * 100)
        ml_c  = round(p['confidence'] * 0.3 * 100)
        tec_c = round(p['ts'] * 0.3 * 100)
        dom   = max([('WR', wr_c), ('ML', ml_c), ('téc', tec_c)], key=lambda x: x[1])[0]
        def _sc(label, val, pts):
            return f"<b>{label} {val:.0f}%</b> (+{pts})" if label == dom else f"{label} {val:.0f}% (+{pts})"
        score_s = (
            f"{_sc('WR', p['wr'] or 0, wr_c)} · "
            f"{_sc('ML', p['confidence']*100, ml_c)} · "
            f"{_sc('téc', p['ts']*100, tec_c)}"
        )
        lines.append(f"<b>{rank}. {_e(tkr)}</b>  ·  {_e(p['model'])}")
        lines.append(
            f"   entrada {_e(entry_s)}  ›  actual {_e(curr_s)} {mtm_icon}<b>{_pct(mtm_pct)}</b>"
            f"{_e(obj_s)}  ·  vence {_e(tgt_s)} ({p['days']}d)"
        )
        lines.append(
            f"   ↳ <b>prob. suba {conv*100:.0f}%</b>  =  {score_s}"
            + (f"  —  <i>{_e(why_s)}</i>" if why_s else "")
        )
        lines.append(f"   📊 {_e(tech_s)}{_e(upside_s)}{_e(extra_s)}")
        lines.append("")
        rank += 1
        if rank > 6:
            break

    focus = [p["ticker"] for p in active if p["ticker"] in shown and p["conv"] >= 0.50][:3]
    if focus:
        lines.append(f"💡 <b>Foco</b>: {' · '.join(f'<b>{_e(t)}</b>' for t in focus)}")
        lines.append("")

    # ── CERRAR HOY — compacto, al final ──────────────────────────────────────
    if exiting:
        lines.append("━━━━━━━━━━━━━━━━━━")
        lines.append("🔴 <b>CERRAR HOY</b>")
        cerrar_parts: list[str] = []
        for p in exiting:
            icon   = "✅" if p["mtm_pct"] >= 0 else "🔴"
            action = "TP" if p["mtm_pct"] >= 3 else ("CRR" if p["mtm_pct"] >= 0 else "SL")
            cerrar_parts.append(f"{icon}{_e(p['ticker'])} {_pct(p['mtm_pct'])} {action}")
        lines.append("  " + "  ·  ".join(cerrar_parts))
        lines.append("")

    lines.append(f"<i>📦 {len(picks)} picks · snapshot {_e(gen_d)}</i>")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Telegram
# ──────────────────────────────────────────────────────────────────────────────

_TG_LIMIT = 4000


def _split_message(text: str) -> list[str]:
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
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if not body.get("ok"):
                    print(f"[reporte] ERROR parte {i+1}: {body.get('description')}", file=sys.stderr)
                    return False
        except Exception as exc:
            print(f"[reporte] ERROR al enviar parte {i+1}: {exc}", file=sys.stderr)
            return False
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        snapshot = _load_snapshot()
    except FileNotFoundError as exc:
        print(f"[reporte] SKIP: {exc}", file=sys.stderr)
        return 0

    meta, picks = _extract_picks(snapshot)
    if not picks:
        print("[reporte] Sin picks activos.", file=sys.stderr)
        return 0

    today = date.today().isoformat()
    tickers_to_analyze = list({
        p["ticker"] for p in picks
        if _days_left(p["target"], today) >= 0
    })
    tech    = _fetch_technicals(tickers_to_analyze)
    fund    = _fetch_fundamentals(tickers_to_analyze)
    message = _build_message(meta, picks, tech, fund)

    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if token and chat_id:
        print("[reporte] Enviando por Telegram...", flush=True)
        ok = _send_telegram(message, token, chat_id)
        if ok:
            print("[reporte] ✓ Enviado.", flush=True)
            return 0
        print("[reporte] ✗ Envío fallido.", file=sys.stderr)
        return 1
    else:
        print("[reporte] Sin token — imprimiendo en consola:")
        print("=" * 70)
        print(re.sub(r"<[^>]+>", "", message))
        print("=" * 70)
        return 0


if __name__ == "__main__":
    sys.exit(main())
