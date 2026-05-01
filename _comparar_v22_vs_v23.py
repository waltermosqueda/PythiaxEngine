#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COMPARACION REAL: ml_trading_v22  vs  ml_trading_v23
=======================================================
• Mismos datos de TitanDB
• Solo tickers que REALMENTE están en la DB
• Output visible (sin suprimir stdout) para ver progreso
• Resultado en pantalla: picks BUY de cada modelo, overlap
"""
import sys, time, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from titan_system.core.database import TitanDB

import pandas as pd
import numpy as np

# ── PARÁMETROS ────────────────────────────────────────────────────────────────
MAX_TICKERS = 8     # ← pequeño para que v22 termine en tiempo razonable
MIN_ROWS    = 260
# Cortar datos en fecha bull market → fuerza picks BUY reales para comparar
# (2025-12-31 mercado en recuperación post-crash, modelos deberían generar BUYs)
DATE_CUTOFF = "2025-12-31"
# ─────────────────────────────────────────────────────────────────────────────

W  = "\033[97m"; G  = "\033[92m"; R  = "\033[91m"
Y  = "\033[93m"; C  = "\033[96m"; B  = "\033[94m"
DIM= "\033[2m";  BOLD="\033[1m"; RST= "\033[0m"
line = lambda: print(f"{DIM}{'─'*72}{RST}")

def load_v(path_rel, model_id):
    path = ROOT / path_rel
    spec = importlib.util.spec_from_file_location(model_id, str(path))
    m    = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

print(f"\n{BOLD}{C}{'═'*72}")
print("  COMPARACION EN VIVO: v22 (original) vs v23 (ultra-fast)")
print(f"{'═'*72}{RST}\n")

# ── PASO 1: Cargar módulos ────────────────────────────────────────────────────
print(f"{Y}[1/5] Cargando módulos...{RST}")
v22 = load_v("ml_investigacion/ml_trading_v22.py", "v22")
v23 = load_v("ml_investigacion/ml_trading_v23.py", "v23")

# Subconjunto compartido (mismos tickers en ambos modelos)
UNIVERSE = list(v22.ACTIVOS.keys())
if MAX_TICKERS:
    UNIVERSE = UNIVERSE[:MAX_TICKERS]
# Siempre incluir SPY
if "SPY" not in UNIVERSE:
    UNIVERSE = ["SPY"] + UNIVERSE

print(f"  {G}v22 loaded{RST}  · {G}v23 loaded{RST}")

# ── PASO 2: Descubrir tickers en DB ──────────────────────────────────────────
print(f"\n{Y}[2/5] Cargando datos reales de TitanDB...{RST}")
t0 = time.time()

def normalize(df):
    work = df.copy().rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"})
    keep = [c for c in ["Open","High","Low","Close","Volume"] if c in work.columns]
    work = work[keep].copy()
    work.index = pd.to_datetime(work.index)
    return work.sort_index()

# Primero SPY, luego el resto del universo
all_candidates = list(dict.fromkeys(["SPY"] + list(v22.ACTIVOS.keys())))
histories = {}
with TitanDB() as db:
    for ticker in all_candidates:
        df = db.get_prices(ticker)
        if df.empty:
            continue
        norm = normalize(df)
        # Recortar a DATE_CUTOFF para simular predicción en esa fecha
        norm = norm[norm.index <= pd.Timestamp(DATE_CUTOFF)]
        if len(norm) >= MIN_ROWS:
            histories[ticker] = norm

t_db = time.time() - t0
print(f"  {G}{len(histories)} tickers OK en DB{RST}  ({t_db:.1f}s)")
if "SPY" not in histories:
    print(f"  {R}FATAL: SPY no disponible en DB{RST}")
    sys.exit(1)

latest_date = histories["SPY"].index[-1].date().isoformat()
print(f"  Última fecha usada (cutoff): {BOLD}{Y}{latest_date}{RST}  ← mercado alcista para forzar picks BUY")

# Seleccionar subconjunto (SPY + primeros MAX_TICKERS del universo que estén en DB)
ticker_subset = ["SPY"] + [t for t in all_candidates if t != "SPY" and t in histories][:MAX_TICKERS]
print(f"  Universo de comparación: {BOLD}{len(ticker_subset)}{RST} tickers ({MAX_TICKERS} activos + SPY)")
print(f"  {DIM}{', '.join(ticker_subset)}{RST}")

# ── Construir data dict compartido ─────────────────────────────────────────────
shared_data = {
    ticker: histories[ticker][["Open","High","Low","Close","Volume"]].copy()
    for ticker in ticker_subset
}

# ══════════════════════════════════════════════════════════════════════════════
# ── PASO 3: Ejecutar V22 (modelo original) ────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{Y}[3/5] Ejecutando V22 (modelo ORIGINAL)...{RST}")
line()
t_v22_start = time.time()

picks_v22 = []
notes_v22 = []
sigs22_by_ticker = {}
try:
    eng22 = v22.TradingEngine()
    eng22.data    = shared_data.copy()
    eng22.spy_ret = eng22.data["SPY"]["Close"].pct_change().fillna(0)
    print(f"  Calculando features V22...")
    eng22.calcular_features()
    print(f"  Entrenando V22 (GBC/RF/ET/MLP/LR/XGB — puede tardar varios minutos)...")
    eng22.entrenar_global(verbose=True)
    sigs22 = eng22.generar_senales()

    # Guardar TODAS las señales (no solo BUY) para comparación completa
    sigs22_by_ticker = {s["ticker"]: s for s in sigs22 if s.get("ticker") != "SPY"}
    buys22 = [s for s in sigs22 if s.get("ticker") != "SPY"
              and (s.get("señal") or s.get("seÃ±al")) == "BUY"]
    picks_v22 = [(s["ticker"], round(s.get("score",0),1), round(s.get("confianza",0),1))
                 for s in buys22]
    t_v22 = time.time() - t_v22_start
    print(f"\n  {G}V22 completado en {t_v22:.1f}s{RST}")
    print(f"  Señales totales: {len(sigs22)}   BUYs: {BOLD}{len(picks_v22)}{RST}")
    for s in sorted(sigs22, key=lambda x: x.get('score',0), reverse=True):
        if s.get('ticker') == 'SPY': continue
        sig = (s.get('señal') or s.get('seÃ±al') or 'HOLD')
        col = G if sig=='BUY' else (R if sig=='SELL' else DIM)
        print(f"    {col}{sig:<5}{RST}  {BOLD}{s['ticker'].ljust(7)}{RST}  score={round(s.get('score',0),1):5.1f}  conf={round(s.get('confianza',0),1):5.1f}%")

except Exception as e:
    t_v22 = time.time() - t_v22_start
    notes_v22.append(str(e))
    print(f"  {R}ERROR en V22: {e}{RST}")

# ══════════════════════════════════════════════════════════════════════════════
# ── PASO 4: Ejecutar V23 (modelo optimizado) ──────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{Y}[4/5] Ejecutando V23 (Ultra-Fast)...{RST}")
line()
t_v23_start = time.time()

picks_v23 = []
notes_v23 = []
sigs23_by_ticker = {}
try:
    eng23 = v23.TradingEngine()
    eng23.data    = shared_data.copy()
    eng23.spy_ret = eng23.data["SPY"]["Close"].pct_change().fillna(0)
    print(f"  Calculando features V23 (paralelo)...")
    eng23.calcular_features()
    print(f"  Entrenando V23 (HistGBC/RF80/ET80/LR/XGB100)...")
    eng23.entrenar_global(verbose=True)
    sigs23 = eng23.generar_senales()

    # Guardar TODAS las señales (no solo BUY) para comparación completa
    sigs23_by_ticker = {s["ticker"]: s for s in sigs23 if s.get("ticker") != "SPY"}
    buys23 = [s for s in sigs23 if s.get("ticker") != "SPY"
              and s.get("señal") == "BUY"]
    picks_v23 = [(s["ticker"], round(s.get("score",0),1), round(s.get("confianza",0),1))
                 for s in buys23]
    t_v23 = time.time() - t_v23_start
    print(f"\n  {G}V23 completado en {t_v23:.1f}s{RST}")
    print(f"  Señales totales: {len(sigs23)}   BUYs: {BOLD}{len(picks_v23)}{RST}")
    for s in sorted(sigs23, key=lambda x: x.get('score',0), reverse=True):
        if s.get('ticker') == 'SPY': continue
        sig = s.get('señal','HOLD')
        col = G if sig=='BUY' else (R if sig=='SELL' else DIM)
        print(f"    {col}{sig:<5}{RST}  {BOLD}{s['ticker'].ljust(7)}{RST}  score={round(s.get('score',0),1):5.1f}  conf={round(s.get('confianza',0),1):5.1f}%")

except Exception as e:
    t_v23 = time.time() - t_v23_start
    notes_v23.append(str(e))
    print(f"  {R}ERROR en V23: {e}{RST}")

# ══════════════════════════════════════════════════════════════════════════════
# ── PASO 5: TABLA COMPARATIVA ─────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{Y}[5/5] RESULTADO COMPARATIVO{RST}")
line()

set22 = set(t for t,_,_ in picks_v22)
set23 = set(t for t,_,_ in picks_v23)
coincidentes  = set22 & set23
solo_v22      = set22 - set23
solo_v23      = set23 - set22

# ── Tabla comparativa completa (TODOS los tickers, todas las señales) ─────────
print(f"\n  {BOLD}{'TICKER':<9} {'─── V22 ORIGINAL ───':^24} {'─── V23 FAST ───':^22} MATCH{RST}")
print(f"  {'─'*72}")

# Todos los tickers del universo (excluyendo SPY)
all_tickers = [t for t in ticker_subset if t != 'SPY']
agreements = 0
for tk in sorted(all_tickers):
    s22 = sigs22_by_ticker.get(tk, {})
    s23 = sigs23_by_ticker.get(tk, {})
    sig22 = (s22.get('señal') or s22.get('seÃ±al') or 'N/A')
    sig23 = s23.get('señal', 'N/A')
    sc22  = round(s22.get('score',0), 1)
    sc23  = round(s23.get('score',0), 1)
    cf22  = round(s22.get('confianza',0), 1)
    cf23  = round(s23.get('confianza',0), 1)
    match = sig22 == sig23
    if match: agreements += 1
    c22 = G if sig22=='BUY' else (R if sig22=='SELL' else DIM)
    c23 = G if sig23=='BUY' else (R if sig23=='SELL' else DIM)
    mc  = G if match else Y
    print(f"  {BOLD}{tk:<9}{RST}  {c22}{sig22:<5}{RST} score={sc22:5.1f} cf={cf22:4.1f}%    {c23}{sig23:<5}{RST} score={sc23:5.1f} cf={cf23:4.1f}%   {mc}{'✓' if match else '≠'}{RST}")

print(f"  {'─'*72}")
agreement_pct = agreements/len(all_tickers)*100 if all_tickers else 100
print(f"  Señales idénticas: {BOLD}{G}{agreements}/{len(all_tickers)}{RST} tickers ({G}{agreement_pct:.0f}% acuerdo{RST})")

print()
print(f"  {BOLD}RESUMEN:{RST}")
print(f"  Picks BUY V22 (original):   {BOLD}{len(set22)}{RST} tickers")
print(f"  Picks BUY V23 (ultra-fast): {BOLD}{len(set23)}{RST} tickers")
print(f"  Coincidencia total señales: {BOLD}{G}{agreements}/{len(all_tickers)}{RST} ({G}{agreement_pct:.0f}%{RST})")
if solo_v22:
    print(f"  Solo BUY en V22:            {Y}{', '.join(sorted(solo_v22))}{RST}")
if solo_v23:
    print(f"  Solo BUY en V23:            {Y}{', '.join(sorted(solo_v23))}{RST}")

speedup = t_v22 / max(t_v23, 0.1)
print(f"  ⏱  V22 tardó:  {BOLD}{t_v22:.1f}s{RST}  ({t_v22/60:.1f} min)")
print(f"  ⏱  V23 tardó:  {BOLD}{t_v23:.1f}s{RST}  ({t_v23/60:.1f} min)")
print(f"  🚀 Speedup:     {BOLD}{G}{speedup:.1f}x más rápido{RST}")

print()
if agreement_pct >= 80:
    verdict = f"{G}{BOLD}✓ ACEPTADO — V23 reproduce las predicciones del V22 ({agreement_pct:.0f}% acuerdo, {speedup:.1f}x speedup){RST}"
elif agreement_pct >= 50:
    verdict = f"{Y}{BOLD}⚠  PARCIAL — {agreements}/{len(all_tickers)} señales coinciden{RST}"
else:
    verdict = f"{R}{BOLD}✗ DIVERGENCIA — las predicciones difieren significativamente{RST}"

print(f"  VEREDICTO: {verdict}")
line()
print()
