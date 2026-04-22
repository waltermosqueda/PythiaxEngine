"""
BESTIA-DOMADA — Taming the Beast
=================================
Objetivo: conservar el potencial explosivo de BESTIA (203 trades, +2853% total)
pero eliminar el MDD catastrófico (-97.2%).

Hipótesis central:
  BESTIA pierde en SECUENCIAS porque opera en bear markets donde RSI<22
  es "normal" (stocks siguen cayendo). La clave es distinguir:
    ✓ "Dip temporal en stock sano"   → RSI<22 raro, rebote probable
    ✗ "Colapso estructural"          → RSI<22 frecuente, sigue cayendo

Nuevos indicadores fuera de la caja:
  1. SPY > SMA200      — bull/bear market line (más permisivo que V4's SMA50)
  2. RSI(70)           — RSI de largo plazo (~semanal proxy)
                         Si RSI70 < 30: stock en declive estructural → evitar
  3. Stochastic K(14)  — doble confirmación oversold (diferente geometría que RSI)
                         Precio dentro de rango 14d: <20 = oversold
  4. Días consecutivos bajando (últimos 5d) — exhaustion signal
  5. Distancia al mínimo 52 semanas — soporte estructural
  6. Rendimiento relativo vs SPY 20d — individual vs sistémico

Variantes a testear (un solo pase de datos):
  BESTIA original     → referencia
  V4 baseline         → referencia alta calidad
  DA-1: + SPY>SMA200                            (primer dique)
  DA-2: + SPY>SMA200 + RSI70>30               (+ no declive estructural)
  DA-3: + SPY>SMA200 + slope no zona muerta    (+ nuestro descubrimiento)
  DA-4: + SPY>SMA200 + Stoch<25               (+ doble oversold)
  DA-5: + SPY>SMA200 + RSI70>30 + slope        (combinación 2+3)
  DA-6: + SPY>SMA200 + RSI70>30 + consec>=2   (+ exhaustion)
  DA-7: + SPY>SMA200 + dist52w > -60%          (+ tiene soporte)
  DA-8: + SPY>SMA200 + relperf < -5%           (individual vs sistémico)
  DA-9: + SPY>SMA200 + RSI70>30 + Stoch<25 + slope  (kitchen sink)
  DA-FINAL: mejor combinación encontrada

Universo: 258 tickers | Sep 2024 – Mar 2026 | Hold 15d
RSI: Wilder ewm(com=13) — VERIFICADO
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os
import pandas as pd
import numpy as np
import warnings

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from titan_system.core.database import TitanDB
from titan_system.core.data_loader import ACTIVOS, CONTEXT_TICKERS

ALL_TICKERS  = list(set(ACTIVOS + CONTEXT_TICKERS))
PERIOD_START = '2024-09-01'
PERIOD_END   = '2026-03-28'
HOLD_DAYS    = 15

# ── Indicadores ───────────────────────────────────────────────────────────────

def calc_rsi_wilder(close, period=14):
    """Wilder's RSI — ewm(com=period-1). VERIFICADO."""
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

def calc_stochastic_k(high, low, close, period=14):
    """Stochastic %K: posición del precio dentro del rango de N períodos."""
    lo_n  = low.rolling(period).min()
    hi_n  = high.rolling(period).max()
    return (close - lo_n) / (hi_n - lo_n + 1e-10) * 100

def calc_score(rsi, dist_sma50, macd_acc_n, vol_ratio):
    return (max(0, min(40, (30 - rsi) / 30 * 40)) +
            max(0, min(30, (abs(dist_sma50) - 5) / 15 * 30)) +
            max(0, min(20, macd_acc_n * 5)) +
            max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10)))

# ── Recopilación única ────────────────────────────────────────────────────────

def collect_pool(all_data, spy_df):
    """
    Pase único con filtros mínimos (RSI<25, dsma<-8).
    Guarda TODOS los nuevos indicadores.
    """
    records = []
    recent  = {}

    # Pre-calcular estado SPY por fecha (SMA50, SMA200, vol)
    spy_states = {}
    spy_c_series = spy_df['close']
    for date in spy_df.index:
        sl = spy_df[spy_df.index <= date]
        if len(sl) < 210:
            spy_states[date] = {'sma50': False, 'sma200': False, 'low_vol': False}
            continue
        c = sl['close']
        sma50_ok  = bool(c.iloc[-1] > c.rolling(50).mean().iloc[-1])
        sma200_ok = bool(c.iloc[-1] > c.rolling(200).mean().iloc[-1])
        low_vol   = bool(c.pct_change().rolling(20).std().iloc[-1] * 100 < 1.0)
        spy_states[date] = {
            'sma50':  sma50_ok,
            'sma200': sma200_ok,
            'low_vol': low_vol,
            'spy_ret20': float(c.pct_change(20).iloc[-1]) if len(c) >= 21 else 0.0,
        }

    dates = sorted(d for d in spy_df.index
                   if PERIOD_START <= str(d)[:10] <= PERIOD_END)

    for date in dates:
        spy_st = spy_states.get(date, {})

        for ticker, df in all_data.items():
            if ticker in CONTEXT_TICKERS:
                continue
            df_sl = df[df.index <= date]
            if len(df_sl) < 210:   # necesitamos 200+ para RSI70 y SMA200
                continue
            if ticker in recent and (date - recent[ticker]).days < 3:
                continue

            c = df_sl['close']; h = df_sl['high']
            l = df_sl['low'];   v = df_sl['volume']

            # ── Filtro rápido (mínimo) ────────────────────────────────────────
            rsi_s = calc_rsi_wilder(c, 14)
            rsi14 = rsi_s.iloc[-1]
            if rsi14 >= 25:
                continue

            sma50 = c.rolling(50).mean().iloc[-1]
            price = c.iloc[-1]
            dsma  = (price / sma50 - 1) * 100
            if dsma >= -8:
                continue

            # ── Indicadores estándar ──────────────────────────────────────────
            rsi_sl  = rsi_s.iloc[-1] - rsi_s.iloc[-4] if len(rsi_s) >= 4 else 0.0
            mh      = calc_macd_hist(c)
            mh_c    = mh.iloc[-1]; mh_p = mh.iloc[-2] if len(mh) > 1 else 0.0
            atr14   = calc_atr(h, l, c).iloc[-1]
            v20     = v.rolling(20).mean().iloc[-1]
            vr      = v.iloc[-1] / (v20 + 1e-10)
            acc_n   = (mh_c - mh_p) / (atr14 * 0.01 + 1e-6)
            score   = calc_score(rsi14, dsma, acc_n, vr)
            macd_up = bool(mh_c > mh_p)

            if any(np.isnan(x) for x in [rsi14, dsma, score, rsi_sl]):
                continue

            # ── Nuevos indicadores ────────────────────────────────────────────

            # RSI largo plazo (70 períodos = ~semanal proxy)
            rsi70 = calc_rsi_wilder(c, 70).iloc[-1]

            # Stochastic K (14 períodos)
            stoch_k = calc_stochastic_k(h, l, c, 14).iloc[-1]

            # Días consecutivos bajando en últimos 5
            last5_ret = c.diff().iloc[-5:]
            consec_down = int((last5_ret < 0).sum())

            # Distancia al mínimo de 52 semanas
            low_52w  = c.rolling(252).min().iloc[-1]
            high_52w = c.rolling(252).max().iloc[-1]
            dist_52w_low  = (price / low_52w - 1) * 100   # >0 = por encima del mínimo
            dist_52w_high = (price / high_52w - 1) * 100  # <0 = por debajo del máximo

            # Rendimiento relativo vs SPY (20 días)
            ret20_stock = float(c.pct_change(20).iloc[-1]) if len(c) >= 21 else 0.0
            ret20_spy   = spy_st.get('spy_ret20', 0.0)
            rel_perf    = (ret20_stock - ret20_spy) * 100  # % outperformance vs SPY

            # SMA200 del stock
            sma200 = c.rolling(200).mean().iloc[-1]
            dist_sma200 = (price / sma200 - 1) * 100

            # ── Retornos futuros ──────────────────────────────────────────────
            future = df[df.index > date]
            if len(future) < 15:
                continue
            ret15 = future.head(15)['close'].iloc[-1] / price - 1
            ret10 = future.head(10)['close'].iloc[-1] / price - 1 if len(future) >= 10 else ret15

            records.append({
                'date': date, 'ticker': ticker,
                # Indicadores estándar
                'rsi': rsi14, 'rsi_slope': rsi_sl, 'dsma': dsma,
                'score': score, 'vr': vr, 'macd_up': macd_up,
                # Estado SPY
                'spy_sma50':  spy_st.get('sma50',  False),
                'spy_sma200': spy_st.get('sma200', False),
                'spy_lowvol': spy_st.get('low_vol', False),
                # Nuevos indicadores
                'rsi70': rsi70,
                'stoch_k': stoch_k,
                'consec_down': consec_down,
                'dist_52w_low': dist_52w_low,
                'dist_52w_high': dist_52w_high,
                'dist_sma200': dist_sma200,
                'rel_perf': rel_perf,
                # Retornos
                'ret': ret15,
                'ret10': ret10,
            })
            recent[ticker] = date

    return pd.DataFrame(records)


# ── Métricas ──────────────────────────────────────────────────────────────────

def metrics(df, hold=15):
    if df is None or len(df) < 2:
        return None
    r     = df['ret'].values
    wins  = (r > 0).sum()
    wr    = wins / len(r) * 100
    avg   = r.mean() * 100
    med   = np.median(r) * 100
    daily = r / hold
    sh    = (daily.mean() / (daily.std() + 1e-10)) * np.sqrt(252)
    tot   = ((1 + r).prod() - 1) * 100
    cum   = np.cumprod(1 + r)
    dd    = (cum / np.maximum.accumulate(cum) - 1).min() * 100
    p90   = np.percentile(r * 100, 90)
    p10   = np.percentile(r * 100, 10)
    expl  = (r * 100 >= 10).sum()   # trades explosivos (>+10%)
    crash = (r * 100 <= -10).sum()  # trades-catástrofe (<-10%)
    return {'trades': len(r), 'wr': wr, 'avg': avg, 'med': med,
            'sharpe': sh, 'mdd': dd, 'total': tot,
            'p90': p90, 'p10': p10, 'explosivos': expl, 'crashes': crash}

def apply_filters(pool, filters):
    df = pool.copy()
    sl = df['rsi_slope']

    # Score
    df = df[df['score'] > filters.get('score_min', 20)]
    # RSI
    df = df[df['rsi'] < filters.get('rsi_max', 22)]
    # dsma
    df = df[df['dsma'] < filters.get('dsma_max', -10)]
    # MACD
    if filters.get('macd_up', False):
        df = df[df['macd_up']]
    # Vol
    vm = filters.get('vol_max', 99)
    df = df[df['vr'] <= vm]

    # SPY
    spy_mode = filters.get('spy', 'none')
    if spy_mode == 'sma50':
        df = df[df['spy_sma50'] & df['spy_lowvol']]
    elif spy_mode == 'sma200':
        df = df[df['spy_sma200']]
    elif spy_mode == 'sma200_soft':
        df = df[df['spy_sma200'] | df['spy_sma50']]  # OR más permisivo aún

    # Slope
    sf = filters.get('slope', 'none')
    sl = df['rsi_slope']
    if sf == 'no_dead_zone':
        df = df[(sl < 0) | (sl >= 3)]
    elif sf == 'neg':
        df = df[sl < 0]
    elif sf == 'strong':
        df = df[sl >= 3]

    # RSI70
    r70_min = filters.get('rsi70_min', 0)
    df = df[df['rsi70'] > r70_min]

    # Stochastic
    stoch_max = filters.get('stoch_max', 100)
    df = df[df['stoch_k'] < stoch_max]

    # Días consecutivos bajando
    cd_min = filters.get('consec_down_min', 0)
    df = df[df['consec_down'] >= cd_min]

    # Distancia 52w low (tiene soporte)
    d52_max = filters.get('dist_52w_low_max', 9999)
    df = df[df['dist_52w_low'] < d52_max]

    # Rendimiento relativo vs SPY
    rp_max = filters.get('rel_perf_max', 9999)  # más negativo = más underperformance
    df = df[df['rel_perf'] < rp_max]

    # SMA200 del stock
    sma200_min = filters.get('dist_sma200_min', -999)
    df = df[df['dist_sma200'] > sma200_min]

    return df.reset_index(drop=True)


def print_row(label, m, ref_mdd=None):
    if not m:
        print(f"  {label:<55}  <2 trades")
        return
    mdd_tag = ""
    if ref_mdd and m['mdd'] < ref_mdd * 0.5:
        mdd_tag = "  ★ MDD mejorado"
    print(f"  {label:<55}  TR:{m['trades']:>4}  WR:{m['wr']:>5.1f}%  "
          f"Avg:{m['avg']:>+6.2f}%  Sh:{m['sharpe']:>6.2f}  "
          f"MDD:{m['mdd']:>+7.1f}%  Tot:{m['total']:>+8.1f}%  "
          f"Expl:{m['explosivos']:>3}{mdd_tag}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 105)
    print("  BESTIA-DOMADA — Capturar explosivos, eliminar catástrofes")
    print("  Nuevos indicadores: RSI70, Stochastic, Días-bajando, Dist52w, RelPerf vs SPY")
    print("  258 tickers | Sep 2024 – Mar 2026 | Hold 15d | RSI Wilder — VERIFICADO")
    print("=" * 105)

    print("\n  Cargando datos...")
    with TitanDB() as db:
        all_data = {}
        for t in ALL_TICKERS:
            df = db.get_prices(t, '2024-01-01', '2026-03-28')  # más historia para SMA200
            if df is not None and len(df) > 210:
                all_data[t] = df.sort_index()
    spy_df = all_data.get('SPY')
    print(f"  {len(all_data)} tickers cargados\n")

    print("  Recopilando pool con indicadores extendidos...")
    pool = collect_pool(all_data, spy_df)
    print(f"  {len(pool)} candidatos en pool\n")

    if len(pool) == 0:
        print("  ERROR: Pool vacío.")
        return

    # ── Distribución de nuevos indicadores ───────────────────────────────────
    print("=" * 105)
    print("  DISTRIBUCIÓN DE INDICADORES EN EL POOL (todos los candidatos)")
    print("=" * 105)
    print(f"\n  RSI70 promedio:      {pool['rsi70'].mean():.1f}  "
          f"  (< 30 = declive estructural: {(pool['rsi70']<30).sum()} trades)")
    print(f"  Stoch K promedio:    {pool['stoch_k'].mean():.1f}  "
          f"  (< 20 = muy oversold: {(pool['stoch_k']<20).sum()} trades, "
          f"< 25: {(pool['stoch_k']<25).sum()} trades)")
    print(f"  Días baj. (avg):     {pool['consec_down'].mean():.1f}  "
          f"  (>= 3 días: {(pool['consec_down']>=3).sum()} trades)")
    print(f"  SPY > SMA200:        {pool['spy_sma200'].sum()} / {len(pool)} trades")
    print(f"  SPY > SMA50:         {pool['spy_sma50'].sum()} / {len(pool)} trades")
    print(f"  Dist SMA200 (avg):   {pool['dist_sma200'].mean():.1f}%")
    print(f"  Dist 52w low (avg):  {pool['dist_52w_low'].mean():.1f}%")
    print(f"  RelPerf vs SPY(avg): {pool['rel_perf'].mean():.1f}%")

    # WR del pool por cuartil de cada indicador nuevo
    print(f"\n  WR por nivel de RSI70:")
    for lo, hi in [(0,25),(25,35),(35,45),(45,60),(60,100)]:
        sub = pool[(pool['rsi70']>=lo) & (pool['rsi70']<hi)]
        if len(sub) > 0:
            wr = (sub['ret']>0).mean()*100
            avg = sub['ret'].mean()*100
            print(f"    RSI70 {lo:>3}-{hi:<3}: N={len(sub):>3}  WR={wr:>5.1f}%  Avg={avg:>+6.2f}%")

    print(f"\n  WR por nivel de Stochastic K:")
    for lo, hi in [(0,10),(10,20),(20,30),(30,50),(50,100)]:
        sub = pool[(pool['stoch_k']>=lo) & (pool['stoch_k']<hi)]
        if len(sub) > 0:
            wr = (sub['ret']>0).mean()*100
            avg = sub['ret'].mean()*100
            print(f"    Stoch {lo:>3}-{hi:<3}: N={len(sub):>3}  WR={wr:>5.1f}%  Avg={avg:>+6.2f}%")

    print(f"\n  WR por días consecutivos bajando:")
    for d in [0,1,2,3,4,5]:
        sub = pool[pool['consec_down']==d]
        if len(sub) > 0:
            wr = (sub['ret']>0).mean()*100
            avg = sub['ret'].mean()*100
            print(f"    {d} días bajando:    N={len(sub):>3}  WR={wr:>5.1f}%  Avg={avg:>+6.2f}%")

    print(f"\n  WR por rendimiento relativo vs SPY (20d):")
    for lo, hi in [(-999,-20),(-20,-10),(-10,-5),(-5,0),(0,999)]:
        sub = pool[(pool['rel_perf']>=lo) & (pool['rel_perf']<hi)]
        if len(sub) > 0:
            wr = (sub['ret']>0).mean()*100
            avg = sub['ret'].mean()*100
            label = f"relperf {lo:>+4}% a {hi:>+4}%"
            print(f"    {label}: N={len(sub):>3}  WR={wr:>5.1f}%  Avg={avg:>+6.2f}%")

    # ── Comparativa de modelos ────────────────────────────────────────────────
    models = {
        # Referencias
        'BESTIA original (NoSPY, RSI<22, score>20, noMACD)': {
            'rsi_max': 22, 'dsma_max': -8, 'score_min': 20,
            'spy': 'none', 'slope': 'none', 'macd_up': False, 'vol_max': 99,
        },
        'V4 baseline    (SPY50, RSI<25, score>30, MACD)': {
            'rsi_max': 25, 'dsma_max': -10, 'score_min': 30,
            'spy': 'sma50', 'slope': 'none', 'macd_up': True, 'vol_max': 1.5,
        },

        # ── DOMADA series ────────────────────────────────────────────────────

        # Solo agregar SPY>SMA200 (primer dique)
        'DA-1: + SPY>SMA200': {
            'rsi_max': 22, 'dsma_max': -8, 'score_min': 20,
            'spy': 'sma200', 'slope': 'none', 'macd_up': False, 'vol_max': 99,
        },

        # SPY>SMA200 + RSI70>30 (no declive estructural)
        'DA-2: + SPY>SMA200 + RSI70>30': {
            'rsi_max': 22, 'dsma_max': -8, 'score_min': 20,
            'spy': 'sma200', 'slope': 'none', 'macd_up': False, 'vol_max': 99,
            'rsi70_min': 30,
        },

        # SPY>SMA200 + sin zona muerta slope
        'DA-3: + SPY>SMA200 + slope no zona muerta': {
            'rsi_max': 22, 'dsma_max': -8, 'score_min': 20,
            'spy': 'sma200', 'slope': 'no_dead_zone', 'macd_up': False, 'vol_max': 99,
        },

        # SPY>SMA200 + Stochastic<25
        'DA-4: + SPY>SMA200 + Stoch<25': {
            'rsi_max': 22, 'dsma_max': -8, 'score_min': 20,
            'spy': 'sma200', 'slope': 'none', 'macd_up': False, 'vol_max': 99,
            'stoch_max': 25,
        },

        # SPY>SMA200 + RSI70>30 + slope no zona muerta
        'DA-5: + SPY>SMA200 + RSI70>30 + slope': {
            'rsi_max': 22, 'dsma_max': -8, 'score_min': 20,
            'spy': 'sma200', 'slope': 'no_dead_zone', 'macd_up': False, 'vol_max': 99,
            'rsi70_min': 30,
        },

        # SPY>SMA200 + RSI70>30 + consec_down >= 2
        'DA-6: + SPY>SMA200 + RSI70>30 + consec>=2': {
            'rsi_max': 22, 'dsma_max': -8, 'score_min': 20,
            'spy': 'sma200', 'slope': 'none', 'macd_up': False, 'vol_max': 99,
            'rsi70_min': 30, 'consec_down_min': 2,
        },

        # SPY>SMA200 + dist 52w low < 60% (no en colapso total)
        'DA-7: + SPY>SMA200 + dist52wLow<60%': {
            'rsi_max': 22, 'dsma_max': -8, 'score_min': 20,
            'spy': 'sma200', 'slope': 'none', 'macd_up': False, 'vol_max': 99,
            'dist_52w_low_max': 60,
        },

        # SPY>SMA200 + relperf vs SPY < -5% (cayó más que SPY = problema individual)
        'DA-8: + SPY>SMA200 + relperf<-5%': {
            'rsi_max': 22, 'dsma_max': -8, 'score_min': 20,
            'spy': 'sma200', 'slope': 'none', 'macd_up': False, 'vol_max': 99,
            'rel_perf_max': -5,
        },

        # Kitchen sink: todo combinado
        'DA-9: + SPY>SMA200 + RSI70>30 + Stoch<25 + slope': {
            'rsi_max': 22, 'dsma_max': -8, 'score_min': 20,
            'spy': 'sma200', 'slope': 'no_dead_zone', 'macd_up': False, 'vol_max': 99,
            'rsi70_min': 30, 'stoch_max': 25,
        },

        # Variante: relajar RSI a <25, mantener SMA200 + RSI70
        'DA-10: RSI<25 + SPY>SMA200 + RSI70>30 + slope': {
            'rsi_max': 25, 'dsma_max': -10, 'score_min': 22,
            'spy': 'sma200', 'slope': 'no_dead_zone', 'macd_up': False, 'vol_max': 99,
            'rsi70_min': 30,
        },

        # Variante: score más alto (calidad)
        'DA-11: RSI<25 + SPY>SMA200 + score>28 + RSI70>30': {
            'rsi_max': 25, 'dsma_max': -10, 'score_min': 28,
            'spy': 'sma200', 'slope': 'none', 'macd_up': False, 'vol_max': 99,
            'rsi70_min': 30,
        },

        # DA-FINAL: mejor combinación riesgo/retorno esperada
        'DA-FINAL: RSI<25 + SMA200 + RSI70>35 + slope + consec>=2': {
            'rsi_max': 25, 'dsma_max': -10, 'score_min': 22,
            'spy': 'sma200', 'slope': 'no_dead_zone', 'macd_up': False, 'vol_max': 99,
            'rsi70_min': 35, 'consec_down_min': 2,
        },
    }

    results = {}
    bestia_mdd = None

    print()
    print("=" * 105)
    print("  COMPARATIVA DE VARIANTES")
    print("=" * 105)
    print(f"\n  {'Modelo':<55}  {'TR':>4}  {'WR':>6}  {'Avg':>7}  {'Sharpe':>7}  "
          f"{'MDD':>8}  {'Total':>9}  {'Expl>10%':>9}")
    print(f"  {'-'*105}")

    for label, filt in models.items():
        df = apply_filters(pool, filt)
        m  = metrics(df)
        results[label] = (df, m)
        if 'BESTIA original' in label and m:
            bestia_mdd = m['mdd']
        print_row(label, m, bestia_mdd)

    # ── Ranking por eficiencia MDD/Sharpe ────────────────────────────────────
    print()
    print("=" * 105)
    print("  RANKING POR EFICIENCIA: Sharpe / (abs MDD + 1)  — premia bajo MDD")
    print("=" * 105)
    ranked = []
    for lbl, (df, m) in results.items():
        if m and m['trades'] >= 5:
            eff = m['sharpe'] / (abs(m['mdd']) + 1)
            ranked.append((lbl, m, eff))
    ranked.sort(key=lambda x: x[2], reverse=True)
    print()
    for i, (lbl, m, eff) in enumerate(ranked, 1):
        print(f"  #{i:<2}  {lbl:<55}  Sh:{m['sharpe']:>6.2f}  "
              f"MDD:{m['mdd']:>+7.1f}%  Eff:{eff:>6.3f}  "
              f"TR:{m['trades']:>3}  Expl:{m['explosivos']:>3}")

    # ── Detalle del mejor ────────────────────────────────────────────────────
    print()
    print("=" * 105)
    print("  DETALLE: TOP 2 VARIANTES DOMADA + comparativa BESTIA")
    print("=" * 105)

    tops = [lbl for lbl, m, eff in ranked[:2]]
    tops = ['BESTIA original (NoSPY, RSI<22, score>20, noMACD)'] + tops

    for lbl in tops:
        df, m = results.get(lbl, (None, None))
        if m is None or len(df) == 0:
            continue
        print(f"\n  {'─'*85}")
        print(f"  {lbl}")
        print(f"  {'─'*85}")
        print(f"  TR:{m['trades']}  WR:{m['wr']:.1f}%  Avg:{m['avg']:+.2f}%  "
              f"Med:{m['med']:+.2f}%  Sharpe:{m['sharpe']:.2f}  "
              f"MDD:{m['mdd']:+.1f}%  Total:{m['total']:+.1f}%")
        print(f"  Explosivos(>+10%): {m['explosivos']}  |  Catástrofes(<-10%): {m['crashes']}  "
              f"|  P10:{m['p10']:+.1f}%  P90:{m['p90']:+.1f}%")

        # Top explosivos
        top_exp = df.nlargest(6, 'ret')
        print(f"\n  Top trades explosivos:")
        print(f"  {'Fecha':<12}  {'Ticker':<6}  {'RSI':>5}  {'RSI70':>6}  "
              f"{'Slope':>7}  {'Stoch':>6}  {'RelPf':>7}  {'Ret':>8}")
        for _, row in top_exp.iterrows():
            print(f"  {str(row['date'])[:10]:<12}  {row['ticker']:<6}  "
                  f"{row['rsi']:>5.1f}  {row['rsi70']:>6.1f}  "
                  f"{row['rsi_slope']:>+7.2f}  {row['stoch_k']:>6.1f}  "
                  f"{row['rel_perf']:>+7.1f}%  {row['ret']*100:>+7.2f}%  ✓")

        # Peores
        bot = df.nsmallest(4, 'ret')
        print(f"\n  Peores trades:")
        for _, row in bot.iterrows():
            print(f"  {str(row['date'])[:10]:<12}  {row['ticker']:<6}  "
                  f"RSI:{row['rsi']:>5.1f}  RSI70:{row['rsi70']:>6.1f}  "
                  f"Slope:{row['rsi_slope']:>+7.2f}  Stoch:{row['stoch_k']:>6.1f}  "
                  f"{row['ret']*100:>+7.2f}%  ✗")

        # Histograma
        print(f"\n  Distribución:")
        bins   = [-30,-20,-15,-10,-5,0,5,10,15,20,30,999]
        blbls  = ['<-20%','-20/-15','-15/-10','-10/-5','-5/0%',
                  '0/5%','5/10%','10/15%','15/20%','20/30%','>30%']
        rets   = df['ret'].values * 100
        for j in range(len(blbls)):
            lo, hi = bins[j], bins[j+1]
            cnt = int(((rets >= lo) & (rets < hi)).sum())
            bar = '█' * min(cnt, 30)
            tag = ''
            if lo >= 15: tag = '  ← EXPLOSIVO'
            elif lo >= 10: tag = '  ← MUY BUENO'
            elif hi <= -10: tag = '  ← PÉRDIDA GRAVE'
            print(f"  {blbls[j]:>10}  {bar:<31} {cnt:>3}{tag}")

    # ── Insight final ─────────────────────────────────────────────────────────
    print()
    print("=" * 105)
    print("  INSIGHT FINAL — Qué indicador ayudó más")
    print("=" * 105)

    bestia_m = results.get('BESTIA original (NoSPY, RSI<22, score>20, noMACD)', (None,None))[1]

    insights = [
        ('Solo SPY>SMA200',     'DA-1: + SPY>SMA200'),
        ('+ RSI70>30',          'DA-2: + SPY>SMA200 + RSI70>30'),
        ('+ Slope no zona',     'DA-3: + SPY>SMA200 + slope no zona muerta'),
        ('+ Stoch<25',          'DA-4: + SPY>SMA200 + Stoch<25'),
        ('+ consec>=2',         'DA-6: + SPY>SMA200 + RSI70>30 + consec>=2'),
        ('+ dist52w<60%',       'DA-7: + SPY>SMA200 + dist52wLow<60%'),
        ('+ relperf<-5%',       'DA-8: + SPY>SMA200 + relperf<-5%'),
    ]

    if bestia_m:
        print(f"\n  BESTIA original: Sharpe {bestia_m['sharpe']:.2f}  MDD {bestia_m['mdd']:+.1f}%  "
              f"TR {bestia_m['trades']}  Total {bestia_m['total']:+.1f}%")
        print(f"  {'─'*80}")
        for tag, key in insights:
            m = results.get(key, (None,None))[1]
            if m:
                mdd_diff = m['mdd'] - bestia_m['mdd']
                tr_diff  = m['trades'] - bestia_m['trades']
                print(f"  {tag:<25}  →  Sh:{m['sharpe']:>6.2f}  MDD:{m['mdd']:>+7.1f}%  "
                      f"(Δ MDD:{mdd_diff:>+6.1f}pp)  TR:{m['trades']:>3} (Δ:{tr_diff:>+4})")

    print()


if __name__ == '__main__':
    main()
