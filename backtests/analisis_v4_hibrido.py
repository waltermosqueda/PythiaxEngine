"""
ANÁLISIS: ¿Pueden los conceptos de V37/V39 mejorar V4?
=======================================================
Hipótesis: algunos features de V37 (Bollinger squeeze, close strength,
volume z-score) podrían añadir valor a V4 como reglas simples (sin ML).

Estrategias comparadas:
  1. V4 baseline        — RSI<25 + SMA<-10% + Score>30 (nuestro ganador)
  2. V4 + close_str     — + cerró en mitad superior del día (V37: close_strength)
  3. V4 + vol_zscore    — + volumen superior a la media (V37: vol_zscore > 0)
  4. V4 + bb_squeeze    — + bandas Bollinger comprimidas (V37: bb_squeeze_rank)
  5. V4 + cs + volz     — + close_strength Y vol_zscore combinados
  6. V4 + cs + bb       — + close_strength Y bb_squeeze
  7. V4 relaxed (RSI<27) — versión relajada para comparar volumen de trades
  8. V37-rules only     — bb_squeeze + vol_zscore + close_str SIN filtros V4
                         (para ver si los features de V37 sirven por sí solos)

Período: Sep 2024 - Mar 2026 (misma ventana que Round 3)
Universo: 80 tickers del Round 3
Holding: 10 días
Fuente de datos: titan.db (local, sin descarga)

Nota: NINGUNA estrategia usa ML. Solo reglas determinísticas.
Si algún hibrido supera V4, lo documentamos y planificamos tests adicionales.
Si ninguno supera V4, la evidencia confirma que V4 es el óptimo actual.
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

# ── Configuración ────────────────────────────────────────────────────────────
PERIOD_START = '2024-09-01'
PERIOD_END   = '2026-03-28'
HOLD_DAYS    = 10
MIN_TRADES   = 3  # mínimo de trades para mostrar resultados

TICKERS = [
    # Tech (20)
    'AAPL','MSFT','GOOGL','AMZN','META','NVDA','AMD','TSLA','NFLX','CRM',
    'ORCL','ADBE','INTC','AVGO','QCOM','MU','AMAT','LRCX','TXN','PLTR',
    # Finanzas (10)
    'JPM','BAC','WFC','GS','V','MA','AXP','C','PYPL','COIN',
    # Healthcare (10)
    'JNJ','PFE','UNH','MRK','ABBV','LLY','TMO','ABT','BMY','AMGN',
    # Energia (10)
    'XOM','CVX','COP','SLB','OXY','HAL','DVN','MPC','VLO','EOG',
    # Consumer (10)
    'KO','PEP','PG','WMT','COST','MCD','NKE','SBUX','TGT','HD',
    # Industrial (10)
    'CAT','BA','GE','RTX','HON','LMT','UPS','FDX','DE','MMM',
    # LatAm + ADR (10)
    'MELI','NU','BABA','VALE','PBR','GLOB','STNE','XP','SBS','ITUB',
    # SPY para régimen
    'SPY',
]

# ── Indicadores ──────────────────────────────────────────────────────────────

def calc_rsi_wilder(close, period=14):
    """RSI con Wilder's smoothing — ewm(com=period-1) OBLIGATORIO."""
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - 100 / (1 + rs)

def calc_macd(close, fast=12, slow=26, signal=9):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd = ema_f - ema_s
    sig = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig, macd - sig

def calc_atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_v4_score(rsi, dist_sma50, macd_accel_norm, vol_ratio):
    """Score idéntico al usado en V4 y Final."""
    rsi_score     = max(0, min(40, (30 - rsi) / 30 * 40))
    stretch_score = max(0, min(30, (abs(dist_sma50) - 5) / 15 * 30))
    macd_score    = max(0, min(20, macd_accel_norm * 5))
    vol_score     = max(0, min(10, (1.5 - vol_ratio) / 1.5 * 10))
    return rsi_score + stretch_score + macd_score + vol_score

def calc_bb_squeeze_rank(close, window=20, lookback=60):
    """
    Bollinger band width percentile rank (0-100).
    Valores BAJOS = bandas comprimidas = posible squeeze.
    Valores ALTOS = bandas expandidas = ya hubo movimiento.
    """
    ma = close.rolling(window).mean()
    std = close.rolling(window).std()
    bb_width = (4 * std) / (ma + 1e-10)
    return bb_width.rolling(lookback, min_periods=20).rank(pct=True) * 100

def calc_close_strength(high, low, close):
    """
    (close - low) / (high - low): 1.0 = cerró en máximo, 0.0 = en mínimo.
    > 0.5 = cerró en mitad superior = fuerza compradora.
    """
    return (close - low) / (high - low + 1e-10)

def calc_vol_zscore(volume, window=20):
    """Z-score del volumen. > 0 = sobre la media."""
    vol_ma  = volume.rolling(window).mean()
    vol_std = volume.rolling(window).std()
    return (volume - vol_ma) / (vol_std + 1e-10)

# ── Backtest engine ──────────────────────────────────────────────────────────

def run_backtest(all_data, spy_df, filters_fn, hold_days=10):
    """
    Genera lista de trades con la función de filtros especificada.
    filters_fn(row) -> bool, donde row tiene todos los indicadores calculados.
    """
    trades = []
    recent_entries = {}  # anti-knife: {ticker: last_entry_date}

    trading_dates = sorted(spy_df.index)

    for i, date in enumerate(trading_dates):
        # SPY regime check
        spy_slice = spy_df[spy_df.index <= date]
        if len(spy_slice) < 55:
            continue
        spy_close = spy_slice['close']
        spy_sma50 = spy_close.rolling(50).mean().iloc[-1]
        spy_price = spy_close.iloc[-1]
        spy_vol20d = spy_close.pct_change().rolling(20).std().iloc[-1] * 100
        regime_ok = (spy_price > spy_sma50) and (spy_vol20d < 1.0)
        if not regime_ok:
            continue

        for ticker, df in all_data.items():
            if ticker == 'SPY':
                continue
            df_slice = df[df.index <= date]
            if len(df_slice) < 80:
                continue

            # Anti-knife
            if ticker in recent_entries:
                days_since = (date - recent_entries[ticker]).days
                if days_since < 7:  # ~5 business days
                    continue

            c = df_slice['close']
            h = df_slice['high']
            l = df_slice['low']
            v = df_slice['volume']

            rsi14       = calc_rsi_wilder(c).iloc[-1]
            _, _, mh    = calc_macd(c)
            mh_curr     = mh.iloc[-1]
            mh_prev     = mh.iloc[-2] if len(mh) > 1 else 0
            sma50       = c.rolling(50).mean().iloc[-1]
            atr14       = calc_atr(h, l, c).iloc[-1]
            vol_avg20   = v.rolling(20).mean().iloc[-1]
            vol_ratio   = v.iloc[-1] / (vol_avg20 + 1e-10)
            price       = c.iloc[-1]
            dist_sma50  = (price / sma50 - 1) * 100
            macd_accel  = mh_curr - mh_prev
            macd_acc_n  = macd_accel / (atr14 * 0.01 + 1e-6)
            score       = calc_v4_score(rsi14, dist_sma50, macd_acc_n, vol_ratio)

            # V37-derived features
            bb_rank     = calc_bb_squeeze_rank(c).iloc[-1]
            cl_strength = calc_close_strength(h, l, c).iloc[-1]
            vol_zscore  = calc_vol_zscore(v).iloc[-1]

            row = {
                'rsi14': rsi14, 'dist_sma50': dist_sma50, 'score': score,
                'vol_ratio': vol_ratio, 'macd_up': mh_curr > mh_prev,
                'bb_rank': bb_rank, 'cl_strength': cl_strength, 'vol_zscore': vol_zscore,
            }

            # Skip NaNs
            if any(np.isnan(v_) for v_ in [rsi14, dist_sma50, score, bb_rank, cl_strength, vol_zscore]):
                continue

            if not filters_fn(row):
                continue

            # Calcular retorno a HOLD_DAYS
            future = df[df.index > date].head(hold_days)
            if len(future) < hold_days:
                continue

            ret = future['close'].iloc[-1] / price - 1

            trades.append({
                'date': date, 'ticker': ticker, 'price': price,
                'ret': ret, 'rsi': rsi14, 'dist_sma50': dist_sma50,
                'score': score, 'bb_rank': bb_rank, 'cl_strength': cl_strength,
                'vol_zscore': vol_zscore,
            })
            recent_entries[ticker] = date

    return pd.DataFrame(trades)

def metrics(trades_df, name):
    """Calcula métricas estándar de la estrategia."""
    if trades_df is None or len(trades_df) < MIN_TRADES:
        return {'name': name, 'trades': len(trades_df) if trades_df is not None else 0,
                'sharpe': 0, 'wr': 0, 'avg_ret': 0, 'total_ret': 0, 'mdd': 0}

    rets = trades_df['ret'].values
    wins = (rets > 0).sum()
    wr   = wins / len(rets) * 100
    avg  = rets.mean() * 100
    avgw = rets[rets > 0].mean() * 100 if wins > 0 else 0
    avgl = rets[rets <= 0].mean() * 100 if (len(rets) - wins) > 0 else 0

    # Equity curve (secuencial, 1 trade a la vez)
    eq = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    mdd = dd.min() * 100

    # Sharpe (anualizado, asume ~252/hold_days periodos por año)
    daily_rets = rets / HOLD_DAYS
    sharpe = (daily_rets.mean() / (daily_rets.std() + 1e-10)) * np.sqrt(252)
    total  = (eq[-1] - 1) * 100

    return {
        'name': name, 'trades': len(rets),
        'wins': int(wins), 'losses': int(len(rets) - wins),
        'wr': wr, 'avg_ret': avg, 'avgw': avgw, 'avgl': avgl,
        'sharpe': sharpe, 'total_ret': total, 'mdd': mdd,
    }

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    print()
    print("=" * 80)
    print("  ANÁLISIS HÍBRIDO V4 + CONCEPTOS V37/V39")
    print(f"  Período: {PERIOD_START} → {PERIOD_END}  |  Hold: {HOLD_DAYS}d")
    print("=" * 80)

    # Cargar datos de DB
    print(f"\n  Cargando datos de titan.db...")
    with TitanDB() as db:
        all_data = {}
        for ticker in TICKERS:
            df = db.get_prices(ticker, PERIOD_START, PERIOD_END)
            if df is not None and len(df) > 80:
                df = df.sort_index()
                all_data[ticker] = df

    print(f"  {len(all_data)} tickers cargados\n")

    spy_df = all_data.get('SPY')
    if spy_df is None:
        print("  ERROR: SPY no encontrado en DB")
        return

    # Definir filtros para cada estrategia
    # BASE V4 filters (sin SPY regime — el regime se aplica en el engine)
    def v4_base(r):
        return (r['rsi14'] < 25 and r['dist_sma50'] < -10 and
                r['score'] > 30 and r['vol_ratio'] < 1.5 and r['macd_up'])

    strategies = [
        # 1. V4 baseline
        ("V4 baseline",
         lambda r: v4_base(r)),

        # 2. V4 + close_strength > 0.5 (cerró en mitad superior)
        ("V4 + close_str>0.5",
         lambda r: v4_base(r) and r['cl_strength'] > 0.5),

        # 3. V4 + vol_zscore > 0 (volumen sobre la media)
        ("V4 + vol_zscore>0",
         lambda r: v4_base(r) and r['vol_zscore'] > 0),

        # 4. V4 + bb_squeeze (bandas en percentil < 30 = comprimidas)
        ("V4 + bb_squeeze<30",
         lambda r: v4_base(r) and r['bb_rank'] < 30),

        # 5. V4 + bb_squeeze < 50 (versión más permisiva)
        ("V4 + bb_squeeze<50",
         lambda r: v4_base(r) and r['bb_rank'] < 50),

        # 6. V4 + close_str + vol_zscore (dos features V37)
        ("V4 + cs>0.5 + volz>0",
         lambda r: v4_base(r) and r['cl_strength'] > 0.5 and r['vol_zscore'] > 0),

        # 7. V4 + close_str + bb_squeeze
        ("V4 + cs>0.5 + bb<30",
         lambda r: v4_base(r) and r['cl_strength'] > 0.5 and r['bb_rank'] < 30),

        # 8. V4 relajado (RSI<27 para más trades)
        ("V4 relaxed (RSI<27)",
         lambda r: (r['rsi14'] < 27 and r['dist_sma50'] < -10 and
                    r['score'] > 30 and r['vol_ratio'] < 1.5 and r['macd_up'])),

        # 9. Solo features V37 sin filtros V4 (para saber si sirven solas)
        ("V37-rules solo (bb<30+cs>0.5+volz>0)",
         lambda r: r['bb_rank'] < 30 and r['cl_strength'] > 0.5 and r['vol_zscore'] > 0),

        # 10. V4 + bb EXPANDIDO (>70) — lo OPUESTO al squeeze
        # Hipótesis: stock oversold + ya en movimiento (bb expandido) puede ser mejor
        ("V4 + bb_expandido>70",
         lambda r: v4_base(r) and r['bb_rank'] > 70),
    ]

    print(f"  Corriendo {len(strategies)} estrategias...\n")

    results = []
    for name, fn in strategies:
        print(f"  [{strategies.index((name, fn))+1}/{len(strategies)}] {name}...")
        trades_df = run_backtest(all_data, spy_df, fn, HOLD_DAYS)
        m = metrics(trades_df, name)
        results.append(m)

        # Guardar trades de V4 baseline para análisis profundo
        if name == "V4 baseline":
            v4_trades = trades_df

    # ── Tabla de resultados ──────────────────────────────────────────────────
    print()
    print("=" * 100)
    print(f"  {'ESTRATEGIA':<35} {'TR':>4} {'W':>3} {'L':>3}  {'WR%':>5}  {'AVG%':>6}  "
          f"{'AVGW%':>6}  {'AVGL%':>6}  {'TOT%':>7}  {'SHARP':>6}  {'MDD%':>6}")
    print("=" * 100)

    for r in sorted(results, key=lambda x: x['sharpe'], reverse=True):
        n_trades = r['trades']
        if n_trades < MIN_TRADES:
            print(f"  {r['name']:<35} {'<' + str(MIN_TRADES) + ' trades':>8}")
            continue
        flag = " ◄ GANADOR" if r['name'] == "V4 baseline" else ""
        print(f"  {r['name']:<35} {n_trades:>4}  "
              f"{r.get('wins',0):>3}  {r.get('losses',0):>3}  "
              f"{r['wr']:>5.1f}%  {r['avg_ret']:>5.2f}%  "
              f"{r.get('avgw',0):>5.2f}%  {r.get('avgl',0):>5.2f}%  "
              f"{r['total_ret']:>6.1f}%  {r['sharpe']:>6.2f}  "
              f"{r['mdd']:>5.1f}%{flag}")
    print("=" * 100)

    # ── Análisis profundo de trades V4 ──────────────────────────────────────
    if v4_trades is not None and len(v4_trades) >= MIN_TRADES:
        print()
        print("=" * 80)
        print("  ANÁLISIS PROFUNDO: ¿Cómo se distribuyen los features V37 en trades V4?")
        print("=" * 80)

        print(f"\n  Total trades V4: {len(v4_trades)}")

        # BB squeeze distribution en trades V4
        print(f"\n  Bollinger Squeeze Rank en trades V4:")
        print(f"    Promedio: {v4_trades['bb_rank'].mean():.1f} (50 = media histórica)")
        print(f"    Mediana:  {v4_trades['bb_rank'].median():.1f}")
        print(f"    < 30 (squeeze): {(v4_trades['bb_rank'] < 30).sum()} trades ({(v4_trades['bb_rank'] < 30).mean()*100:.0f}%)")
        print(f"    > 70 (expand):  {(v4_trades['bb_rank'] > 70).sum()} trades ({(v4_trades['bb_rank'] > 70).mean()*100:.0f}%)")

        # Performance por bb_rank
        print(f"\n  Performance V4 segun BB rank:")
        for label, mask in [
            ("BB < 30 (squeeze)",   v4_trades['bb_rank'] < 30),
            ("BB 30-50",            (v4_trades['bb_rank'] >= 30) & (v4_trades['bb_rank'] < 50)),
            ("BB 50-70",            (v4_trades['bb_rank'] >= 50) & (v4_trades['bb_rank'] < 70)),
            ("BB > 70 (expandido)", v4_trades['bb_rank'] >= 70),
        ]:
            sub = v4_trades[mask]
            if len(sub) == 0:
                continue
            wr  = (sub['ret'] > 0).mean() * 100
            avg = sub['ret'].mean() * 100
            sh  = (sub['ret'].mean() / (sub['ret'].std() + 1e-10)) * np.sqrt(252 / HOLD_DAYS)
            print(f"    {label:<25}  {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>5.2f}%  Sharpe: {sh:>5.2f}")

        # Close strength distribution
        print(f"\n  Close Strength en trades V4:")
        print(f"    Promedio: {v4_trades['cl_strength'].mean():.3f} (0.5 = neutral)")
        print(f"    > 0.5 (fuerza comp.): {(v4_trades['cl_strength'] > 0.5).sum()} trades")
        for label, mask in [
            ("CS < 0.3 (cierre debil)",    v4_trades['cl_strength'] < 0.3),
            ("CS 0.3-0.5",                 (v4_trades['cl_strength'] >= 0.3) & (v4_trades['cl_strength'] < 0.5)),
            ("CS > 0.5 (cierre fuerte)",   v4_trades['cl_strength'] >= 0.5),
        ]:
            sub = v4_trades[mask]
            if len(sub) == 0:
                continue
            wr  = (sub['ret'] > 0).mean() * 100
            avg = sub['ret'].mean() * 100
            sh  = (sub['ret'].mean() / (sub['ret'].std() + 1e-10)) * np.sqrt(252 / HOLD_DAYS)
            print(f"    {label:<30}  {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>5.2f}%  Sharpe: {sh:>5.2f}")

        # Volume z-score distribution
        print(f"\n  Volume Z-Score en trades V4:")
        for label, mask in [
            ("VolZ < -0.5 (vol bajo)",  v4_trades['vol_zscore'] < -0.5),
            ("VolZ -0.5 a 0.5",         (v4_trades['vol_zscore'] >= -0.5) & (v4_trades['vol_zscore'] < 0.5)),
            ("VolZ > 0.5 (vol alto)",   v4_trades['vol_zscore'] >= 0.5),
        ]:
            sub = v4_trades[mask]
            if len(sub) == 0:
                continue
            wr  = (sub['ret'] > 0).mean() * 100
            avg = sub['ret'].mean() * 100
            sh  = (sub['ret'].mean() / (sub['ret'].std() + 1e-10)) * np.sqrt(252 / HOLD_DAYS)
            print(f"    {label:<30}  {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>5.2f}%  Sharpe: {sh:>5.2f}")

        # Trades V4 individuales con features V37
        print(f"\n  Trades V4 con features V37 mostrados:")
        v4_trades_sorted = v4_trades.sort_values('date')
        print(f"  {'Fecha':<12} {'Ticker':<7} {'RSI':>5} {'vs SMA':>7} {'Score':>6} "
              f"{'BB rank':>8} {'CS':>6} {'VolZ':>6} {'Ret10d':>8}")
        print(f"  {'-'*75}")
        for _, t in v4_trades_sorted.iterrows():
            ret_str = f"{t['ret']*100:+.1f}%"
            print(f"  {str(t['date'])[:10]:<12} {t['ticker']:<7} "
                  f"{t['rsi']:>5.1f} {t['dist_sma50']:>6.1f}% {t['score']:>6.0f} "
                  f"{t['bb_rank']:>8.1f} {t['cl_strength']:>6.2f} {t['vol_zscore']:>6.2f} "
                  f"{ret_str:>8}")

    print()
    print("=" * 80)
    print("  CONCLUSIÓN")
    print("=" * 80)

    v4_result   = next(r for r in results if r['name'] == "V4 baseline")
    v4_sharpe   = v4_result['sharpe']
    v4_trades_n = v4_result['trades']

    better = [r for r in results if r['sharpe'] > v4_sharpe and r['trades'] >= MIN_TRADES
              and r['name'] != "V4 baseline"]
    worse  = [r for r in results if r['sharpe'] < v4_sharpe and r['trades'] >= MIN_TRADES
              and r['name'] != "V4 baseline"]

    if better:
        print(f"\n  Estrategias que SUPERAN a V4 (Sharpe {v4_sharpe:.2f}):")
        for r in sorted(better, key=lambda x: x['sharpe'], reverse=True):
            extra_trades = r['trades'] - v4_trades_n
            print(f"    ► {r['name']:<35} Sharpe {r['sharpe']:>6.2f} | "
                  f"{r['trades']} trades ({extra_trades:+d} vs V4) | WR {r['wr']:.1f}%")
        print()
        print("  → Estos merecen análisis adicional y Walk-Forward antes de usar en producción.")
    else:
        print(f"\n  Ninguna variante supera a V4 (Sharpe {v4_sharpe:.2f}).")
        print("  → Los conceptos de V37/V39 NO agregan valor a V4 como reglas simples.")
        print("  → Recomendación: mantener V4 sin cambios.")

    if worse:
        print(f"\n  Estrategias PEORES que V4:")
        for r in sorted(worse, key=lambda x: x['sharpe']):
            if r['trades'] >= MIN_TRADES:
                print(f"    ✗ {r['name']:<35} Sharpe {r['sharpe']:>6.2f} | {r['trades']} trades")

    print()
    print("  Nota: con 15 trades el Sharpe tiene alta varianza estadística.")
    print("  Un Sharpe superior con <10 trades puede ser ruido, no señal.")
    print()

if __name__ == '__main__':
    main()
