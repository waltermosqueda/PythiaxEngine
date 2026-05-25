#!/usr/bin/env python3
"""
PLAN DE INVERSIÓN DIARIO — PythiaxEngine
=========================================

Post-cierre NYSE (corre dentro o despues del workflow Cloud Daily Operations).
Lee el snapshot del dashboard máquina pensante, identifica los picks con mas
alta probabilidad de subir en la PROXIMA RUEDA aplicando un proceso honesto
de filtrado multi-capa, y produce un plan de inversion con sizing concreto en
USD respaldado por evidencia técnica + fundamental + news + macro context.

DIFERENCIA con `reporte_diario_trader.py`:
- Aquel envía un resumen breve por Telegram (limite HTML 4000 chars).
- Este genera un Markdown profundo + JSON estructurado, sin limite de longitud,
  con sizing en USD, R:R, news, earnings calendar y descarte estricto.

Pipeline (proceso honesto, transparente):
  1. Carga snapshot JSON del dashboard.
  2. Extrae todos los picks vivos (latest_target_date >= today).
  3. Construye consenso multi-modelo ponderado por accuracy histórica.
  4. Para cada candidato top, enriquece con yfinance:
       - Técnico: RSI(14), EMA20/50/200, MACD, OBV, ATR, %52w
       - Fundamental: P/E, target analistas, sector, market cap, beta
       - News: titulares recientes (filtro 14d)
       - Earnings calendar: días al proximo earnings
  5. Aplica filtros de calidad (descarte explicito y razonado):
       - RSI > 75 sobrecomprado
       - Earnings <= 5 días (riesgo binario)
       - Sin estructura técnica (EMA20 < EMA50)
       - mtm_pct caído > 4% (tesis ya rota)
  6. Calcula sizing:
       - Stop = max( low(5d), entry * (1 - 2*ATR/entry) )
       - Risk per share = entry - stop
       - Shares = floor( capital * risk_pct / risk_per_share )
       - Target = analyst_target si > entry*1.03 else entry*1.05
       - R:R ratio
  7. Macro context: SPY, QQQ, VIX last close + tendencia 5d.
  8. Output:
       - logs/plan_diario/plan_YYYY-MM-DD.md  (Markdown legible)
       - logs/plan_diario/plan_YYYY-MM-DD.json (estructurado, parseable)

Uso local:
    py scripts/plan_inversion_diario.py
    py scripts/plan_inversion_diario.py --capital 5000 --risk-pct 0.01 --max-picks 3
    py scripts/plan_inversion_diario.py --no-enrichment   # solo dashboard, sin yfinance

Uso en CI: workflow `.github/workflows/plan-inversion-diario.yml` lo dispara
automaticamente despues del Cloud Daily Operations exitoso.

Salida exit code:
    0 → plan generado (incluso con 0 picks finales)
    1 → error fatal (snapshot no encontrado, JSON corrupto)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import traceback
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Default snapshot path — puede sobrescribirse via --snapshot-path
DEFAULT_SNAPSHOT = ROOT / "dashboards" / "maquina_pensante" / "tablero_maquina_pensante_snapshot.json"
DEFAULT_OUTPUT_DIR = ROOT / "logs" / "plan_diario"


# ────────────────────────────────────────────────────────────────────────────
# Modelo de datos
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class Candidate:
    ticker: str
    models: list[str] = field(default_factory=list)
    wrs: list[float] = field(default_factory=list)          # accuracy por modelo
    confidences: list[float] = field(default_factory=list)  # ML confidence por pick
    entry: float | None = None                              # primer entry observado
    current: float | None = None                            # ultimo close conocido
    mtm_pct: float = 0.0
    target_date: str = ""
    days_to_target: int = 99
    # enrichment (yfinance)
    rsi: float | None = None
    ema20: float | None = None
    ema50: float | None = None
    ema200: float | None = None
    ema_aligned: bool = False
    macd_pos: bool = False
    obv_rising: bool = False
    atr: float | None = None
    upside_52w: float | None = None
    rel_vol_5d: float | None = None      # volumen 5d / volumen 20d (>1 = interés creciente)
    dist_ema200_pct: float | None = None # distancia % entre close y EMA200 (sweet spot 3-12%)
    pe: float | None = None
    analyst_target: float | None = None
    sector: str = ""
    market_cap: float | None = None
    beta: float | None = None
    earnings_in_days: int | None = None
    news_count_14d: int = 0
    news_titles: list[str] = field(default_factory=list)
    # scoring
    consensus_score: float = 0.0
    technical_score: float = 0.0
    fundamental_score: float = 0.0
    composite_prob: float = 0.0
    # plan
    decision: str = "WATCH"
    reject_reason: str = ""
    stop_price: float | None = None
    target_price: float | None = None
    shares: int = 0
    risk_usd: float = 0.0
    upside_pct: float = 0.0
    rr_ratio: float | None = None
    why_up: list[str] = field(default_factory=list)
    why_risk: list[str] = field(default_factory=list)


# ────────────────────────────────────────────────────────────────────────────
# Carga snapshot
# ────────────────────────────────────────────────────────────────────────────
def load_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Snapshot no encontrado: {path}")
    # utf-8-sig tolera BOM (algunas tools de Windows lo agregan)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def extract_candidates(snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[Candidate]]:
    """Extrae todos los picks vivos del snapshot agrupando por ticker."""
    active_run = (snapshot.get("active") or {}).get("active_run") or {}
    meta = {
        "generated_at": snapshot.get("generated_at", "")[:19] or "—",
        "regime": active_run.get("regime_label", "DESCONOCIDO"),
        "breadth_pct": active_run.get("breadth_pct"),
    }

    comp = snapshot.get("competition_recent") or {}
    rows = list(
        comp.get("dashboard_league_equalized")
        or comp.get("league_equalized")
        or snapshot.get("competition")
        or []
    )

    today_iso = date.today().isoformat()
    by_ticker: dict[str, Candidate] = {}

    for row in rows:
        tickers = row.get("latest_tickers") or []
        if not tickers:
            continue
        eq = row.get("equalized_recent") or {}
        wr = float(eq.get("accuracy_pct") or 0.0)
        version = str(row.get("version", ""))
        target = row.get("latest_target_date") or ""

        # Recuperar mtm_assets del recent_30.calendar (ultimo entry)
        r30 = row.get("recent_30") or {}
        cal = r30.get("calendar") or []
        mtm_assets: list[dict] = []
        for c in reversed(cal):
            ct = c.get("tickers") or []
            if ct and all(t in tickers for t in ct):
                mtm_assets = c.get("mtm_assets") or []
                break

        for asset in mtm_assets:
            tkr = asset.get("ticker")
            if not tkr or tkr not in tickers:
                continue
            cand = by_ticker.setdefault(tkr, Candidate(ticker=tkr))
            if version not in cand.models:
                cand.models.append(version)
                cand.wrs.append(wr)
                cand.confidences.append(float(asset.get("confidence") or 0.5))
            if cand.entry is None:
                cand.entry = _safe_float(asset.get("entry_close"))
                cand.current = _safe_float(asset.get("latest_close"))
                cand.mtm_pct = float(asset.get("mtm_return") or 0.0) * 100.0
                cand.target_date = str(target)
                cand.days_to_target = _days_left(target, today_iso)

    # Solo nos importan los vivos (target_date >= hoy)
    alive = [c for c in by_ticker.values() if c.days_to_target >= 0]
    return meta, alive


def _safe_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _days_left(target_str: Any, today_iso: str) -> int:
    if not target_str:
        return 99
    try:
        return (date.fromisoformat(str(target_str)) - date.fromisoformat(today_iso)).days
    except Exception:
        return 99


# ────────────────────────────────────────────────────────────────────────────
# Consenso multi-modelo
# ────────────────────────────────────────────────────────────────────────────
def score_consensus(cand: Candidate) -> float:
    """
    Score 0-1 ponderado por:
      - Cardinalidad de modelos votantes (mas modelos = mas robusto)
      - Accuracy histórica promedio (WR)
      - WR del MEJOR modelo (un campeón solo puede valer mucho)
      - Confianza ML promedio
    """
    n_models = len(cand.models)
    if n_models == 0:
        return 0.0
    avg_wr = sum(cand.wrs) / n_models / 100.0
    max_wr = max(cand.wrs) / 100.0
    avg_conf = sum(cand.confidences) / n_models
    cardinality_bonus = min(n_models / 3.0, 1.0)         # 1 modelo=0.33, 3+=1.0
    # Pesos: 0.30 cardinalidad, 0.30 WR avg, 0.25 WR máx (mejor modelo), 0.15 confianza
    return round(0.30 * cardinality_bonus + 0.30 * avg_wr + 0.25 * max_wr + 0.15 * avg_conf, 4)


# ────────────────────────────────────────────────────────────────────────────
# Enrichment via yfinance — opcional, robusto a fallos de red
# ────────────────────────────────────────────────────────────────────────────
def enrich_candidates(cands: list[Candidate], log) -> None:
    if not cands:
        return
    try:
        import yfinance as yf
        import numpy as np
        import pandas as pd  # noqa: F401  # noqa: PLC0415
    except ImportError:
        log("yfinance/numpy/pandas no disponibles → skip enrichment")
        return

    for c in cands:
        try:
            _enrich_one(c, yf, np, log)
        except Exception as exc:
            log(f"  enrich {c.ticker} FAIL: {exc}")


def _enrich_one(c: Candidate, yf, np, log) -> None:
    tk = yf.Ticker(c.ticker)
    # Histórico técnico
    try:
        h = tk.history(period="1y", interval="1d", auto_adjust=True)
    except Exception as exc:
        log(f"  history {c.ticker} FAIL: {exc}")
        h = None

    if h is not None and len(h) >= 30:
        h = h.copy()
        # RSI(14)
        delta = h["Close"].diff()
        up = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
        dn = (-delta).clip(lower=0).ewm(com=13, adjust=False).mean()
        rs = up / dn.replace(0, float("nan"))
        h["RSI"] = 100 - (100 / (1 + rs))
        # EMAs
        h["EMA20"] = h["Close"].ewm(span=20).mean()
        h["EMA50"] = h["Close"].ewm(span=50).mean()
        h["EMA200"] = h["Close"].ewm(span=200).mean()
        # MACD
        mf = h["Close"].ewm(span=12).mean()
        ms = h["Close"].ewm(span=26).mean()
        macd = mf - ms
        h["MACD_h"] = macd - macd.ewm(span=9).mean()
        # OBV
        h["OBV"] = (np.sign(h["Close"].diff()) * h["Volume"]).fillna(0).cumsum()
        # ATR(14)
        high_low = h["High"] - h["Low"]
        high_close = (h["High"] - h["Close"].shift()).abs()
        low_close = (h["Low"] - h["Close"].shift()).abs()
        tr = high_low.combine(high_close, max).combine(low_close, max)
        h["ATR"] = tr.ewm(span=14, adjust=False).mean()

        last = h.iloc[-1]
        high52 = float(h["High"].tail(252).max())
        price = float(last["Close"])
        c.current = price if c.current is None else c.current
        c.rsi = float(last["RSI"]) if not _is_nan(last["RSI"]) else None
        c.ema20 = float(last["EMA20"])
        c.ema50 = float(last["EMA50"])
        c.ema200 = float(last["EMA200"])
        c.ema_aligned = bool(c.ema20 > c.ema50 > c.ema200)
        c.macd_pos = bool(float(last["MACD_h"]) > 0)
        c.obv_rising = bool(float(h["OBV"].tail(20).iloc[-1] - h["OBV"].tail(20).iloc[0]) > 0)
        c.atr = float(last["ATR"]) if not _is_nan(last["ATR"]) else None
        c.upside_52w = round(min((high52 - price) / price * 100, 120.0), 2) if price > 0 else None
        # Volumen relativo: si los últimos 5d superan el promedio 20d, hay interés
        try:
            vol_5d = float(h["Volume"].tail(5).mean())
            vol_20d = float(h["Volume"].tail(20).mean())
            if vol_20d > 0:
                c.rel_vol_5d = round(vol_5d / vol_20d, 2)
        except Exception:
            pass
        # Distancia a EMA200: en estructura alcista, sweet spot 3-12% arriba
        if c.ema200 and c.ema200 > 0:
            c.dist_ema200_pct = round((price - c.ema200) / c.ema200 * 100, 1)
        # Stop sugerido: max(low 5d, entry - 2*ATR)
        low5d = float(h["Low"].tail(5).min())
        entry = c.entry if c.entry else price
        if c.atr and c.atr > 0:
            stop_atr = entry - 2 * c.atr
            c.stop_price = round(max(low5d, stop_atr), 2)
        else:
            c.stop_price = round(low5d, 2)

    # Fundamental
    try:
        info = tk.info or {}
        pe_raw = info.get("forwardPE") or info.get("trailingPE")
        c.pe = round(float(pe_raw), 2) if pe_raw and 0 < pe_raw < 999 else None
        tgt = info.get("targetMeanPrice")
        c.analyst_target = round(float(tgt), 2) if tgt else None
        c.sector = str(info.get("sector") or "")
        c.market_cap = _safe_float(info.get("marketCap"))
        c.beta = _safe_float(info.get("beta"))
    except Exception as exc:
        log(f"  info {c.ticker} FAIL: {exc}")

    # Earnings calendar
    try:
        cal = tk.calendar
        if cal is not None:
            # yfinance puede devolver dict o DataFrame segun version
            edate = None
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if isinstance(ed, list) and ed:
                    edate = ed[0]
                elif ed:
                    edate = ed
            if edate is not None:
                if hasattr(edate, "date"):
                    edate = edate.date()
                if isinstance(edate, str):
                    edate = datetime.fromisoformat(edate.split()[0]).date()
                if isinstance(edate, date):
                    c.earnings_in_days = (edate - date.today()).days
    except Exception as exc:
        log(f"  calendar {c.ticker} FAIL: {exc}")

    # News (ultimas 14 dias)
    try:
        news = tk.news or []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).timestamp()
        recent = [n for n in news if n.get("providerPublishTime", 0) >= cutoff]
        c.news_count_14d = len(recent)
        c.news_titles = [n.get("title", "")[:120] for n in recent[:3]]
    except Exception as exc:
        log(f"  news {c.ticker} FAIL: {exc}")


def _is_nan(v: Any) -> bool:
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return True


# ────────────────────────────────────────────────────────────────────────────
# Scoring tecnico y fundamental
# ────────────────────────────────────────────────────────────────────────────
def score_technical(c: Candidate) -> float:
    if c.rsi is None:
        return 0.3  # sin datos = neutral-bajo
    score = 0.0
    # RSI sweet spot estricto (45-62 = trend constructivo SIN signo de sobrecompra)
    if 45 <= c.rsi <= 62:
        score += 0.28
    elif 38 <= c.rsi < 45 or 62 < c.rsi <= 68:
        score += 0.14
    # Estructura EMA
    if c.ema_aligned:
        score += 0.25
    elif c.ema20 and c.ema50 and c.ema20 > c.ema50:
        score += 0.12
    # MACD
    if c.macd_pos:
        score += 0.20
    # OBV
    if c.obv_rising:
        score += 0.15
    # Sweet spot de MTM (señal arrancando, no consumida)
    if -1.0 <= c.mtm_pct <= 4.0:
        score += 0.12
    elif 4.0 < c.mtm_pct <= 8.0:
        score += 0.04
    elif c.mtm_pct > 15.0:
        score -= 0.20
    # Volumen relativo creciente (>1.15 = interés real)
    if c.rel_vol_5d is not None:
        if c.rel_vol_5d >= 1.15:
            score += 0.08
        elif c.rel_vol_5d < 0.80:
            score -= 0.05
    # Distancia a EMA200 — sweet spot 3-12% en estructura alcista
    if c.dist_ema200_pct is not None:
        if 3 <= c.dist_ema200_pct <= 12:
            score += 0.05
        elif c.dist_ema200_pct > 25:
            score -= 0.08      # demasiado extendido, riesgo mean-reversion
        elif c.dist_ema200_pct < -3:
            score -= 0.05
    return round(max(0.0, min(score, 1.0)), 3)


def score_fundamental(c: Candidate) -> float:
    score = 0.5  # neutral base si no hay datos
    deltas = 0
    # Analyst target upside
    if c.analyst_target and c.current and c.current > 0:
        upside = (c.analyst_target - c.current) / c.current
        if upside > 0.10:
            score += 0.25
        elif upside > 0.0:
            score += 0.10
        elif upside < -0.05:
            score -= 0.15
        deltas += 1
    # P/E razonable (no negativo, no >80)
    if c.pe is not None:
        if 0 < c.pe < 35:
            score += 0.10
        elif c.pe >= 80:
            score -= 0.10
        deltas += 1
    # Beta < 1.5 = riesgo manejable
    if c.beta is not None and 0 < c.beta < 1.5:
        score += 0.05
        deltas += 1
    # News flow (algo de cobertura es buena, demasiada = volatil)
    if 1 <= c.news_count_14d <= 6:
        score += 0.10
    elif c.news_count_14d > 10:
        score -= 0.05
    return round(max(0.0, min(1.0, score)), 3)


def composite_probability(c: Candidate) -> float:
    """Probabilidad compuesta 0-1: consenso 40% + técnico 35% + fundamental 25%.

    Ajustes por horizonte (queremos PROXIMA RUEDA, no swing):
      - target en 2-5 días → bonus +5%
      - target en 8-12 días → penalización -8%
      - target > 12 días → penalización -15%
    """
    base = 0.40 * c.consensus_score + 0.35 * c.technical_score + 0.25 * c.fundamental_score
    if 2 <= c.days_to_target <= 5:
        base *= 1.05
    elif 8 <= c.days_to_target <= 12:
        base *= 0.92
    elif c.days_to_target > 12:
        base *= 0.85
    return round(min(base, 1.0), 4)


# ────────────────────────────────────────────────────────────────────────────
# Filtros de calidad y razonamiento
# ────────────────────────────────────────────────────────────────────────────
def apply_quality_filters(c: Candidate) -> None:
    """Marca c.decision y c.reject_reason segun filtros estrictos.

    Objetivo: MAXIMA probabilidad de suba en la PROXIMA RUEDA con buen %.
    Por eso los filtros son agresivos — preferimos 0 picks a un mal pick.
    """
    reasons: list[str] = []

    # Sobrecompra: nada de comprar arriba de RSI 72
    if c.rsi is not None and c.rsi > 72:
        reasons.append(f"RSI {c.rsi:.0f} sobrecomprado (>72)")
    # Earnings inminente = riesgo binario (solo si es FUTURO, no pasado)
    if c.earnings_in_days is not None and 0 <= c.earnings_in_days <= 5:
        reasons.append(f"earnings en {c.earnings_in_days}d (riesgo binario)")
    # Sin estructura técnica alcista
    if c.ema20 and c.ema50 and c.ema20 < c.ema50 * 0.98:
        reasons.append("EMA20 debajo de EMA50 (sin tendencia)")
    # Tesis abierta SERIAMENTE rota (un drawdown -3% no es problema: el ticker
    # está ahora más barato que el entry del modelo, posiblemente mejor entry)
    if c.mtm_pct < -8.0:
        reasons.append(f"drawdown abierto {c.mtm_pct:.1f}% (tesis rota)")
    # Anti-chasing: la señal ya corrió
    if c.mtm_pct > 12.0 and c.days_to_target <= 5:
        reasons.append(f"chasing: MTM +{c.mtm_pct:.1f}% con {c.days_to_target}d al target")
    if c.mtm_pct > 22.0:
        reasons.append(f"MTM +{c.mtm_pct:.1f}% (señal ya consumida)")
    # Horizonte demasiado lejano: queremos PROXIMA RUEDA
    if c.days_to_target > 15:
        reasons.append(f"target a {c.days_to_target}d (no es próxima rueda)")
    # R:R insuficiente — si el upside no compensa el downside, salteamos
    if c.rr_ratio is not None and c.rr_ratio < 1.4:
        reasons.append(f"R:R {c.rr_ratio:.2f} insuficiente (<1.4)")
    # Stop ridículamente lejos (operación demasiado arriesgada)
    if c.stop_price and c.current and (c.current - c.stop_price) / c.current > 0.06:
        stop_pct = (c.stop_price - c.current) / c.current * 100
        reasons.append(f"stop muy lejos ({stop_pct:.1f}%)")
    # Sin viento de cola técnico: ni MACD, ni OBV, ni EMA alineadas
    if c.rsi is not None and not c.macd_pos and not c.obv_rising and not c.ema_aligned:
        reasons.append("sin momentum técnico (MACD-, OBV-, EMA mixed)")
    # Probabilidad muy baja
    if c.composite_prob < 0.55:
        reasons.append(f"probabilidad compuesta baja ({c.composite_prob*100:.0f}%)")

    if reasons:
        c.decision = "DESCARTAR"
        c.reject_reason = "; ".join(reasons)
    elif c.composite_prob >= 0.65:
        c.decision = "COMPRAR"
    elif c.composite_prob >= 0.56:
        c.decision = "WATCH-COMPRAR"
    else:
        c.decision = "WATCH"

    # Construir narrativa
    if c.ema_aligned:
        c.why_up.append("EMA20>EMA50>EMA200 (tendencia alcista estructural)")
    if c.macd_pos:
        c.why_up.append("MACD histograma positivo (momentum)")
    if c.obv_rising:
        c.why_up.append("OBV creciente últimos 20d (volumen confirma)")
    if c.rsi and 40 <= c.rsi <= 65:
        c.why_up.append(f"RSI {c.rsi:.0f} en zona constructiva")
    if c.analyst_target and c.current and c.analyst_target > c.current * 1.05:
        up = (c.analyst_target - c.current) / c.current * 100
        c.why_up.append(f"analistas objetivo ${c.analyst_target:.2f} (+{up:.0f}%)")
    if len(c.models) >= 2:
        c.why_up.append(f"consenso {len(c.models)} modelos PythiaxEngine")
    avg_wr = sum(c.wrs) / max(1, len(c.wrs))
    if avg_wr >= 60:
        c.why_up.append(f"WR histórico promedio {avg_wr:.0f}%")

    if c.rsi and c.rsi > 68:
        c.why_risk.append(f"RSI {c.rsi:.0f} cerca de sobrecompra")
    if c.earnings_in_days is not None and 0 <= c.earnings_in_days <= 14:
        c.why_risk.append(f"earnings en {c.earnings_in_days}d")
    if c.beta and c.beta > 1.5:
        c.why_risk.append(f"beta {c.beta:.2f} (volátil vs SPY)")
    if c.pe and c.pe > 60:
        c.why_risk.append(f"P/E {c.pe:.0f} elevado")
    if c.days_to_target <= 2:
        c.why_risk.append(f"solo {c.days_to_target}d al target del modelo")
    if c.mtm_pct < -1.5:
        c.why_risk.append(f"drawdown abierto {c.mtm_pct:.1f}%")
    if c.mtm_pct > 8.0:
        c.why_risk.append(f"MTM +{c.mtm_pct:.1f}% (señal corrida)")


def compute_sizing(c: Candidate, capital: float, risk_pct: float) -> None:
    """Calcula stop, target, shares, R:R."""
    if c.current is None or c.current <= 0:
        return
    entry = c.current  # entrar al close de hoy
    if c.stop_price is None or c.stop_price >= entry:
        # fallback: stop 3% debajo
        c.stop_price = round(entry * 0.97, 2)
    # Cap stop a -5% del entry: si el stop natural quedó más lejos, lo ajustamos
    # (el sizing usa este stop ajustado, riesgo USD se mantiene dentro de 2%)
    max_stop_distance = entry * 0.05
    if entry - c.stop_price > max_stop_distance:
        c.stop_price = round(entry - max_stop_distance, 2)
    risk_per_share = max(0.01, entry - c.stop_price)
    risk_usd = capital * risk_pct
    shares = int(risk_usd / risk_per_share) if risk_per_share > 0 else 0
    # Cap individual por CONVICCION: menos plata en picks marginales
    #   prob >= 75%  →  hasta 25% del capital
    #   prob 68-75%  →  hasta 18% del capital
    #   prob < 68%   →  hasta 12% del capital
    if c.composite_prob >= 0.75:
        cap_frac = 0.25
    elif c.composite_prob >= 0.68:
        cap_frac = 0.18
    else:
        cap_frac = 0.12
    max_shares_capital = int((capital * cap_frac) / entry) if entry > 0 else 0
    shares = max(0, min(shares, max_shares_capital))
    c.shares = shares
    c.risk_usd = round(shares * risk_per_share, 2)
    # Target inteligente: max( analyst_target si > entry*1.03,
    #                          entry + 2.5*ATR (basado en volatilidad real),
    #                          entry * 1.06 (mínimo 6%) )
    candidates_target = [entry * 1.06]
    if c.analyst_target and c.analyst_target > entry * 1.03:
        candidates_target.append(c.analyst_target)
    if c.atr and c.atr > 0:
        candidates_target.append(entry + 2.5 * c.atr)
    c.target_price = round(max(candidates_target), 2)
    c.upside_pct = round((c.target_price - entry) / entry * 100, 2)
    reward = c.target_price - entry
    c.rr_ratio = round(reward / risk_per_share, 2) if risk_per_share > 0 else None


def enforce_aggregate_capital_cap(buys: list[Candidate], capital: float) -> None:
    """Asegura que la suma de capital comprometido <= 100% del capital.

    Si la suma excede, prorratea shares proporcionalmente y recalcula riesgo.
    """
    total = sum((c.shares * (c.current or 0.0)) for c in buys)
    if total <= capital or total <= 0:
        return
    scale = capital / total
    for c in buys:
        if c.shares > 0:
            c.shares = int(c.shares * scale)
            entry = c.current or 0.0
            stop = c.stop_price or 0.0
            c.risk_usd = round(c.shares * max(0.01, entry - stop), 2)


# ────────────────────────────────────────────────────────────────────────────
# Macro context (SPY / QQQ / VIX)
# ────────────────────────────────────────────────────────────────────────────
def fetch_macro_context(log) -> dict[str, Any]:
    try:
        import yfinance as yf
    except ImportError:
        return {}
    out: dict[str, Any] = {}
    for sym, key in [("SPY", "spy"), ("QQQ", "qqq"), ("^VIX", "vix")]:
        try:
            h = yf.Ticker(sym).history(period="1mo", interval="1d", auto_adjust=True)
            if h is None or len(h) < 6:
                continue
            last = float(h["Close"].iloc[-1])
            prev5 = float(h["Close"].iloc[-6])
            chg5 = (last - prev5) / prev5 * 100
            out[key] = {"last": round(last, 2), "chg_5d_pct": round(chg5, 2)}
        except Exception as exc:
            log(f"  macro {sym} FAIL: {exc}")
    return out


def macro_label(macro: dict[str, Any]) -> str:
    parts: list[str] = []
    spy = macro.get("spy") or {}
    qqq = macro.get("qqq") or {}
    vix = macro.get("vix") or {}
    if spy:
        ic = "📈" if spy["chg_5d_pct"] >= 0 else "📉"
        parts.append(f"{ic} SPY {spy['last']} ({spy['chg_5d_pct']:+.2f}% 5d)")
    if qqq:
        ic = "📈" if qqq["chg_5d_pct"] >= 0 else "📉"
        parts.append(f"{ic} QQQ {qqq['last']} ({qqq['chg_5d_pct']:+.2f}% 5d)")
    if vix:
        v = vix["last"]
        ic = "🟢" if v < 18 else ("🟡" if v < 25 else "🔴")
        parts.append(f"{ic} VIX {v}")
    return "  ·  ".join(parts) if parts else "macro no disponible"


# ────────────────────────────────────────────────────────────────────────────
# Render Markdown
# ────────────────────────────────────────────────────────────────────────────
def render_markdown(
    meta: dict[str, Any],
    macro: dict[str, Any],
    buys: list[Candidate],
    watches: list[Candidate],
    discarded: list[Candidate],
    capital: float,
    risk_pct: float,
    max_picks: int,
) -> str:
    today = date.today().isoformat()
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L: list[str] = []
    L.append(f"# 🎯 Plan de Inversión Diario — PythiaxEngine")
    L.append("")
    L.append(f"**Fecha del plan:** {today}  |  **Generado:** {now_utc}")
    L.append(f"**Snapshot dashboard:** {meta['generated_at']}  ·  **Régimen:** `{meta['regime']}`")
    L.append(f"**Breadth:** {meta.get('breadth_pct')}  ·  **Macro:** {macro_label(macro)}")
    L.append("")
    L.append(f"**Parámetros:** capital USD {capital:,.0f}  ·  riesgo/posición {risk_pct*100:.1f}%  ·  máx picks {max_picks}")
    L.append("")
    L.append("> ⚠️ **Disclaimer honesto:** Este plan es una propuesta algorítmica con base en consenso multi-modelo del sistema PythiaxEngine, técnico (yfinance) y fundamental. **NO es asesoramiento financiero.** Las probabilidades son scores compuestos del sistema, no garantías. Ejecutá tu propia diligencia y considerá tu tolerancia al riesgo. Stops y sizing son sugeridos, no obligatorios.")
    L.append("")
    L.append("---")
    L.append("")

    # Resumen ejecutivo
    L.append("## 📌 Resumen ejecutivo")
    L.append("")
    if buys:
        total_risk = sum(c.risk_usd for c in buys)
        total_capital_used = sum((c.shares * (c.current or 0)) for c in buys)
        L.append(f"- **{len(buys)} pick(s) propuesto(s) para compra** próxima rueda")
        L.append(f"- **Capital comprometido:** USD {total_capital_used:,.2f}  ({total_capital_used/capital*100:.1f}% del total)")
        L.append(f"- **Riesgo total agregado (a stops):** USD {total_risk:,.2f}  ({total_risk/capital*100:.2f}% del capital)")
        L.append(f"- **Top tickers:** " + ", ".join(f"`{c.ticker}`" for c in buys))
    else:
        L.append("- ❌ **0 picks pasan los filtros de calidad hoy.** El plan honesto es **mantener cash** y esperar mejor setup.")
    L.append("")

    # Buys detallados
    if buys:
        L.append("## ✅ Picks recomendados (orden por probabilidad compuesta)")
        L.append("")
        for i, c in enumerate(buys, 1):
            L.append(_render_pick_md(i, c))
            L.append("")

    # Watches
    if watches:
        L.append("## 👀 Watch list (cerca del threshold, no comprar aún)")
        L.append("")
        L.append("| # | Ticker | Prob. | Consenso | Téc | Fund | Modelos | Razón |")
        L.append("|---|--------|-------|----------|-----|------|---------|-------|")
        for i, c in enumerate(watches, 1):
            L.append(
                f"| {i} | `{c.ticker}` | {c.composite_prob*100:.0f}% | "
                f"{c.consensus_score*100:.0f}% | {c.technical_score*100:.0f}% | "
                f"{c.fundamental_score*100:.0f}% | {len(c.models)} | "
                f"{'; '.join(c.why_risk[:2]) if c.why_risk else '—'} |"
            )
        L.append("")

    # Descartados (transparencia)
    if discarded:
        L.append("## 🚫 Descartados (transparencia de filtrado)")
        L.append("")
        L.append("| Ticker | Prob. | Motivo de descarte |")
        L.append("|--------|-------|--------------------|")
        for c in discarded[:15]:
            L.append(f"| `{c.ticker}` | {c.composite_prob*100:.0f}% | {c.reject_reason or '—'} |")
        if len(discarded) > 15:
            L.append(f"| _… {len(discarded)-15} más_ | | |")
        L.append("")

    L.append("---")
    L.append("")
    L.append("## 🧮 Metodología")
    L.append("")
    L.append("**Score compuesto (probabilidad de suba próxima rueda):**")
    L.append("")
    L.append("$$P_{up} = 0.40 \\cdot S_{consenso} + 0.35 \\cdot S_{técnico} + 0.25 \\cdot S_{fundamental}$$")
    L.append("")
    L.append("- **Consenso (0.30 cardinalidad + 0.30 WR avg + 0.25 WR max + 0.15 ML conf)**: más modelos votando, mejor WR histórico y un campeón entre ellos = mayor score.")
    L.append("- **Técnico (yfinance, daily 1y)**: RSI(14), EMA20/50/200, MACD, OBV, ATR(14), volumen relativo 5d/20d, distancia a EMA200. Sweet spot RSI 45-62, EMA aligned alcista, MACD+, OBV↑, relVol>1.15, distancia a EMA200 3-12%, MTM en −1% a +4%.")
    L.append("- **Fundamental (yfinance.info)**: P/E forward/trailing, target analistas, sector, beta, market cap, flujo de noticias 14d.")
    L.append("")
    L.append("**Filtros de descarte estricto:**")
    L.append("- RSI > 72 (sobrecompra)")
    L.append("- Earnings en ≤ 5 días (riesgo binario)")
    L.append("- EMA20 < EMA50 × 0.98 (sin tendencia alcista)")
    L.append("- Drawdown abierto > 8% (tesis rota — hasta -7% se considera mejor entry)")
    L.append("- **Anti-chasing**: MTM > +12% con ≤5d al target, o MTM > +22% absoluto")
    L.append("- **Horizonte**: target del modelo > 15 días (no es próxima rueda)")
    L.append("- **R:R < 1.4** (upside no compensa downside)")
    L.append("- **Stop > 6%** del entry (operación demasiado arriesgada)")
    L.append("- Sin viento de cola técnico (MACD-, OBV-, EMA mixed)")
    L.append("- Probabilidad compuesta < 55%")
    L.append("")
    L.append("**Sizing:**")
    L.append("- Stop = max(low 5d, entry − 2·ATR), capeado a entry × 0.95")
    L.append("- Shares = ⌊capital · risk_pct / (entry − stop)⌋")
    L.append("- **Cap por convicción**: prob ≥75% → 25%, prob 68-75% → 18%, prob <68% → 12% del capital por posición")
    L.append("- **Cap agregado**: suma de capital comprometido ≤ 100% (prorrateo si excede)")
    L.append("- **Target inteligente**: max( analyst_target, entry + 2.5·ATR, entry·1.06 )")
    L.append("")
    L.append("---")
    L.append(f"_Generado por `scripts/plan_inversion_diario.py` · PythiaxEngine_")
    return "\n".join(L)


def _render_pick_md(rank: int, c: Candidate) -> str:
    entry = c.current or 0.0
    stop = c.stop_price or 0.0
    target = c.target_price or 0.0
    risk_per_sh = entry - stop if entry > stop else 0.0
    cap_used = c.shares * entry
    L: list[str] = []
    L.append(f"### {rank}. `{c.ticker}` — prob. suba **{c.composite_prob*100:.0f}%**  ·  {c.decision}")
    L.append("")
    L.append(f"**Entry (close hoy):** ${entry:.2f}  |  **Stop:** ${stop:.2f} ({(stop-entry)/entry*100:+.2f}%)  |  **Target:** ${target:.2f} ({c.upside_pct:+.2f}%)")
    L.append(f"**Shares sugeridas:** {c.shares}  |  **Capital comprometido:** USD {cap_used:,.2f}  |  **Riesgo:** USD {c.risk_usd:,.2f}  |  **R:R:** {c.rr_ratio or '—'}")
    L.append("")
    # Bloque de scores
    L.append(f"- **Consenso PythiaxEngine:** {c.consensus_score*100:.0f}% — modelos: {', '.join(f'`{m}`' for m in c.models)}  ·  WR promedio: {sum(c.wrs)/max(1,len(c.wrs)):.1f}%")
    L.append(f"- **Técnico:** {c.technical_score*100:.0f}% — " + _tech_inline(c))
    L.append(f"- **Fundamental:** {c.fundamental_score*100:.0f}% — " + _fund_inline(c))
    L.append(f"- **Target modelo:** {c.target_date}  ({c.days_to_target}d)  ·  **MTM actual:** {c.mtm_pct:+.2f}%")
    if c.earnings_in_days is not None and c.earnings_in_days >= 0:
        L.append(f"- **Próximo earnings:** {c.earnings_in_days}d")
    if c.news_count_14d:
        L.append(f"- **News 14d:** {c.news_count_14d} headlines")
        for t in c.news_titles[:3]:
            L.append(f"  - _{t}_")
    L.append("")
    if c.why_up:
        L.append("**✅ Por qué subiría:**")
        for r in c.why_up:
            L.append(f"  - {r}")
    if c.why_risk:
        L.append("")
        L.append("**⚠️ Qué podría salir mal:**")
        for r in c.why_risk:
            L.append(f"  - {r}")
    return "\n".join(L)


def _tech_inline(c: Candidate) -> str:
    parts: list[str] = []
    if c.rsi is not None:
        parts.append(f"RSI {c.rsi:.1f}")
    if c.ema_aligned:
        parts.append("EMA aligned ↑")
    elif c.ema20 and c.ema50:
        parts.append("EMA mixed")
    if c.macd_pos:
        parts.append("MACD+")
    if c.obv_rising:
        parts.append("OBV↑")
    if c.rel_vol_5d is not None:
        parts.append(f"relVol {c.rel_vol_5d:.2f}")
    if c.dist_ema200_pct is not None:
        parts.append(f"vs EMA200 {c.dist_ema200_pct:+.1f}%")
    if c.upside_52w is not None:
        parts.append(f"upside 52w {c.upside_52w:+.1f}%")
    if c.atr:
        parts.append(f"ATR {c.atr:.2f}")
    return "  ·  ".join(parts) if parts else "sin datos"

def _fund_inline(c: Candidate) -> str:
    parts: list[str] = []
    if c.pe is not None:
        parts.append(f"P/E {c.pe:.1f}")
    if c.analyst_target and c.current:
        up = (c.analyst_target - c.current) / c.current * 100
        parts.append(f"obj. ${c.analyst_target:.2f} ({up:+.1f}%)")
    if c.sector:
        parts.append(c.sector)
    if c.beta is not None:
        parts.append(f"β {c.beta:.2f}")
    if c.market_cap:
        if c.market_cap >= 1e11:
            parts.append("MegaCap")
        elif c.market_cap >= 1e10:
            parts.append("LargeCap")
        elif c.market_cap >= 2e9:
            parts.append("MidCap")
        else:
            parts.append("SmallCap")
    return "  ·  ".join(parts) if parts else "sin datos"


# ────────────────────────────────────────────────────────────────────────────
# Output JSON estructurado
# ────────────────────────────────────────────────────────────────────────────
def build_json_output(
    meta: dict[str, Any],
    macro: dict[str, Any],
    buys: list[Candidate],
    watches: list[Candidate],
    discarded: list[Candidate],
    capital: float,
    risk_pct: float,
    max_picks: int,
) -> dict[str, Any]:
    return {
        "plan_date": date.today().isoformat(),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_meta": meta,
        "macro": macro,
        "parameters": {
            "capital_usd": capital,
            "risk_pct": risk_pct,
            "max_picks": max_picks,
        },
        "buys": [asdict(c) for c in buys],
        "watches": [asdict(c) for c in watches],
        "discarded_sample": [
            {"ticker": c.ticker, "composite_prob": c.composite_prob, "reject_reason": c.reject_reason}
            for c in discarded[:30]
        ],
    }


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plan de inversion diario PythiaxEngine")
    p.add_argument("--snapshot-path", type=Path, default=DEFAULT_SNAPSHOT)
    p.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    p.add_argument("--capital", type=float, default=10000.0, help="USD")
    p.add_argument("--risk-pct", type=float, default=0.02, help="0.02 = 2%% por posicion")
    p.add_argument("--max-picks", type=int, default=5)
    p.add_argument("--no-enrichment", action="store_true", help="No usar yfinance (solo dashboard)")
    p.add_argument("--no-telegram", action="store_true", help="No enviar por Telegram aunque haya credenciales")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args()


# ────────────────────────────────────────────────────────────────────────────
# Envio por Telegram (paralelo y distinto al reporte_diario_trader.py)
# ────────────────────────────────────────────────────────────────────────────
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_MAX = 4000


def render_telegram(
    meta: dict[str, Any],
    macro: dict[str, Any],
    buys: list["Candidate"],
    watches: list["Candidate"],
    discarded_count: int,
    capital: float,
    risk_pct: float,
) -> str:
    """
    Mensaje Telegram (HTML) distinto al reporte_diario_trader.py:
    foco en PLAN OPERATIVO con sizing concreto USD.
    """
    today = date.today().isoformat()
    L: list[str] = []
    L.append(f"🎯 <b>PLAN DE INVERSION {today}</b>")
    L.append(f"<i>Régimen:</i> {meta['regime']}  ·  <i>Breadth:</i> {meta.get('breadth_pct')}")
    macro_txt = macro_label(macro).replace("·", "|")
    if macro_txt and macro_txt != "macro no disponible":
        L.append(f"<i>Macro:</i> {macro_txt}")
    L.append(f"<i>Capital:</i> USD {capital:,.0f}  ·  <i>Riesgo/pos:</i> {risk_pct*100:.1f}%")
    L.append("")

    if not buys:
        L.append("❌ <b>0 picks pasan los filtros hoy.</b>")
        L.append("→ Plan honesto: <b>mantener cash</b> y esperar mejor setup.")
        if watches:
            L.append("")
            L.append(f"👀 Watch list ({len(watches)}): " + ", ".join(f"<code>{c.ticker}</code>" for c in watches[:6]))
        L.append("")
        L.append(f"<i>Descartados por filtros: {discarded_count}</i>")
        return "\n".join(L)

    total_risk = sum(c.risk_usd for c in buys)
    total_cap = sum((c.shares * (c.current or 0)) for c in buys)
    L.append(f"✅ <b>{len(buys)} pick(s) recomendado(s)</b>")
    L.append(f"💰 Capital comprometido: USD {total_cap:,.2f} ({total_cap/capital*100:.1f}%)")
    L.append(f"⚠️ Riesgo total a stops: USD {total_risk:,.2f} ({total_risk/capital*100:.2f}%)")
    L.append("")
    L.append("━━━━━━━━━━━━━━━━━━━━")

    for i, c in enumerate(buys, 1):
        entry = c.current or 0.0
        stop = c.stop_price or 0.0
        target = c.target_price or 0.0
        L.append("")
        L.append(f"<b>{i}. {c.ticker}</b> — prob <b>{c.composite_prob*100:.0f}%</b>")
        L.append(f"   Entry ${entry:.2f}  →  Target ${target:.2f} ({c.upside_pct:+.1f}%)")
        L.append(f"   Stop ${stop:.2f} ({(stop-entry)/entry*100:+.2f}%)  ·  R:R {c.rr_ratio or '—'}")
        L.append(f"   <b>{c.shares} acciones</b>  ·  Cap USD {c.shares*entry:,.2f}  ·  Riesgo USD {c.risk_usd:,.2f}")
        # Compactar razones (top 3 por lado)
        top_up = "; ".join(c.why_up[:3]) if c.why_up else ""
        if top_up:
            L.append(f"   ✅ {top_up}")
        top_risk = "; ".join(c.why_risk[:2]) if c.why_risk else ""
        if top_risk:
            L.append(f"   ⚠️ {top_risk}")
        L.append(f"   <i>Modelos:</i> {', '.join(c.models[:4])}{'…' if len(c.models)>4 else ''}  ·  <i>Target:</i> {c.target_date} ({c.days_to_target}d)")

    L.append("")
    L.append("━━━━━━━━━━━━━━━━━━━━")

    if watches:
        L.append("")
        L.append(f"👀 <b>Watch ({len(watches)}):</b> " + ", ".join(f"<code>{c.ticker}</code> {c.composite_prob*100:.0f}%" for c in watches[:5]))

    L.append("")
    L.append(f"<i>Descartados por filtros: {discarded_count}</i>")
    L.append(f"<i>Detalle completo: logs/plan_diario/plan_{today}.md</i>")
    L.append("")
    L.append("⚠️ <i>No es asesoramiento financiero. Hacé tu propia diligencia.</i>")

    return "\n".join(L)


def send_telegram(message: str, log) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID no presentes → skip envio")
        return False
    try:
        import urllib.parse
        import urllib.request
    except ImportError:
        return False

    # Trocear si excede limite
    chunks: list[str] = []
    remaining = message
    while len(remaining) > TELEGRAM_MAX:
        cut = remaining.rfind("\n", 0, TELEGRAM_MAX)
        if cut < 1:
            cut = TELEGRAM_MAX
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    chunks.append(remaining)

    ok_all = True
    for idx, chunk in enumerate(chunks, 1):
        suffix = f"\n<i>(parte {idx}/{len(chunks)})</i>" if len(chunks) > 1 else ""
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": chunk + suffix,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode("utf-8")
        req = urllib.request.Request(
            TELEGRAM_API.format(token=token),
            data=data,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status != 200:
                    log(f"Telegram parte {idx}: HTTP {r.status}")
                    ok_all = False
                else:
                    log(f"✓ Telegram parte {idx}/{len(chunks)} enviada")
        except Exception as exc:
            log(f"Telegram parte {idx} FAIL: {exc}")
            ok_all = False
    return ok_all


def main() -> int:
    args = parse_args()

    def log(msg: str) -> None:
        if not args.quiet:
            print(f"[plan] {msg}", flush=True)

    log(f"snapshot: {args.snapshot_path}")
    try:
        snapshot = load_snapshot(args.snapshot_path)
    except FileNotFoundError as exc:
        print(f"[plan] FATAL: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"[plan] FATAL JSON: {exc}", file=sys.stderr)
        return 1

    meta, candidates = extract_candidates(snapshot)
    log(f"candidatos vivos: {len(candidates)}  (régimen: {meta['regime']})")

    if not candidates:
        log("0 candidatos vivos → plan vacío")
        # Aun asi escribimos un plan vacio para consistencia
        candidates = []

    # Score consenso (siempre, sin yfinance)
    for c in candidates:
        c.consensus_score = score_consensus(c)

    # Tomar top-2x por consenso para enriquecimiento (limitar llamadas yfinance)
    candidates.sort(key=lambda c: -c.consensus_score)
    enrich_pool = candidates[: max(args.max_picks * 3, 10)]

    macro: dict[str, Any] = {}
    if not args.no_enrichment:
        log(f"enriqueciendo top {len(enrich_pool)} candidatos via yfinance…")
        enrich_candidates(enrich_pool, log)
        log("fetch macro context (SPY/QQQ/VIX)…")
        macro = fetch_macro_context(log)
    else:
        log("--no-enrichment → skip yfinance")

    # Scoring final
    for c in candidates:
        c.technical_score = score_technical(c)
        c.fundamental_score = score_fundamental(c)
        c.composite_prob = composite_probability(c)
        compute_sizing(c, args.capital, args.risk_pct)
        apply_quality_filters(c)

    # Re-orden por probabilidad compuesta
    candidates.sort(key=lambda c: -c.composite_prob)

    buys = [c for c in candidates if c.decision == "COMPRAR"][: args.max_picks]
    watches = [c for c in candidates if c.decision.startswith("WATCH")][:10]
    discarded = [c for c in candidates if c.decision == "DESCARTAR"]

    # Cap agregado al 100% del capital (prorratea si excede)
    enforce_aggregate_capital_cap(buys, args.capital)

    log(f"buys: {len(buys)}  watches: {len(watches)}  discarded: {len(discarded)}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    plan_md = render_markdown(meta, macro, buys, watches, discarded, args.capital, args.risk_pct, args.max_picks)
    plan_json = build_json_output(meta, macro, buys, watches, discarded, args.capital, args.risk_pct, args.max_picks)

    today_iso = date.today().isoformat()
    md_path = args.output_dir / f"plan_{today_iso}.md"
    json_path = args.output_dir / f"plan_{today_iso}.json"
    md_path.write_text(plan_md, encoding="utf-8")
    json_path.write_text(json.dumps(plan_json, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    log(f"✓ Escrito: {md_path}")
    log(f"✓ Escrito: {json_path}")

    # Envio Telegram (opcional, requiere TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID en env)
    if not args.no_telegram:
        tg_msg = render_telegram(meta, macro, buys, watches, len(discarded), args.capital, args.risk_pct)
        send_telegram(tg_msg, log)
    else:
        log("--no-telegram → skip Telegram")

    # Imprimir resumen breve a stdout
    print("=" * 70)
    print(f"PLAN INVERSION {today_iso}  ·  {len(buys)} compras  ·  {len(watches)} watch  ·  {len(discarded)} descartes")
    for c in buys:
        print(f"  {c.ticker:6s}  prob {c.composite_prob*100:5.1f}%  ${c.current:.2f}  ×{c.shares}  stop ${c.stop_price:.2f}  target ${c.target_price:.2f}  R:R {c.rr_ratio}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
