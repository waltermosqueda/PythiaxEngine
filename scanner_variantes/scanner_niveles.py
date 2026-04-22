"""
SCANNER DE NIVELES — Sistema de alertas con ranking de agresividad
==================================================================
Basado en toda la investigación acumulada (sesiones 1-13).

JERARQUÍA DE NIVELES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  🔥🔥🔥  NIVEL 1 — FUEGO MÁXIMO      Compra sí o sí, todo alineado
  ⭐⭐     NIVEL 2 — COMPRA PREMIUM    V4 validado (Sharpe 14.15 histórico)
  💪       NIVEL 3 — COMPRA FUERTE     BESTIA-DOMADA (WF 3/5, Sharpe 7.79)
  👀       NIVEL 4 — EN RADAR         Setup casi listo, vigilar mañana
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CRITERIOS POR NIVEL:

  🔥 NIVEL 1 — FUEGO MÁXIMO:
     Requiere V4 (PREMIUM) + Stoch golden zone + capitulación extrema
     RSI < 22 + SPY>SMA50+baja_vol + score>30 + MACD↑
     + Stoch 10-25 (saliendo del fondo, no en piso absoluto)
     + relperf20 < -20% (cayó mucho más que el mercado = capitulación)
     Hold: 15 días | WR histórico: ~100% | Avg: +8%+ | Muy raro

  ⭐ NIVEL 2 — COMPRA PREMIUM:
     V4 estándar (el más validado, mayor Sharpe histórico)
     RSI < 25 + SPY>SMA50+baja_vol + score>30 + MACD↑ + vol<1.5
     Hold: 10 días | WR histórico: 80%+ | Sharpe 14.15
     (V4 sin relperf ni Stoch — pureza del sistema original)

  💪 NIVEL 3 — COMPRA FUERTE:
     BESTIA-DOMADA (agresivo pero con protección SMA200)
     RSI < 22 + SPY>SMA200 + Stoch<25 + score>20
     Hold: 15 días | WR histórico: 68% | Sharpe 7.79 | WF 3/5 ✓
     (NO requiere SPY SMA50 = más señales que V4)

  👀 NIVEL 4 — EN RADAR:
     RSI bajando hacia zona, setup formándose
     RSI < 28 + SPY>SMA200 + score>15 + dsma<-7%
     Mensaje: vigilar mañana, puede escalar a 3 o 2

RSI: Wilder's smoothing ewm(com=13) — VERIFICADO
Universo: 258 tickers (titan.db)
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os
import pandas as pd
import numpy as np
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from titan_system.core.database import TitanDB
from titan_system.core.data_loader import ACTIVOS, CONTEXT_TICKERS

ALL_TICKERS = list(set(ACTIVOS + CONTEXT_TICKERS))

# ── Indicadores ───────────────────────────────────────────────────────────────

def calc_rsi_wilder(close, period=14):
    """Wilder's RSI — ewm(com=period-1, adjust=False). VERIFICADO."""
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False).mean()
    return 100 - 100 / (1 + gain / (loss + 1e-10))

def calc_macd_hist(close, fast=12, slow=26, signal=9):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd  = ema_f - ema_s
    return macd - macd.ewm(span=signal, adjust=False).mean()

def calc_atr(high, low, close, period=14):
    tr = pd.concat([
        (high - low),
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_stoch_k(high, low, close, period=14):
    lo = low.rolling(period).min()
    hi = high.rolling(period).max()
    return (close - lo) / (hi - lo + 1e-10) * 100

def calc_score(rsi, dsma, macd_acc_n, vr):
    return (max(0, min(40, (30-rsi)/30*40)) +
            max(0, min(30, (abs(dsma)-5)/15*30)) +
            max(0, min(20, macd_acc_n*5)) +
            max(0, min(10, (1.5-vr)/1.5*10)))

def rsi_slope(rsi_series):
    return rsi_series.iloc[-1] - rsi_series.iloc[-4] if len(rsi_series) >= 4 else 0.0

# ── Clasificador de niveles ───────────────────────────────────────────────────

def classify_signal(ind, spy_ok_sma50, spy_ok_sma200, spy_lowvol):
    """
    Retorna (nivel, razon) donde nivel 1=mejor, 4=radar, 0=sin señal.
    """
    rsi     = ind['rsi']
    dsma    = ind['dsma']
    score   = ind['score']
    vr      = ind['vr']
    macd_up = ind['macd_up']
    stoch   = ind['stoch_k']
    relp20  = ind['relperf20']
    slope   = ind['rsi_slope']

    # ── NIVEL 1: FUEGO MÁXIMO ─────────────────────────────────────────────────
    # V4 + Stoch golden zone + capitulación extrema
    if (rsi < 22 and dsma < -10 and score > 30 and
            spy_ok_sma50 and spy_lowvol and macd_up and vr < 1.5 and
            stoch >= 10 and stoch < 25 and relp20 < -20):
        reasons = []
        if rsi < 18:       reasons.append(f"RSI EXTREMO {rsi:.1f}")
        if relp20 < -30:   reasons.append(f"CAPITULACION {relp20:+.1f}%")
        if slope >= 3:     reasons.append("GIRO FUERTE")
        if score > 45:     reasons.append(f"SCORE MAXIMO {score:.0f}")
        return 1, " | ".join(reasons) if reasons else "Todo alineado"

    # ── NIVEL 2: COMPRA PREMIUM (V4 puro) ────────────────────────────────────
    if (rsi < 25 and dsma < -10 and score > 30 and
            spy_ok_sma50 and spy_lowvol and macd_up and vr < 1.5):
        reasons = []
        if rsi < 22:       reasons.append(f"RSI Profundo {rsi:.1f}")
        if stoch >= 10 and stoch < 25: reasons.append(f"Stoch Golden {stoch:.0f}")
        if relp20 < -20:   reasons.append(f"Capitulacion {relp20:+.0f}%")
        if score > 40:     reasons.append(f"Score alto {score:.0f}")
        return 2, " | ".join(reasons) if reasons else "V4 validado"

    # ── NIVEL 3: COMPRA FUERTE (BESTIA-DOMADA) ────────────────────────────────
    if (rsi < 22 and dsma < -10 and score > 20 and
            spy_ok_sma200 and stoch < 25):
        reasons = []
        if spy_ok_sma50:   reasons.append("SPY bull")
        if relp20 < -25:   reasons.append(f"Capitulacion {relp20:+.0f}%")
        if stoch >= 10:    reasons.append(f"Stoch ok {stoch:.0f}")
        if slope >= 3:     reasons.append("Giro fuerte")
        if not spy_ok_sma50: reasons.append("Solo SMA200")
        return 3, " | ".join(reasons) if reasons else "BESTIA-DOMADA"

    # ── NIVEL 4: EN RADAR ────────────────────────────────────────────────────
    if (rsi < 28 and dsma < -7 and score > 15 and spy_ok_sma200):
        gap_to_2  = max(0, rsi - 25)
        gap_score = max(0, 30 - score)
        reasons   = []
        if gap_to_2 > 0:  reasons.append(f"RSI necesita -{gap_to_2:.1f} mas ({rsi:.1f})")
        if not macd_up:   reasons.append("Esperar MACD")
        if not spy_ok_sma50: reasons.append("SPY solo SMA200")
        if stoch < 10:    reasons.append(f"Stoch fondo {stoch:.0f}")
        return 4, " | ".join(reasons) if reasons else "Vigilar mañana"

    return 0, ""

# ── Scanner principal ─────────────────────────────────────────────────────────

def scan(date_str=None):
    with TitanDB() as db:
        all_data = {}
        for t in ALL_TICKERS:
            df = db.get_prices(t, '2024-01-01', '2026-04-02')
            if df is not None and len(df) > 210:
                all_data[t] = df.sort_index()

    spy_df = all_data.get('SPY')
    if spy_df is None:
        print("  ERROR: SPY no disponible.")
        return

    # Fecha de análisis
    if date_str:
        ref_date = pd.Timestamp(date_str)
    else:
        ref_date = spy_df.index[-1]

    spy_sl = spy_df[spy_df.index <= ref_date]
    spy_c  = spy_sl['close']

    # Estado SPY
    spy_ok_sma50  = bool(spy_c.iloc[-1] > spy_c.rolling(50).mean().iloc[-1])
    spy_ok_sma200 = bool(len(spy_c) > 200 and spy_c.iloc[-1] > spy_c.rolling(200).mean().iloc[-1])
    spy_lowvol    = bool(spy_c.pct_change().rolling(20).std().iloc[-1] * 100 < 1.0)
    spy_rsi       = calc_rsi_wilder(spy_c).iloc[-1]
    spy_ret5      = spy_c.pct_change(5).iloc[-1]
    spy_ret20     = spy_c.pct_change(20).iloc[-1]
    spy_sma50_val = spy_c.rolling(50).mean().iloc[-1]
    spy_dist_sma50 = (spy_c.iloc[-1] / spy_sma50_val - 1) * 100

    signals = []

    for ticker, df in all_data.items():
        if ticker in CONTEXT_TICKERS:
            continue

        df_sl = df[df.index <= ref_date]
        if len(df_sl) < 210:
            continue

        c = df_sl['close']; h = df_sl['high']
        l = df_sl['low'];   v = df_sl['volume']

        # Pre-filtro rápido
        rsi_s = calc_rsi_wilder(c)
        rsi14 = rsi_s.iloc[-1]
        if rsi14 >= 30:
            continue

        sma50 = c.rolling(50).mean().iloc[-1]
        price = c.iloc[-1]
        dsma  = (price / sma50 - 1) * 100
        if dsma >= -5:
            continue

        # Indicadores completos
        sl_val  = rsi_slope(rsi_s)
        mh      = calc_macd_hist(c)
        mh_c    = mh.iloc[-1]; mh_p = mh.iloc[-2] if len(mh) > 1 else 0.0
        atr14   = calc_atr(h, l, c).iloc[-1]
        v20     = v.rolling(20).mean().iloc[-1]
        vr      = v.iloc[-1] / (v20 + 1e-10)
        acc_n   = (mh_c - mh_p) / (atr14 * 0.01 + 1e-6)
        score   = calc_score(rsi14, dsma, acc_n, vr)
        stoch   = calc_stoch_k(h, l, c).iloc[-1]
        sma200  = c.rolling(200).mean().iloc[-1]
        rsi70   = calc_rsi_wilder(c, 70).iloc[-1]

        # RelPerf vs SPY
        r5_stock  = c.pct_change(5).iloc[-1]  if len(c) > 5  else 0.0
        r20_stock = c.pct_change(20).iloc[-1] if len(c) > 20 else 0.0
        relperf5  = (r5_stock  - spy_ret5)  * 100
        relperf20 = (r20_stock - spy_ret20) * 100

        # Distancia 52w
        high_52w  = c.rolling(252).max().iloc[-1]
        dist_52w  = (price / high_52w - 1) * 100

        if any(np.isnan(x) for x in [rsi14, dsma, score, sl_val, stoch]):
            continue

        ind = {
            'rsi': rsi14, 'dsma': dsma, 'score': score,
            'vr': vr, 'macd_up': bool(mh_c > mh_p),
            'stoch_k': stoch, 'rsi_slope': sl_val,
            'relperf20': relperf20, 'relperf5': relperf5,
            'rsi70': rsi70,
            'dist_52w': dist_52w,
            'dist_sma200': (price / sma200 - 1) * 100,
            'price': price, 'atr': atr14,
        }

        nivel, razon = classify_signal(ind, spy_ok_sma50, spy_ok_sma200, spy_lowvol)

        if nivel > 0:
            hold_rec = 15 if nivel in (1, 3) else 10
            signals.append({
                'nivel': nivel, 'ticker': ticker, 'razon': razon,
                'hold': hold_rec, **ind
            })

    return signals, {
        'spy_price': spy_c.iloc[-1],
        'spy_sma50': spy_ok_sma50,
        'spy_sma200': spy_ok_sma200,
        'spy_lowvol': spy_lowvol,
        'spy_rsi': spy_rsi,
        'spy_dist_sma50': spy_dist_sma50,
        'spy_ret5': spy_ret5 * 100,
        'spy_ret20': spy_ret20 * 100,
        'ref_date': ref_date,
    }

# ── Imprimir resultados ───────────────────────────────────────────────────────

NIVEL_META = {
    1: ("🔥🔥🔥 FUEGO MÁXIMO",    "COMPRA SÍ O SÍ",      "~100% WR hist | Avg +8%+ | Hold 15d"),
    2: ("⭐⭐  COMPRA PREMIUM",    "COMPRA PRIMERO",       "80%+ WR hist  | Sharpe 14 | Hold 10d"),
    3: ("💪   COMPRA FUERTE",     "COMPRA CONFIRMADA",    "68% WR hist   | Sharpe 7.8| Hold 15d"),
    4: ("👀   EN RADAR",          "VIGILAR MAÑANA",       "Setup en formación — puede escalar"),
}

def print_results(signals, spy_info):
    date_str = str(spy_info['ref_date'])[:10]

    print()
    print("╔" + "═"*78 + "╗")
    print("║" + "  SCANNER DE NIVELES — TITAN SYSTEM".center(78) + "║")
    print("║" + f"  Fecha: {date_str}   |   258 tickers   |   RSI Wilder verificado".center(78) + "║")
    print("╚" + "═"*78 + "╝")

    # Estado SPY
    sma50_tag  = "✓ SPY > SMA50"  if spy_info['spy_sma50']  else "✗ SPY < SMA50"
    sma200_tag = "✓ SPY > SMA200" if spy_info['spy_sma200'] else "✗ SPY < SMA200"
    vol_tag    = "✓ Vol baja"     if spy_info['spy_lowvol']  else "⚠ Vol alta"

    regime_v4  = spy_info['spy_sma50'] and spy_info['spy_lowvol']
    regime_bd  = spy_info['spy_sma200']

    print(f"\n  📊 ESTADO MERCADO (SPY):")
    print(f"     Precio: ${spy_info['spy_price']:.2f}  |  RSI: {spy_info['spy_rsi']:.1f}  |  "
          f"Dist SMA50: {spy_info['spy_dist_sma50']:+.1f}%")
    print(f"     {sma50_tag}  |  {sma200_tag}  |  {vol_tag}")
    print(f"     Ret 5d: {spy_info['spy_ret5']:+.2f}%  |  Ret 20d: {spy_info['spy_ret20']:+.2f}%")

    if not regime_bd:
        print(f"\n  ⛔ MERCADO BAJISTA (SPY < SMA200) — Todos los niveles suspendidos.")
        print(f"     No operar hasta que SPY recupere SMA200.\n")
        return
    elif not regime_v4:
        print(f"\n  ⚠️  SPY EN CORRECCIÓN (< SMA50 o vol alta) — Niveles 1 y 2 no activos.")
        print(f"     Solo Nivel 3 y 4 disponibles.\n")
    else:
        print(f"\n  ✅ RÉGIMEN: Bull market activo — Todos los niveles operativos.\n")

    if not signals:
        print("  Sin señales hoy. El mercado no presenta setups válidos.\n")
        return

    # Ordenar: nivel (asc) → RSI (asc, más oversold primero) → score (desc)
    signals_sorted = sorted(signals, key=lambda x: (x['nivel'], x['rsi'], -x['score']))

    by_nivel = {}
    for s in signals_sorted:
        by_nivel.setdefault(s['nivel'], []).append(s)

    total = len(signals)
    print(f"  📋 {total} señal{'es' if total>1 else ''} encontrada{'s' if total>1 else ''} hoy:\n")

    for nivel in sorted(by_nivel.keys()):
        sigs   = by_nivel[nivel]
        emoj, accion, stats = NIVEL_META[nivel]

        print(f"  {'─'*78}")
        print(f"  {emoj}")
        print(f"  Acción:  {accion}")
        print(f"  Stats:   {stats}")
        print(f"  Señales: {len(sigs)}")
        print(f"  {'─'*78}")

        for s in sigs:
            stoch_tag = ""
            if 10 <= s['stoch_k'] < 25:
                stoch_tag = " 🎯"  # golden zone

            relp_tag = ""
            if s['relperf20'] < -25:
                relp_tag = " 💥"  # capitulación extrema
            elif s['relperf20'] < -15:
                relp_tag = " ⚡"

            slope_tag = ""
            if s['rsi_slope'] >= 3:
                slope_tag = " ↑"
            elif s['rsi_slope'] < -3:
                slope_tag = " ↓"

            print(f"\n  {'★' if nivel==1 else '●'} [{nivel}] {s['ticker']:<7}  "
                  f"${s['price']:.2f}  |  Hold {s['hold']}d")
            print(f"    RSI: {s['rsi']:.1f}{slope_tag}  |  "
                  f"Dist SMA50: {s['dsma']:+.1f}%  |  "
                  f"Score: {s['score']:.0f}  |  "
                  f"Vol: {s['vr']:.2f}x")
            print(f"    Stoch: {s['stoch_k']:.1f}{stoch_tag}  |  "
                  f"RSI70: {s['rsi70']:.1f}  |  "
                  f"RelPerf20: {s['relperf20']:+.1f}%{relp_tag}  |  "
                  f"RelPerf5: {s['relperf5']:+.1f}%")
            print(f"    Dist SMA200: {s['dist_sma200']:+.1f}%  |  "
                  f"Dist 52w-high: {s['dist_52w']:+.1f}%  |  "
                  f"ATR: {s['atr']:.2f}")
            print(f"    ▶ {s['razon']}")

        print()

    # Resumen de compra
    print(f"  {'═'*78}")
    print(f"  RESUMEN DE ACCIÓN:")
    for nivel in sorted(by_nivel.keys()):
        sigs  = by_nivel[nivel]
        emoj, accion, _ = NIVEL_META[nivel]
        tickers = ', '.join(s['ticker'] for s in sigs)
        print(f"  {emoj:<25}  →  {tickers}")

    # Indicadores de referencia de los tops
    if 1 in by_nivel or 2 in by_nivel:
        top_nivel = 1 if 1 in by_nivel else 2
        print(f"\n  💡 COMENZAR CON: {by_nivel[top_nivel][0]['ticker']} "
              f"(Nivel {top_nivel}, RSI {by_nivel[top_nivel][0]['rsi']:.1f}, "
              f"Score {by_nivel[top_nivel][0]['score']:.0f})")
    elif 3 in by_nivel:
        s = by_nivel[3][0]
        print(f"\n  💡 COMENZAR CON: {s['ticker']} "
              f"(Nivel 3, RSI {s['rsi']:.1f}, Score {s['score']:.0f})")

    print(f"  {'═'*78}\n")

    # Leyenda de iconos
    print("  Iconos:  🎯 Stoch golden zone (10-25)  |  💥 Capitulación extrema (relperf<-25%)")
    print("           ⚡ Capitulación fuerte (relperf<-15%)  |  ↑ RSI slope ≥+3  |  ↓ slope <-3")
    print()


# ── Ejecutar ──────────────────────────────────────────────────────────────────

def main():
    print("\n  Cargando datos y escaneando...", flush=True)
    result = scan()
    if result is None:
        return
    signals, spy_info = result
    print_results(signals, spy_info)


if __name__ == '__main__':
    main()
