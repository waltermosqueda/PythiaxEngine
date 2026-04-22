"""
MODELO AGRESIVO — Captura de movimientos explosivos
=====================================================
Objetivo: maximizar retornos explosivos, aceptando mayor riesgo/MDD.
El usuario decide si usar o no. Análisis completo con distribución de retornos.

Estrategia de velocidad: UN SOLO PASE sobre los datos.
Se recopilan TODOS los candidatos con filtros mínimos (RSI<30, dsma<-8),
guardando todas las features. Luego cada modelo filtra en post-proceso.
Esto es 8x más rápido que correr cada modelo por separado.

Modelos comparados:
  V4 ref    → filtros estándar + SPY + hold10
  V4-h15    → V4 con hold15 (referencia)
  A) FULL   → sin SPY, RSI<20, slope extremo (<-3 OR >=+3), hold15
  B) SPY    → con SPY, RSI<20, slope extremo, hold15
  C) RSI22  → sin SPY, RSI<22, slope<0, hold15
  D) PANICO → sin SPY, RSI<25, vol>1.5, hold15
  E) ULTRA  → sin SPY, RSI<18, score>45, hold20
  F) GIRO   → sin SPY, RSI<25, slope>=+3, hold15
  G) AMPLIO → sin SPY, RSI<25, score>35, hold15
  H) BESTIA → sin SPY, RSI<22, score>20, sin macd, hold15

Universo: 258 tickers | Sep 2024 – Mar 2026
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

# ── Indicadores ───────────────────────────────────────────────────────────────

def calc_rsi_wilder(close, period=14):
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

def calc_score(rsi, dist_sma50, macd_acc_n, vol_ratio):
    return (max(0, min(40, (30 - rsi) / 30 * 40)) +
            max(0, min(30, (abs(dist_sma50) - 5) / 15 * 30)) +
            max(0, min(20, macd_acc_n * 5)) +
            max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10)))

# ── Recopilación única ────────────────────────────────────────────────────────

def collect_all_candidates(all_data, spy_df):
    """
    Pase único: RSI<30, dsma<-8, score>15.
    Guarda todas las features + retornos a 10, 15 y 20 días.
    También guarda estado SPY en cada fecha.
    """
    records = []
    recent  = {}   # anti-knife: 3 días mínimo para no perderse señales

    # Pre-calcular estado SPY por fecha
    spy_states = {}
    for date in spy_df.index:
        sl = spy_df[spy_df.index <= date]
        if len(sl) < 55:
            spy_states[date] = False
            continue
        c = sl['close']
        above_sma = c.iloc[-1] > c.rolling(50).mean().iloc[-1]
        low_vol   = c.pct_change().rolling(20).std().iloc[-1] * 100 < 1.0
        spy_states[date] = bool(above_sma and low_vol)

    dates = sorted(d for d in spy_df.index
                   if PERIOD_START <= str(d)[:10] <= PERIOD_END)

    for date in dates:
        spy_ok = spy_states.get(date, False)

        for ticker, df in all_data.items():
            if ticker in CONTEXT_TICKERS:
                continue
            df_sl = df[df.index <= date]
            if len(df_sl) < 80:
                continue
            if ticker in recent and (date - recent[ticker]).days < 3:
                continue

            c = df_sl['close']; h = df_sl['high']
            l = df_sl['low'];   v = df_sl['volume']

            rsi_s  = calc_rsi_wilder(c)
            rsi14  = rsi_s.iloc[-1]
            if rsi14 >= 30:
                continue

            rsi_sl = rsi_s.iloc[-1] - rsi_s.iloc[-4] if len(rsi_s) >= 4 else 0.0
            mh     = calc_macd_hist(c)
            mh_c   = mh.iloc[-1]; mh_p = mh.iloc[-2] if len(mh) > 1 else 0.0
            sma50  = c.rolling(50).mean().iloc[-1]
            atr14  = calc_atr(h, l, c).iloc[-1]
            v20    = v.rolling(20).mean().iloc[-1]
            vr     = v.iloc[-1] / (v20 + 1e-10)
            price  = c.iloc[-1]
            dsma   = (price / sma50 - 1) * 100

            if dsma >= -8:
                continue

            acc_n  = (mh_c - mh_p) / (atr14 * 0.01 + 1e-6)
            score  = calc_score(rsi14, dsma, acc_n, vr)
            macd_up = bool(mh_c > mh_p)

            if any(np.isnan(x) for x in [rsi14, dsma, score, rsi_sl]):
                continue

            # Retornos futuros a 10, 15 y 20 días
            future = df[df.index > date]
            ret10  = future.head(10)['close'].iloc[-1] / price - 1 if len(future) >= 10 else None
            ret15  = future.head(15)['close'].iloc[-1] / price - 1 if len(future) >= 15 else None
            ret20  = future.head(20)['close'].iloc[-1] / price - 1 if len(future) >= 20 else None

            if ret10 is None:
                continue

            records.append({
                'date': date, 'ticker': ticker,
                'rsi': rsi14, 'rsi_slope': rsi_sl,
                'dsma': dsma, 'score': score,
                'vr': vr, 'macd_up': macd_up,
                'spy_ok': spy_ok,
                'ret10': ret10,
                'ret15': ret15 if ret15 is not None else ret10,
                'ret20': ret20 if ret20 is not None else ret10,
            })
            recent[ticker] = date

    return pd.DataFrame(records)


def apply_model(pool, cfg):
    """Filtra el pool de candidatos según la config del modelo."""
    df = pool.copy()

    # Anti-knife por modelo (re-aplicar con parámetro correcto)
    knife = cfg.get('anti_knife', 5)
    if knife > 3:  # el pool ya tiene 3 días de anti-knife
        keep = []
        last_trade = {}
        for _, row in df.sort_values('date').iterrows():
            t = row['ticker']
            d = row['date']
            if t in last_trade and (d - last_trade[t]).days < knife:
                continue
            keep.append(row.name)
            last_trade[t] = d
        df = df.loc[keep]

    # SPY
    if cfg.get('use_spy', True):
        df = df[df['spy_ok']]

    # RSI
    df = df[df['rsi'] < cfg.get('rsi_thresh', 25)]

    # SMA dist
    df = df[df['dsma'] < cfg.get('dsma_thresh', -10)]

    # Score
    df = df[df['score'] > cfg.get('score_thresh', 30)]

    # Vol
    df = df[(df['vr'] >= cfg.get('vol_min', 0)) & (df['vr'] <= cfg.get('vol_max', 1.5))]

    # MACD
    if cfg.get('macd_up', True):
        df = df[df['macd_up']]

    # Slope
    sl = df['rsi_slope']
    sf = cfg.get('slope_filter', 'none')
    if sf == 'neg':
        df = df[sl < 0]
    elif sf == 'extreme':
        df = df[(sl < -3) | (sl >= 3)]
    elif sf == 'neg_or_strong':
        df = df[(sl < 0) | (sl >= 3)]
    elif sf == 'strong_only':
        df = df[sl >= 3]

    # Columna de retorno según hold
    hold = cfg.get('hold_days', 10)
    if hold >= 20:
        df = df.assign(ret=df['ret20'])
    elif hold >= 15:
        df = df.assign(ret=df['ret15'])
    else:
        df = df.assign(ret=df['ret10'])

    return df.reset_index(drop=True)


def metrics(df, label, hold):
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
    return {'trades': len(r), 'wr': wr, 'avg': avg, 'med': med,
            'sharpe': sh, 'mdd': dd, 'total': tot, 'p90': p90, 'p10': p10}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 100)
    print("  MODELO AGRESIVO — Captura de movimientos explosivos")
    print("  258 tickers  |  Sep 2024 – Mar 2026  |  ALTO RIESGO — SOLO ANÁLISIS")
    print("  RSI: Wilder ewm(com=13) — VERIFICADO")
    print("=" * 100)

    print("\n  Cargando datos...")
    with TitanDB() as db:
        all_data = {}
        for t in ALL_TICKERS:
            df = db.get_prices(t, '2024-06-01', '2026-03-28')
            if df is not None and len(df) > 80:
                all_data[t] = df.sort_index()
    spy_df = all_data.get('SPY')
    print(f"  {len(all_data)} tickers cargados\n")

    print("  Recopilando candidatos (un solo pase — RSI<30, dsma<-8)...")
    pool = collect_all_candidates(all_data, spy_df)
    print(f"  {len(pool)} candidatos en pool\n")

    # ── Configs de modelos ────────────────────────────────────────────────────
    models = {
        'V4 baseline  (SPY, RSI<25, score>30, vol<1.5, h10)': {
            'rsi_thresh': 25, 'dsma_thresh': -10, 'score_thresh': 30,
            'use_spy': True, 'slope_filter': 'none',
            'vol_min': 0, 'vol_max': 1.5, 'macd_up': True,
            'hold_days': 10, 'anti_knife': 7,
        },
        'V4 hold15    (SPY, RSI<25, score>30, vol<1.5, h15)': {
            'rsi_thresh': 25, 'dsma_thresh': -10, 'score_thresh': 30,
            'use_spy': True, 'slope_filter': 'none',
            'vol_min': 0, 'vol_max': 1.5, 'macd_up': True,
            'hold_days': 15, 'anti_knife': 7,
        },
        'A) FULL      (NoSPY, RSI<20, slope extremo, h15)': {
            'rsi_thresh': 20, 'dsma_thresh': -10, 'score_thresh': 25,
            'use_spy': False, 'slope_filter': 'extreme',
            'vol_min': 0, 'vol_max': 99, 'macd_up': True,
            'hold_days': 15, 'anti_knife': 5,
        },
        'B) AGR-SPY   (SPY,   RSI<20, slope extremo, h15)': {
            'rsi_thresh': 20, 'dsma_thresh': -10, 'score_thresh': 25,
            'use_spy': True, 'slope_filter': 'extreme',
            'vol_min': 0, 'vol_max': 99, 'macd_up': True,
            'hold_days': 15, 'anti_knife': 5,
        },
        'C) RSI-22    (NoSPY, RSI<22, slope<0, h15)': {
            'rsi_thresh': 22, 'dsma_thresh': -10, 'score_thresh': 25,
            'use_spy': False, 'slope_filter': 'neg',
            'vol_min': 0, 'vol_max': 99, 'macd_up': True,
            'hold_days': 15, 'anti_knife': 5,
        },
        'D) PANICO    (NoSPY, RSI<25, vol>1.5, h15)': {
            'rsi_thresh': 25, 'dsma_thresh': -10, 'score_thresh': 25,
            'use_spy': False, 'slope_filter': 'none',
            'vol_min': 1.5, 'vol_max': 99, 'macd_up': True,
            'hold_days': 15, 'anti_knife': 5,
        },
        'E) ULTRA     (NoSPY, RSI<18, score>45, h20)': {
            'rsi_thresh': 18, 'dsma_thresh': -12, 'score_thresh': 45,
            'use_spy': False, 'slope_filter': 'none',
            'vol_min': 0, 'vol_max': 99, 'macd_up': True,
            'hold_days': 20, 'anti_knife': 5,
        },
        'F) GIRO-FUER (NoSPY, RSI<25, slope>=+3, h15)': {
            'rsi_thresh': 25, 'dsma_thresh': -10, 'score_thresh': 25,
            'use_spy': False, 'slope_filter': 'strong_only',
            'vol_min': 0, 'vol_max': 99, 'macd_up': True,
            'hold_days': 15, 'anti_knife': 5,
        },
        'G) AMPLIO    (NoSPY, RSI<25, score>35, h15)': {
            'rsi_thresh': 25, 'dsma_thresh': -10, 'score_thresh': 35,
            'use_spy': False, 'slope_filter': 'none',
            'vol_min': 0, 'vol_max': 99, 'macd_up': True,
            'hold_days': 15, 'anti_knife': 5,
        },
        'H) BESTIA    (NoSPY, RSI<22, score>20, noMACD, h15)': {
            'rsi_thresh': 22, 'dsma_thresh': -8, 'score_thresh': 20,
            'use_spy': False, 'slope_filter': 'none',
            'vol_min': 0, 'vol_max': 99, 'macd_up': False,
            'hold_days': 15, 'anti_knife': 3,
        },
    }

    # ── Aplicar modelos ───────────────────────────────────────────────────────
    results = {}
    for label, cfg in models.items():
        df = apply_model(pool, cfg)
        results[label] = (df, metrics(df, label, cfg['hold_days']), cfg)

    # ── Tabla comparativa ─────────────────────────────────────────────────────
    print("=" * 100)
    print("  COMPARATIVA DE MODELOS")
    print("=" * 100)
    print(f"\n  {'Modelo':<50}  {'TR':>4}  {'WR':>6}  {'Avg':>7}  {'Med':>7}  "
          f"{'Sharpe':>7}  {'MDD':>7}  {'Total':>8}")
    print(f"  {'-'*100}")
    for label, (df, m, cfg) in results.items():
        if m:
            spy_tag = "SPY" if cfg.get('use_spy') else "   "
            print(f"  {label:<50}  {m['trades']:>4}  {m['wr']:>5.1f}%  "
                  f"{m['avg']:>+6.2f}%  {m['med']:>+6.2f}%  "
                  f"{m['sharpe']:>7.2f}  {m['mdd']:>+6.1f}%  {m['total']:>+7.1f}%  [{spy_tag},h{cfg['hold_days']}]")
        else:
            print(f"  {label:<50}  <2 trades")

    # ── Ranking por Sharpe ────────────────────────────────────────────────────
    print()
    print("=" * 100)
    print("  RANKING POR SHARPE")
    print("=" * 100)
    ranked = [(lbl, df, m, cfg) for lbl, (df, m, cfg) in results.items()
              if m and m['trades'] >= 3]
    ranked.sort(key=lambda x: x[2]['sharpe'], reverse=True)
    print()
    for i, (lbl, df, m, cfg) in enumerate(ranked, 1):
        print(f"  #{i:<2}  {lbl:<50}  Sh:{m['sharpe']:>7.2f}  WR:{m['wr']:>5.1f}%  "
              f"TR:{m['trades']:>3}  MDD:{m['mdd']:>+6.1f}%")

    # ── Detalle top 3 ─────────────────────────────────────────────────────────
    print()
    print("=" * 100)
    print("  DETALLE TOP 3 — Mejores trades y distribución")
    print("=" * 100)

    for i, (lbl, df, m, cfg) in enumerate(ranked[:3], 1):
        hold = cfg['hold_days']
        print(f"\n  {'─'*88}")
        print(f"  #{i}  {lbl}")
        print(f"  {'─'*88}")
        print(f"  Trades:{m['trades']}  WR:{m['wr']:.1f}%  Avg:{m['avg']:+.2f}%  "
              f"Med:{m['med']:+.2f}%  Sharpe:{m['sharpe']:.2f}  "
              f"MDD:{m['mdd']:+.1f}%  Total:{m['total']:+.1f}%")
        print(f"  P10 (peor decil):{m['p10']:+.2f}%  P90 (mejor decil):{m['p90']:+.2f}%")

        # Top 5 explosivos
        top5 = df.nlargest(5, 'ret')
        print(f"\n  Top 5 trades más explosivos (hold {hold}d):")
        print(f"  {'Fecha':<12}  {'Ticker':<6}  {'RSI':>5}  {'Slope':>7}  {'Score':>5}  {'Ret':>8}")
        for _, row in top5.iterrows():
            print(f"  {str(row['date'])[:10]:<12}  {row['ticker']:<6}  "
                  f"{row['rsi']:>5.1f}  {row['rsi_slope']:>+7.2f}  "
                  f"{row['score']:>5.0f}  {row['ret']*100:>+7.2f}%  ✓")

        # Peores 3
        bot3 = df.nsmallest(3, 'ret')
        print(f"\n  Peores 3 trades (riesgo real):")
        for _, row in bot3.iterrows():
            print(f"  {str(row['date'])[:10]:<12}  {row['ticker']:<6}  "
                  f"RSI:{row['rsi']:>5.1f}  Slope:{row['rsi_slope']:>+7.2f}  "
                  f"{row['ret']*100:>+7.2f}%  ✗")

        # Histograma
        print(f"\n  Distribución de retornos (hold {hold}d):")
        bins   = [-30, -20, -15, -10, -5, 0, 5, 10, 15, 20, 30, 999]
        labels = ['<-20%', '-20/-15', '-15/-10', '-10/-5', '-5/0%',
                  '0/5%', '5/10%', '10/15%', '15/20%', '20/30%', '>30%']
        rets   = df['ret'].values * 100
        for j in range(len(labels)):
            lo, hi  = bins[j], bins[j+1]
            count   = int(((rets >= lo) & (rets < hi)).sum())
            bar     = '█' * min(count, 25)
            tag     = ''
            if lo >= 15:  tag = '  ← EXPLOSIVO'
            elif hi <= -10: tag = '  ← PÉRDIDA GRAVE'
            elif lo >= 10: tag = '  ← MUY BUENO'
            print(f"  {labels[j]:>10}  {bar:<26} {count:>3}{tag}")

    # ── Tabla riesgo/recompensa ────────────────────────────────────────────────
    print()
    print("=" * 100)
    print("  MAPA RIESGO / RECOMPENSA  (P90 = mejor decil, P10 = peor decil)")
    print("=" * 100)
    print(f"\n  {'Modelo':<50}  {'P10':>8}  {'P90':>8}  {'Ratio':>8}  {'MDD':>8}")
    print(f"  {'-'*85}")
    for lbl, (df, m, cfg) in results.items():
        if m and m['trades'] >= 3:
            ratio = abs(m['p90'] / m['p10']) if m['p10'] != 0 else 0
            print(f"  {lbl:<50}  {m['p10']:>+7.2f}%  {m['p90']:>+7.2f}%  "
                  f"{ratio:>7.2f}x  {m['mdd']:>+7.1f}%")

    # ── Advertencias ──────────────────────────────────────────────────────────
    print()
    print("=" * 100)
    print("  ⚠️  ADVERTENCIAS — LEER ANTES DE USAR")
    print("=" * 100)
    print("""
  1. SIN filtro SPY = operar en CUALQUIER condición de mercado.
     Este backtest cubre solo 18 meses con mercado relativamente benigno.
     En crashes prolongados (2022, 2008) el MDD puede ser -60% a -80%.

  2. Los retornos explosivos (>+15%) son ESTADÍSTICAMENTE RAROS.
     El pool completo tiene solo unos pocos por año. No escalar demasiado.

  3. Hold 15-20 días = más exposición a earnings inesperados y gap-downs.

  4. Modelo H (BESTIA) tiene señal de menor calidad. En mercado real
     el slippage afecta más estrategias de alta frecuencia.

  5. Tamaño de posición sugerido para modelos agresivos: 1-2% del portfolio.
     NUNCA usar el mismo tamaño que V4 hasta validar en tiempo real.

  6. V4 sigue siendo el scanner de producción. Estos modelos son INVESTIGACIÓN.
    """)


if __name__ == '__main__':
    main()
