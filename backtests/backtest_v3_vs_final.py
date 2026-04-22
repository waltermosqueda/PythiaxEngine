"""
BACKTEST: INVERTIR V3 vs FINAL vs V2
=====================================
Valida si los filtros optimizados de V3 realmente mejoran sobre Final.

V3 filtros:
  - RSI < 25 (vs 30)
  - SMA50 dist -15% a -10% (vs >-5%)
  - Volume < 0.8x (vs 1.5x)
  - MACD accel media-alta
  - Solo Mie/Jue
  - Score 30-50

Periodos:
  - In-Sample:  Jun 2025 - Mar 2026
  - Out-Sample: Sep 2024 - Jun 2025
  - Full:       Sep 2024 - Mar 2026
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
import os

warnings.filterwarnings('ignore')
os.environ['PYTHONIOENCODING'] = 'utf-8'

# ═══════════════════════════════════════════════════
# UNIVERSO
# ═══════════════════════════════════════════════════
TICKERS = [
    'AAPL','MSFT','GOOGL','AMZN','META','NVDA','AMD','TSLA','NFLX','CRM',
    'ORCL','ADBE','INTC','AVGO','QCOM','MU','AMAT','LRCX','KLAC','TXN',
    'JPM','BAC','WFC','GS','MS','V','MA','AXP','C','BLK',
    'JNJ','PFE','UNH','MRK','ABBV','LLY','TMO','ABT','BMY','AMGN',
    'XOM','CVX','COP','SLB','EOG','OXY','DVN','HAL','MPC','VLO',
    'KO','PEP','PG','WMT','COST','MCD','NKE','SBUX','TGT','HD',
    'CAT','BA','GE','RTX','HON','LMT','UPS','FDX','DE','MMM',
    'DIS','CMCSA','T','VZ','TMUS','PYPL','XYZ','COIN','MSTR','PLTR',
]
CONTEXT_TICKERS = ['SPY','QQQ','IWM','^VIX']

# ═══════════════════════════════════════════════════
# INDICADORES
# ═══════════════════════════════════════════════════
def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast).mean()
    ema_slow = series.ewm(span=slow).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal).mean()
    return macd, macd_signal, macd - macd_signal

def calc_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

# ═══════════════════════════════════════════════════
# DESCARGA
# ═══════════════════════════════════════════════════
def download_data(start='2024-06-01', end='2026-03-27'):
    print(f"\nDescargando datos de {len(TICKERS)} activos + {len(CONTEXT_TICKERS)} contexto...")
    print(f"Periodo: {start} -> {end}")

    all_tickers = TICKERS + CONTEXT_TICKERS
    data = yf.download(all_tickers, start=start, end=end, progress=False, threads=True)

    if isinstance(data.columns, pd.MultiIndex):
        available = []
        for t in TICKERS:
            try:
                close = data['Close'][t].dropna()
                if len(close) > 100:
                    available.append(t)
            except:
                pass
        print(f"{len(available)} activos con datos suficientes")
        return data, available
    else:
        print("Error en formato de datos")
        return None, []

# ═══════════════════════════════════════════════════
# ESTRATEGIA: INVERTIR V2 (base)
# ═══════════════════════════════════════════════════
def strategy_v2(data, ticker, date_idx):
    """RSI<30 + MACD up + >5% debajo SMA50 + volumen calmo"""
    try:
        close = data['Close'][ticker]
        high = data['High'][ticker]
        low = data['Low'][ticker]
        volume = data['Volume'][ticker]

        rsi = calc_rsi(close)
        _, _, macd_hist = calc_macd(close)
        sma50 = close.rolling(50).mean()
        vol_avg = volume.rolling(20).mean()
        atr = calc_atr(high, low, close)

        rsi_val = rsi.iloc[date_idx]
        macd_now = macd_hist.iloc[date_idx]
        macd_prev = macd_hist.iloc[date_idx - 1]
        price = close.iloc[date_idx]
        sma50_val = sma50.iloc[date_idx]
        vol_ratio = volume.iloc[date_idx] / vol_avg.iloc[date_idx] if vol_avg.iloc[date_idx] > 0 else 2
        atr_val = atr.iloc[date_idx]
        dist_sma = (price - sma50_val) / sma50_val * 100
        macd_accel = macd_now - macd_prev
        macd_accel_norm = macd_accel / (atr_val * 0.01 + 1e-6)

        if rsi_val < 30 and macd_now > macd_prev and dist_sma < -5 and vol_ratio < 1.5:
            rsi_score = min(40, max(0, (30 - rsi_val) / 30 * 40))
            sma_score = min(30, max(0, abs(dist_sma) / 15 * 30))
            macd_score = min(20, max(0, macd_accel_norm * 5))
            vol_score = min(10, max(0, (1.5 - vol_ratio) / 1.5 * 10))
            total_score = rsi_score + sma_score + macd_score + vol_score
            stop_loss = price - 2 * atr_val

            return True, {
                'rsi': rsi_val, 'dist_sma': dist_sma, 'vol_ratio': vol_ratio,
                'score': total_score, 'stop_loss': stop_loss, 'atr': atr_val,
                'macd_accel_norm': macd_accel_norm,
            }
    except:
        pass
    return False, {}

# ═══════════════════════════════════════════════════
# ESTRATEGIA: INVERTIR FINAL (V2 + regime + anti-knife)
# ═══════════════════════════════════════════════════
def strategy_final(data, ticker, date_idx, last_signals):
    try:
        spy_close = data['Close']['SPY']
        spy_sma50 = spy_close.rolling(50).mean()
        spy_ret = spy_close.pct_change()
        spy_vol = spy_ret.rolling(20).std() * 100

        if spy_close.iloc[date_idx] < spy_sma50.iloc[date_idx]:
            return False, {}
        if spy_vol.iloc[date_idx] > 1.0:
            return False, {}

        current_date = data['Close'].index[date_idx]
        if ticker in last_signals:
            days_since = (current_date - last_signals[ticker]).days
            if days_since < 5:
                return False, {}

        signal, info = strategy_v2(data, ticker, date_idx)
        return signal, info
    except:
        pass
    return False, {}

# ═══════════════════════════════════════════════════
# ESTRATEGIA: INVERTIR V3 (filtros optimizados)
# ═══════════════════════════════════════════════════
V3_RSI_MAX = 25
V3_SMA_DIST_MIN = -15.0
V3_SMA_DIST_MAX = -10.0
V3_VOL_MAX = 0.8
V3_SCORE_MIN = 30
V3_SCORE_MAX = 50
V3_DIAS_OK = [2, 3]  # Mie, Jue
V3_MACD_ACCEL_MIN = 0.3

def strategy_v3(data, ticker, date_idx, last_signals):
    """V3: Final + filtros optimizados de backtests"""
    try:
        # Regime check (same as Final)
        spy_close = data['Close']['SPY']
        spy_sma50 = spy_close.rolling(50).mean()
        spy_ret = spy_close.pct_change()
        spy_vol = spy_ret.rolling(20).std() * 100

        if spy_close.iloc[date_idx] < spy_sma50.iloc[date_idx]:
            return False, {}
        if spy_vol.iloc[date_idx] > 1.0:
            return False, {}

        # Anti-knife
        current_date = data['Close'].index[date_idx]
        if ticker in last_signals:
            days_since = (current_date - last_signals[ticker]).days
            if days_since < 5:
                return False, {}

        # Day of week filter
        weekday = current_date.weekday()
        if weekday not in V3_DIAS_OK:
            return False, {}

        # Base indicators
        close = data['Close'][ticker]
        high = data['High'][ticker]
        low = data['Low'][ticker]
        volume = data['Volume'][ticker]

        rsi = calc_rsi(close)
        _, _, macd_hist = calc_macd(close)
        sma50 = close.rolling(50).mean()
        vol_avg = volume.rolling(20).mean()
        atr = calc_atr(high, low, close)

        rsi_val = rsi.iloc[date_idx]
        macd_now = macd_hist.iloc[date_idx]
        macd_prev = macd_hist.iloc[date_idx - 1]
        price = close.iloc[date_idx]
        sma50_val = sma50.iloc[date_idx]
        vol_ratio = volume.iloc[date_idx] / vol_avg.iloc[date_idx] if vol_avg.iloc[date_idx] > 0 else 2
        atr_val = atr.iloc[date_idx]
        dist_sma = (price - sma50_val) / sma50_val * 100
        macd_accel = macd_now - macd_prev
        macd_accel_norm = macd_accel / (atr_val * 0.01 + 1e-6)

        # V3 filters
        if rsi_val >= V3_RSI_MAX:
            return False, {}
        if macd_now <= macd_prev:
            return False, {}
        if dist_sma < V3_SMA_DIST_MIN or dist_sma > V3_SMA_DIST_MAX:
            return False, {}
        if vol_ratio > V3_VOL_MAX:
            return False, {}
        if macd_accel_norm < V3_MACD_ACCEL_MIN:
            return False, {}

        # Score
        rsi_score = min(40, max(0, (30 - rsi_val) / 30 * 40))
        sma_score = min(30, max(0, abs(dist_sma) / 15 * 30))
        macd_score = min(20, max(0, macd_accel_norm * 5))
        vol_score = min(10, max(0, (1.5 - vol_ratio) / 1.5 * 10))
        total_score = rsi_score + sma_score + macd_score + vol_score

        if total_score < V3_SCORE_MIN or total_score > V3_SCORE_MAX:
            return False, {}

        stop_loss = price - 2 * atr_val

        return True, {
            'rsi': rsi_val, 'dist_sma': dist_sma, 'vol_ratio': vol_ratio,
            'score': total_score, 'stop_loss': stop_loss, 'atr': atr_val,
            'macd_accel_norm': macd_accel_norm, 'weekday': weekday,
        }
    except:
        pass
    return False, {}

# Also test V3 RELAXED: same as V3 but without day-of-week filter
def strategy_v3_noday(data, ticker, date_idx, last_signals):
    """V3 sin filtro de dia - para ver cuanto aporta el filtro"""
    try:
        spy_close = data['Close']['SPY']
        spy_sma50 = spy_close.rolling(50).mean()
        spy_ret = spy_close.pct_change()
        spy_vol = spy_ret.rolling(20).std() * 100

        if spy_close.iloc[date_idx] < spy_sma50.iloc[date_idx]:
            return False, {}
        if spy_vol.iloc[date_idx] > 1.0:
            return False, {}

        current_date = data['Close'].index[date_idx]
        if ticker in last_signals:
            days_since = (current_date - last_signals[ticker]).days
            if days_since < 5:
                return False, {}

        close = data['Close'][ticker]
        high = data['High'][ticker]
        low = data['Low'][ticker]
        volume = data['Volume'][ticker]

        rsi = calc_rsi(close)
        _, _, macd_hist = calc_macd(close)
        sma50 = close.rolling(50).mean()
        vol_avg = volume.rolling(20).mean()
        atr = calc_atr(high, low, close)

        rsi_val = rsi.iloc[date_idx]
        macd_now = macd_hist.iloc[date_idx]
        macd_prev = macd_hist.iloc[date_idx - 1]
        price = close.iloc[date_idx]
        sma50_val = sma50.iloc[date_idx]
        vol_ratio = volume.iloc[date_idx] / vol_avg.iloc[date_idx] if vol_avg.iloc[date_idx] > 0 else 2
        atr_val = atr.iloc[date_idx]
        dist_sma = (price - sma50_val) / sma50_val * 100
        macd_accel = macd_now - macd_prev
        macd_accel_norm = macd_accel / (atr_val * 0.01 + 1e-6)

        # V3 filters (WITHOUT day filter)
        if rsi_val >= V3_RSI_MAX:
            return False, {}
        if macd_now <= macd_prev:
            return False, {}
        if dist_sma < V3_SMA_DIST_MIN or dist_sma > V3_SMA_DIST_MAX:
            return False, {}
        if vol_ratio > V3_VOL_MAX:
            return False, {}
        if macd_accel_norm < V3_MACD_ACCEL_MIN:
            return False, {}

        rsi_score = min(40, max(0, (30 - rsi_val) / 30 * 40))
        sma_score = min(30, max(0, abs(dist_sma) / 15 * 30))
        macd_score = min(20, max(0, macd_accel_norm * 5))
        vol_score = min(10, max(0, (1.5 - vol_ratio) / 1.5 * 10))
        total_score = rsi_score + sma_score + macd_score + vol_score

        if total_score < V3_SCORE_MIN or total_score > V3_SCORE_MAX:
            return False, {}

        stop_loss = price - 2 * atr_val

        return True, {
            'rsi': rsi_val, 'dist_sma': dist_sma, 'vol_ratio': vol_ratio,
            'score': total_score, 'stop_loss': stop_loss, 'atr': atr_val,
            'macd_accel_norm': macd_accel_norm,
        }
    except:
        pass
    return False, {}

# ═══════════════════════════════════════════════════
# BACKTEST ENGINE
# ═══════════════════════════════════════════════════
def backtest(data, tickers, strategy_fn, start_date, end_date, hold_days=10, commission=0.001):
    dates = data['Close'].index
    mask = (dates >= start_date) & (dates <= end_date)
    valid_dates = dates[mask]

    trades = []
    last_signals = {}

    for i in range(len(dates)):
        if dates[i] not in valid_dates.values:
            continue
        if i < 55 or i + hold_days >= len(dates):
            continue

        for ticker in tickers:
            try:
                if strategy_fn.__name__ in ('strategy_final', 'strategy_v3', 'strategy_v3_noday'):
                    signal, info = strategy_fn(data, ticker, i, last_signals)
                else:
                    signal, info = strategy_fn(data, ticker, i)

                if signal:
                    entry_price = data['Close'][ticker].iloc[i]

                    returns = {}
                    for h in [1, 3, 5, 10]:
                        if i + h < len(dates):
                            exit_price = data['Close'][ticker].iloc[i + h]
                            ret = (exit_price / entry_price - 1) - 2 * commission
                            returns[f'ret_{h}d'] = ret

                    # SL/TP check
                    stopped = False
                    actual_ret = None
                    actual_days = hold_days
                    if 'stop_loss' in info and 'atr' in info:
                        stop = info['stop_loss']
                        tp = entry_price * 1.03
                        for d in range(1, min(hold_days + 1, len(dates) - i)):
                            low_d = data['Low'][ticker].iloc[i + d]
                            high_d = data['High'][ticker].iloc[i + d]
                            if low_d <= stop:
                                actual_ret = (stop / entry_price - 1) - 2 * commission
                                actual_days = d
                                stopped = True
                                break
                            if high_d >= tp:
                                actual_ret = (tp / entry_price - 1) - 2 * commission
                                actual_days = d
                                break
                        if actual_ret is None and i + hold_days < len(dates):
                            actual_ret = (data['Close'][ticker].iloc[i + hold_days] / entry_price - 1) - 2 * commission

                    trade = {
                        'date': dates[i],
                        'ticker': ticker,
                        'entry_price': entry_price,
                        **info,
                        **returns,
                        'actual_ret': actual_ret if actual_ret is not None else returns.get(f'ret_{hold_days}d', None),
                        'actual_days': actual_days,
                        'stopped': stopped,
                    }
                    trades.append(trade)
                    last_signals[ticker] = dates[i]
            except:
                continue

    return pd.DataFrame(trades)

# ═══════════════════════════════════════════════════
# ANALISIS
# ═══════════════════════════════════════════════════
def analyze(trades_df, name, hold_col='actual_ret'):
    if trades_df is None or len(trades_df) == 0:
        return {'name': name, 'trades': 0, 'error': 'Sin trades'}

    df = trades_df.dropna(subset=[hold_col])
    if len(df) == 0:
        return {'name': name, 'trades': 0, 'error': 'Sin returns'}

    returns = df[hold_col]
    wins = returns[returns > 0]
    losses = returns[returns <= 0]

    equity = (1 + returns).cumprod()
    peak = equity.expanding().max()
    drawdown = (equity - peak) / peak

    n_activos = df['ticker'].nunique() if 'ticker' in df.columns else 0

    is_loss = (returns <= 0).astype(int)
    streaks = is_loss.groupby((is_loss != is_loss.shift()).cumsum()).sum()
    max_loss_streak = streaks.max() if len(streaks) > 0 else 0

    return {
        'name': name,
        'trades': len(df),
        'n_wins': len(wins),
        'n_losses': len(losses),
        'win_rate': len(wins) / len(df) * 100,
        'loss_rate': len(losses) / len(df) * 100,
        'avg_return': returns.mean() * 100,
        'avg_win': wins.mean() * 100 if len(wins) > 0 else 0,
        'avg_loss': losses.mean() * 100 if len(losses) > 0 else 0,
        'total_return': (equity.iloc[-1] - 1) * 100,
        'sharpe': returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0,
        'max_drawdown': drawdown.min() * 100,
        'profit_factor': abs(wins.sum() / losses.sum()) if len(losses) > 0 and losses.sum() != 0 else float('inf'),
        'n_activos': n_activos,
        'risk_reward': abs(wins.mean() / losses.mean()) if len(losses) > 0 and losses.mean() != 0 else float('inf'),
        'max_loss_streak': max_loss_streak,
    }

def print_table(results_list, title=""):
    if title:
        print(f"\n{'=' * 150}")
        print(f"  {title}")
        print(f"{'=' * 150}")

    print(f"  {'ESTRATEGIA':<28} {'TRADES':>6} {'WINS':>5} {'LOSS':>5} {'WIN%':>6} {'LOSS%':>6} "
          f"{'AVG%':>7} {'AVGW%':>7} {'AVGL%':>7} {'TOT%':>9} {'SHARPE':>7} {'MDD%':>7} "
          f"{'PF':>5} {'ACT':>4} {'R:R':>5} {'RACH-':>5}")
    print(f"  {'-'*145}")

    sorted_r = sorted(results_list, key=lambda x: x.get('sharpe', -999), reverse=True)

    for r in sorted_r:
        if r.get('error'):
            print(f"  {r['name']:<28} {'ERROR':>6}  {r['error']}")
            continue
        pf = f"{r['profit_factor']:.1f}" if r['profit_factor'] < 100 else "inf"
        rr = f"{r['risk_reward']:.1f}" if r['risk_reward'] < 100 else "inf"
        print(f"  {r['name']:<28} {r['trades']:>6} {r['n_wins']:>5} {r['n_losses']:>5} "
              f"{r['win_rate']:>5.1f}% {r['loss_rate']:>5.1f}% "
              f"{r['avg_return']:>6.2f}% {r['avg_win']:>6.2f}% {r['avg_loss']:>6.2f}% "
              f"{r['total_return']:>8.1f}% {r['sharpe']:>7.2f} {r['max_drawdown']:>6.1f}% "
              f"{pf:>5} {r['n_activos']:>4} {rr:>5} {r['max_loss_streak']:>5.0f}")

    print(f"  {'=' * 145}")

def deep_analysis_v3(trades_df, name):
    """Analisis profundo de V3 trades"""
    if trades_df is None or len(trades_df) == 0:
        print(f"\n  {name}: Sin trades para analizar")
        return

    df = trades_df.dropna(subset=['actual_ret'])
    if len(df) == 0:
        return

    print(f"\n{'='*80}")
    print(f"  ANALISIS PROFUNDO: {name} ({len(df)} trades)")
    print(f"{'='*80}")

    # Por RSI
    if 'rsi' in df.columns:
        print(f"\n  Por RSI:")
        for lo, hi in [(0, 15), (15, 20), (20, 22), (22, 25), (25, 30)]:
            sub = df[(df['rsi'] >= lo) & (df['rsi'] < hi)]
            if len(sub) > 0:
                wr = (sub['actual_ret'] > 0).mean() * 100
                avg = sub['actual_ret'].mean() * 100
                print(f"    RSI {lo:>2}-{hi:<2}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%")

    # Por SMA distance
    if 'dist_sma' in df.columns:
        print(f"\n  Por Dist SMA50:")
        for lo, hi in [(-20, -15), (-15, -12), (-12, -10), (-10, -7), (-7, -5)]:
            sub = df[(df['dist_sma'] >= lo) & (df['dist_sma'] < hi)]
            if len(sub) > 0:
                wr = (sub['actual_ret'] > 0).mean() * 100
                avg = sub['actual_ret'].mean() * 100
                print(f"    SMA {lo:>3}% a {hi:>3}%: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%")

    # Por dia de semana
    if 'date' in df.columns:
        print(f"\n  Por dia de semana:")
        dias = ['Lun', 'Mar', 'Mie', 'Jue', 'Vie']
        df['weekday'] = pd.to_datetime(df['date']).dt.weekday
        for d in range(5):
            sub = df[df['weekday'] == d]
            if len(sub) > 0:
                wr = (sub['actual_ret'] > 0).mean() * 100
                avg = sub['actual_ret'].mean() * 100
                marker = " <--" if d in V3_DIAS_OK else ""
                print(f"    {dias[d]}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%{marker}")

    # Por volumen
    if 'vol_ratio' in df.columns:
        print(f"\n  Por Volume Ratio:")
        for lo, hi in [(0, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0), (1.0, 1.5)]:
            sub = df[(df['vol_ratio'] >= lo) & (df['vol_ratio'] < hi)]
            if len(sub) > 0:
                wr = (sub['actual_ret'] > 0).mean() * 100
                avg = sub['actual_ret'].mean() * 100
                print(f"    Vol {lo:.1f}-{hi:.1f}x: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%")

    # Por score
    if 'score' in df.columns:
        print(f"\n  Por Score:")
        for lo, hi in [(0, 20), (20, 30), (30, 40), (40, 50), (50, 60), (60, 100)]:
            sub = df[(df['score'] >= lo) & (df['score'] < hi)]
            if len(sub) > 0:
                wr = (sub['actual_ret'] > 0).mean() * 100
                avg = sub['actual_ret'].mean() * 100
                marker = " <-- V3" if lo >= V3_SCORE_MIN and hi <= V3_SCORE_MAX + 10 else ""
                print(f"    Score {lo:>2}-{hi:<3}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%{marker}")

    # Top tickers
    print(f"\n  Top tickers:")
    ticker_stats = df.groupby('ticker').agg(
        trades=('actual_ret', 'count'),
        wr=('actual_ret', lambda x: (x > 0).mean() * 100),
        avg=('actual_ret', lambda x: x.mean() * 100),
    ).sort_values('trades', ascending=False).head(10)
    for t, row in ticker_stats.iterrows():
        print(f"    {t:<8} Trades: {row['trades']:>3}  WR: {row['wr']:>5.1f}%  Avg: {row['avg']:>6.2f}%")

    # Monthly
    if 'date' in df.columns:
        print(f"\n  Por mes:")
        df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
        monthly = df.groupby('month').agg(
            trades=('actual_ret', 'count'),
            wr=('actual_ret', lambda x: (x > 0).mean() * 100),
            total=('actual_ret', lambda x: ((1+x).prod()-1)*100)
        )
        for m, row in monthly.iterrows():
            bar = "+" * int(max(0, row['total'])) + "-" * int(max(0, -row['total']))
            print(f"    {str(m):<8} Trades: {row['trades']:>3}  WR: {row['wr']:>5.1f}%  Total: {row['total']:>7.2f}% {bar}")


# ═══════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════
def main():
    print("=" * 80)
    print("  BACKTEST: INVERTIR V3 vs FINAL vs V2")
    print("  Validacion de filtros optimizados")
    print("=" * 80)

    data, available = download_data('2024-06-01', '2026-03-27')
    if data is None:
        return

    IS_START = '2025-06-01'
    IS_END = '2026-03-20'
    OOS_START = '2024-09-01'
    OOS_END = '2025-05-31'
    FULL_START = '2024-09-01'
    FULL_END = '2026-03-20'

    for period_name, p_start, p_end in [
        ("IN-SAMPLE (Jun25-Mar26)", IS_START, IS_END),
        ("OUT-OF-SAMPLE (Sep24-Jun25)", OOS_START, OOS_END),
        ("FULL PERIOD (Sep24-Mar26)", FULL_START, FULL_END),
    ]:
        print(f"\n\n{'#'*80}")
        print(f"#  {period_name}")
        print(f"{'#'*80}")

        all_results = []
        all_trades = {}

        # V2
        print(f"\n  [1/4] INVERTIR V2...")
        trades_v2 = backtest(data, available, strategy_v2, p_start, p_end, hold_days=10)
        all_trades['V2'] = trades_v2
        for h in [5, 10]:
            col = f'ret_{h}d'
            if col in trades_v2.columns:
                all_results.append(analyze(trades_v2, f"INV V2 ({h}d)", hold_col=col))
        all_results.append(analyze(trades_v2, "INV V2 (SL/TP)", hold_col='actual_ret'))

        # Final
        print(f"  [2/4] INVERTIR Final...")
        trades_final = backtest(data, available, strategy_final, p_start, p_end, hold_days=10)
        all_trades['Final'] = trades_final
        for h in [5, 10]:
            col = f'ret_{h}d'
            if col in trades_final.columns:
                all_results.append(analyze(trades_final, f"INV Final ({h}d)", hold_col=col))
        all_results.append(analyze(trades_final, "INV Final (SL/TP)", hold_col='actual_ret'))

        # V3 (full filters)
        print(f"  [3/4] INVERTIR V3 (todos los filtros)...")
        trades_v3 = backtest(data, available, strategy_v3, p_start, p_end, hold_days=10)
        all_trades['V3'] = trades_v3
        for h in [5, 10]:
            col = f'ret_{h}d'
            if len(trades_v3) > 0 and col in trades_v3.columns:
                all_results.append(analyze(trades_v3, f"INV V3 ({h}d)", hold_col=col))
        if len(trades_v3) > 0:
            all_results.append(analyze(trades_v3, "INV V3 (SL/TP)", hold_col='actual_ret'))
        else:
            all_results.append({'name': 'INV V3 (todos)', 'trades': 0, 'error': 'Sin trades - filtros muy estrictos'})

        # V3 sin filtro de dia
        print(f"  [4/4] INVERTIR V3 sin filtro dia...")
        trades_v3nd = backtest(data, available, strategy_v3_noday, p_start, p_end, hold_days=10)
        all_trades['V3_noday'] = trades_v3nd
        for h in [5, 10]:
            col = f'ret_{h}d'
            if len(trades_v3nd) > 0 and col in trades_v3nd.columns:
                all_results.append(analyze(trades_v3nd, f"INV V3-noDia ({h}d)", hold_col=col))
        if len(trades_v3nd) > 0:
            all_results.append(analyze(trades_v3nd, "INV V3-noDia (SL/TP)", hold_col='actual_ret'))
        else:
            all_results.append({'name': 'INV V3-noDia', 'trades': 0, 'error': 'Sin trades'})

        # Print
        print_table(all_results, period_name)

        # Deep analysis for Final (reference) and V3 variants
        deep_analysis_v3(trades_final, "INVERTIR Final")
        deep_analysis_v3(trades_v3, "INVERTIR V3 (todos)")
        deep_analysis_v3(trades_v3nd, "INVERTIR V3 sin dia")

    # ═══════════════════════════════════════════════
    # CONCLUSIONES
    # ═══════════════════════════════════════════════
    print(f"\n\n{'='*80}")
    print("  CONCLUSIONES")
    print(f"{'='*80}")
    print("""
  Este backtest compara 4 variantes:

  1. INV V2:        RSI<30, SMA>5%, Vol<1.5x (sin regime)
  2. INV Final:     V2 + SPY regime + anti-knife
  3. INV V3:        Final + RSI<25 + SMA -15%/-10% + Vol<0.8x + MACD accel + Mie/Jue + Score 30-50
  4. INV V3-noDia:  V3 sin filtro de dia (para evaluar impacto del filtro)

  CLAVE: V3 tendra MENOS trades pero deberian ser de mayor calidad.
  Si V3 tiene un Sharpe y WR mas altos que Final con menos MDD,
  los filtros optimizados funcionan. Si no, los filtros son overfitting.

  ADVERTENCIA: Pocos trades = resultados menos estadisticamente significativos.
  Si V3 tiene <20 trades, interpretar con cautela.
""")

if __name__ == '__main__':
    main()
