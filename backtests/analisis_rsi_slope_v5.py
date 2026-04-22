"""
BACKTEST: V4 + RSI Slope — ¿Filtrando entradas con RSI aún cayendo mejora V4?
==============================================================================
Hipótesis confirmada 2 veces:
  1. Round 3 deep analysis: RSI Falling WR 69% Sharpe 5.81 > RSI Rising WR 61% Sharpe 4.08
  2. Análisis V39 (73 tickers): V4 + rsi_slope<0 eliminó trade CRM (-6.9%), WR 67%→80%

Este test es DEFINITIVO: universo completo 260+ tickers, misma metodología que Round 3.

Estrategias:
  1. V4 baseline             — referencia (Sharpe 14.15 en Round 3)
  2. V4 + rsi_slope < 0      — RSI aún bajando en el día de entrada
  3. V4 + rsi_slope < -2     — cayendo con más fuerza
  4. V4 + rsi_slope < -5     — cayendo fuerte (muy selectivo)
  5. V4 + rsi_slope >= 0     — RSI estabilizando o girando (el complemento — ¿sirve?)
  6. V4 relajado RSI<27      — comparativa (más trades, ¿qué slope tiene?)
  7. V4 + rsi_slope<0 + Vol<1.0x — combinación con filtro vol que ya fue prometedor

Universo: 260+ tickers (titan.db completo)
Período: Sep 2024 – Mar 2026 (misma ventana que Round 3)
Holding: 10 días
RSI: Wilder's smoothing ewm(com=13) — VERIFICADO
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
from titan_system.core.data_loader import ACTIVOS, CONTEXT_TICKERS

# ── Config ────────────────────────────────────────────────────────────────────
PERIOD_START = '2024-09-01'
PERIOD_END   = '2026-03-28'
HOLD_DAYS    = 10
MIN_TRADES   = 3

# Universo completo: todos los activos de titan.db
ALL_TICKERS = list(set(ACTIVOS + CONTEXT_TICKERS))

# ── Indicadores ───────────────────────────────────────────────────────────────

def calc_rsi_wilder(close, period=14):
    """WILDER'S SMOOTHING — ewm(com=period-1, adjust=False). VERIFICADO."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False).mean()
    return 100 - 100 / (1 + gain / (loss + 1e-10))

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd  = ema_f - ema_s
    sig   = macd.ewm(span=signal, adjust=False).mean()
    return macd - sig  # solo histograma

def calc_atr(high, low, close, period=14):
    tr = pd.concat([
        (high - low),
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_v4_score(rsi, dist_sma50, macd_accel_norm, vol_ratio):
    rsi_s  = max(0, min(40, (30 - rsi) / 30 * 40))
    str_s  = max(0, min(30, (abs(dist_sma50) - 5) / 15 * 30))
    macd_s = max(0, min(20, macd_accel_norm * 5))
    vol_s  = max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10))
    return rsi_s + str_s + macd_s + vol_s

# ── Backtest engine ───────────────────────────────────────────────────────────

def run_backtest(all_data, spy_df, filters_fn, hold_days=10):
    trades = []
    recent_entries = {}
    trading_dates  = sorted(spy_df.index)

    for date in trading_dates:
        # Régimen SPY
        spy_sl = spy_df[spy_df.index <= date]
        if len(spy_sl) < 55:
            continue
        spy_c     = spy_sl['close']
        spy_sma50 = spy_c.rolling(50).mean().iloc[-1]
        spy_price = spy_c.iloc[-1]
        spy_vol20 = spy_c.pct_change().rolling(20).std().iloc[-1] * 100
        if not (spy_price > spy_sma50 and spy_vol20 < 1.0):
            continue

        for ticker, df in all_data.items():
            if ticker in CONTEXT_TICKERS:
                continue
            df_sl = df[df.index <= date]
            if len(df_sl) < 80:
                continue
            # Anti-knife 5d
            if ticker in recent_entries and (date - recent_entries[ticker]).days < 7:
                continue

            c  = df_sl['close']
            h  = df_sl['high']
            l  = df_sl['low']
            v  = df_sl['volume']

            # RSI — Wilder (VERIFICADO)
            rsi_series = calc_rsi_wilder(c)
            rsi14      = rsi_series.iloc[-1]

            # RSI slope (V39 feature): RSI ahora vs RSI hace 3 días
            rsi_slope  = rsi_series.iloc[-1] - rsi_series.iloc[-4] if len(rsi_series) >= 4 else 0.0

            # MACD
            mh     = calc_macd(c)
            mh_c   = mh.iloc[-1]
            mh_p   = mh.iloc[-2] if len(mh) > 1 else 0.0

            # SMA50 y score
            sma50      = c.rolling(50).mean().iloc[-1]
            atr14      = calc_atr(h, l, c).iloc[-1]
            vol_avg20  = v.rolling(20).mean().iloc[-1]
            vol_ratio  = v.iloc[-1] / (vol_avg20 + 1e-10)
            price      = c.iloc[-1]
            dist_sma50 = (price / sma50 - 1) * 100
            macd_acc_n = (mh_c - mh_p) / (atr14 * 0.01 + 1e-6)
            score      = calc_v4_score(rsi14, dist_sma50, macd_acc_n, vol_ratio)

            # Validar NaNs
            if any(np.isnan(x) for x in [rsi14, dist_sma50, score, rsi_slope, atr14]):
                continue

            row = {
                'rsi14':      rsi14,
                'rsi_slope':  rsi_slope,
                'dist_sma50': dist_sma50,
                'score':      score,
                'vol_ratio':  vol_ratio,
                'macd_up':    mh_c > mh_p,
            }

            if not filters_fn(row):
                continue

            # Retorno a 10 días
            future = df[df.index > date].head(hold_days)
            if len(future) < hold_days:
                continue

            ret = future['close'].iloc[-1] / price - 1
            trades.append({
                'date':       date,
                'ticker':     ticker,
                'price':      price,
                'ret':        ret,
                'rsi':        rsi14,
                'rsi_slope':  rsi_slope,
                'dist_sma50': dist_sma50,
                'score':      score,
                'vol_ratio':  vol_ratio,
            })
            recent_entries[ticker] = date

    return pd.DataFrame(trades)

def metrics(df, name):
    if df is None or len(df) < MIN_TRADES:
        return {'name': name, 'trades': len(df) if df is not None else 0,
                'sharpe': -99, 'wr': 0, 'avg_ret': 0, 'total_ret': 0,
                'mdd': 0, 'wins': 0, 'losses': 0, 'avgw': 0, 'avgl': 0}
    r    = df['ret'].values
    wins = (r > 0).sum()
    wr   = wins / len(r) * 100
    avgw = r[r > 0].mean() * 100 if wins > 0 else 0
    avgl = r[r <= 0].mean() * 100 if (len(r) - wins) > 0 else 0
    eq   = np.cumprod(1 + r)
    mdd  = ((eq - np.maximum.accumulate(eq)) / np.maximum.accumulate(eq)).min() * 100
    # Sharpe anualizado igual que Round 3
    daily = r / HOLD_DAYS
    sharpe = (daily.mean() / (daily.std() + 1e-10)) * np.sqrt(252)
    return {
        'name': name, 'trades': len(r), 'wins': int(wins),
        'losses': int(len(r) - wins), 'wr': wr, 'avg_ret': r.mean() * 100,
        'avgw': avgw, 'avgl': avgl,
        'sharpe': sharpe, 'total_ret': (eq[-1] - 1) * 100, 'mdd': mdd,
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 80)
    print("  TEST DEFINITIVO: V4 + RSI SLOPE")
    print(f"  Universo: 260+ tickers  |  {PERIOD_START} → {PERIOD_END}  |  Hold: {HOLD_DAYS}d")
    print(f"  RSI: Wilder ewm(com=13) — VERIFICADO")
    print("=" * 80)

    print(f"\n  Cargando {len(ALL_TICKERS)} tickers de titan.db...")
    with TitanDB() as db:
        all_data = {}
        for ticker in ALL_TICKERS:
            df = db.get_prices(ticker, PERIOD_START, PERIOD_END)
            if df is not None and len(df) > 80:
                all_data[ticker] = df.sort_index()
    print(f"  {len(all_data)} tickers con datos suficientes\n")

    spy_df = all_data.get('SPY')
    if spy_df is None:
        print("  ERROR: SPY no encontrado"); return

    # ── Filtros base V4 ──
    def v4_base(r):
        return (r['rsi14'] < 25 and r['dist_sma50'] < -10 and
                r['score'] > 30 and r['vol_ratio'] < 1.5 and r['macd_up'])

    strategies = [
        ("V4 baseline",
         lambda r: v4_base(r)),

        ("V4 + rsi_slope < 0   (aun cayendo)",
         lambda r: v4_base(r) and r['rsi_slope'] < 0),

        ("V4 + rsi_slope < -2  (cayendo mod.)",
         lambda r: v4_base(r) and r['rsi_slope'] < -2),

        ("V4 + rsi_slope < -5  (cayendo fuerte)",
         lambda r: v4_base(r) and r['rsi_slope'] < -5),

        ("V4 + rsi_slope >= 0  (estabilizando)",
         lambda r: v4_base(r) and r['rsi_slope'] >= 0),

        ("V4 relajado RSI<27",
         lambda r: (r['rsi14'] < 27 and r['dist_sma50'] < -10 and
                    r['score'] > 30 and r['vol_ratio'] < 1.5 and r['macd_up'])),

        ("V4 + rsi_slope<0 + Vol<1.0x",
         lambda r: v4_base(r) and r['rsi_slope'] < 0 and r['vol_ratio'] < 1.0),
    ]

    print(f"  Corriendo {len(strategies)} estrategias sobre universo completo...\n")
    results = []
    v4_trades = None

    for i, (name, fn) in enumerate(strategies):
        print(f"  [{i+1}/{len(strategies)}] {name}...")
        t = run_backtest(all_data, spy_df, fn, HOLD_DAYS)
        m = metrics(t, name)
        results.append(m)
        if name == "V4 baseline":
            v4_trades = t

    # ── Tabla de resultados ───────────────────────────────────────────────────
    print()
    print("=" * 100)
    print(f"  {'ESTRATEGIA':<38} {'TR':>4} {'W':>3} {'L':>3}  {'WR%':>5}  {'AVG%':>6}  "
          f"{'AVGW%':>6}  {'AVGL%':>6}  {'TOT%':>8}  {'SHARP':>6}  {'MDD%':>6}")
    print("=" * 100)

    v4_sharpe = next(r['sharpe'] for r in results if r['name'] == "V4 baseline")
    for r in sorted(results, key=lambda x: x['sharpe'], reverse=True):
        if r['trades'] < MIN_TRADES:
            print(f"  {r['name']:<38} {r['trades']:>4} trades  ✗ muestra insuficiente")
            continue
        flag = " ◄ REF" if r['name'] == "V4 baseline" else \
               " ★ SUPERA V4" if r['sharpe'] > v4_sharpe * 1.05 else \
               " ↓ PEOR" if r['sharpe'] < v4_sharpe * 0.85 else ""
        print(f"  {r['name']:<38} {r['trades']:>4}  "
              f"{r['wins']:>3}  {r['losses']:>3}  "
              f"{r['wr']:>5.1f}%  {r['avg_ret']:>5.2f}%  "
              f"{r['avgw']:>5.2f}%  {r['avgl']:>5.2f}%  "
              f"{r['total_ret']:>7.1f}%  {r['sharpe']:>6.2f}  "
              f"{r['mdd']:>5.1f}%{flag}")
    print("=" * 100)

    # ── Análisis de trades V4 por RSI slope ──────────────────────────────────
    if v4_trades is not None and len(v4_trades) >= MIN_TRADES:
        print()
        print("=" * 80)
        print("  DESGLOSE: TRADES V4 POR RSI SLOPE")
        print("=" * 80)

        slope_stats = [
            ("rsi_slope < -5  (fuerte caida)",   v4_trades['rsi_slope'] < -5),
            ("rsi_slope -5 a -2",                (v4_trades['rsi_slope'] >= -5) & (v4_trades['rsi_slope'] < -2)),
            ("rsi_slope -2 a 0",                 (v4_trades['rsi_slope'] >= -2) & (v4_trades['rsi_slope'] < 0)),
            ("rsi_slope 0 a +3 (neutro/giro)",   (v4_trades['rsi_slope'] >= 0) & (v4_trades['rsi_slope'] < 3)),
            ("rsi_slope >= +3  (giro fuerte)",   v4_trades['rsi_slope'] >= 3),
        ]
        print(f"\n  {'Bucket RSI slope':<35}  {'TR':>3}  {'WR':>5}  {'AVG%':>6}  {'SHARP':>6}")
        print(f"  {'-'*60}")
        for label, mask in slope_stats:
            sub = v4_trades[mask]
            if len(sub) == 0:
                continue
            wr  = (sub['ret'] > 0).mean() * 100
            avg = sub['ret'].mean() * 100
            sh  = (sub['ret'].mean() / (sub['ret'].std() + 1e-10)) / HOLD_DAYS * np.sqrt(252) \
                  if len(sub) > 1 else float('nan')
            print(f"  {label:<35}  {len(sub):>3}  {wr:>5.1f}%  {avg:>+5.2f}%  "
                  f"{'nan':>6}" if np.isnan(sh) else
                  f"  {label:<35}  {len(sub):>3}  {wr:>5.1f}%  {avg:>+5.2f}%  {sh:>6.2f}")

        # Lista de trades V4 con su slope
        print(f"\n  Todos los trades V4 baseline ({len(v4_trades)}):")
        print(f"  {'Fecha':<12} {'Ticker':<7} {'RSI':>5} {'Slope':>7} {'vs SMA':>8} "
              f"{'Score':>6} {'Vol':>5} {'Ret10d':>8}")
        print(f"  {'-'*70}")
        for _, t in v4_trades.sort_values('date').iterrows():
            flag = " WIN" if t['ret'] > 0 else " loss"
            slope_flag = " ↑ girando" if t['rsi_slope'] >= 0 else ""
            print(f"  {str(t['date'])[:10]:<12} {t['ticker']:<7} "
                  f"{t['rsi']:>5.1f} {t['rsi_slope']:>+7.2f} "
                  f"{t['dist_sma50']:>7.1f}% {t['score']:>6.0f} "
                  f"{t['vol_ratio']:>5.2f}x {t['ret']*100:>+7.1f}%{flag}{slope_flag}")

    # ── Conclusión ────────────────────────────────────────────────────────────
    print()
    print("=" * 80)
    print("  CONCLUSIÓN")
    print("=" * 80)

    v4_r = next(r for r in results if r['name'] == "V4 baseline")
    slope_r = next((r for r in results if 'rsi_slope < 0' in r['name'] and 'Vol' not in r['name']), None)

    if slope_r and slope_r['trades'] >= MIN_TRADES:
        delta_sharpe = slope_r['sharpe'] - v4_r['sharpe']
        delta_trades = slope_r['trades'] - v4_r['trades']
        delta_wr     = slope_r['wr'] - v4_r['wr']

        print(f"\n  V4 baseline:        {v4_r['trades']:>3} trades | WR {v4_r['wr']:.1f}% | Sharpe {v4_r['sharpe']:.2f}")
        print(f"  V4 + rsi_slope<0:   {slope_r['trades']:>3} trades | WR {slope_r['wr']:.1f}% | Sharpe {slope_r['sharpe']:.2f}")
        print(f"  Diferencia:         {delta_trades:>+3} trades | WR {delta_wr:>+.1f}% | Sharpe {delta_sharpe:>+.2f}")

        if delta_sharpe > 1.0 and slope_r['wr'] >= v4_r['wr']:
            print(f"\n  RESULTADO: RSI slope < 0 MEJORA V4.")
            print(f"  Filtrar entradas donde RSI ya está girando al alza elimina trades de peor calidad.")
            print(f"  Recomendación: evaluar V5 = V4 + rsi_slope < 0 con walk-forward completo.")
        elif delta_sharpe > 0 and delta_trades >= -(v4_r['trades'] * 0.3):
            print(f"\n  RESULTADO: RSI slope < 0 muestra mejora MODERADA.")
            print(f"  Mejora Sharpe sin perder demasiados trades.")
            print(f"  Pero con {slope_r['trades']} trades la diferencia puede ser ruido.")
            print(f"  Requiere más datos para confirmar.")
        else:
            print(f"\n  RESULTADO: RSI slope < 0 NO mejora V4 de forma significativa.")
            print(f"  O reduce demasiados trades, o el Sharpe no mejora.")
            print(f"  Mantener V4 sin cambios.")
    else:
        print(f"\n  Muestra insuficiente para V4 + rsi_slope. V4 permanece sin cambios.")

    print()

if __name__ == '__main__':
    main()
