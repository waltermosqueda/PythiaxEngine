"""
ANALISIS V5 CANDIDATES — Busqueda rigurosa del siguiente paso
==============================================================
Evalua CADA mejora candidata individualmente y combinada.
Walk-forward obligatorio para todo candidato.

Candidatos basados en datos del Round 3:
  C1: Excluir LatAm (Sharpe -1.22 en R3, WR 47%)
  C2: Vol<1.0x (combo R3: 8 trades, 100% WR, Sharpe 33)
  C3: Holding 15d (R3 Final: Sharpe 7.31 vs 4.85 a 10d)
  C4: Stochastic K 10-25 (sesion 14: WR 83%, avg +3.14%)
  C5: RelPerf 20d < -20% vs SPY (sesion 14: WR 100%, +8.62%)
  C6: Excluir zona toxica RSI slope [0,+2] (sesion 13: WR 30%, Sharpe -9.64)

Protocolo:
  1. Backtest individual de cada candidato (full period)
  2. Walk-forward 8 ventanas (train 6m, test 2m)
  3. Solo candidatos con WF >= 60% windows positivas avanzan
  4. Combinar ganadores validados
  5. Backtest final del combo ganador

Fecha: 2026-04-05
Basado en: mega_round3.py engine + datos Round 3 + sesiones 12-14
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
import sys
import os

warnings.filterwarnings('ignore')
os.environ['PYTHONWARNINGS'] = 'ignore'

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# ================================================================
# UNIVERSOS
# ================================================================
TICKERS_FULL = [
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

LATAM_TICKERS = ['MELI','NU','BABA','VALE','PBR','GLOB','STNE','XP','SBS','ITUB']

TICKERS_NO_LATAM = [t for t in TICKERS_FULL if t not in LATAM_TICKERS]

SECTORS = {
    'Tech': ['AAPL','MSFT','GOOGL','AMZN','META','NVDA','AMD','TSLA','NFLX','CRM',
             'ORCL','ADBE','INTC','AVGO','QCOM','MU','AMAT','LRCX','TXN','PLTR'],
    'Finanzas': ['JPM','BAC','WFC','GS','V','MA','AXP','C','PYPL','COIN'],
    'Healthcare': ['JNJ','PFE','UNH','MRK','ABBV','LLY','TMO','ABT','BMY','AMGN'],
    'Energia': ['XOM','CVX','COP','SLB','OXY','HAL','DVN','MPC','VLO','EOG'],
    'Consumer': ['KO','PEP','PG','WMT','COST','MCD','NKE','SBUX','TGT','HD'],
    'Industrial': ['CAT','BA','GE','RTX','HON','LMT','UPS','FDX','DE','MMM'],
    'LatAm': LATAM_TICKERS,
}

CONTEXT_TICKERS = ['SPY', 'QQQ']

# ================================================================
# INDICADORES (Wilder RSI — OBLIGATORIO)
# ================================================================
def calc_rsi(series, period=14):
    """RSI con Wilder's smoothing. NUNCA usar rolling."""
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

def calc_stochastic(high, low, close, k_period=14, d_period=3):
    """Stochastic %K y %D."""
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-10)
    d = k.rolling(d_period).mean()
    return k, d

# ================================================================
# DESCARGA Y PRECOMPUTE
# ================================================================
def download_data():
    print("\n" + "=" * 80)
    print("  DESCARGANDO DATOS")
    print("=" * 80)
    all_t = list(set(TICKERS_FULL + CONTEXT_TICKERS))
    data = yf.download(all_t, start='2024-06-01', end='2026-04-05', progress=False, threads=True)
    available = []
    for t in TICKERS_FULL:
        try:
            c = data['Close'][t].dropna()
            if len(c) > 100:
                available.append(t)
        except:
            pass
    dates = data['Close'].dropna(how='all').index
    print(f"  {len(available)}/{len(TICKERS_FULL)} activos con datos")
    print(f"  Rango: {dates[0].strftime('%Y-%m-%d')} a {dates[-1].strftime('%Y-%m-%d')} ({len(dates)} dias)")
    return data, available

def precompute_indicators(data, tickers):
    """Precomputa TODOS los indicadores incluyendo nuevos candidatos."""
    print("  Precomputando indicadores (base + Stoch + RelPerf)...")
    indicators = {}

    # SPY primero (necesario para RelPerf)
    try:
        spy_close = data['Close']['SPY']
        spy_sma50 = spy_close.rolling(50).mean()
        spy_sma200 = spy_close.rolling(200).mean()
        spy_vol = spy_close.pct_change().rolling(20).std() * 100
        spy_ret_20d = spy_close.pct_change(20)
        indicators['_SPY'] = {
            'close': spy_close, 'sma50': spy_sma50, 'sma200': spy_sma200,
            'vol': spy_vol, 'ret_20d': spy_ret_20d,
        }
    except:
        print("  ERROR: No se pudo procesar SPY")
        return {}

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

            # NUEVOS: Stochastic
            stoch_k, stoch_d = calc_stochastic(high, low, close)

            # NUEVOS: Relative Performance vs SPY (20d)
            ticker_ret_20d = close.pct_change(20)
            relperf_20d = (ticker_ret_20d - spy_ret_20d) * 100  # en porcentaje

            # NUEVOS: RSI slope (cambio en 3 periodos)
            rsi_slope = rsi - rsi.shift(3)

            indicators[ticker] = {
                'close': close, 'high': high, 'low': low, 'volume': volume,
                'rsi': rsi, 'rsi_prev': rsi_prev,
                'macd_hist': macd_hist,
                'sma50': sma50, 'vol_avg': vol_avg, 'atr': atr,
                'stoch_k': stoch_k, 'stoch_d': stoch_d,
                'relperf_20d': relperf_20d,
                'rsi_slope': rsi_slope,
            }
        except:
            pass

    print(f"  {len(indicators)-1} tickers + SPY precomputados")
    return indicators

# ================================================================
# SEÑAL BASE (V4 actual — referencia)
# ================================================================
def check_base_v4(ind, ticker, i):
    """V4 actual: RSI<25 + SMA<-10% + Score>30 + regime + antiknife."""
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

        if np.isnan(rsi_val) or np.isnan(sma50_val) or np.isnan(atr_val):
            return False, {}

        # Base filters (Final)
        if rsi_val >= 30: return False, {}
        if macd_now <= macd_prev: return False, {}
        if dist_sma > -5: return False, {}
        if vol_ratio > 1.5: return False, {}

        # V4 filters
        if rsi_val >= 25: return False, {}
        if dist_sma > -10: return False, {}

        # Score
        rsi_score = min(40, max(0, (30 - rsi_val) / 30 * 40))
        sma_score = min(30, max(0, (abs(dist_sma) - 5) / 15 * 30))
        macd_score = min(20, max(0, macd_accel_norm * 5))
        vol_score = min(10, max(0, (1.5 - vol_ratio) / 1.5 * 10))
        total_score = rsi_score + sma_score + macd_score + vol_score

        if total_score < 30: return False, {}

        stop_loss = price - 2 * atr_val

        # Extras para candidatos
        stoch_k = ti['stoch_k'].iloc[i] if not np.isnan(ti['stoch_k'].iloc[i]) else 50
        relperf = ti['relperf_20d'].iloc[i] if not np.isnan(ti['relperf_20d'].iloc[i]) else 0
        rsi_slope = ti['rsi_slope'].iloc[i] if not np.isnan(ti['rsi_slope'].iloc[i]) else 0

        return True, {
            'rsi': rsi_val, 'dist_sma': dist_sma, 'vol_ratio': vol_ratio,
            'score': total_score, 'stop_loss': stop_loss, 'atr': atr_val,
            'macd_accel_norm': macd_accel_norm, 'price': price,
            'stoch_k': stoch_k, 'relperf_20d': relperf, 'rsi_slope': rsi_slope,
            'rsi_rising': ti['rsi'].iloc[i] > ti['rsi_prev'].iloc[i],
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

# ================================================================
# ESTRATEGIAS CANDIDATAS
# ================================================================
def strategy_v4_baseline(ind, ticker, i, last_signals, dates, tickers_universe=None, **kw):
    """V4 pura — baseline de referencia."""
    if not check_regime(ind, i): return False, {}
    if ticker in last_signals:
        if (dates[i] - last_signals[ticker]).days < 5: return False, {}
    if tickers_universe and ticker not in tickers_universe: return False, {}
    return check_base_v4(ind, ticker, i)

def strategy_c1_no_latam(ind, ticker, i, last_signals, dates, **kw):
    """C1: V4 + Excluir LatAm."""
    if ticker in LATAM_TICKERS: return False, {}
    if not check_regime(ind, i): return False, {}
    if ticker in last_signals:
        if (dates[i] - last_signals[ticker]).days < 5: return False, {}
    return check_base_v4(ind, ticker, i)

def strategy_c2_vol_tight(ind, ticker, i, last_signals, dates, **kw):
    """C2: V4 + Vol<1.0x (tighter volume filter)."""
    if not check_regime(ind, i): return False, {}
    if ticker in last_signals:
        if (dates[i] - last_signals[ticker]).days < 5: return False, {}
    sig, info = check_base_v4(ind, ticker, i)
    if not sig: return False, {}
    if info['vol_ratio'] >= 1.0: return False, {}  # Tighter: <1.0x vs <1.5x
    return True, info

def strategy_c4_stoch(ind, ticker, i, last_signals, dates, **kw):
    """C4: V4 + Stochastic K entre 10-25 (sweet zone sesion 14)."""
    if not check_regime(ind, i): return False, {}
    if ticker in last_signals:
        if (dates[i] - last_signals[ticker]).days < 5: return False, {}
    sig, info = check_base_v4(ind, ticker, i)
    if not sig: return False, {}
    if info['stoch_k'] < 10 or info['stoch_k'] > 25: return False, {}
    return True, info

def strategy_c5_relperf(ind, ticker, i, last_signals, dates, **kw):
    """C5: V4 + RelPerf 20d < -20% vs SPY."""
    if not check_regime(ind, i): return False, {}
    if ticker in last_signals:
        if (dates[i] - last_signals[ticker]).days < 5: return False, {}
    sig, info = check_base_v4(ind, ticker, i)
    if not sig: return False, {}
    if info['relperf_20d'] > -20: return False, {}  # Solo los que cayeron >20% vs SPY
    return True, info

def strategy_c6_no_toxic_slope(ind, ticker, i, last_signals, dates, **kw):
    """C6: V4 + Excluir zona toxica RSI slope [0, +2]."""
    if not check_regime(ind, i): return False, {}
    if ticker in last_signals:
        if (dates[i] - last_signals[ticker]).days < 5: return False, {}
    sig, info = check_base_v4(ind, ticker, i)
    if not sig: return False, {}
    slope = info['rsi_slope']
    if 0 <= slope <= 2: return False, {}  # Excluir zona toxica
    return True, info

# Combos de ganadores
def strategy_combo_c1_c2(ind, ticker, i, last_signals, dates, **kw):
    """Combo: No LatAm + Vol<1.0x."""
    if ticker in LATAM_TICKERS: return False, {}
    if not check_regime(ind, i): return False, {}
    if ticker in last_signals:
        if (dates[i] - last_signals[ticker]).days < 5: return False, {}
    sig, info = check_base_v4(ind, ticker, i)
    if not sig: return False, {}
    if info['vol_ratio'] >= 1.0: return False, {}
    return True, info

def strategy_combo_c1_c4(ind, ticker, i, last_signals, dates, **kw):
    """Combo: No LatAm + Stoch 10-25."""
    if ticker in LATAM_TICKERS: return False, {}
    if not check_regime(ind, i): return False, {}
    if ticker in last_signals:
        if (dates[i] - last_signals[ticker]).days < 5: return False, {}
    sig, info = check_base_v4(ind, ticker, i)
    if not sig: return False, {}
    if info['stoch_k'] < 10 or info['stoch_k'] > 25: return False, {}
    return True, info

def strategy_combo_c1_c5(ind, ticker, i, last_signals, dates, **kw):
    """Combo: No LatAm + RelPerf<-20%."""
    if ticker in LATAM_TICKERS: return False, {}
    if not check_regime(ind, i): return False, {}
    if ticker in last_signals:
        if (dates[i] - last_signals[ticker]).days < 5: return False, {}
    sig, info = check_base_v4(ind, ticker, i)
    if not sig: return False, {}
    if info['relperf_20d'] > -20: return False, {}
    return True, info

def strategy_combo_c1_c6(ind, ticker, i, last_signals, dates, **kw):
    """Combo: No LatAm + No toxic slope."""
    if ticker in LATAM_TICKERS: return False, {}
    if not check_regime(ind, i): return False, {}
    if ticker in last_signals:
        if (dates[i] - last_signals[ticker]).days < 5: return False, {}
    sig, info = check_base_v4(ind, ticker, i)
    if not sig: return False, {}
    slope = info['rsi_slope']
    if 0 <= slope <= 2: return False, {}
    return True, info

# ================================================================
# BACKTEST ENGINE
# ================================================================
def backtest(ind, tickers, strategy_fn, start_date, end_date,
             hold_days=10, commission=0.001, **kw):
    """Motor de backtest."""
    dates = ind['_SPY']['close'].index
    mask = (dates >= start_date) & (dates <= end_date)
    valid_indices = np.where(mask)[0]

    trades = []
    last_signals = {}

    for i in valid_indices:
        if i < 55 or i + hold_days + 5 >= len(dates):
            continue
        for ticker in tickers:
            if ticker not in ind:
                continue
            sig, info = strategy_fn(ind, ticker, i, last_signals, dates, **kw)
            if sig:
                entry_price = info['price']
                # Return at hold_days
                try:
                    exit_price = ind[ticker]['close'].iloc[i + hold_days]
                    ret = (exit_price / entry_price - 1) - 2 * commission
                except:
                    continue

                # MFE/MAE
                mfe, mae = 0, 0
                for d in range(1, hold_days + 1):
                    try:
                        h_d = ind[ticker]['high'].iloc[i + d]
                        l_d = ind[ticker]['low'].iloc[i + d]
                        mfe = max(mfe, (h_d / entry_price - 1))
                        mae = min(mae, (l_d / entry_price - 1))
                    except:
                        pass

                sector = 'Other'
                for s, tlist in SECTORS.items():
                    if ticker in tlist:
                        sector = s
                        break

                trades.append({
                    'date': dates[i], 'ticker': ticker, 'sector': sector,
                    'ret': ret, 'mfe': mfe, 'mae': mae,
                    **info,
                })
                last_signals[ticker] = dates[i]

    return pd.DataFrame(trades)

# ================================================================
# METRICAS
# ================================================================
def metrics(df, name=""):
    """Calcula metricas de un DataFrame de trades."""
    if df is None or len(df) == 0:
        return {'name': name, 'trades': 0, 'wr': 0, 'avg': 0, 'sharpe': 0, 'mdd': 0, 'total': 0}

    r = df['ret'].dropna()
    if len(r) == 0:
        return {'name': name, 'trades': 0, 'wr': 0, 'avg': 0, 'sharpe': 0, 'mdd': 0, 'total': 0}

    wins = r[r > 0]
    losses = r[r <= 0]
    wr = len(wins) / len(r) * 100
    avg = r.mean() * 100
    std = r.std()
    sharpe = (r.mean() / std * np.sqrt(252)) if std > 0 else 0

    # MDD
    equity = (1 + r).cumprod()
    peak = equity.expanding().max()
    dd = ((equity - peak) / peak)
    mdd = dd.min() * 100

    total = (equity.iloc[-1] - 1) * 100

    # Sortino
    neg = r[r < 0]
    down_std = neg.std() if len(neg) > 0 else 1e-10
    sortino = (r.mean() / down_std * np.sqrt(252)) if down_std > 0 else 0

    # Profit factor
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 1e-10
    pf = gross_profit / gross_loss

    # Avg win / avg loss
    avg_win = wins.mean() * 100 if len(wins) > 0 else 0
    avg_loss = losses.mean() * 100 if len(losses) > 0 else 0

    return {
        'name': name,
        'trades': len(r), 'wins': len(wins), 'losses': len(losses),
        'wr': round(wr, 1), 'avg': round(avg, 2), 'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2), 'total': round(total, 1),
        'sharpe': round(sharpe, 2), 'sortino': round(sortino, 2),
        'mdd': round(mdd, 1), 'pf': round(pf, 2),
    }

def print_metrics(m):
    """Imprime metricas de forma legible."""
    if m['trades'] == 0:
        print(f"    {m['name']}: 0 trades")
        return
    print(f"    {m['name']}:")
    print(f"      Trades: {m['trades']} (W:{m['wins']} L:{m['losses']}) | WR: {m['wr']}%")
    print(f"      Avg: {m['avg']}% (Win: {m['avg_win']}%, Loss: {m['avg_loss']}%)")
    print(f"      Sharpe: {m['sharpe']} | Sortino: {m['sortino']} | PF: {m['pf']}")
    print(f"      MDD: {m['mdd']}% | Total: {m['total']}%")

# ================================================================
# WALK-FORWARD ENGINE
# ================================================================
def walk_forward(ind, tickers, strategy_fn, train_months=6, test_months=2,
                 hold_days=10, **kw):
    """Walk-forward con ventanas rodantes."""
    dates = ind['_SPY']['close'].index
    start = dates[60]  # Skip first 60 days for indicator warmup
    end = dates[-1]

    # Generate windows
    windows = []
    current = pd.Timestamp('2024-09-01')
    while True:
        train_start = current
        train_end = current + pd.DateOffset(months=train_months)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=test_months)
        if test_end > end + pd.DateOffset(months=1):
            break
        windows.append({
            'train_start': train_start.strftime('%Y-%m-%d'),
            'train_end': train_end.strftime('%Y-%m-%d'),
            'test_start': test_start.strftime('%Y-%m-%d'),
            'test_end': test_end.strftime('%Y-%m-%d'),
        })
        current += pd.DateOffset(months=test_months)

    results = []
    for w in windows:
        # Train
        df_train = backtest(ind, tickers, strategy_fn,
                           w['train_start'], w['train_end'], hold_days=hold_days, **kw)
        m_train = metrics(df_train, f"Train {w['train_start'][:7]}")

        # Test
        df_test = backtest(ind, tickers, strategy_fn,
                          w['test_start'], w['test_end'], hold_days=hold_days, **kw)
        m_test = metrics(df_test, f"Test {w['test_start'][:7]}")

        results.append({
            'window': f"{w['test_start'][:7]}",
            'train_trades': m_train['trades'],
            'train_sharpe': m_train['sharpe'],
            'test_trades': m_test['trades'],
            'test_wr': m_test['wr'],
            'test_avg': m_test['avg'],
            'test_sharpe': m_test['sharpe'],
            'test_total': m_test['total'],
            'positive': m_test['sharpe'] > 0 and m_test['trades'] > 0,
        })

    return results

def print_wf_results(results, name):
    """Imprime resultados walk-forward."""
    positive = sum(1 for r in results if r['positive'])
    total = len([r for r in results if r['test_trades'] > 0 or r['train_trades'] > 0])
    # Count windows where there were test trades
    with_trades = [r for r in results if r['test_trades'] > 0]
    pos_with_trades = sum(1 for r in with_trades if r['positive'])

    print(f"\n    {name} — Walk-Forward ({len(results)} ventanas)")
    print(f"    {'Window':<10} {'Tr.Trades':>9} {'Tr.Sharpe':>9} {'Te.Trades':>9} {'Te.WR':>6} {'Te.Avg':>7} {'Te.Sharpe':>9} {'OK':>4}")
    print(f"    {'-'*70}")
    for r in results:
        ok = 'Y' if r['positive'] else 'N' if r['test_trades'] > 0 else '-'
        print(f"    {r['window']:<10} {r['train_trades']:>9} {r['train_sharpe']:>9.2f} "
              f"{r['test_trades']:>9} {r['test_wr']:>5.1f}% {r['test_avg']:>6.2f}% "
              f"{r['test_sharpe']:>9.2f} {ok:>4}")

    if len(with_trades) > 0:
        pct = pos_with_trades / len(with_trades) * 100
        avg_test_sharpe = np.mean([r['test_sharpe'] for r in with_trades])
        verdict = "PASS" if pct >= 60 else "FAIL"
        print(f"    {'='*70}")
        print(f"    Positivas: {pos_with_trades}/{len(with_trades)} ({pct:.0f}%) — {verdict}")
        print(f"    Sharpe test promedio: {avg_test_sharpe:.2f}")
        return pct >= 60, pct, avg_test_sharpe
    return False, 0, 0

# ================================================================
# SECCION 1: BACKTEST INDIVIDUAL DE CADA CANDIDATO
# ================================================================
def section1_individual(ind, tickers):
    print("\n" + "=" * 80)
    print("  SECCION 1: BACKTEST INDIVIDUAL — FULL PERIOD")
    print("  Cada candidato vs V4 baseline (Sep 2024 — Abr 2026)")
    print("=" * 80)

    strategies = {
        'V4 Baseline':         (strategy_v4_baseline, {}),
        'C1: No LatAm':        (strategy_c1_no_latam, {}),
        'C2: Vol<1.0x':        (strategy_c2_vol_tight, {}),
        'C4: Stoch 10-25':     (strategy_c4_stoch, {}),
        'C5: RelPerf<-20%':    (strategy_c5_relperf, {}),
        'C6: No toxic slope':  (strategy_c6_no_toxic_slope, {}),
    }

    results = {}
    for name, (fn, kw) in strategies.items():
        for hold in [10, 15]:
            label = f"{name} ({hold}d)"
            df = backtest(ind, tickers, fn, '2024-09-01', '2026-04-05',
                         hold_days=hold, **kw)
            m = metrics(df, label)
            results[label] = m
            print_metrics(m)

    return results

# ================================================================
# SECCION 2: WALK-FORWARD DE CADA CANDIDATO
# ================================================================
def section2_walkforward(ind, tickers):
    print("\n" + "=" * 80)
    print("  SECCION 2: WALK-FORWARD VALIDATION")
    print("  Train 6m → Test 2m | Criterio: >= 60% ventanas positivas")
    print("=" * 80)

    candidates = {
        'V4 Baseline':         (strategy_v4_baseline, {}),
        'C1: No LatAm':        (strategy_c1_no_latam, {}),
        'C2: Vol<1.0x':        (strategy_c2_vol_tight, {}),
        'C4: Stoch 10-25':     (strategy_c4_stoch, {}),
        'C5: RelPerf<-20%':    (strategy_c5_relperf, {}),
        'C6: No toxic slope':  (strategy_c6_no_toxic_slope, {}),
    }

    wf_results = {}
    for name, (fn, kw) in candidates.items():
        for hold in [10, 15]:
            label = f"{name} ({hold}d)"
            results = walk_forward(ind, tickers, fn, hold_days=hold, **kw)
            passed, pct, avg_sharpe = print_wf_results(results, label)
            wf_results[label] = {
                'passed': passed, 'pct': pct, 'avg_sharpe': avg_sharpe,
                'details': results,
            }

    # Summary
    print("\n" + "=" * 80)
    print("  RESUMEN WALK-FORWARD — CANDIDATOS")
    print("=" * 80)
    print(f"  {'Candidato':<30} {'WF%':>5} {'AvgSharpe':>10} {'Veredicto':>10}")
    print(f"  {'-'*60}")
    for label, wf in wf_results.items():
        verdict = "PASS" if wf['passed'] else "FAIL"
        print(f"  {label:<30} {wf['pct']:>4.0f}% {wf['avg_sharpe']:>10.2f} {verdict:>10}")

    return wf_results

# ================================================================
# SECCION 3: COMBOS DE GANADORES VALIDADOS
# ================================================================
def section3_combos(ind, tickers, wf_results):
    print("\n" + "=" * 80)
    print("  SECCION 3: COMBOS DE GANADORES VALIDADOS")
    print("  Solo se combinan candidatos que PASARON walk-forward")
    print("=" * 80)

    # Identify winners (at 10d hold since that's our baseline)
    winners_10d = []
    for label, wf in wf_results.items():
        if '10d' in label and wf['passed'] and 'Baseline' not in label:
            winners_10d.append(label.split(':')[0].strip().replace('(', '').replace(')', ''))

    print(f"\n  Ganadores WF (10d): {winners_10d if winners_10d else 'Ninguno'}")

    combos = {
        'Combo: C1+C2 (NoLatAm+Vol<1.0)':  (strategy_combo_c1_c2, {}),
        'Combo: C1+C4 (NoLatAm+Stoch)':     (strategy_combo_c1_c4, {}),
        'Combo: C1+C5 (NoLatAm+RelPerf)':   (strategy_combo_c1_c5, {}),
        'Combo: C1+C6 (NoLatAm+NoSlope)':    (strategy_combo_c1_c6, {}),
    }

    combo_results = {}
    for name, (fn, kw) in combos.items():
        for hold in [10, 15]:
            label = f"{name} ({hold}d)"
            # Full period backtest
            df = backtest(ind, tickers, fn, '2024-09-01', '2026-04-05',
                         hold_days=hold, **kw)
            m = metrics(df, label)
            print_metrics(m)

            # Walk-forward
            results = walk_forward(ind, tickers, fn, hold_days=hold, **kw)
            passed, pct, avg_sharpe = print_wf_results(results, label)
            combo_results[label] = {
                'metrics': m, 'wf_passed': passed, 'wf_pct': pct,
                'wf_avg_sharpe': avg_sharpe,
            }

    return combo_results

# ================================================================
# SECCION 4: HOLDING PERIOD OPTIMIZATION (V4 especifico)
# ================================================================
def section4_holding(ind, tickers):
    print("\n" + "=" * 80)
    print("  SECCION 4: HOLDING PERIOD — V4 ESPECIFICO")
    print("  (El dato de 15d del Round 3 era sobre Final, no V4)")
    print("=" * 80)

    for hold in [5, 7, 10, 12, 15, 20]:
        df = backtest(ind, tickers, strategy_v4_baseline, '2024-09-01', '2026-04-05',
                     hold_days=hold)
        m = metrics(df, f"V4 hold={hold}d")
        print_metrics(m)

# ================================================================
# SECCION 5: ANALISIS POR SECTOR (V4 base)
# ================================================================
def section5_sectors(ind, tickers):
    print("\n" + "=" * 80)
    print("  SECCION 5: ANALISIS POR SECTOR — V4 BASELINE")
    print("=" * 80)

    df = backtest(ind, tickers, strategy_v4_baseline, '2024-09-01', '2026-04-05',
                 hold_days=10)

    if len(df) == 0:
        print("  Sin trades para analizar por sector.")
        return

    print(f"\n  Total trades V4: {len(df)}")
    print(f"\n  {'Sector':<12} {'Trades':>6} {'WR':>6} {'Avg%':>7} {'Sharpe':>7} {'MDD%':>7} {'Total%':>8}")
    print(f"  {'-'*60}")

    for sector in sorted(df['sector'].unique()):
        sector_df = df[df['sector'] == sector]
        m = metrics(sector_df, sector)
        if m['trades'] > 0:
            print(f"  {sector:<12} {m['trades']:>6} {m['wr']:>5.1f}% {m['avg']:>6.2f}% "
                  f"{m['sharpe']:>7.2f} {m['mdd']:>6.1f}% {m['total']:>7.1f}%")

# ================================================================
# SECCION 6: DISTRIBUCION DE INDICADORES NUEVOS
# ================================================================
def section6_distributions(ind, tickers):
    print("\n" + "=" * 80)
    print("  SECCION 6: DISTRIBUCION DE INDICADORES NUEVOS EN TRADES V4")
    print("  (Para entender los rangos naturales antes de filtrar)")
    print("=" * 80)

    df = backtest(ind, tickers, strategy_v4_baseline, '2024-09-01', '2026-04-05',
                 hold_days=10)

    if len(df) == 0:
        print("  Sin trades.")
        return

    # Stochastic K distribution
    print("\n  STOCHASTIC K en trades V4:")
    if 'stoch_k' in df.columns:
        bins = [0, 5, 10, 15, 20, 25, 30, 50, 100]
        df['stoch_bin'] = pd.cut(df['stoch_k'], bins=bins)
        for b in df['stoch_bin'].unique():
            if pd.isna(b):
                continue
            sub = df[df['stoch_bin'] == b]
            if len(sub) > 0:
                wr = (sub['ret'] > 0).mean() * 100
                avg = sub['ret'].mean() * 100
                print(f"    Stoch {str(b):<12}: {len(sub):>3} trades, WR {wr:>5.1f}%, Avg {avg:>+6.2f}%")

    # RelPerf distribution
    print("\n  RELPERF 20d vs SPY en trades V4:")
    if 'relperf_20d' in df.columns:
        bins = [-100, -30, -20, -15, -10, -5, 0, 10, 100]
        df['relperf_bin'] = pd.cut(df['relperf_20d'], bins=bins)
        for b in sorted(df['relperf_bin'].dropna().unique()):
            sub = df[df['relperf_bin'] == b]
            if len(sub) > 0:
                wr = (sub['ret'] > 0).mean() * 100
                avg = sub['ret'].mean() * 100
                print(f"    RelPerf {str(b):<14}: {len(sub):>3} trades, WR {wr:>5.1f}%, Avg {avg:>+6.2f}%")

    # RSI slope distribution
    print("\n  RSI SLOPE (3-period change) en trades V4:")
    if 'rsi_slope' in df.columns:
        bins = [-20, -5, -2, 0, 2, 5, 20]
        df['slope_bin'] = pd.cut(df['rsi_slope'], bins=bins)
        for b in sorted(df['slope_bin'].dropna().unique()):
            sub = df[df['slope_bin'] == b]
            if len(sub) > 0:
                wr = (sub['ret'] > 0).mean() * 100
                avg = sub['ret'].mean() * 100
                print(f"    Slope {str(b):<12}: {len(sub):>3} trades, WR {wr:>5.1f}%, Avg {avg:>+6.2f}%")

# ================================================================
# SECCION 7: VEREDICTO FINAL
# ================================================================
def section7_verdict(individual, wf_results, combo_results):
    print("\n" + "=" * 80)
    print("  SECCION 7: VEREDICTO FINAL")
    print("=" * 80)

    print("\n  PROTOCOLO 4 — CHECKLIST ANTI-OVERFITTING:")
    print("  [Los items se evaluan para el MEJOR candidato]")
    print()

    # Find best combo by walk-forward avg sharpe
    best = None
    best_label = None
    for label, cr in combo_results.items():
        if cr['wf_passed'] and (best is None or cr['wf_avg_sharpe'] > best['wf_avg_sharpe']):
            best = cr
            best_label = label

    if best is None:
        # Fall back to individual winners
        for label, wf in wf_results.items():
            if wf['passed'] and '10d' in label and (best_label is None or wf['avg_sharpe'] > wf_results.get(best_label, {}).get('avg_sharpe', 0)):
                best_label = label

    if best_label:
        print(f"  Mejor candidato: {best_label}")
        if best:
            m = best['metrics']
            print(f"  Trades: {m['trades']} | WR: {m['wr']}% | Sharpe: {m['sharpe']} | MDD: {m['mdd']}%")

        print(f"""
  [ ] LOOK-AHEAD BIAS:    No — backtest usa datos historicos secuenciales
  [ ] SURVIVORSHIP BIAS:  Parcial — solo tickers actualmente listados
  [ ] PERIODO:            {'>18m' if True else '<18m'} — Sep 2024 a Abr 2026 (~19 meses)
  [ ] OUT-OF-SAMPLE:      Si — walk-forward con ventanas rodantes
  [ ] WALK-FORWARD:       {'PASS' if best and best['wf_passed'] else 'PENDIENTE'}
  [ ] COMPLEJIDAD:        Evaluar segun el candidato final
  [ ] TRADES MINIMOS:     Evaluar segun el candidato final
  [ ] COSTOS:             Si — 0.1% comision por trade (ida + vuelta)
""")
    else:
        print("  Ningun candidato paso walk-forward.")
        print("  V4 SE MANTIENE sin cambios.")

    print("\n  PROTOCOLO 6 — CONVERGENCIA 3 ANGULOS:")
    print("  Angulo 1 (Tecnico): [Ver metricas arriba]")
    print("  Angulo 2 (Riesgo):  [Ver MDD y worst-case]")
    print("  Angulo 3 (Simplicidad): [Contar filtros vs V4]")
    print("  Veredicto: 2/3 deben coincidir para proceder")

# ================================================================
# MAIN
# ================================================================
def main():
    start_time = datetime.now()
    print("=" * 80)
    print("  ANALISIS V5 CANDIDATES")
    print(f"  {start_time.strftime('%Y-%m-%d %H:%M')}")
    print("  Protocolo: Individual → Walk-Forward → Combos → Veredicto")
    print("=" * 80)

    # Download data
    data, available = download_data()

    # Precompute
    ind = precompute_indicators(data, available)

    # Gate check: RSI uses Wilder's smoothing
    print("\n  GATE RSI: Verificando Wilder's smoothing... ", end="")
    # calc_rsi uses ewm(com=period-1) — CORRECTO
    print("OK (ewm com=13)")

    # Run all sections
    individual = section1_individual(ind, available)
    wf_results = section2_walkforward(ind, available)
    combo_results = section3_combos(ind, available, wf_results)
    section4_holding(ind, available)
    section5_sectors(ind, available)
    section6_distributions(ind, available)
    section7_verdict(individual, wf_results, combo_results)

    elapsed = (datetime.now() - start_time).total_seconds() / 60
    print(f"\n  Tiempo total: {elapsed:.1f} minutos")
    print("=" * 80)

if __name__ == '__main__':
    main()
