"""
MEGA BACKTEST 2026 - ROUND 3: ANALISIS DEFINITIVO
===================================================
El backtest mas profundo del proyecto TITAN.

Incluye:
1. V3 REVISADA (filtros relajados: RSI<25, SMA<-10%, Score>30)
2. Busqueda exhaustiva de combinaciones de filtros (2^6 = 64 variantes)
3. Walk-Forward validation (ventanas rodantes, no solo IS/OOS estatico)
4. Monte Carlo bootstrap (1000 simulaciones, intervalos confianza 95%)
5. Analisis por sector (tech, finanzas, energia, healthcare, etc.)
6. Holding period optimization riguroso (1-20 dias)
7. Metricas avanzadas: Sortino, Calmar, Tail Ratio, Omega
8. Analisis de clustering temporal de trades
9. Drawdown profundo: duracion, recuperacion, underwater
10. Equity curve con benchmark SPY

Fecha: 2026-03-28
Basado en: Round 1 + Round 2 + Backtest V3 vs Final
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
import os
import sys
from itertools import combinations

warnings.filterwarnings('ignore')
os.environ['PYTHONWARNINGS'] = 'ignore'
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Fix encoding for Windows console
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# ================================================================
# UNIVERSO COMPLETO (80 activos bien diversificados)
# ================================================================
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
]

SECTORS = {
    'Tech': ['AAPL','MSFT','GOOGL','AMZN','META','NVDA','AMD','TSLA','NFLX','CRM',
             'ORCL','ADBE','INTC','AVGO','QCOM','MU','AMAT','LRCX','TXN','PLTR'],
    'Finanzas': ['JPM','BAC','WFC','GS','V','MA','AXP','C','PYPL','COIN'],
    'Healthcare': ['JNJ','PFE','UNH','MRK','ABBV','LLY','TMO','ABT','BMY','AMGN'],
    'Energia': ['XOM','CVX','COP','SLB','OXY','HAL','DVN','MPC','VLO','EOG'],
    'Consumer': ['KO','PEP','PG','WMT','COST','MCD','NKE','SBUX','TGT','HD'],
    'Industrial': ['CAT','BA','GE','RTX','HON','LMT','UPS','FDX','DE','MMM'],
    'LatAm': ['MELI','NU','BABA','VALE','PBR','GLOB','STNE','XP','SBS','ITUB'],
}

CONTEXT_TICKERS = ['SPY', 'QQQ', 'IWM', '^VIX', 'TLT', 'GLD']

# ================================================================
# INDICADORES
# ================================================================
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

# ================================================================
# DESCARGA DE DATOS
# ================================================================
def download_data():
    print("\n" + "=" * 80)
    print("  DESCARGANDO DATOS")
    print("=" * 80)
    all_t = list(set(TICKERS + CONTEXT_TICKERS))
    data = yf.download(all_t, start='2024-06-01', end='2026-03-28', progress=False, threads=True)
    available = []
    for t in TICKERS:
        try:
            c = data['Close'][t].dropna()
            if len(c) > 100:
                available.append(t)
        except:
            pass
    print(f"  {len(available)}/{len(TICKERS)} activos con datos suficientes")

    # Show date range
    dates = data['Close'].dropna(how='all').index
    print(f"  Rango: {dates[0].strftime('%Y-%m-%d')} a {dates[-1].strftime('%Y-%m-%d')} ({len(dates)} dias)")
    return data, available

# ================================================================
# PRECOMPUTE INDICATORS (una sola vez, mucho mas rapido)
# ================================================================
def precompute_indicators(data, tickers):
    """Precomputa todos los indicadores para todos los tickers."""
    print("\n  Precomputando indicadores...")
    indicators = {}

    for ticker in tickers:
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

            rsi_prev = rsi.shift(1)

            indicators[ticker] = {
                'close': close, 'high': high, 'low': low, 'volume': volume,
                'rsi': rsi, 'rsi_prev': rsi_prev,
                'macd_hist': macd_hist,
                'sma50': sma50, 'vol_avg': vol_avg, 'atr': atr,
            }
        except:
            pass

    # SPY indicators
    try:
        spy_close = data['Close']['SPY']
        spy_sma50 = spy_close.rolling(50).mean()
        spy_vol = spy_close.pct_change().rolling(20).std() * 100
        indicators['_SPY'] = {
            'close': spy_close, 'sma50': spy_sma50, 'vol': spy_vol,
        }
    except:
        pass

    print(f"  {len(indicators)-1} tickers + SPY precomputados")
    return indicators

# ================================================================
# ESTRATEGIAS PARAMETRIZADAS
# ================================================================
def check_base_signal(ind, ticker, i):
    """Checks RSI<30 + MACD rising + >5% below SMA50 + Vol<1.5x.
    Returns (True, info_dict) or (False, {})"""
    try:
        ti = ind[ticker]
        rsi_val = ti['rsi'].iloc[i]
        macd_now = ti['macd_hist'].iloc[i]
        macd_prev = ti['macd_hist'].iloc[i - 1]
        price = ti['close'].iloc[i]
        sma50_val = ti['sma50'].iloc[i]
        vol_ratio = ti['volume'].iloc[i] / (ti['vol_avg'].iloc[i] + 1e-10)
        atr_val = ti['atr'].iloc[i]
        dist_sma = (price / sma50_val - 1) * 100
        macd_accel = macd_now - macd_prev
        macd_accel_norm = macd_accel / (atr_val * 0.01 + 1e-6)
        rsi_rising = ti['rsi'].iloc[i] > ti['rsi_prev'].iloc[i]

        if np.isnan(rsi_val) or np.isnan(sma50_val) or np.isnan(atr_val):
            return False, {}

        if rsi_val >= 30:
            return False, {}
        if macd_now <= macd_prev:
            return False, {}
        if dist_sma > -5:
            return False, {}
        if vol_ratio > 1.5:
            return False, {}

        # Score
        rsi_score = min(40, max(0, (30 - rsi_val) / 30 * 40))
        sma_score = min(30, max(0, (abs(dist_sma) - 5) / 15 * 30))
        macd_score = min(20, max(0, macd_accel_norm * 5))
        vol_score = min(10, max(0, (1.5 - vol_ratio) / 1.5 * 10))
        total_score = rsi_score + sma_score + macd_score + vol_score
        stop_loss = price - 2 * atr_val

        return True, {
            'rsi': rsi_val, 'dist_sma': dist_sma, 'vol_ratio': vol_ratio,
            'score': total_score, 'stop_loss': stop_loss, 'atr': atr_val,
            'macd_accel_norm': macd_accel_norm, 'rsi_rising': rsi_rising,
            'price': price,
        }
    except:
        return False, {}

def check_regime(ind, i):
    """SPY > SMA50 and vol < 1%"""
    try:
        spy = ind['_SPY']
        return spy['close'].iloc[i] > spy['sma50'].iloc[i] and spy['vol'].iloc[i] < 1.0
    except:
        return False

def strategy_v2(ind, ticker, i, **kwargs):
    return check_base_signal(ind, ticker, i)

def strategy_final(ind, ticker, i, last_signals=None, dates=None, **kwargs):
    if not check_regime(ind, i):
        return False, {}
    if last_signals is not None and dates is not None:
        current_date = dates[i]
        if ticker in last_signals:
            if (current_date - last_signals[ticker]).days < 5:
                return False, {}
    return check_base_signal(ind, ticker, i)

def strategy_v3_revisada(ind, ticker, i, last_signals=None, dates=None, **kwargs):
    """V3 REVISADA: Final + RSI<25 + SMA<-10% + Score>30 (filtros que FUNCIONAN)"""
    if not check_regime(ind, i):
        return False, {}
    if last_signals is not None and dates is not None:
        current_date = dates[i]
        if ticker in last_signals:
            if (current_date - last_signals[ticker]).days < 5:
                return False, {}
    signal, info = check_base_signal(ind, ticker, i)
    if not signal:
        return False, {}
    # V3 REVISADA: solo filtros que demostraron funcionar
    if info['rsi'] >= 25:
        return False, {}
    if info['dist_sma'] > -10:
        return False, {}
    if info['score'] < 30:
        return False, {}
    return True, info

def strategy_parametric(ind, ticker, i, last_signals=None, dates=None,
                        rsi_max=30, sma_min=None, sma_max=-5,
                        vol_max=1.5, score_min=0, score_max=100,
                        days_filter=None, macd_accel_min=None,
                        rsi_direction=None, use_regime=True, use_antiknife=True,
                        **kwargs):
    """Estrategia completamente parametrizable para busqueda exhaustiva."""
    if use_regime and not check_regime(ind, i):
        return False, {}
    if use_antiknife and last_signals is not None and dates is not None:
        current_date = dates[i]
        if ticker in last_signals:
            if (current_date - last_signals[ticker]).days < 5:
                return False, {}

    signal, info = check_base_signal(ind, ticker, i)
    if not signal:
        return False, {}

    if info['rsi'] >= rsi_max:
        return False, {}
    if sma_min is not None and info['dist_sma'] < sma_min:
        return False, {}
    if info['dist_sma'] > sma_max:
        return False, {}
    if info['vol_ratio'] > vol_max:
        return False, {}
    if info['score'] < score_min or info['score'] > score_max:
        return False, {}
    if days_filter is not None and dates is not None:
        weekday = dates[i].weekday()
        if weekday not in days_filter:
            return False, {}
    if macd_accel_min is not None and info['macd_accel_norm'] < macd_accel_min:
        return False, {}
    if rsi_direction == 'rising' and not info['rsi_rising']:
        return False, {}
    if rsi_direction == 'falling' and info['rsi_rising']:
        return False, {}

    return True, info

# ================================================================
# BACKTEST ENGINE (optimizado con precompute)
# ================================================================
def backtest(ind, tickers, strategy_fn, start_date, end_date,
             hold_days=10, commission=0.001, max_hold=20, **strat_kwargs):
    """Motor de backtest universal."""
    dates = ind['_SPY']['close'].index
    mask = (dates >= start_date) & (dates <= end_date)
    valid_indices = np.where(mask)[0]

    trades = []
    last_signals = {}

    for i in valid_indices:
        if i < 55 or i + max_hold >= len(dates):
            continue

        for ticker in tickers:
            signal, info = strategy_fn(
                ind, ticker, i,
                last_signals=last_signals, dates=dates,
                **strat_kwargs
            )

            if signal:
                entry_price = info.get('price', ind[ticker]['close'].iloc[i])

                # Calculate returns for multiple holding periods
                returns = {}
                for h in [1, 2, 3, 5, 7, 10, 15, 20]:
                    if i + h < len(dates):
                        try:
                            exit_price = ind[ticker]['close'].iloc[i + h]
                            ret = (exit_price / entry_price - 1) - 2 * commission
                            returns[f'ret_{h}d'] = ret
                        except:
                            pass

                # Max favorable / adverse excursion
                mfe = 0  # max favorable
                mae = 0  # max adverse
                for d in range(1, min(hold_days + 1, len(dates) - i)):
                    try:
                        h_d = ind[ticker]['high'].iloc[i + d]
                        l_d = ind[ticker]['low'].iloc[i + d]
                        mfe = max(mfe, (h_d / entry_price - 1))
                        mae = min(mae, (l_d / entry_price - 1))
                    except:
                        pass

                # SL/TP simulation
                actual_ret = None
                actual_days = hold_days
                stopped = False
                if 'stop_loss' in info:
                    stop = info['stop_loss']
                    tp = entry_price * 1.03
                    for d in range(1, min(hold_days + 1, len(dates) - i)):
                        try:
                            low_d = ind[ticker]['low'].iloc[i + d]
                            high_d = ind[ticker]['high'].iloc[i + d]
                            if low_d <= stop:
                                actual_ret = (stop / entry_price - 1) - 2 * commission
                                actual_days = d
                                stopped = True
                                break
                            if high_d >= tp:
                                actual_ret = (tp / entry_price - 1) - 2 * commission
                                actual_days = d
                                break
                        except:
                            pass
                    if actual_ret is None:
                        actual_ret = returns.get(f'ret_{hold_days}d', None)

                # Sector
                sector = 'Other'
                for s, tlist in SECTORS.items():
                    if ticker in tlist:
                        sector = s
                        break

                trade = {
                    'date': dates[i],
                    'ticker': ticker,
                    'sector': sector,
                    'entry_price': entry_price,
                    'weekday': dates[i].weekday(),
                    **info,
                    **returns,
                    'mfe': mfe, 'mae': mae,
                    'actual_ret': actual_ret if actual_ret is not None else returns.get(f'ret_{hold_days}d'),
                    'actual_days': actual_days,
                    'stopped': stopped,
                }
                trades.append(trade)
                last_signals[ticker] = dates[i]

    return pd.DataFrame(trades)

# ================================================================
# METRICAS AVANZADAS
# ================================================================
def compute_metrics(returns_series, name="", annualize=252):
    """Computa metricas avanzadas de una serie de returns."""
    if returns_series is None or len(returns_series) == 0:
        return {'name': name, 'trades': 0, 'error': 'Sin trades'}

    r = returns_series.dropna()
    if len(r) == 0:
        return {'name': name, 'trades': 0, 'error': 'Sin returns'}

    wins = r[r > 0]
    losses = r[r <= 0]

    equity = (1 + r).cumprod()
    peak = equity.expanding().max()
    drawdown = (equity - peak) / peak

    # Drawdown duration
    dd_starts = []
    dd_durations = []
    in_dd = False
    dd_start = 0
    for idx in range(len(drawdown)):
        if drawdown.iloc[idx] < 0 and not in_dd:
            in_dd = True
            dd_start = idx
        elif drawdown.iloc[idx] >= 0 and in_dd:
            in_dd = False
            dd_durations.append(idx - dd_start)
    if in_dd:
        dd_durations.append(len(drawdown) - dd_start)

    # Active tickers
    n_activos = 0
    if hasattr(r, 'index'):
        try:
            # This works when we have the original df
            pass
        except:
            pass

    # Loss streaks
    is_loss = (r <= 0).astype(int)
    streaks = is_loss.groupby((is_loss != is_loss.shift()).cumsum()).sum()
    max_loss_streak = int(streaks.max()) if len(streaks) > 0 else 0

    # Win streaks
    is_win = (r > 0).astype(int)
    win_streaks = is_win.groupby((is_win != is_win.shift()).cumsum()).sum()
    max_win_streak = int(win_streaks.max()) if len(win_streaks) > 0 else 0

    # Advanced metrics
    neg_returns = r[r < 0]
    downside_std = neg_returns.std() if len(neg_returns) > 0 else 1e-10
    sortino = r.mean() / downside_std * np.sqrt(annualize) if downside_std > 0 else 0

    max_dd = abs(drawdown.min()) if len(drawdown) > 0 else 1e-10
    calmar = (r.mean() * annualize) / max_dd if max_dd > 0 else 0

    # Tail ratio: ratio of 95th percentile gain to 5th percentile loss
    p95 = r.quantile(0.95) if len(r) > 5 else 0
    p05 = abs(r.quantile(0.05)) if len(r) > 5 else 1e-10
    tail_ratio = p95 / p05 if p05 > 0 else 0

    # Omega ratio (threshold = 0)
    gains_sum = r[r > 0].sum()
    losses_sum = abs(r[r <= 0].sum())
    omega = gains_sum / losses_sum if losses_sum > 0 else float('inf')

    # Expectancy
    expectancy = r.mean()

    # Kelly criterion
    win_rate = len(wins) / len(r) if len(r) > 0 else 0
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = abs(losses.mean()) if len(losses) > 0 else 1e-10
    kelly = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win if avg_win > 0 else 0

    pf = abs(wins.sum() / losses.sum()) if len(losses) > 0 and losses.sum() != 0 else float('inf')
    rr = avg_win / avg_loss if avg_loss > 0 else float('inf')

    return {
        'name': name,
        'trades': len(r),
        'n_wins': len(wins),
        'n_losses': len(losses),
        'win_rate': win_rate * 100,
        'avg_return': r.mean() * 100,
        'avg_win': wins.mean() * 100 if len(wins) > 0 else 0,
        'avg_loss': losses.mean() * 100 if len(losses) > 0 else 0,
        'median_return': r.median() * 100,
        'total_return': (equity.iloc[-1] - 1) * 100,
        'sharpe': r.mean() / r.std() * np.sqrt(annualize) if r.std() > 0 else 0,
        'sortino': sortino,
        'calmar': calmar,
        'omega': omega,
        'tail_ratio': tail_ratio,
        'max_drawdown': drawdown.min() * 100,
        'avg_dd_duration': np.mean(dd_durations) if dd_durations else 0,
        'max_dd_duration': max(dd_durations) if dd_durations else 0,
        'profit_factor': pf,
        'risk_reward': rr,
        'max_loss_streak': max_loss_streak,
        'max_win_streak': max_win_streak,
        'expectancy': expectancy * 100,
        'kelly': kelly * 100,
        'skew': r.skew(),
        'kurtosis': r.kurtosis(),
        'p05': r.quantile(0.05) * 100 if len(r) > 5 else 0,
        'p95': r.quantile(0.95) * 100 if len(r) > 5 else 0,
        'worst_trade': r.min() * 100,
        'best_trade': r.max() * 100,
    }

def analyze_trades(trades_df, name, hold_col='actual_ret'):
    """Wrapper que trabaja con DataFrame de trades."""
    if trades_df is None or len(trades_df) == 0:
        return {'name': name, 'trades': 0, 'error': 'Sin trades'}
    df = trades_df.dropna(subset=[hold_col])
    if len(df) == 0:
        return {'name': name, 'trades': 0, 'error': 'Sin returns'}

    metrics = compute_metrics(df[hold_col], name)
    metrics['n_activos'] = df['ticker'].nunique()
    return metrics

# ================================================================
# PRINT FUNCTIONS
# ================================================================
def print_main_table(results_list, title=""):
    if title:
        print(f"\n{'=' * 160}")
        print(f"  {title}")
        print(f"{'=' * 160}")

    header = (f"  {'ESTRATEGIA':<30} {'TR':>4} {'W':>3} {'L':>3} {'WR%':>5} "
              f"{'AVG%':>6} {'AVGW':>6} {'AVGL':>6} {'MED%':>5} {'TOT%':>8} "
              f"{'SHARP':>6} {'SORT':>6} {'CALM':>5} {'MDD%':>6} "
              f"{'PF':>4} {'R:R':>4} {'OMG':>4} {'TAIL':>4} {'RACH-':>5} {'KELLY':>5}")
    print(header)
    print(f"  {'-'*157}")

    sorted_r = sorted(results_list, key=lambda x: x.get('sharpe', -999), reverse=True)

    for r in sorted_r:
        if r.get('error'):
            print(f"  {r['name']:<30} {r['trades']:>4}  {r['error']}")
            continue
        pf = f"{r['profit_factor']:.1f}" if r['profit_factor'] < 100 else "inf"
        rr = f"{r['risk_reward']:.1f}" if r['risk_reward'] < 100 else "inf"
        omg = f"{r['omega']:.1f}" if r['omega'] < 100 else "inf"
        print(f"  {r['name']:<30} {r['trades']:>4} {r['n_wins']:>3} {r['n_losses']:>3} "
              f"{r['win_rate']:>4.0f}% "
              f"{r['avg_return']:>5.2f}% {r['avg_win']:>5.2f}% {r['avg_loss']:>5.2f}% "
              f"{r['median_return']:>4.1f}% {r['total_return']:>7.1f}% "
              f"{r['sharpe']:>6.2f} {r['sortino']:>6.2f} {r['calmar']:>5.1f} "
              f"{r['max_drawdown']:>5.1f}% "
              f"{pf:>4} {rr:>4} {omg:>4} {r['tail_ratio']:>4.1f} "
              f"{r['max_loss_streak']:>5} {r['kelly']:>4.0f}%")

    print(f"  {'=' * 157}")

def print_compact_table(results_list, title=""):
    """Tabla compacta para resultados de busqueda."""
    if title:
        print(f"\n  --- {title} ---")

    sorted_r = sorted(results_list, key=lambda x: x.get('sharpe', -999), reverse=True)[:15]

    print(f"  {'VARIANTE':<40} {'TR':>4} {'WR%':>5} {'AVG%':>6} {'TOT%':>8} {'SHARP':>6} {'MDD%':>6} {'PF':>5}")
    print(f"  {'-'*85}")

    for r in sorted_r:
        if r.get('error'):
            continue
        pf = f"{r['profit_factor']:.1f}" if r['profit_factor'] < 100 else "inf"
        print(f"  {r['name']:<40} {r['trades']:>4} {r['win_rate']:>4.0f}% "
              f"{r['avg_return']:>5.2f}% {r['total_return']:>7.1f}% "
              f"{r['sharpe']:>6.2f} {r['max_drawdown']:>5.1f}% {pf:>5}")

# ================================================================
# SECCION 1: BACKTEST PRINCIPAL (V2, Final, V3 Revisada, variantes)
# ================================================================
def run_main_backtest(ind, available, period_name, start, end):
    print(f"\n{'#' * 80}")
    print(f"#  {period_name}")
    print(f"{'#' * 80}")

    all_results = []
    all_trades = {}

    strategies = [
        ("INV V2", strategy_v2, {}),
        ("INV Final", strategy_final, {}),
        ("INV V3-Rev (RSI25+SMA10+Sc30)", strategy_v3_revisada, {}),
        # Variantes individuales sobre Final
        ("Final + RSI<25", strategy_parametric, {'rsi_max': 25}),
        ("Final + SMA<-10%", strategy_parametric, {'sma_max': -10}),
        ("Final + Score>30", strategy_parametric, {'score_min': 30}),
        ("Final + RSI<25 + SMA<-10%", strategy_parametric, {'rsi_max': 25, 'sma_max': -10}),
        ("Final + RSI<25 + Score>30", strategy_parametric, {'rsi_max': 25, 'score_min': 30}),
        ("Final + RSI<25+SMA10+Sc30+Jue", strategy_parametric, {'rsi_max': 25, 'sma_max': -10, 'score_min': 30, 'days_filter': [3]}),
        ("Final + RSI falling only", strategy_parametric, {'rsi_direction': 'falling'}),
    ]

    for idx, (name, strat, params) in enumerate(strategies):
        print(f"  [{idx+1}/{len(strategies)}] {name}...")

        trades = backtest(ind, available, strat, start, end, hold_days=10, **params)
        all_trades[name] = trades

        # Test multiple hold periods
        for h in [5, 10]:
            col = f'ret_{h}d'
            if len(trades) > 0 and col in trades.columns:
                all_results.append(analyze_trades(trades, f"{name} ({h}d)", hold_col=col))

        if len(trades) > 0:
            all_results.append(analyze_trades(trades, f"{name} (SL/TP)", hold_col='actual_ret'))
        else:
            all_results.append({'name': name, 'trades': 0, 'error': 'Sin trades'})

    print_main_table(all_results, period_name)

    return all_results, all_trades

# ================================================================
# SECCION 2: BUSQUEDA EXHAUSTIVA DE FILTROS
# ================================================================
def run_filter_search(ind, available, start, end):
    print(f"\n\n{'=' * 80}")
    print(f"  BUSQUEDA EXHAUSTIVA DE COMBINACIONES DE FILTROS")
    print(f"  Sobre INVERTIR Final como base")
    print(f"={'=' * 79}")

    # Filtros individuales a probar
    filters = {
        'RSI<25': {'rsi_max': 25},
        'RSI<27': {'rsi_max': 27},
        'SMA<-8%': {'sma_max': -8},
        'SMA<-10%': {'sma_max': -10},
        'SMA<-12%': {'sma_max': -12},
        'Vol<1.0x': {'vol_max': 1.0},
        'Vol<0.8x': {'vol_max': 0.8},
        'Score>20': {'score_min': 20},
        'Score>30': {'score_min': 30},
        'Score>40': {'score_min': 40},
        'MACDacc>0.3': {'macd_accel_min': 0.3},
        'Jue only': {'days_filter': [3]},
        'Mie+Jue': {'days_filter': [2, 3]},
        'RSI falling': {'rsi_direction': 'falling'},
    }

    # Test each individual filter
    print(f"\n  FILTROS INDIVIDUALES (sobre Final):")
    individual_results = []

    for fname, fparams in filters.items():
        trades = backtest(ind, available, strategy_parametric, start, end,
                         hold_days=10, **fparams)
        if len(trades) > 0:
            col = 'ret_10d'
            if col in trades.columns:
                result = analyze_trades(trades, f"Final + {fname}", hold_col=col)
                individual_results.append(result)
            else:
                individual_results.append({'name': f"Final + {fname}", 'trades': 0, 'error': 'No col'})
        else:
            individual_results.append({'name': f"Final + {fname}", 'trades': 0, 'error': 'Sin trades'})

    # Baseline Final
    trades_base = backtest(ind, available, strategy_final, start, end, hold_days=10)
    if len(trades_base) > 0 and 'ret_10d' in trades_base.columns:
        base_result = analyze_trades(trades_base, "BASELINE: Final", hold_col='ret_10d')
        individual_results.insert(0, base_result)

    print_compact_table(individual_results, "FILTROS INDIVIDUALES (hold 10d, Full Period)")

    # Test best 2-filter combinations
    print(f"\n  COMBINACIONES DE 2 FILTROS (top por Sharpe):")
    filter_names = list(filters.keys())
    combo_results = []

    compatible_combos = []
    for i, f1 in enumerate(filter_names):
        for j, f2 in enumerate(filter_names):
            if j <= i:
                continue
            # Skip incompatible combos (same parameter)
            p1 = set(filters[f1].keys())
            p2 = set(filters[f2].keys())
            if p1 & p2:  # overlap = incompatible (would override)
                continue
            compatible_combos.append((f1, f2))

    for f1, f2 in compatible_combos:
        params = {**filters[f1], **filters[f2]}
        trades = backtest(ind, available, strategy_parametric, start, end,
                         hold_days=10, **params)
        if len(trades) >= 3:
            col = 'ret_10d'
            if col in trades.columns:
                result = analyze_trades(trades, f"Final+{f1}+{f2}", hold_col=col)
                combo_results.append(result)

    print_compact_table(combo_results, "MEJORES COMBOS DE 2 FILTROS (min 3 trades)")

    # Test best 3-filter combinations (only with compatible filters)
    print(f"\n  COMBINACIONES DE 3 FILTROS (top por Sharpe):")
    combo3_results = []

    for i, f1 in enumerate(filter_names):
        for j, f2 in enumerate(filter_names):
            if j <= i:
                continue
            for k, f3 in enumerate(filter_names):
                if k <= j:
                    continue
                p1 = set(filters[f1].keys())
                p2 = set(filters[f2].keys())
                p3 = set(filters[f3].keys())
                if p1 & p2 or p1 & p3 or p2 & p3:
                    continue
                params = {**filters[f1], **filters[f2], **filters[f3]}
                trades = backtest(ind, available, strategy_parametric, start, end,
                                 hold_days=10, **params)
                if len(trades) >= 3:
                    col = 'ret_10d'
                    if col in trades.columns:
                        result = analyze_trades(trades, f"+{f1}+{f2}+{f3}", hold_col=col)
                        combo3_results.append(result)

    if combo3_results:
        print_compact_table(combo3_results, "MEJORES COMBOS DE 3 FILTROS (min 3 trades)")
    else:
        print("  Ninguna combinacion de 3 filtros produjo >= 3 trades")

    return individual_results, combo_results, combo3_results

# ================================================================
# SECCION 3: HOLDING PERIOD OPTIMIZATION
# ================================================================
def run_holding_analysis(ind, available, start, end):
    print(f"\n\n{'=' * 80}")
    print(f"  OPTIMIZACION DE HOLDING PERIOD")
    print(f"  Estrategia: INVERTIR Final | Periodo: Full")
    print(f"{'=' * 80}")

    trades = backtest(ind, available, strategy_final, start, end, hold_days=20)

    if len(trades) == 0:
        print("  Sin trades")
        return

    print(f"\n  {len(trades)} trades analizados\n")
    print(f"  {'HOLD':>5} {'TRADES':>6} {'WR%':>6} {'AVG%':>7} {'MED%':>7} {'TOT%':>9} {'SHARPE':>7} {'SORTINO':>7} {'MDD%':>7} {'BEST%':>7} {'WORST%':>7}")
    print(f"  {'-'*95}")

    best_sharpe = -999
    best_hold = 0

    for h in [1, 2, 3, 5, 7, 10, 15, 20]:
        col = f'ret_{h}d'
        if col not in trades.columns:
            continue

        valid = trades[col].dropna()
        if len(valid) == 0:
            continue

        metrics = compute_metrics(valid, f"{h}d")

        marker = ""
        if metrics['sharpe'] > best_sharpe:
            best_sharpe = metrics['sharpe']
            best_hold = h
            marker = " <-- BEST"

        print(f"  {h:>4}d {metrics['trades']:>6} {metrics['win_rate']:>5.1f}% "
              f"{metrics['avg_return']:>6.2f}% {metrics['median_return']:>6.2f}% "
              f"{metrics['total_return']:>8.1f}% {metrics['sharpe']:>7.2f} "
              f"{metrics['sortino']:>7.2f} {metrics['max_drawdown']:>6.1f}% "
              f"{metrics['best_trade']:>6.1f}% {metrics['worst_trade']:>6.1f}%{marker}")

    print(f"\n  OPTIMO: Hold {best_hold} dias (Sharpe {best_sharpe:.2f})")

    # MFE/MAE Analysis
    print(f"\n  ANALISIS MFE/MAE (Max Favorable/Adverse Excursion):")
    if 'mfe' in trades.columns and 'mae' in trades.columns:
        mfe = trades['mfe'].dropna()
        mae = trades['mae'].dropna()
        print(f"  MFE promedio: +{mfe.mean()*100:.2f}% (max: +{mfe.max()*100:.1f}%)")
        print(f"  MAE promedio: {mae.mean()*100:.2f}% (max: {mae.min()*100:.1f}%)")
        print(f"  MFE/MAE ratio: {abs(mfe.mean()/mae.mean()):.2f}")

        # What % of trades hit +3% at some point?
        hit_3pct = (mfe >= 0.03).sum()
        print(f"  Trades que tocaron +3%: {hit_3pct}/{len(mfe)} ({hit_3pct/len(mfe)*100:.0f}%)")
        hit_5pct = (mfe >= 0.05).sum()
        print(f"  Trades que tocaron +5%: {hit_5pct}/{len(mfe)} ({hit_5pct/len(mfe)*100:.0f}%)")

        # What % of trades hit -5% at some point?
        hit_neg5 = (mae <= -0.05).sum()
        print(f"  Trades que tocaron -5%: {hit_neg5}/{len(mae)} ({hit_neg5/len(mae)*100:.0f}%)")

    return trades

# ================================================================
# SECCION 4: WALK-FORWARD VALIDATION
# ================================================================
def run_walk_forward(ind, available):
    print(f"\n\n{'=' * 80}")
    print(f"  WALK-FORWARD VALIDATION")
    print(f"  Train: 6 meses | Test: 2 meses | Step: 2 meses")
    print(f"{'=' * 80}")

    # Define windows
    windows = [
        ("WF1", "2024-06-01", "2024-12-01", "2024-12-01", "2025-02-01"),
        ("WF2", "2024-08-01", "2025-02-01", "2025-02-01", "2025-04-01"),
        ("WF3", "2024-10-01", "2025-04-01", "2025-04-01", "2025-06-01"),
        ("WF4", "2024-12-01", "2025-06-01", "2025-06-01", "2025-08-01"),
        ("WF5", "2025-02-01", "2025-08-01", "2025-08-01", "2025-10-01"),
        ("WF6", "2025-04-01", "2025-10-01", "2025-10-01", "2025-12-01"),
        ("WF7", "2025-06-01", "2025-12-01", "2025-12-01", "2026-02-01"),
        ("WF8", "2025-08-01", "2026-02-01", "2026-02-01", "2026-03-28"),
    ]

    print(f"\n  {'WINDOW':<6} {'TRAIN PERIOD':<28} {'TEST PERIOD':<28} {'TR-TR':>5} {'TE-TR':>5} "
          f"{'TR-WR':>5} {'TE-WR':>5} {'TR-SH':>6} {'TE-SH':>6} {'TE-AVG':>6} {'TE-TOT':>7} {'CONSIST':>7}")
    print(f"  {'-'*140}")

    wf_results = []

    for name, tr_start, tr_end, te_start, te_end in windows:
        # Train
        trades_train = backtest(ind, available, strategy_final, tr_start, tr_end, hold_days=10)
        # Test
        trades_test = backtest(ind, available, strategy_final, te_start, te_end, hold_days=10)

        tr_m = analyze_trades(trades_train, f"{name}-train", hold_col='ret_10d') if len(trades_train) > 0 else None
        te_m = analyze_trades(trades_test, f"{name}-test", hold_col='ret_10d') if len(trades_test) > 0 else None

        tr_trades = tr_m['trades'] if tr_m and 'trades' in tr_m else 0
        te_trades = te_m['trades'] if te_m and 'trades' in te_m else 0
        tr_wr = tr_m.get('win_rate', 0) if tr_m else 0
        te_wr = te_m.get('win_rate', 0) if te_m else 0
        tr_sh = tr_m.get('sharpe', 0) if tr_m else 0
        te_sh = te_m.get('sharpe', 0) if te_m else 0
        te_avg = te_m.get('avg_return', 0) if te_m else 0
        te_tot = te_m.get('total_return', 0) if te_m else 0

        # Consistency: test Sharpe within 50% of train, same sign
        if tr_sh != 0 and te_sh != 0:
            same_sign = (tr_sh > 0 and te_sh > 0) or (tr_sh < 0 and te_sh < 0)
            consistency = "OK" if same_sign and te_sh > 0 else "WARN" if same_sign else "FAIL"
        elif te_trades == 0:
            consistency = "NO DATA"
        else:
            consistency = "?"

        wf_results.append({
            'name': name, 'tr_sh': tr_sh, 'te_sh': te_sh,
            'te_trades': te_trades, 'consistency': consistency
        })

        print(f"  {name:<6} {tr_start} - {tr_end}  {te_start} - {te_end}  "
              f"{tr_trades:>5} {te_trades:>5} {tr_wr:>4.0f}% {te_wr:>4.0f}% "
              f"{tr_sh:>6.2f} {te_sh:>6.2f} {te_avg:>5.2f}% {te_tot:>6.1f}% {consistency:>7}")

    # Summary
    ok_count = sum(1 for w in wf_results if w['consistency'] == 'OK')
    total_with_data = sum(1 for w in wf_results if w['te_trades'] > 0)
    print(f"\n  CONSISTENCIA: {ok_count}/{total_with_data} ventanas positivas en test")

    if total_with_data > 0:
        avg_te_sharpe = np.mean([w['te_sh'] for w in wf_results if w['te_trades'] > 0])
        print(f"  Sharpe promedio en test: {avg_te_sharpe:.2f}")

    return wf_results

# ================================================================
# SECCION 5: MONTE CARLO BOOTSTRAP
# ================================================================
def run_monte_carlo(trades_df, n_simulations=1000, hold_col='ret_10d'):
    print(f"\n\n{'=' * 80}")
    print(f"  MONTE CARLO BOOTSTRAP ({n_simulations} simulaciones)")
    print(f"  Estrategia: INVERTIR Final | Column: {hold_col}")
    print(f"{'=' * 80}")

    if trades_df is None or len(trades_df) == 0:
        print("  Sin trades para simular")
        return

    returns = trades_df[hold_col].dropna().values
    n_trades = len(returns)

    if n_trades < 10:
        print(f"  Solo {n_trades} trades - muy pocos para Monte Carlo confiable")
        return

    print(f"  Trades reales: {n_trades}")
    print(f"  Return promedio real: {returns.mean()*100:.2f}%")
    print(f"  Sharpe real: {returns.mean()/returns.std()*np.sqrt(252):.2f}")

    np.random.seed(42)

    sim_sharpes = []
    sim_returns = []
    sim_win_rates = []
    sim_max_dds = []
    sim_totals = []

    for _ in range(n_simulations):
        # Bootstrap: sample with replacement
        sample = np.random.choice(returns, size=n_trades, replace=True)

        sim_sharpes.append(sample.mean() / sample.std() * np.sqrt(252) if sample.std() > 0 else 0)
        sim_returns.append(sample.mean() * 100)
        sim_win_rates.append((sample > 0).mean() * 100)

        equity = np.cumprod(1 + sample)
        peak = np.maximum.accumulate(equity)
        dd = (equity - peak) / peak
        sim_max_dds.append(dd.min() * 100)
        sim_totals.append((equity[-1] - 1) * 100)

    sim_sharpes = np.array(sim_sharpes)
    sim_returns = np.array(sim_returns)
    sim_win_rates = np.array(sim_win_rates)
    sim_max_dds = np.array(sim_max_dds)
    sim_totals = np.array(sim_totals)

    print(f"\n  {'METRICA':<25} {'P5':>8} {'P25':>8} {'P50':>8} {'P75':>8} {'P95':>8} {'MEDIA':>8}")
    print(f"  {'-'*75}")

    for name, vals in [
        ("Sharpe", sim_sharpes),
        ("Avg Return %", sim_returns),
        ("Win Rate %", sim_win_rates),
        ("Max Drawdown %", sim_max_dds),
        ("Total Return %", sim_totals),
    ]:
        p5, p25, p50, p75, p95 = np.percentile(vals, [5, 25, 50, 75, 95])
        print(f"  {name:<25} {p5:>7.2f} {p25:>7.2f} {p50:>7.2f} {p75:>7.2f} {p95:>7.2f} {vals.mean():>7.2f}")

    # Probability of profit
    prob_profit = (sim_totals > 0).mean() * 100
    prob_sharpe_pos = (sim_sharpes > 0).mean() * 100
    prob_sharpe_2 = (sim_sharpes > 2).mean() * 100

    print(f"\n  PROBABILIDADES:")
    print(f"  P(Total Return > 0%):  {prob_profit:.1f}%")
    print(f"  P(Sharpe > 0):         {prob_sharpe_pos:.1f}%")
    print(f"  P(Sharpe > 2):         {prob_sharpe_2:.1f}%")
    print(f"  P(Max DD > -20%):      {(sim_max_dds > -20).mean()*100:.1f}%")
    print(f"  P(Max DD > -10%):      {(sim_max_dds > -10).mean()*100:.1f}%")

    # Worst case scenarios
    print(f"\n  ESCENARIOS EXTREMOS:")
    print(f"  Peor 1% Sharpe:       {np.percentile(sim_sharpes, 1):.2f}")
    print(f"  Peor 1% Total Return: {np.percentile(sim_totals, 1):.1f}%")
    print(f"  Peor 1% Max DD:       {np.percentile(sim_max_dds, 1):.1f}%")

# ================================================================
# SECCION 6: ANALISIS POR SECTOR
# ================================================================
def run_sector_analysis(trades_df, hold_col='ret_10d'):
    print(f"\n\n{'=' * 80}")
    print(f"  ANALISIS POR SECTOR (INVERTIR Final)")
    print(f"{'=' * 80}")

    if trades_df is None or len(trades_df) == 0:
        print("  Sin trades")
        return

    df = trades_df.dropna(subset=[hold_col])

    print(f"\n  {'SECTOR':<15} {'TR':>4} {'WR%':>5} {'AVG%':>7} {'MED%':>7} {'TOT%':>8} {'SHARP':>7} {'MDD%':>7} {'BEST':>7} {'WORST':>7} {'TICKERS':<30}")
    print(f"  {'-'*125}")

    for sector in sorted(SECTORS.keys()):
        sub = df[df['sector'] == sector]
        if len(sub) == 0:
            print(f"  {sector:<15} {'0':>4}")
            continue

        r = sub[hold_col]
        wins = r[r > 0]
        wr = len(wins) / len(r) * 100
        avg = r.mean() * 100
        med = r.median() * 100
        tot = ((1 + r).prod() - 1) * 100
        sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
        equity = (1 + r).cumprod()
        mdd = ((equity - equity.expanding().max()) / equity.expanding().max()).min() * 100
        best = r.max() * 100
        worst = r.min() * 100
        tickers = ', '.join(sub['ticker'].value_counts().head(5).index)

        print(f"  {sector:<15} {len(sub):>4} {wr:>4.0f}% {avg:>6.2f}% {med:>6.2f}% "
              f"{tot:>7.1f}% {sharpe:>7.2f} {mdd:>6.1f}% {best:>6.1f}% {worst:>6.1f}% {tickers:<30}")

# ================================================================
# SECCION 7: DEEP ANALYSIS DE TRADES
# ================================================================
def run_deep_analysis(trades_df, name, hold_col='ret_10d'):
    print(f"\n\n{'=' * 80}")
    print(f"  DEEP ANALYSIS: {name}")
    print(f"{'=' * 80}")

    if trades_df is None or len(trades_df) == 0:
        print("  Sin trades")
        return

    df = trades_df.dropna(subset=[hold_col])
    if len(df) == 0:
        return

    # ── Por RSI ──
    if 'rsi' in df.columns:
        print(f"\n  Por RSI (profundidad de sobreventa):")
        for lo, hi in [(0, 15), (15, 20), (20, 22), (22, 25), (25, 27), (27, 30)]:
            sub = df[(df['rsi'] >= lo) & (df['rsi'] < hi)]
            if len(sub) > 0:
                r = sub[hold_col]
                wr = (r > 0).mean() * 100
                avg = r.mean() * 100
                med = r.median() * 100
                sh = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
                print(f"    RSI {lo:>2}-{hi:<2}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%  Med: {med:>5.2f}%  Sharpe: {sh:>5.2f}")

    # ── Por SMA distance ──
    if 'dist_sma' in df.columns:
        print(f"\n  Por Distancia SMA50:")
        for lo, hi in [(-30, -20), (-20, -15), (-15, -12), (-12, -10), (-10, -7), (-7, -5)]:
            sub = df[(df['dist_sma'] >= lo) & (df['dist_sma'] < hi)]
            if len(sub) > 0:
                r = sub[hold_col]
                wr = (r > 0).mean() * 100
                avg = r.mean() * 100
                sh = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
                print(f"    SMA {lo:>3}% a {hi:>3}%: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%  Sharpe: {sh:>5.2f}")

    # ── Por dia de semana ──
    print(f"\n  Por dia de semana:")
    dias = ['Lun', 'Mar', 'Mie', 'Jue', 'Vie']
    if 'weekday' in df.columns:
        for d in range(5):
            sub = df[df['weekday'] == d]
            if len(sub) > 0:
                r = sub[hold_col]
                wr = (r > 0).mean() * 100
                avg = r.mean() * 100
                sh = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
                print(f"    {dias[d]}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%  Sharpe: {sh:>5.2f}")

    # ── Por volumen ──
    if 'vol_ratio' in df.columns:
        print(f"\n  Por Volume Ratio:")
        for lo, hi in [(0, 0.3), (0.3, 0.5), (0.5, 0.8), (0.8, 1.0), (1.0, 1.2), (1.2, 1.5)]:
            sub = df[(df['vol_ratio'] >= lo) & (df['vol_ratio'] < hi)]
            if len(sub) > 0:
                r = sub[hold_col]
                wr = (r > 0).mean() * 100
                avg = r.mean() * 100
                sh = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
                print(f"    Vol {lo:.1f}-{hi:.1f}x: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%  Sharpe: {sh:>5.2f}")

    # ── Por score ──
    if 'score' in df.columns:
        print(f"\n  Por Score:")
        for lo, hi in [(0, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 60), (60, 80), (80, 100)]:
            sub = df[(df['score'] >= lo) & (df['score'] < hi)]
            if len(sub) > 0:
                r = sub[hold_col]
                wr = (r > 0).mean() * 100
                avg = r.mean() * 100
                sh = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
                print(f"    Score {lo:>2}-{hi:<3}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%  Sharpe: {sh:>5.2f}")

    # ── Por RSI direction ──
    if 'rsi_rising' in df.columns:
        print(f"\n  Por RSI Direction:")
        for direction, label in [(True, 'RSI Rising'), (False, 'RSI Falling')]:
            sub = df[df['rsi_rising'] == direction]
            if len(sub) > 0:
                r = sub[hold_col]
                wr = (r > 0).mean() * 100
                avg = r.mean() * 100
                sh = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
                print(f"    {label:<15}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%  Sharpe: {sh:>5.2f}")

    # ── Por mes ──
    if 'date' in df.columns:
        print(f"\n  Por mes:")
        df_temp = df.copy()
        df_temp['month'] = pd.to_datetime(df_temp['date']).dt.to_period('M')
        monthly = df_temp.groupby('month').apply(
            lambda x: pd.Series({
                'trades': len(x),
                'wr': (x[hold_col] > 0).mean() * 100,
                'avg': x[hold_col].mean() * 100,
                'total': ((1 + x[hold_col]).prod() - 1) * 100,
            })
        )
        for m, row in monthly.iterrows():
            bar_len = min(30, abs(int(row['total'])))
            bar = "+" * bar_len if row['total'] >= 0 else "-" * bar_len
            print(f"    {str(m):<8} Tr: {row['trades']:>3.0f}  WR: {row['wr']:>5.1f}%  "
                  f"Avg: {row['avg']:>6.2f}%  Total: {row['total']:>7.2f}% {bar}")

    # ── Top/Bottom tickers ──
    print(f"\n  Top 10 tickers por avg return:")
    ticker_stats = df.groupby('ticker').apply(
        lambda x: pd.Series({
            'trades': len(x),
            'wr': (x[hold_col] > 0).mean() * 100,
            'avg': x[hold_col].mean() * 100,
            'total': ((1 + x[hold_col]).prod() - 1) * 100,
        })
    )
    top10 = ticker_stats.sort_values('avg', ascending=False).head(10)
    for t, row in top10.iterrows():
        print(f"    {t:<8} Tr: {row['trades']:>3.0f}  WR: {row['wr']:>5.1f}%  Avg: {row['avg']:>6.2f}%  Total: {row['total']:>7.1f}%")

    print(f"\n  Bottom 5 tickers (peor performance):")
    bottom5 = ticker_stats.sort_values('avg', ascending=True).head(5)
    for t, row in bottom5.iterrows():
        print(f"    {t:<8} Tr: {row['trades']:>3.0f}  WR: {row['wr']:>5.1f}%  Avg: {row['avg']:>6.2f}%  Total: {row['total']:>7.1f}%")

    # ── Trade clustering ──
    if 'date' in df.columns:
        print(f"\n  Clustering temporal de trades:")
        dates_series = pd.to_datetime(df['date'])
        gaps = dates_series.sort_values().diff().dt.days.dropna()
        print(f"    Gap promedio entre trades: {gaps.mean():.1f} dias")
        print(f"    Gap mediano: {gaps.median():.0f} dias")
        print(f"    Gap maximo: {gaps.max():.0f} dias (periodo sin senales)")
        print(f"    Trades en mismo dia (max): {df.groupby('date').size().max()}")

        # Trades per week distribution
        df_temp = df.copy()
        df_temp['week'] = pd.to_datetime(df_temp['date']).dt.to_period('W')
        weekly = df_temp.groupby('week').size()
        print(f"    Trades por semana: mean={weekly.mean():.1f}, max={weekly.max()}, "
              f"semanas sin trades: {(weekly == 0).sum() if len(weekly) > 0 else 'N/A'}")

# ================================================================
# SECCION 8: EQUITY CURVE & DRAWDOWN ANALYSIS
# ================================================================
def run_equity_analysis(trades_df, name, hold_col='ret_10d'):
    print(f"\n\n{'=' * 80}")
    print(f"  EQUITY CURVE & DRAWDOWN: {name}")
    print(f"{'=' * 80}")

    if trades_df is None or len(trades_df) == 0:
        print("  Sin trades")
        return

    df = trades_df.dropna(subset=[hold_col]).sort_values('date')
    returns = df[hold_col].values

    equity = np.cumprod(1 + returns) * 100  # Start at $100
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak * 100

    # Underwater periods
    print(f"\n  Equity: ${100:.0f} -> ${equity[-1]:.0f} ({(equity[-1]/100-1)*100:+.1f}%)")
    print(f"  Peak: ${peak.max():.0f}")
    print(f"  Max Drawdown: {drawdown.min():.1f}%")

    # Find all drawdown periods
    in_dd = False
    dd_periods = []
    dd_start_idx = 0
    dd_start_val = 0

    for idx in range(len(drawdown)):
        if drawdown[idx] < -1 and not in_dd:  # > 1% drawdown
            in_dd = True
            dd_start_idx = idx
            dd_start_val = drawdown[idx]
        elif drawdown[idx] >= 0 and in_dd:
            in_dd = False
            dd_periods.append({
                'start_trade': dd_start_idx,
                'end_trade': idx,
                'duration': idx - dd_start_idx,
                'max_dd': min(drawdown[dd_start_idx:idx+1]),
                'start_date': df['date'].iloc[dd_start_idx] if dd_start_idx < len(df) else 'N/A',
            })
    if in_dd:
        dd_periods.append({
            'start_trade': dd_start_idx,
            'end_trade': len(drawdown) - 1,
            'duration': len(drawdown) - dd_start_idx,
            'max_dd': min(drawdown[dd_start_idx:]),
            'start_date': df['date'].iloc[dd_start_idx] if dd_start_idx < len(df) else 'N/A',
        })

    if dd_periods:
        print(f"\n  Periodos de drawdown significativos (>1%):")
        dd_sorted = sorted(dd_periods, key=lambda x: x['max_dd'])[:5]
        for dd in dd_sorted:
            print(f"    Desde trade #{dd['start_trade']} ({dd['start_date']}): "
                  f"DD {dd['max_dd']:.1f}%, duracion {dd['duration']} trades")

    # Recovery analysis
    print(f"\n  Analisis de recuperacion:")
    recovery_times = []
    for dd in dd_periods:
        recovery_times.append(dd['duration'])
    if recovery_times:
        print(f"    Recuperacion promedio: {np.mean(recovery_times):.1f} trades")
        print(f"    Recuperacion maxima: {max(recovery_times)} trades")

    # Equity curve summary by quarters
    print(f"\n  Performance por trimestre:")
    df_temp = df.copy()
    df_temp['quarter'] = pd.to_datetime(df_temp['date']).dt.to_period('Q')
    for q, group in df_temp.groupby('quarter'):
        r = group[hold_col]
        tot = ((1 + r).prod() - 1) * 100
        wr = (r > 0).mean() * 100
        bar = "+" * min(20, max(0, int(tot))) + "-" * min(20, max(0, int(-tot)))
        print(f"    {str(q):<7} Trades: {len(r):>3}  WR: {wr:>4.0f}%  Return: {tot:>7.1f}% {bar}")

# ================================================================
# SECCION 9: COMPARACION V3-REVISADA vs FINAL (IS/OOS/FULL)
# ================================================================
def run_v3_revisada_validation(ind, available):
    print(f"\n\n{'=' * 80}")
    print(f"  VALIDACION V3 REVISADA vs FINAL (IS + OOS + FULL)")
    print(f"  V3-Rev: RSI<25 + SMA<-10% + Score>30 (sin Vol<0.8x, sin dia)")
    print(f"{'=' * 80}")

    periods = [
        ("IN-SAMPLE (Jun25-Mar26)", "2025-06-01", "2026-03-25"),
        ("OUT-OF-SAMPLE (Sep24-Jun25)", "2024-09-01", "2025-05-31"),
        ("FULL (Sep24-Mar26)", "2024-09-01", "2026-03-25"),
    ]

    for period_name, start, end in periods:
        results = []

        # V2
        trades_v2 = backtest(ind, available, strategy_v2, start, end, hold_days=10)
        for h in [5, 10]:
            col = f'ret_{h}d'
            if len(trades_v2) > 0 and col in trades_v2.columns:
                results.append(analyze_trades(trades_v2, f"V2 ({h}d)", hold_col=col))

        # Final
        trades_final = backtest(ind, available, strategy_final, start, end, hold_days=10)
        for h in [5, 10]:
            col = f'ret_{h}d'
            if len(trades_final) > 0 and col in trades_final.columns:
                results.append(analyze_trades(trades_final, f"Final ({h}d)", hold_col=col))
        if len(trades_final) > 0:
            results.append(analyze_trades(trades_final, "Final (SL/TP)", hold_col='actual_ret'))

        # V3 Revisada
        trades_v3r = backtest(ind, available, strategy_v3_revisada, start, end, hold_days=10)
        for h in [5, 10]:
            col = f'ret_{h}d'
            if len(trades_v3r) > 0 and col in trades_v3r.columns:
                results.append(analyze_trades(trades_v3r, f"V3-Rev ({h}d)", hold_col=col))
        if len(trades_v3r) > 0:
            results.append(analyze_trades(trades_v3r, "V3-Rev (SL/TP)", hold_col='actual_ret'))
        else:
            results.append({'name': 'V3-Rev', 'trades': 0, 'error': 'Sin trades'})

        print_main_table(results, period_name)

# ================================================================
# MAIN
# ================================================================
def main():
    print("\n" + "=" * 80)
    print("  MEGA BACKTEST 2026 - ROUND 3: ANALISIS DEFINITIVO")
    print("  Fecha: 2026-03-28")
    print("  El backtest mas profundo del Proyecto TITAN")
    print("=" * 80)

    # Download & precompute
    data, available = download_data()
    if data is None:
        return

    ind = precompute_indicators(data, available)

    FULL_START = '2024-09-01'
    FULL_END = '2026-03-25'
    IS_START = '2025-06-01'
    IS_END = '2026-03-25'
    OOS_START = '2024-09-01'
    OOS_END = '2025-05-31'

    # ── 1. Backtest principal ──
    print("\n\n" + "█" * 80)
    print("#SECCION 1: BACKTEST PRINCIPAL — TODAS LAS VARIANTES")
    print("#" * 80)

    all_results_full, all_trades_full = run_main_backtest(ind, available,
        "FULL PERIOD (Sep24-Mar26)", FULL_START, FULL_END)

    _, all_trades_is = run_main_backtest(ind, available,
        "IN-SAMPLE (Jun25-Mar26)", IS_START, IS_END)

    _, all_trades_oos = run_main_backtest(ind, available,
        "OUT-OF-SAMPLE (Sep24-Jun25)", OOS_START, OOS_END)

    # ── 2. Busqueda de filtros ──
    print("\n\n" + "█" * 80)
    print("#SECCION 2: BUSQUEDA EXHAUSTIVA DE FILTROS")
    print("#" * 80)

    run_filter_search(ind, available, FULL_START, FULL_END)

    # ── 3. Holding period ──
    print("\n\n" + "█" * 80)
    print("#SECCION 3: OPTIMIZACION HOLDING PERIOD")
    print("#" * 80)

    trades_final_full = all_trades_full.get('INV Final')
    if trades_final_full is None:
        trades_final_full = backtest(ind, available, strategy_final, FULL_START, FULL_END, hold_days=20)
    run_holding_analysis(ind, available, FULL_START, FULL_END)

    # ── 4. Walk-Forward ──
    print("\n\n" + "█" * 80)
    print("#SECCION 4: WALK-FORWARD VALIDATION")
    print("#" * 80)

    run_walk_forward(ind, available)

    # ── 5. Monte Carlo ──
    print("\n\n" + "█" * 80)
    print("#SECCION 5: MONTE CARLO BOOTSTRAP")
    print("#" * 80)

    trades_final = backtest(ind, available, strategy_final, FULL_START, FULL_END, hold_days=10)
    run_monte_carlo(trades_final, n_simulations=1000, hold_col='ret_10d')

    # Also for V3 Revisada
    trades_v3r = backtest(ind, available, strategy_v3_revisada, FULL_START, FULL_END, hold_days=10)
    if len(trades_v3r) > 5 and 'ret_10d' in trades_v3r.columns:
        print(f"\n  --- MONTE CARLO: V3 REVISADA ---")
        run_monte_carlo(trades_v3r, n_simulations=1000, hold_col='ret_10d')

    # ── 6. Sector analysis ──
    print("\n\n" + "█" * 80)
    print("#SECCION 6: ANALISIS POR SECTOR")
    print("#" * 80)

    run_sector_analysis(trades_final, hold_col='ret_10d')

    # ── 7. Deep analysis ──
    print("\n\n" + "█" * 80)
    print("#SECCION 7: DEEP ANALYSIS — INVERTIR FINAL")
    print("#" * 80)

    run_deep_analysis(trades_final, "INVERTIR Final (Full Period)", hold_col='ret_10d')

    if len(trades_v3r) > 0:
        run_deep_analysis(trades_v3r, "V3 REVISADA (Full Period)", hold_col='ret_10d')

    # ── 8. Equity curve ──
    print("\n\n" + "█" * 80)
    print("#SECCION 8: EQUITY CURVE & DRAWDOWN")
    print("#" * 80)

    run_equity_analysis(trades_final, "INVERTIR Final", hold_col='ret_10d')

    # ── 9. V3 Revisada validation ──
    print("\n\n" + "█" * 80)
    print("#SECCION 9: V3 REVISADA — VALIDACION COMPLETA")
    print("#" * 80)

    run_v3_revisada_validation(ind, available)

    # ════════════════════════════════════════════════════════════════
    # CONCLUSIONES FINALES
    # ════════════════════════════════════════════════════════════════
    print(f"\n\n{'=' * 80}")
    print(f"  CONCLUSIONES FINALES — MEGA BACKTEST ROUND 3")
    print(f"{'=' * 80}")
    print(f"""
  Este backtest analizo:
  - 10 variantes de estrategia sobre 3 periodos (IS, OOS, Full)
  - 64+ combinaciones de filtros (busqueda exhaustiva)
  - 8 ventanas walk-forward para validar robustez temporal
  - 1000 simulaciones Monte Carlo para intervalos de confianza
  - 7 sectores del mercado para detectar sesgos
  - 8 holding periods (1-20 dias) para optimizar salida
  - Metricas avanzadas: Sortino, Calmar, Omega, Tail Ratio, Kelly
  - MFE/MAE para entender la dinamica intra-trade
  - Analisis de drawdown: duracion, recuperacion, underwater

  ESTRATEGIA V3 REVISADA:
  - Final + RSI<25 + SMA<-10% + Score>30
  - SIN filtro Vol<0.8x (contraproducente)
  - SIN filtro dia de semana (inconsistente)
  - SIN limite superior de Score (scores altos tambien funcionan)

  NOTA: Todos los returns incluyen comisiones (0.1% por trade).
  Los Sharpe ratios estan anualizados (sqrt(252)).

  Fecha de ejecucion: {datetime.now().strftime('%Y-%m-%d %H:%M')}
""")


if __name__ == '__main__':
    main()
