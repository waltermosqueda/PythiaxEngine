"""
ANÁLISIS PROFUNDO: ¿Qué tiene V39 que V4 no tiene?
====================================================
V39 tiene 44 features. La pregunta no es "funciona el ML de V39"
(ya probado: NO). La pregunta es: ¿hay algún CONCEPTO de V39
que, como regla simple, mejore V4?

Conceptos V39 que V4 NO tiene:
  A. zscore20      — z-score vs MA20 normalizado por volatilidad
                     Diferencia con dist_sma50: normaliza por std
                     KO -10% SMA ≠ NVDA -10% SMA en términos de "qué tan extremo"
  B. Cross-sectional ranks — posición relativa vs universo
                     ret5_rank bajo = stock más caído vs peers (selección relativa)
  C. Idiosyncratic alpha — retorno ajustado por beta del mercado
                     Stock que cae mientras mercado sube = señal más fuerte
  D. RSI slope (rsi_slope) — velocidad de cambio del RSI
                     RSI cayendo aún vs RSI girando al alza

Estrategias testeadas:
  1. V4 baseline
  2. V4 + zscore20 < -1.5  (oversold normalizado por vol)
  3. V4 + zscore20 < -2.0  (más estricto)
  4. V4 + rsi_slope < 0    (RSI aún cayendo — ya sugerido por Round 3)
  5. V4 + idio5 < 0        (stock cae más de lo que el mercado explica)
  6. V4 + ret5_rank < 0.20 (entre los más caídos del universo últimos 5d)
  7. V4 con zscore<-1.5 REEMPLAZANDO dist_sma50 (test de sustitución)
  8. V4 + zscore<-2 + rsi_slope<0 (combo de los dos más prometedores)

Nota crítica: V39's RSI usa ewm(span=14) ≠ Wilder ewm(com=13).
Aquí usamos Wilder correcto en todas las estrategias.
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os
import pandas as pd
import numpy as np
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from titan_system.core.database import TitanDB

# ── Config ────────────────────────────────────────────────────────────────────
PERIOD_START = '2024-09-01'
PERIOD_END   = '2026-03-28'
HOLD_DAYS    = 10
MIN_TRADES   = 3

TICKERS = [
    'AAPL','MSFT','GOOGL','AMZN','META','NVDA','AMD','TSLA','NFLX','CRM',
    'ORCL','ADBE','INTC','AVGO','QCOM','MU','AMAT','LRCX','TXN','PLTR',
    'JPM','BAC','WFC','GS','V','MA','AXP','C','PYPL','COIN',
    'JNJ','PFE','UNH','MRK','ABBV','LLY','TMO','ABT','BMY','AMGN',
    'XOM','CVX','COP','SLB','OXY','HAL','DVN','MPC','VLO','EOG',
    'KO','PEP','PG','WMT','COST','MCD','NKE','SBUX','TGT','HD',
    'CAT','BA','GE','RTX','HON','LMT','UPS','FDX','DE','MMM',
    'MELI','NU','BABA','VALE','PBR','GLOB','STNE','XP','SBS','ITUB',
    'SPY',
]

# ── Indicadores ───────────────────────────────────────────────────────────────

def calc_rsi_wilder(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False).mean()
    return 100 - 100 / (1 + gain / (loss + 1e-10))

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd = ema_f - ema_s
    return macd, macd.ewm(span=signal, adjust=False).mean(), macd - macd.ewm(span=signal, adjust=False).mean()

def calc_atr(high, low, close, period=14):
    tr = pd.concat([(high-low), (high-close.shift(1)).abs(), (low-close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_v4_score(rsi, dist_sma50, macd_accel_norm, vol_ratio):
    rsi_s  = max(0, min(40, (30-rsi)/30*40))
    str_s  = max(0, min(30, (abs(dist_sma50)-5)/15*30))
    macd_s = max(0, min(20, macd_accel_norm*5))
    vol_s  = max(0, min(10, (1.5-vol_ratio)/1.5*10))
    return rsi_s + str_s + macd_s + vol_s

# ── Cross-sectional ranks: requiere calcular sobre TODOS los tickers el mismo día ──

def precompute_cross_section(all_data, dates):
    """
    Pre-calcula ret5_rank para cada (date, ticker).
    Esta es la feature más genuinamente nueva de V39 — posición relativa vs universo.
    """
    cs_ranks = {}  # {date: {ticker: rank}}
    for date in dates:
        ret5_dict = {}
        for ticker, df in all_data.items():
            if ticker == 'SPY':
                continue
            d_slice = df[df.index <= date]
            if len(d_slice) < 10:
                continue
            c = d_slice['close']
            ret5 = c.iloc[-1] / c.iloc[-6] - 1 if len(c) >= 6 else np.nan
            if not np.isnan(ret5):
                ret5_dict[ticker] = ret5

        if len(ret5_dict) > 5:
            series = pd.Series(ret5_dict)
            ranks = series.rank(pct=True)
            cs_ranks[date] = ranks.to_dict()

    return cs_ranks

# ── Backtest engine ───────────────────────────────────────────────────────────

def run_backtest(all_data, spy_df, filters_fn, hold_days=10, cs_ranks=None):
    trades = []
    recent_entries = {}
    trading_dates = sorted(spy_df.index)

    for i, date in enumerate(trading_dates):
        spy_slice = spy_df[spy_df.index <= date]
        if len(spy_slice) < 55:
            continue
        spy_c = spy_slice['close']
        spy_sma50 = spy_c.rolling(50).mean().iloc[-1]
        spy_price = spy_c.iloc[-1]
        spy_vol20d = spy_c.pct_change().rolling(20).std().iloc[-1] * 100
        if not ((spy_price > spy_sma50) and (spy_vol20d < 1.0)):
            continue

        for ticker, df in all_data.items():
            if ticker == 'SPY':
                continue
            df_slice = df[df.index <= date]
            if len(df_slice) < 80:
                continue
            if ticker in recent_entries and (date - recent_entries[ticker]).days < 7:
                continue

            c = df_slice['close']
            h = df_slice['high']
            l = df_slice['low']
            v = df_slice['volume']

            rsi14      = calc_rsi_wilder(c).iloc[-1]
            _, _, mh   = calc_macd(c)
            mh_c = mh.iloc[-1]; mh_p = mh.iloc[-2] if len(mh) > 1 else 0
            sma50      = c.rolling(50).mean().iloc[-1]
            atr14      = calc_atr(h, l, c).iloc[-1]
            vol_avg20  = v.rolling(20).mean().iloc[-1]
            vol_ratio  = v.iloc[-1] / (vol_avg20 + 1e-10)
            price      = c.iloc[-1]
            dist_sma50 = (price / sma50 - 1) * 100
            macd_acc_n = (mh_c - mh_p) / (atr14 * 0.01 + 1e-6)
            score      = calc_v4_score(rsi14, dist_sma50, macd_acc_n, vol_ratio)

            # ── Features nuevas de V39 ──

            # A. zscore20: normaliza distancia por volatilidad
            ma20  = c.rolling(20).mean().iloc[-1]
            std20 = c.rolling(20).std().iloc[-1]
            zscore20 = (price - ma20) / (std20 + 1e-10)

            # B. RSI slope (V39: rsi_slope = rsi14 - rsi14.shift(3))
            rsi_series  = calc_rsi_wilder(c)
            rsi_slope   = rsi_series.iloc[-1] - rsi_series.iloc[-4] if len(rsi_series) >= 4 else 0

            # C. Idiosyncratic alpha: retorno no explicado por SPY
            spy_ret5 = spy_c.pct_change(5).iloc[-1] if len(spy_c) >= 6 else 0
            ret5_stock = c.pct_change(5).iloc[-1] if len(c) >= 6 else 0
            # Beta simple (relación ret5 stock vs SPY)
            # Para simplificar: idio5 = ret5_stock - ret5_spy
            # Negativo = cayó más que el mercado = más oversold de lo que SPY explica
            idio5 = ret5_stock - spy_ret5

            # D. Cross-sectional rank (pre-computado)
            ret5_rank = 0.5  # default neutro
            if cs_ranks and date in cs_ranks and ticker in cs_ranks[date]:
                ret5_rank = cs_ranks[date][ticker]

            # Skip NaNs
            vals = [rsi14, dist_sma50, score, zscore20, rsi_slope, idio5]
            if any(np.isnan(v_) for v_ in vals):
                continue

            row = {
                'rsi14': rsi14, 'dist_sma50': dist_sma50, 'score': score,
                'vol_ratio': vol_ratio, 'macd_up': mh_c > mh_p,
                'zscore20': zscore20, 'rsi_slope': rsi_slope,
                'idio5': idio5, 'ret5_rank': ret5_rank,
            }

            if not filters_fn(row):
                continue

            future = df[df.index > date].head(hold_days)
            if len(future) < hold_days:
                continue

            ret = future['close'].iloc[-1] / price - 1
            trades.append({
                'date': date, 'ticker': ticker, 'price': price, 'ret': ret,
                'rsi': rsi14, 'dist_sma50': dist_sma50, 'score': score,
                'zscore20': zscore20, 'rsi_slope': rsi_slope,
                'idio5': idio5, 'ret5_rank': ret5_rank,
            })
            recent_entries[ticker] = date

    return pd.DataFrame(trades)

def metrics(df, name):
    if df is None or len(df) < MIN_TRADES:
        n = len(df) if df is not None else 0
        return {'name': name, 'trades': n, 'sharpe': -99, 'wr': 0,
                'avg_ret': 0, 'total_ret': 0, 'mdd': 0, 'wins': 0, 'losses': 0}
    r = df['ret'].values
    wins = (r > 0).sum()
    wr   = wins / len(r) * 100
    avgw = r[r > 0].mean() * 100 if wins > 0 else 0
    avgl = r[r <= 0].mean() * 100 if (len(r) - wins) > 0 else 0
    eq   = np.cumprod(1 + r)
    mdd  = ((eq - np.maximum.accumulate(eq)) / np.maximum.accumulate(eq)).min() * 100
    sharpe = (r.mean() / (r.std() + 1e-10) / HOLD_DAYS) * np.sqrt(252)
    return {
        'name': name, 'trades': len(r), 'wins': int(wins), 'losses': int(len(r)-wins),
        'wr': wr, 'avg_ret': r.mean()*100, 'avgw': avgw, 'avgl': avgl,
        'sharpe': sharpe, 'total_ret': (eq[-1]-1)*100, 'mdd': mdd,
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 85)
    print("  ANÁLISIS PROFUNDO: CONCEPTOS V39 → ¿MEJORAN V4?")
    print(f"  {PERIOD_START} → {PERIOD_END}  |  Hold: {HOLD_DAYS}d  |  Universo: 80 tickers")
    print("=" * 85)

    print("\n  Cargando datos de titan.db...")
    with TitanDB() as db:
        all_data = {}
        for ticker in TICKERS:
            df = db.get_prices(ticker, PERIOD_START, PERIOD_END)
            if df is not None and len(df) > 80:
                all_data[ticker] = df.sort_index()
    print(f"  {len(all_data)} tickers cargados")

    spy_df = all_data.get('SPY')
    if spy_df is None:
        print("  ERROR: SPY no encontrado"); return

    # Pre-calcular cross-sectional ranks (esto toma tiempo)
    print("  Pre-calculando cross-sectional ranks...")
    trading_dates = sorted(spy_df.index)
    # Solo calcular para fechas donde hay régimen OK (optimización)
    cs_ranks = precompute_cross_section(all_data, trading_dates)
    print(f"  {len(cs_ranks)} fechas con cross-sectional ranks listos\n")

    # ── Definición de filtros base V4 ──
    def v4_base(r):
        return (r['rsi14'] < 25 and r['dist_sma50'] < -10 and
                r['score'] > 30 and r['vol_ratio'] < 1.5 and r['macd_up'])

    strategies = [
        # Baseline
        ("1. V4 baseline",
         lambda r: v4_base(r)),

        # A. zscore20 como FILTRO ADICIONAL
        ("2. V4 + zscore20 < -1.5",
         lambda r: v4_base(r) and r['zscore20'] < -1.5),

        ("3. V4 + zscore20 < -2.0",
         lambda r: v4_base(r) and r['zscore20'] < -2.0),

        # A'. zscore20 REEMPLAZANDO dist_sma50 (test de sustitución total)
        ("4. V4 con zscore<-1.5 (reemplaza SMA)",
         lambda r: (r['rsi14'] < 25 and r['zscore20'] < -1.5 and
                    r['score'] > 30 and r['vol_ratio'] < 1.5 and r['macd_up'])),

        # B. RSI slope (de V39, ya sugerido por Round 3)
        ("5. V4 + rsi_slope < 0 (RSI aun cayendo)",
         lambda r: v4_base(r) and r['rsi_slope'] < 0),

        ("6. V4 + rsi_slope < -3 (cayendo fuerte)",
         lambda r: v4_base(r) and r['rsi_slope'] < -3),

        # C. Idiosyncratic alpha (concepto genuinamente nuevo de V39)
        ("7. V4 + idio5 < 0 (cayo mas que SPY)",
         lambda r: v4_base(r) and r['idio5'] < 0),

        ("8. V4 + idio5 < -0.05 (cayo >5% mas que SPY)",
         lambda r: v4_base(r) and r['idio5'] < -0.05),

        # D. Cross-sectional rank (el más novel de V39)
        ("9. V4 + ret5_rank < 0.25 (peor 25% del universo)",
         lambda r: v4_base(r) and r['ret5_rank'] < 0.25),

        ("10. V4 + ret5_rank < 0.10 (peor 10% del universo)",
         lambda r: v4_base(r) and r['ret5_rank'] < 0.10),

        # Combos: los más prometedores juntos
        ("11. V4 + zscore<-1.5 + rsi_slope<0",
         lambda r: v4_base(r) and r['zscore20'] < -1.5 and r['rsi_slope'] < 0),

        ("12. V4 + idio5<0 + rsi_slope<0",
         lambda r: v4_base(r) and r['idio5'] < 0 and r['rsi_slope'] < 0),

        # La pregunta inversa: ¿lo OPUESTO de V39 mejora V4?
        # (V39 busca momentum, V4 busca reversal — quizás lo opuesto de V39 refuerza V4)
        ("13. V4 + ret5_rank > 0.50 (NO el mas caido)",
         lambda r: v4_base(r) and r['ret5_rank'] > 0.50),
    ]

    print(f"  Corriendo {len(strategies)} estrategias...")
    results = []
    v4_trades = None
    for i, (name, fn) in enumerate(strategies):
        print(f"  [{i+1}/{len(strategies)}] {name}...")
        trades_df = run_backtest(all_data, spy_df, fn, HOLD_DAYS, cs_ranks)
        m = metrics(trades_df, name)
        results.append(m)
        if i == 0:
            v4_trades = trades_df

    # ── Tabla comparativa ────────────────────────────────────────────────────
    print()
    print("=" * 105)
    print(f"  {'ESTRATEGIA':<45} {'TR':>4} {'W':>3} {'L':>3}  {'WR%':>5}  "
          f"{'AVG%':>6}  {'AVGW%':>6}  {'AVGL%':>6}  {'TOT%':>7}  {'SHARP':>6}  {'MDD%':>6}")
    print("=" * 105)

    v4_sharpe = next(r['sharpe'] for r in results if '1.' in r['name'])
    for r in sorted(results, key=lambda x: x['sharpe'], reverse=True):
        if r['trades'] < MIN_TRADES:
            mark = " ✗ POCOS TRADES"
            print(f"  {r['name']:<45} {r['trades']:>4} trades{mark}")
            continue
        flag = " ◄ V4" if '1.' in r['name'] else \
               " ★ MEJOR" if r['sharpe'] > v4_sharpe * 1.1 else ""
        print(f"  {r['name']:<45} {r['trades']:>4}  "
              f"{r['wins']:>3}  {r['losses']:>3}  {r['wr']:>5.1f}%  "
              f"{r['avg_ret']:>5.2f}%  {r.get('avgw',0):>5.2f}%  "
              f"{r.get('avgl',0):>5.2f}%  {r['total_ret']:>6.1f}%  "
              f"{r['sharpe']:>6.2f}  {r['mdd']:>5.1f}%{flag}")
    print("=" * 105)

    # ── Análisis profundo de features V39 en trades V4 ──────────────────────
    if v4_trades is not None and len(v4_trades) >= MIN_TRADES:
        print()
        print("=" * 85)
        print("  ANÁLISIS: ¿CÓMO SE DISTRIBUYEN LOS FEATURES V39 EN LOS TRADES V4?")
        print("=" * 85)

        # zscore20
        print(f"\n  A. zscore20 (normalización por volatilidad vs MA20):")
        print(f"     Promedio: {v4_trades['zscore20'].mean():.2f}  |  Mediana: {v4_trades['zscore20'].median():.2f}")
        print(f"     Rango: [{v4_trades['zscore20'].min():.2f}, {v4_trades['zscore20'].max():.2f}]")
        for label, mask in [
            ("zscore20 < -3  (muy extremo)",  v4_trades['zscore20'] < -3),
            ("zscore20 -3 a -2",              (v4_trades['zscore20'] >= -3) & (v4_trades['zscore20'] < -2)),
            ("zscore20 -2 a -1.5",            (v4_trades['zscore20'] >= -2) & (v4_trades['zscore20'] < -1.5)),
            ("zscore20 > -1.5 (moderado)",    v4_trades['zscore20'] >= -1.5),
        ]:
            sub = v4_trades[mask]
            if len(sub) == 0: continue
            wr = (sub['ret'] > 0).mean() * 100
            avg = sub['ret'].mean() * 100
            print(f"     {label:<30}  {len(sub):>2} trades  WR: {wr:>5.1f}%  Avg: {avg:>+5.2f}%")

        # RSI slope
        print(f"\n  B. RSI Slope (positivo = RSI subiendo, negativo = RSI cayendo):")
        print(f"     Promedio: {v4_trades['rsi_slope'].mean():.2f}  |  "
              f"Cayendo: {(v4_trades['rsi_slope'] < 0).sum()} trades  "
              f"Subiendo: {(v4_trades['rsi_slope'] >= 0).sum()} trades")
        for label, mask in [
            ("RSI slope < -5  (cayendo fuerte)", v4_trades['rsi_slope'] < -5),
            ("RSI slope -5 a 0",                 (v4_trades['rsi_slope'] >= -5) & (v4_trades['rsi_slope'] < 0)),
            ("RSI slope >= 0 (estabilizando)",   v4_trades['rsi_slope'] >= 0),
        ]:
            sub = v4_trades[mask]
            if len(sub) == 0: continue
            wr = (sub['ret'] > 0).mean() * 100
            avg = sub['ret'].mean() * 100
            print(f"     {label:<35}  {len(sub):>2} trades  WR: {wr:>5.1f}%  Avg: {avg:>+5.2f}%")

        # Idiosyncratic
        print(f"\n  C. Idio5 (stock vs SPY ret5, negativo = cayo mas que SPY):")
        print(f"     Promedio: {v4_trades['idio5'].mean():.3f}  |  "
              f"< 0: {(v4_trades['idio5'] < 0).sum()} trades  "
              f">= 0: {(v4_trades['idio5'] >= 0).sum()} trades")
        for label, mask in [
            ("idio5 < -0.10 (>10% bajo SPY)", v4_trades['idio5'] < -0.10),
            ("idio5 -0.10 a 0",               (v4_trades['idio5'] >= -0.10) & (v4_trades['idio5'] < 0)),
            ("idio5 >= 0   (no peor q SPY)",  v4_trades['idio5'] >= 0),
        ]:
            sub = v4_trades[mask]
            if len(sub) == 0: continue
            wr = (sub['ret'] > 0).mean() * 100
            avg = sub['ret'].mean() * 100
            print(f"     {label:<35}  {len(sub):>2} trades  WR: {wr:>5.1f}%  Avg: {avg:>+5.2f}%")

        # Cross-sectional rank
        print(f"\n  D. ret5_rank (0 = el MÁS caído del universo, 1 = el que más subió):")
        print(f"     Promedio: {v4_trades['ret5_rank'].mean():.2f}  |  "
              f"< 0.25: {(v4_trades['ret5_rank'] < 0.25).sum()} trades  "
              f"< 0.10: {(v4_trades['ret5_rank'] < 0.10).sum()} trades")
        for label, mask in [
            ("rank < 0.10 (peor 10%)",   v4_trades['ret5_rank'] < 0.10),
            ("rank 0.10 - 0.25",          (v4_trades['ret5_rank'] >= 0.10) & (v4_trades['ret5_rank'] < 0.25)),
            ("rank 0.25 - 0.50",          (v4_trades['ret5_rank'] >= 0.25) & (v4_trades['ret5_rank'] < 0.50)),
            ("rank > 0.50",               v4_trades['ret5_rank'] >= 0.50),
        ]:
            sub = v4_trades[mask]
            if len(sub) == 0: continue
            wr = (sub['ret'] > 0).mean() * 100
            avg = sub['ret'].mean() * 100
            print(f"     {label:<30}  {len(sub):>2} trades  WR: {wr:>5.1f}%  Avg: {avg:>+5.2f}%")

        # Tabla de trades con features V39
        print(f"\n  Trades V4 con features V39:")
        print(f"  {'Fecha':<12} {'Ticker':<7} {'RSI':>5} {'vs SMA':>7} {'z20':>6} "
              f"{'RSI sl':>7} {'idio5':>7} {'cs_rk':>7} {'Ret':>7}")
        print(f"  {'-'*80}")
        for _, t in v4_trades.sort_values('date').iterrows():
            print(f"  {str(t['date'])[:10]:<12} {t['ticker']:<7} "
                  f"{t['rsi']:>5.1f} {t['dist_sma50']:>6.1f}% "
                  f"{t['zscore20']:>6.2f} {t['rsi_slope']:>7.2f} "
                  f"{t['idio5']:>7.3f} {t['ret5_rank']:>7.2f} "
                  f"{t['ret']*100:>+6.1f}%")

    # ── Conclusión final ─────────────────────────────────────────────────────
    print()
    print("=" * 85)
    print("  VEREDICTO FINAL")
    print("=" * 85)

    v4_r = next(r for r in results if '1.' in r['name'])
    better = [r for r in results if r['sharpe'] > v4_r['sharpe'] and
              r['trades'] >= MIN_TRADES and '1.' not in r['name']]

    if better:
        print(f"\n  Estrategias que superan V4 (Sharpe {v4_r['sharpe']:.2f}):")
        for r in sorted(better, key=lambda x: x['sharpe'], reverse=True):
            diff = r['trades'] - v4_r['trades']
            print(f"  ► {r['name']:<45} Sharpe {r['sharpe']:>6.2f} | "
                  f"{r['trades']} trades ({diff:+d}) | WR {r['wr']:.1f}%")
        print()
        print("  → Requieren walk-forward antes de usar en producción.")
        print("  → Con < 10 trades la diferencia puede ser ruido estadístico.")
    else:
        print(f"\n  Ningún concepto de V39 supera a V4 (Sharpe {v4_r['sharpe']:.2f}).")
        print("  → Los features de V39 no agregan valor como reglas simples sobre V4.")

    print()
    print("  Nota sobre V39's RSI: usa ewm(span=14) en lugar de ewm(com=13).")
    print("  Diferencia: alpha=2/15 vs alpha=1/14. El RSI de V39 es ligeramente")
    print("  diferente al de TradingView (Wilder). Este análisis usa Wilder correcto.")
    print()

if __name__ == '__main__':
    main()
