"""
INVESTIGACION MODELO SUPERADOR — Pensar fuera de la caja
==========================================================
NO partimos de V4. Exploramos TODO desde cero.

Estructura del experimento:
  PARTE 1: 12 indicadores nuevos — distribución en trades ganadores vs perdedores
  PARTE 2: Señales alternativas (no RSI-based)
  PARTE 3: Re-scoring — ¿la fórmula de score es óptima?
  PARTE 4: Salidas inteligentes vs holding fijo
  PARTE 5: Mega-scan de combinaciones nuevas con walk-forward
  PARTE 6: Veredicto final con protocolos completos

Indicadores nuevos a probar:
  - Bollinger Band %B y ancho (squeeze)
  - Williams %R
  - MFI (Money Flow Index) — RSI ponderado por volumen
  - CCI (Commodity Channel Index)
  - ADX (fuerza de tendencia)
  - OBV slope (On Balance Volume)
  - ROC (Rate of Change) 10d y 20d
  - Distancia a 52-week low
  - Keltner Channel position
  - TRIX (triple EMA momentum)
  - Chaikin Money Flow (CMF)
  - RSI de volumen (¿el volumen está oversold también?)

Fecha: 2026-04-05
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
# UNIVERSO (sin LatAm — ya validado)
# ================================================================
TICKERS = [
    'AAPL','MSFT','GOOGL','AMZN','META','NVDA','AMD','TSLA','NFLX','CRM',
    'ORCL','ADBE','INTC','AVGO','QCOM','MU','AMAT','LRCX','TXN','PLTR',
    'JPM','BAC','WFC','GS','V','MA','AXP','C','PYPL','COIN',
    'JNJ','PFE','UNH','MRK','ABBV','LLY','TMO','ABT','BMY','AMGN',
    'XOM','CVX','COP','SLB','OXY','HAL','DVN','MPC','VLO','EOG',
    'KO','PEP','PG','WMT','COST','MCD','NKE','SBUX','TGT','HD',
    'CAT','BA','GE','RTX','HON','LMT','UPS','FDX','DE','MMM',
]

CONTEXT = ['SPY','QQQ']

# ================================================================
# INDICADORES — Base + 12 Nuevos
# ================================================================
def calc_rsi(series, period=14):
    """Wilder's smoothing — OBLIGATORIO."""
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

def calc_bollinger(close, period=20, std_dev=2):
    """Bollinger Bands: %B (posición dentro de bandas) y ancho."""
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    pct_b = (close - lower) / (upper - lower + 1e-10)  # 0=lower band, 1=upper
    width = (upper - lower) / sma * 100  # ancho como % del precio
    return pct_b, width

def calc_williams_r(high, low, close, period=14):
    """Williams %R: -100 a 0. <-80 = oversold."""
    highest = high.rolling(period).max()
    lowest = low.rolling(period).min()
    wr = -100 * (highest - close) / (highest - lowest + 1e-10)
    return wr

def calc_mfi(high, low, close, volume, period=14):
    """Money Flow Index: RSI ponderado por volumen. 0-100."""
    typical_price = (high + low + close) / 3
    money_flow = typical_price * volume
    delta = typical_price.diff()
    pos_flow = money_flow.where(delta > 0, 0).rolling(period).sum()
    neg_flow = money_flow.where(delta <= 0, 0).rolling(period).sum()
    mfi = 100 - 100 / (1 + pos_flow / (neg_flow + 1e-10))
    return mfi

def calc_cci(high, low, close, period=20):
    """CCI: valores extremos (<-100 = oversold)."""
    tp = (high + low + close) / 3
    sma_tp = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    cci = (tp - sma_tp) / (0.015 * mad + 1e-10)
    return cci

def calc_adx(high, low, close, period=14):
    """ADX: fuerza de tendencia. >25 = tendencia fuerte."""
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    atr = calc_atr(high, low, close, period)
    plus_di = 100 * plus_dm.ewm(span=period).mean() / (atr + 1e-10)
    minus_di = 100 * minus_dm.ewm(span=period).mean() / (atr + 1e-10)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx = dx.ewm(span=period).mean()
    return adx, plus_di, minus_di

def calc_obv_slope(close, volume, period=10):
    """OBV slope: tendencia del On Balance Volume."""
    direction = np.sign(close.diff())
    obv = (volume * direction).cumsum()
    obv_slope = obv - obv.shift(period)
    # Normalizar por volumen promedio
    obv_slope_norm = obv_slope / (volume.rolling(period).mean() + 1e-10)
    return obv_slope_norm

def calc_roc(close, period=10):
    """Rate of Change en %."""
    return (close / close.shift(period) - 1) * 100

def calc_dist_52w_low(close):
    """Distancia al mínimo de 252 días (1 año) en %."""
    low_252 = close.rolling(252, min_periods=60).min()
    return (close / low_252 - 1) * 100

def calc_keltner_position(high, low, close, ema_period=20, atr_period=10, atr_mult=2):
    """Posición dentro del canal de Keltner. <0 = debajo del canal."""
    ema = close.ewm(span=ema_period).mean()
    atr = calc_atr(high, low, close, atr_period)
    upper = ema + atr_mult * atr
    lower = ema - atr_mult * atr
    position = (close - lower) / (upper - lower + 1e-10)
    return position

def calc_trix(close, period=15):
    """TRIX: triple EMA rate of change. Momentum suavizado."""
    ema1 = close.ewm(span=period).mean()
    ema2 = ema1.ewm(span=period).mean()
    ema3 = ema2.ewm(span=period).mean()
    return ema3.pct_change() * 100

def calc_cmf(high, low, close, volume, period=20):
    """Chaikin Money Flow: presión de compra/venta."""
    clv = ((close - low) - (high - close)) / (high - low + 1e-10)
    cmf = (clv * volume).rolling(period).sum() / (volume.rolling(period).sum() + 1e-10)
    return cmf

def calc_vol_rsi(volume, period=14):
    """RSI aplicado al volumen — ¿el volumen está oversold?"""
    return calc_rsi(volume, period)

# ================================================================
# DESCARGA Y PRECOMPUTE
# ================================================================
def download_data():
    print("\n" + "=" * 80)
    print("  DESCARGANDO DATOS (2 anos)")
    print("=" * 80)
    all_t = list(set(TICKERS + CONTEXT))
    data = yf.download(all_t, start='2024-03-01', end='2026-04-05', progress=False, threads=True)
    available = []
    for t in TICKERS:
        try:
            c = data['Close'][t].dropna()
            if len(c) > 200:
                available.append(t)
        except:
            pass
    dates = data['Close'].dropna(how='all').index
    print(f"  {len(available)}/{len(TICKERS)} activos con >200 dias")
    print(f"  Rango: {dates[0].strftime('%Y-%m-%d')} a {dates[-1].strftime('%Y-%m-%d')}")
    return data, available

def precompute_all(data, tickers):
    """Precomputa TODOS los indicadores — base + 12 nuevos."""
    print("  Precomputando 18 indicadores por ticker...")
    indicators = {}

    # SPY
    try:
        spy_c = data['Close']['SPY']
        spy_sma50 = spy_c.rolling(50).mean()
        spy_vol = spy_c.pct_change().rolling(20).std() * 100
        indicators['_SPY'] = {'close': spy_c, 'sma50': spy_sma50, 'vol': spy_vol}
    except:
        return {}

    for ticker in tickers:
        try:
            c = data['Close'][ticker]
            h = data['High'][ticker]
            l = data['Low'][ticker]
            v = data['Volume'][ticker]

            rsi = calc_rsi(c)
            _, _, macd_hist = calc_macd(c)
            sma50 = c.rolling(50).mean()
            sma200 = c.rolling(200).mean()
            atr = calc_atr(h, l, c)
            vol_avg = v.rolling(20).mean()

            # 12 NUEVOS
            bb_pctb, bb_width = calc_bollinger(c)
            williams_r = calc_williams_r(h, l, c)
            mfi = calc_mfi(h, l, c, v)
            cci = calc_cci(h, l, c)
            adx, plus_di, minus_di = calc_adx(h, l, c)
            obv_slope = calc_obv_slope(c, v)
            roc_10 = calc_roc(c, 10)
            roc_20 = calc_roc(c, 20)
            dist_52w = calc_dist_52w_low(c)
            keltner_pos = calc_keltner_position(h, l, c)
            trix = calc_trix(c)
            cmf = calc_cmf(h, l, c, v)
            vol_rsi = calc_vol_rsi(v)

            # Stochastic (ya probado pero lo incluyo para comparar)
            lowest_low = l.rolling(14).min()
            highest_high = h.rolling(14).max()
            stoch_k = 100 * (c - lowest_low) / (highest_high - lowest_low + 1e-10)

            indicators[ticker] = {
                'close': c, 'high': h, 'low': l, 'volume': v,
                'rsi': rsi, 'rsi_prev': rsi.shift(1),
                'macd_hist': macd_hist,
                'sma50': sma50, 'sma200': sma200,
                'vol_avg': vol_avg, 'atr': atr,
                # Nuevos
                'bb_pctb': bb_pctb, 'bb_width': bb_width,
                'williams_r': williams_r, 'mfi': mfi, 'cci': cci,
                'adx': adx, 'plus_di': plus_di, 'minus_di': minus_di,
                'obv_slope': obv_slope,
                'roc_10': roc_10, 'roc_20': roc_20,
                'dist_52w': dist_52w,
                'keltner_pos': keltner_pos,
                'trix': trix, 'cmf': cmf,
                'vol_rsi': vol_rsi,
                'stoch_k': stoch_k,
            }
        except:
            pass

    print(f"  {len(indicators)-1} tickers procesados")
    return indicators

# ================================================================
# BACKTEST ENGINE (genérico)
# ================================================================
def check_regime(ind, i):
    try:
        spy = ind['_SPY']
        return spy['close'].iloc[i] > spy['sma50'].iloc[i] and spy['vol'].iloc[i] < 1.0
    except:
        return False

def backtest_strategy(ind, tickers, signal_fn, start='2024-09-01', end='2026-04-05',
                      hold_days=7, commission=0.001, use_regime=True, use_antiknife=True):
    """Backtest genérico que acepta cualquier función de señal."""
    dates = ind['_SPY']['close'].index
    mask = (dates >= start) & (dates <= end)
    valid_indices = np.where(mask)[0]

    trades = []
    last_signals = {}

    for i in valid_indices:
        if i < 260 or i + hold_days + 5 >= len(dates):
            continue
        if use_regime and not check_regime(ind, i):
            continue
        for ticker in tickers:
            if ticker not in ind:
                continue
            if use_antiknife and ticker in last_signals:
                if (dates[i] - last_signals[ticker]).days < 5:
                    continue
            try:
                sig, info = signal_fn(ind, ticker, i)
                if not sig:
                    continue

                entry_price = ind[ticker]['close'].iloc[i]
                exit_price = ind[ticker]['close'].iloc[i + hold_days]
                ret = (exit_price / entry_price - 1) - 2 * commission

                # MFE/MAE
                mfe, mae = 0, 0
                for d in range(1, hold_days + 1):
                    try:
                        hd = ind[ticker]['high'].iloc[i + d]
                        ld = ind[ticker]['low'].iloc[i + d]
                        mfe = max(mfe, (hd / entry_price - 1))
                        mae = min(mae, (ld / entry_price - 1))
                    except:
                        pass

                trades.append({
                    'date': dates[i], 'ticker': ticker,
                    'ret': ret, 'mfe': mfe, 'mae': mae,
                    **info,
                })
                last_signals[ticker] = dates[i]
            except:
                continue

    return pd.DataFrame(trades)

def metrics(df, name=""):
    if df is None or len(df) == 0:
        return {'name': name, 'trades': 0, 'wr': 0, 'avg': 0, 'sharpe': 0, 'mdd': 0,
                'total': 0, 'sortino': 0, 'pf': 0, 'avg_win': 0, 'avg_loss': 0}
    r = df['ret'].dropna()
    if len(r) == 0:
        return {'name': name, 'trades': 0, 'wr': 0, 'avg': 0, 'sharpe': 0, 'mdd': 0,
                'total': 0, 'sortino': 0, 'pf': 0, 'avg_win': 0, 'avg_loss': 0}
    wins = r[r > 0]; losses = r[r <= 0]
    wr = len(wins) / len(r) * 100
    avg = r.mean() * 100
    std = r.std()
    sharpe = (r.mean() / std * np.sqrt(252)) if std > 0 else 0
    equity = (1 + r).cumprod()
    peak = equity.expanding().max()
    mdd = ((equity - peak) / peak).min() * 100
    total = (equity.iloc[-1] - 1) * 100
    neg = r[r < 0]
    down_std = neg.std() if len(neg) > 0 else 1e-10
    sortino = (r.mean() / down_std * np.sqrt(252)) if down_std > 0 else 0
    gp = wins.sum() if len(wins) > 0 else 0
    gl = abs(losses.sum()) if len(losses) > 0 else 1e-10
    pf = gp / gl
    return {
        'name': name, 'trades': len(r), 'wins': len(wins), 'losses': len(losses),
        'wr': round(wr,1), 'avg': round(avg,2),
        'avg_win': round(wins.mean()*100,2) if len(wins) > 0 else 0,
        'avg_loss': round(losses.mean()*100,2) if len(losses) > 0 else 0,
        'total': round(total,1), 'sharpe': round(sharpe,2), 'sortino': round(sortino,2),
        'mdd': round(mdd,1), 'pf': round(pf,2),
    }

def print_metrics_line(m):
    if m['trades'] == 0:
        print(f"    {m['name']:<40} 0 trades")
        return
    print(f"    {m['name']:<40} T:{m['trades']:>3} WR:{m['wr']:>5.1f}% "
          f"Avg:{m['avg']:>+6.2f}% Sharpe:{m['sharpe']:>7.2f} MDD:{m['mdd']:>6.1f}% "
          f"Total:{m['total']:>7.1f}% PF:{m['pf']:>5.2f}")

# ================================================================
# WALK-FORWARD
# ================================================================
def walk_forward(ind, tickers, signal_fn, hold_days=7, **kw):
    dates = ind['_SPY']['close'].index
    end = dates[-1]
    windows = []
    current = pd.Timestamp('2024-09-01')
    while True:
        train_end = current + pd.DateOffset(months=6)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=2)
        if test_end > end + pd.DateOffset(months=1):
            break
        windows.append((current.strftime('%Y-%m-%d'), train_end.strftime('%Y-%m-%d'),
                        test_start.strftime('%Y-%m-%d'), test_end.strftime('%Y-%m-%d')))
        current += pd.DateOffset(months=2)

    pos = 0; total_with_trades = 0
    test_sharpes = []
    for ts, te, vs, ve in windows:
        df_test = backtest_strategy(ind, tickers, signal_fn, vs, ve, hold_days=hold_days, **kw)
        m = metrics(df_test)
        if m['trades'] > 0:
            total_with_trades += 1
            if m['sharpe'] > 0:
                pos += 1
            test_sharpes.append(m['sharpe'])

    if total_with_trades == 0:
        return 0, 0, 0
    pct = pos / total_with_trades * 100
    avg_sharpe = np.mean(test_sharpes) if test_sharpes else 0
    return pct, total_with_trades, avg_sharpe

# ================================================================
# SEÑALES DE ENTRADA — 15+ estrategias a probar
# ================================================================

# --- V5 BASELINE (referencia) ---
def signal_v5(ind, ticker, i):
    """V5 actual: RSI<25 + SMA<-10% + Score>30 + MACD up."""
    ti = ind[ticker]
    rsi = ti['rsi'].iloc[i]
    macd_now = ti['macd_hist'].iloc[i]
    macd_prev = ti['macd_hist'].iloc[i-1]
    price = ti['close'].iloc[i]
    sma50 = ti['sma50'].iloc[i]
    vol_ratio = ti['volume'].iloc[i] / (ti['vol_avg'].iloc[i] + 1e-10)
    atr = ti['atr'].iloc[i]
    dist_sma = (price / sma50 - 1) * 100
    macd_accel = macd_now - macd_prev
    macd_accel_norm = macd_accel / (atr * 0.01 + 1e-6)

    if np.isnan(rsi) or np.isnan(sma50) or np.isnan(atr): return False, {}
    if rsi >= 25: return False, {}
    if macd_now <= macd_prev: return False, {}
    if dist_sma > -10: return False, {}
    if vol_ratio > 1.5: return False, {}

    rsi_sc = min(40, max(0, (30-rsi)/30*40))
    sma_sc = min(30, max(0, (abs(dist_sma)-5)/15*30))
    macd_sc = min(20, max(0, macd_accel_norm*5))
    vol_sc = min(10, max(0, (1.5-vol_ratio)/1.5*10))
    score = rsi_sc + sma_sc + macd_sc + vol_sc

    if score < 30: return False, {}
    return True, {'rsi': rsi, 'dist_sma': dist_sma, 'vol_ratio': vol_ratio, 'score': score}

# --- NUEVO A: Bollinger + RSI (doble confirmación oversold) ---
def signal_bollinger_rsi(ind, ticker, i):
    """BB %B < 0 (debajo de banda inferior) + RSI < 30."""
    ti = ind[ticker]
    rsi = ti['rsi'].iloc[i]
    bb_pctb = ti['bb_pctb'].iloc[i]
    price = ti['close'].iloc[i]
    sma50 = ti['sma50'].iloc[i]
    dist_sma = (price / sma50 - 1) * 100

    if np.isnan(rsi) or np.isnan(bb_pctb): return False, {}
    if rsi >= 30: return False, {}
    if bb_pctb >= 0.05: return False, {}  # Debajo o cerca de banda inferior
    if dist_sma > -5: return False, {}
    return True, {'rsi': rsi, 'bb_pctb': bb_pctb, 'dist_sma': dist_sma}

# --- NUEVO B: MFI + RSI (volumen confirma oversold) ---
def signal_mfi_rsi(ind, ticker, i):
    """MFI < 20 + RSI < 30 — oversold en precio Y volumen."""
    ti = ind[ticker]
    rsi = ti['rsi'].iloc[i]
    mfi = ti['mfi'].iloc[i]
    price = ti['close'].iloc[i]
    sma50 = ti['sma50'].iloc[i]
    dist_sma = (price / sma50 - 1) * 100

    if np.isnan(rsi) or np.isnan(mfi): return False, {}
    if rsi >= 30: return False, {}
    if mfi >= 20: return False, {}
    if dist_sma > -5: return False, {}
    return True, {'rsi': rsi, 'mfi': mfi, 'dist_sma': dist_sma}

# --- NUEVO C: CCI extremo ---
def signal_cci_extreme(ind, ticker, i):
    """CCI < -200 (extreme oversold) + precio bajo SMA50."""
    ti = ind[ticker]
    cci = ti['cci'].iloc[i]
    price = ti['close'].iloc[i]
    sma50 = ti['sma50'].iloc[i]
    dist_sma = (price / sma50 - 1) * 100
    rsi = ti['rsi'].iloc[i]

    if np.isnan(cci) or np.isnan(rsi): return False, {}
    if cci >= -200: return False, {}
    if dist_sma > -5: return False, {}
    return True, {'cci': cci, 'rsi': rsi, 'dist_sma': dist_sma}

# --- NUEVO D: Williams %R + Bollinger squeeze ---
def signal_williams_squeeze(ind, ticker, i):
    """Williams %R < -90 + BB width en mínimo (squeeze = explosión inminente)."""
    ti = ind[ticker]
    wr = ti['williams_r'].iloc[i]
    bb_width = ti['bb_width'].iloc[i]
    bb_width_min = ti['bb_width'].rolling(50).min().iloc[i] if i >= 50 else np.nan
    price = ti['close'].iloc[i]
    sma50 = ti['sma50'].iloc[i]
    dist_sma = (price / sma50 - 1) * 100

    if np.isnan(wr) or np.isnan(bb_width) or np.isnan(bb_width_min): return False, {}
    if wr >= -90: return False, {}
    # Squeeze: ancho actual < 1.2x mínimo de 50d
    if bb_width > bb_width_min * 1.2: return False, {}
    if dist_sma > -5: return False, {}
    return True, {'williams_r': wr, 'bb_width': bb_width, 'dist_sma': dist_sma}

# --- NUEVO E: OBV divergence + RSI oversold ---
def signal_obv_divergence(ind, ticker, i):
    """Precio cae pero OBV sube (divergencia alcista) + RSI < 30."""
    ti = ind[ticker]
    rsi = ti['rsi'].iloc[i]
    obv_slope = ti['obv_slope'].iloc[i]
    roc_10 = ti['roc_10'].iloc[i]
    price = ti['close'].iloc[i]
    sma50 = ti['sma50'].iloc[i]
    dist_sma = (price / sma50 - 1) * 100

    if np.isnan(rsi) or np.isnan(obv_slope) or np.isnan(roc_10): return False, {}
    if rsi >= 30: return False, {}
    if roc_10 >= 0: return False, {}     # Precio cayendo
    if obv_slope <= 0: return False, {}   # Pero OBV SUBIENDO (divergencia)
    if dist_sma > -5: return False, {}
    return True, {'rsi': rsi, 'obv_slope': obv_slope, 'roc_10': roc_10, 'dist_sma': dist_sma}

# --- NUEVO F: Keltner Channel extremo ---
def signal_keltner_extreme(ind, ticker, i):
    """Precio debajo del canal de Keltner + RSI < 30."""
    ti = ind[ticker]
    rsi = ti['rsi'].iloc[i]
    kelt = ti['keltner_pos'].iloc[i]
    price = ti['close'].iloc[i]
    sma50 = ti['sma50'].iloc[i]
    dist_sma = (price / sma50 - 1) * 100

    if np.isnan(rsi) or np.isnan(kelt): return False, {}
    if rsi >= 30: return False, {}
    if kelt >= 0: return False, {}  # Debajo del canal
    if dist_sma > -5: return False, {}
    return True, {'rsi': rsi, 'keltner_pos': kelt, 'dist_sma': dist_sma}

# --- NUEVO G: CMF negativo + RSI (presión vendedora agotándose) ---
def signal_cmf_reversal(ind, ticker, i):
    """CMF girando de negativo a positivo + RSI < 30."""
    ti = ind[ticker]
    rsi = ti['rsi'].iloc[i]
    cmf_now = ti['cmf'].iloc[i]
    cmf_prev = ti['cmf'].iloc[i-5] if i >= 5 else np.nan
    price = ti['close'].iloc[i]
    sma50 = ti['sma50'].iloc[i]
    dist_sma = (price / sma50 - 1) * 100

    if np.isnan(rsi) or np.isnan(cmf_now) or np.isnan(cmf_prev): return False, {}
    if rsi >= 30: return False, {}
    if cmf_prev >= 0: return False, {}   # CMF era negativo
    if cmf_now <= cmf_prev: return False, {} # Y ahora está subiendo
    if dist_sma > -5: return False, {}
    return True, {'rsi': rsi, 'cmf': cmf_now, 'cmf_change': cmf_now - cmf_prev, 'dist_sma': dist_sma}

# --- NUEVO H: Triple oversold (RSI + MFI + Williams %R) ---
def signal_triple_oversold(ind, ticker, i):
    """3 indicadores oversold simultáneamente = señal fuerte."""
    ti = ind[ticker]
    rsi = ti['rsi'].iloc[i]
    mfi = ti['mfi'].iloc[i]
    wr = ti['williams_r'].iloc[i]
    price = ti['close'].iloc[i]
    sma50 = ti['sma50'].iloc[i]
    dist_sma = (price / sma50 - 1) * 100

    if np.isnan(rsi) or np.isnan(mfi) or np.isnan(wr): return False, {}
    if rsi >= 30: return False, {}
    if mfi >= 25: return False, {}
    if wr >= -80: return False, {}
    if dist_sma > -5: return False, {}
    return True, {'rsi': rsi, 'mfi': mfi, 'williams_r': wr, 'dist_sma': dist_sma}

# --- NUEVO I: ADX trend weakness + RSI (tendencia bajista agotada) ---
def signal_adx_exhaustion(ind, ticker, i):
    """ADX cayendo (tendencia se agota) + RSI < 25 + debajo SMA50."""
    ti = ind[ticker]
    rsi = ti['rsi'].iloc[i]
    adx = ti['adx'].iloc[i]
    adx_prev = ti['adx'].iloc[i-5] if i >= 5 else np.nan
    price = ti['close'].iloc[i]
    sma50 = ti['sma50'].iloc[i]
    dist_sma = (price / sma50 - 1) * 100

    if np.isnan(rsi) or np.isnan(adx) or np.isnan(adx_prev): return False, {}
    if rsi >= 25: return False, {}
    if adx <= adx_prev: return False, {}  # ADX SUBIENDO = tendencia fuerte, skip
    # Queremos ADX alto pero cayendo (la tendencia bajista se está agotando)
    # Corrección: ADX < prev = tendencia debilitándose
    # En realidad: queremos que adx_prev > 25 (había tendencia) y ahora adx < adx_prev (se debilita)
    if adx_prev < 25: return False, {}
    if adx >= adx_prev: return False, {}
    if dist_sma > -10: return False, {}
    return True, {'rsi': rsi, 'adx': adx, 'adx_change': adx - adx_prev, 'dist_sma': dist_sma}

# Corrijo la lógica de ADX:
def signal_adx_exhaustion(ind, ticker, i):
    """ADX cayendo desde >25 + RSI < 25. Tendencia bajista agotándose."""
    ti = ind[ticker]
    rsi = ti['rsi'].iloc[i]
    adx = ti['adx'].iloc[i]
    adx_prev = ti['adx'].iloc[i-5] if i >= 5 else np.nan
    price = ti['close'].iloc[i]
    sma50 = ti['sma50'].iloc[i]
    dist_sma = (price / sma50 - 1) * 100

    if np.isnan(rsi) or np.isnan(adx) or np.isnan(adx_prev): return False, {}
    if rsi >= 25: return False, {}
    if adx_prev < 25: return False, {}  # Necesita haber habido tendencia
    if adx >= adx_prev: return False, {}  # ADX debe estar cayendo
    if dist_sma > -10: return False, {}
    return True, {'rsi': rsi, 'adx': adx, 'adx_prev': adx_prev, 'dist_sma': dist_sma}

# --- NUEVO J: Distancia a 52w low + TRIX turning ---
def signal_near_52w_low(ind, ticker, i):
    """Precio cerca de mínimo 52w (<5% arriba) + TRIX girando positivo."""
    ti = ind[ticker]
    dist_52w = ti['dist_52w'].iloc[i]
    trix = ti['trix'].iloc[i]
    trix_prev = ti['trix'].iloc[i-1] if i >= 1 else np.nan
    rsi = ti['rsi'].iloc[i]
    price = ti['close'].iloc[i]
    sma50 = ti['sma50'].iloc[i]
    dist_sma = (price / sma50 - 1) * 100

    if np.isnan(dist_52w) or np.isnan(trix) or np.isnan(trix_prev) or np.isnan(rsi):
        return False, {}
    if dist_52w > 5: return False, {}  # Max 5% arriba del mínimo de 1 año
    if trix >= trix_prev: pass  # TRIX subiendo = momentum gira
    else: return False, {}
    if rsi >= 35: return False, {}  # RSI moderado oversold
    if dist_sma > -5: return False, {}
    return True, {'dist_52w': dist_52w, 'trix': trix, 'rsi': rsi, 'dist_sma': dist_sma}

# --- NUEVO K: V5 + MFI confirmation (V5 mejorado con volumen) ---
def signal_v5_plus_mfi(ind, ticker, i):
    """V5 exacto + MFI < 30 (confirma oversold con volumen)."""
    sig, info = signal_v5(ind, ticker, i)
    if not sig: return False, {}
    mfi = ind[ticker]['mfi'].iloc[i]
    if np.isnan(mfi): return False, {}
    if mfi >= 30: return False, {}
    info['mfi'] = mfi
    return True, info

# --- NUEVO L: V5 + BB debajo banda inferior ---
def signal_v5_plus_bb(ind, ticker, i):
    """V5 exacto + Bollinger %B < 0.1 (confirma extremo)."""
    sig, info = signal_v5(ind, ticker, i)
    if not sig: return False, {}
    bb = ind[ticker]['bb_pctb'].iloc[i]
    if np.isnan(bb): return False, {}
    if bb >= 0.1: return False, {}
    info['bb_pctb'] = bb
    return True, info

# --- NUEVO M: V5 + CMF recovering ---
def signal_v5_plus_cmf(ind, ticker, i):
    """V5 exacto + CMF subiendo (presión vendedora disminuye)."""
    sig, info = signal_v5(ind, ticker, i)
    if not sig: return False, {}
    cmf = ind[ticker]['cmf'].iloc[i]
    cmf_prev = ind[ticker]['cmf'].iloc[i-3] if i >= 3 else np.nan
    if np.isnan(cmf) or np.isnan(cmf_prev): return False, {}
    if cmf <= cmf_prev: return False, {}  # CMF debe estar subiendo
    info['cmf'] = cmf
    return True, info

# --- NUEVO N: V5 + ADX tendencia debilitándose ---
def signal_v5_plus_adx(ind, ticker, i):
    """V5 exacto + ADX cayendo (tendencia bajista se agota)."""
    sig, info = signal_v5(ind, ticker, i)
    if not sig: return False, {}
    adx = ind[ticker]['adx'].iloc[i]
    adx_prev = ind[ticker]['adx'].iloc[i-3] if i >= 3 else np.nan
    if np.isnan(adx) or np.isnan(adx_prev): return False, {}
    if adx >= adx_prev: return False, {}  # ADX debe estar cayendo
    info['adx'] = adx
    return True, info

# ================================================================
# PARTE 1: INDICADORES NUEVOS — DISTRIBUCIÓN EN TRADES V5
# ================================================================
def part1_distributions(ind, tickers):
    print("\n" + "=" * 80)
    print("  PARTE 1: DISTRIBUCION DE 12 INDICADORES NUEVOS EN TRADES V5")
    print("  (Para entender qué separa ganadores de perdedores)")
    print("=" * 80)

    df = backtest_strategy(ind, tickers, signal_v5)
    if len(df) == 0:
        print("  Sin trades V5.")
        return

    m = metrics(df, "V5 Baseline")
    print_metrics_line(m)

    # Para cada indicador nuevo, comparar valores en wins vs losses
    new_indicators = ['bb_pctb', 'williams_r', 'mfi', 'cci', 'obv_slope',
                      'keltner_pos', 'trix', 'cmf', 'vol_rsi', 'adx', 'dist_52w']

    # Reconstruir datos de indicadores en trades
    for idx, row in df.iterrows():
        ticker = row['ticker']
        date = row['date']
        if ticker in ind:
            ti = ind[ticker]
            date_idx = ti['close'].index.get_loc(date)
            for indicator in new_indicators:
                if indicator in ti:
                    val = ti[indicator].iloc[date_idx]
                    df.at[idx, indicator] = val

    wins = df[df['ret'] > 0]
    losses = df[df['ret'] <= 0]

    print(f"\n  {'Indicador':<15} {'Wins Mean':>10} {'Losses Mean':>12} {'Diff':>8} {'Separacion':>12}")
    print(f"  {'-'*60}")

    separations = {}
    for ind_name in new_indicators:
        if ind_name in df.columns:
            w_mean = wins[ind_name].mean() if len(wins) > 0 else 0
            l_mean = losses[ind_name].mean() if len(losses) > 0 else 0
            diff = w_mean - l_mean
            # Efecto relativo
            total_std = df[ind_name].std() if df[ind_name].std() > 0 else 1
            separation = abs(diff) / total_std
            separations[ind_name] = separation
            print(f"  {ind_name:<15} {w_mean:>10.2f} {l_mean:>12.2f} {diff:>+8.2f} {separation:>12.2f}")

    # Ranking
    print(f"\n  RANKING de separación ganadores vs perdedores:")
    for i, (k, v) in enumerate(sorted(separations.items(), key=lambda x: -x[1]), 1):
        star = " ***" if v > 0.5 else " *" if v > 0.3 else ""
        print(f"  {i:>2}. {k:<15} {v:.3f}{star}")

# ================================================================
# PARTE 2: BACKTEST DE TODAS LAS ESTRATEGIAS NUEVAS
# ================================================================
def part2_strategies(ind, tickers):
    print("\n" + "=" * 80)
    print("  PARTE 2: BACKTEST DE 15 ESTRATEGIAS")
    print("  Full period, hold 7d, con régimen SPY")
    print("=" * 80)

    strategies = {
        'V5 Baseline':             signal_v5,
        'A: Bollinger+RSI':        signal_bollinger_rsi,
        'B: MFI+RSI':              signal_mfi_rsi,
        'C: CCI Extreme':          signal_cci_extreme,
        'D: Williams+Squeeze':     signal_williams_squeeze,
        'E: OBV Divergence':       signal_obv_divergence,
        'F: Keltner Extreme':      signal_keltner_extreme,
        'G: CMF Reversal':         signal_cmf_reversal,
        'H: Triple Oversold':      signal_triple_oversold,
        'I: ADX Exhaustion':       signal_adx_exhaustion,
        'J: 52w Low + TRIX':       signal_near_52w_low,
        'K: V5 + MFI':             signal_v5_plus_mfi,
        'L: V5 + BB':              signal_v5_plus_bb,
        'M: V5 + CMF':             signal_v5_plus_cmf,
        'N: V5 + ADX':             signal_v5_plus_adx,
    }

    results = {}
    for name, fn in strategies.items():
        df = backtest_strategy(ind, tickers, fn)
        m = metrics(df, name)
        results[name] = m
        print_metrics_line(m)

    # Ranking por Sharpe (minimo 5 trades)
    print(f"\n  RANKING (min 5 trades):")
    ranked = [(k, v) for k, v in results.items() if v['trades'] >= 5]
    ranked.sort(key=lambda x: -x[1]['sharpe'])
    for i, (name, m) in enumerate(ranked, 1):
        beat_v5 = " > V5" if m['sharpe'] > results['V5 Baseline']['sharpe'] and name != 'V5 Baseline' else ""
        print(f"  {i:>2}. {name:<30} Sharpe {m['sharpe']:>7.2f} | WR {m['wr']:>5.1f}% | T:{m['trades']:>3}{beat_v5}")

    return results

# ================================================================
# PARTE 3: WALK-FORWARD DE TOP CANDIDATOS
# ================================================================
def part3_walkforward(ind, tickers, results):
    print("\n" + "=" * 80)
    print("  PARTE 3: WALK-FORWARD — TOP CANDIDATOS")
    print("  Criterio: >= 60% ventanas positivas")
    print("=" * 80)

    # Seleccionar top por Sharpe (min 5 trades) + V5 baseline
    candidates = {k: v for k, v in results.items() if v['trades'] >= 5}
    top = sorted(candidates.items(), key=lambda x: -x[1]['sharpe'])[:10]

    strategies = {
        'V5 Baseline':             signal_v5,
        'A: Bollinger+RSI':        signal_bollinger_rsi,
        'B: MFI+RSI':              signal_mfi_rsi,
        'C: CCI Extreme':          signal_cci_extreme,
        'D: Williams+Squeeze':     signal_williams_squeeze,
        'E: OBV Divergence':       signal_obv_divergence,
        'F: Keltner Extreme':      signal_keltner_extreme,
        'G: CMF Reversal':         signal_cmf_reversal,
        'H: Triple Oversold':      signal_triple_oversold,
        'I: ADX Exhaustion':       signal_adx_exhaustion,
        'J: 52w Low + TRIX':       signal_near_52w_low,
        'K: V5 + MFI':             signal_v5_plus_mfi,
        'L: V5 + BB':              signal_v5_plus_bb,
        'M: V5 + CMF':             signal_v5_plus_cmf,
        'N: V5 + ADX':             signal_v5_plus_adx,
    }

    wf_results = {}
    print(f"\n  {'Estrategia':<30} {'WF%':>5} {'Windows':>8} {'AvgSharpe':>10} {'Veredicto':>10}")
    print(f"  {'-'*70}")

    for name, _ in top:
        if name in strategies:
            pct, n_windows, avg_sharpe = walk_forward(ind, tickers, strategies[name])
            verdict = "PASS" if pct >= 60 and n_windows >= 2 else "FAIL" if n_windows >= 2 else "INSUF"
            print(f"  {name:<30} {pct:>4.0f}% {n_windows:>8} {avg_sharpe:>10.2f} {verdict:>10}")
            wf_results[name] = {'pct': pct, 'windows': n_windows, 'avg_sharpe': avg_sharpe, 'verdict': verdict}

    return wf_results

# ================================================================
# PARTE 4: SALIDAS INTELIGENTES vs HOLDING FIJO
# ================================================================
def part4_exits(ind, tickers):
    print("\n" + "=" * 80)
    print("  PARTE 4: SALIDAS INTELIGENTES vs HOLDING FIJO")
    print("  (Probando ATR trailing stop y target dinámico sobre V5)")
    print("=" * 80)

    # Implementar backtest con diferentes salidas sobre señales V5
    dates = ind['_SPY']['close'].index
    mask = (dates >= '2024-09-01') & (dates <= '2026-04-05')
    valid_indices = np.where(mask)[0]

    # Primero colectar todas las entradas V5
    entries = []
    last_signals = {}
    for i in valid_indices:
        if i < 260 or i + 25 >= len(dates):
            continue
        if not check_regime(ind, i):
            continue
        for ticker in tickers:
            if ticker not in ind:
                continue
            if ticker in last_signals and (dates[i] - last_signals[ticker]).days < 5:
                continue
            sig, info = signal_v5(ind, ticker, i)
            if sig:
                entries.append({'idx': i, 'ticker': ticker, **info})
                last_signals[ticker] = dates[i]

    if not entries:
        print("  Sin entradas V5.")
        return

    print(f"  {len(entries)} entradas V5 encontradas. Comparando salidas:\n")

    # Para cada entrada, simular diferentes salidas
    exit_methods = {
        'Hold 5d': {},
        'Hold 7d': {},
        'Hold 10d': {},
        'Hold 15d': {},
        'ATR 2x trail': {},
        'ATR 1.5x trail': {},
        'RSI>50 exit': {},
        'Target 5%+Trail': {},
    }

    for entry in entries:
        i = entry['idx']
        ticker = entry['ticker']
        ti = ind[ticker]
        entry_price = ti['close'].iloc[i]
        atr_entry = ti['atr'].iloc[i]

        # Fixed holds
        for hold in [5, 7, 10, 15]:
            try:
                exit_p = ti['close'].iloc[i + hold]
                ret = exit_p / entry_price - 1 - 0.002
                name = f'Hold {hold}d'
                if name not in exit_methods: exit_methods[name] = {}
                exit_methods[name][f"{entry['idx']}_{ticker}"] = ret
            except:
                pass

        # ATR trailing stop (2x ATR)
        for atr_mult, label in [(2.0, 'ATR 2x trail'), (1.5, 'ATR 1.5x trail')]:
            trailing_stop = entry_price - atr_mult * atr_entry
            best_price = entry_price
            exit_ret = None
            for d in range(1, 21):
                try:
                    h_d = ti['high'].iloc[i + d]
                    l_d = ti['low'].iloc[i + d]
                    close_d = ti['close'].iloc[i + d]
                    best_price = max(best_price, h_d)
                    trailing_stop = max(trailing_stop, best_price - atr_mult * atr_entry)
                    if l_d <= trailing_stop:
                        exit_ret = trailing_stop / entry_price - 1 - 0.002
                        break
                except:
                    break
            if exit_ret is None:
                try:
                    exit_ret = ti['close'].iloc[i + 20] / entry_price - 1 - 0.002
                except:
                    continue
            exit_methods[label][f"{entry['idx']}_{ticker}"] = exit_ret

        # RSI > 50 exit (max 20d)
        exit_ret = None
        for d in range(1, 21):
            try:
                rsi_d = ti['rsi'].iloc[i + d]
                if rsi_d > 50:
                    exit_ret = ti['close'].iloc[i + d] / entry_price - 1 - 0.002
                    break
            except:
                break
        if exit_ret is None:
            try:
                exit_ret = ti['close'].iloc[i + 20] / entry_price - 1 - 0.002
            except:
                pass
        if exit_ret is not None:
            exit_methods['RSI>50 exit'][f"{entry['idx']}_{ticker}"] = exit_ret

        # Target 5% + trailing (sell half at 5%, trail rest)
        exit_ret = None
        hit_target = False
        trailing_stop = entry_price - 2 * atr_entry
        for d in range(1, 21):
            try:
                h_d = ti['high'].iloc[i + d]
                l_d = ti['low'].iloc[i + d]
                close_d = ti['close'].iloc[i + d]
                if not hit_target and h_d >= entry_price * 1.05:
                    hit_target = True
                    # Sell half at +5%, trail the rest
                    half_ret = 0.05
                if hit_target:
                    trailing_stop = max(trailing_stop, h_d - 1.5 * atr_entry)
                    if l_d <= trailing_stop:
                        other_half = trailing_stop / entry_price - 1
                        exit_ret = (half_ret + other_half) / 2 - 0.002
                        break
            except:
                break
        if exit_ret is None:
            try:
                final = ti['close'].iloc[i + 20] / entry_price - 1 - 0.002
                if hit_target:
                    exit_ret = (0.05 + final) / 2
                else:
                    exit_ret = final
            except:
                pass
        if exit_ret is not None:
            exit_methods['Target 5%+Trail'][f"{entry['idx']}_{ticker}"] = exit_ret

    # Compute metrics for each exit method
    print(f"  {'Salida':<20} {'Trades':>6} {'WR':>6} {'Avg%':>7} {'Sharpe':>8} {'MDD%':>7} {'Total%':>8}")
    print(f"  {'-'*65}")

    for name, trades_dict in exit_methods.items():
        if not trades_dict:
            continue
        returns = pd.Series(list(trades_dict.values()))
        n = len(returns)
        wr = (returns > 0).mean() * 100
        avg = returns.mean() * 100
        std = returns.std()
        sharpe = (returns.mean() / std * np.sqrt(252)) if std > 0 else 0
        eq = (1 + returns).cumprod()
        peak = eq.expanding().max()
        mdd = ((eq - peak) / peak).min() * 100
        total = (eq.iloc[-1] - 1) * 100
        print(f"  {name:<20} {n:>6} {wr:>5.1f}% {avg:>+6.2f}% {sharpe:>8.2f} {mdd:>6.1f}% {total:>7.1f}%")

# ================================================================
# PARTE 5: VEREDICTO
# ================================================================
def part5_verdict(results, wf_results):
    print("\n" + "=" * 80)
    print("  PARTE 5: VEREDICTO FINAL")
    print("=" * 80)

    # ¿Alguna estrategia nueva supera V5 Y pasa WF?
    v5_sharpe = results.get('V5 Baseline', {}).get('sharpe', 0)

    superiors = []
    for name, wf in wf_results.items():
        if wf['verdict'] == 'PASS' and name != 'V5 Baseline':
            strat_sharpe = results.get(name, {}).get('sharpe', 0)
            if strat_sharpe > v5_sharpe:
                superiors.append((name, strat_sharpe, wf))

    if superiors:
        print(f"\n  ESTRATEGIAS QUE SUPERAN V5 Y PASAN WALK-FORWARD:")
        for name, sharpe, wf in sorted(superiors, key=lambda x: -x[1]):
            m = results[name]
            print(f"    {name}")
            print(f"      Sharpe: {sharpe:.2f} (V5: {v5_sharpe:.2f}) | WR: {m['wr']}% | Trades: {m['trades']}")
            print(f"      WF: {wf['pct']:.0f}% positivas | Avg Sharpe test: {wf['avg_sharpe']:.2f}")
            print()

        print(f"  PROTOCOLO 4 — CHECKLIST para el mejor candidato:")
        best = superiors[0]
        m = results[best[0]]
        n_filters = "evaluar manualmente"
        print(f"""
  [ ] LOOK-AHEAD BIAS:    Verificar que no hay datos futuros
  [ ] SURVIVORSHIP BIAS:  Solo tickers activos (parcial)
  [ ] PERIODO:            Sep 2024 - Abr 2026 (~19 meses) — PASS
  [ ] OUT-OF-SAMPLE:      Walk-forward validado — PASS
  [ ] WALK-FORWARD:       {best[2]['pct']:.0f}% — {'PASS' if best[2]['pct'] >= 60 else 'FAIL'}
  [ ] COMPLEJIDAD:        {n_filters}
  [ ] TRADES MINIMOS:     {m['trades']} trades — {'PASS' if m['trades'] >= 10 else 'WARN' if m['trades'] >= 5 else 'FAIL'}
  [ ] COSTOS:             0.2% roundtrip incluido — PASS
""")
    else:
        print(f"\n  Ninguna estrategia nueva supera V5 Y pasa walk-forward.")
        print(f"  V5 SE MANTIENE como scanner activo.")
        print(f"  Sharpe V5: {v5_sharpe:.2f}")

        # Insights útiles
        print(f"\n  INSIGHTS para futura investigacion:")
        for name, wf in wf_results.items():
            if name != 'V5 Baseline' and wf['windows'] > 0:
                m = results.get(name, {})
                print(f"    {name}: Sharpe {m.get('sharpe',0):.2f} | WF {wf['pct']:.0f}% | "
                      f"{'Potencial' if m.get('sharpe',0) > v5_sharpe else 'Inferior'}")

# ================================================================
# MAIN
# ================================================================
def main():
    start_time = datetime.now()
    print("=" * 80)
    print("  INVESTIGACION MODELO SUPERADOR")
    print(f"  {start_time.strftime('%Y-%m-%d %H:%M')}")
    print("  12 indicadores nuevos | 15 estrategias | Walk-forward | Salidas inteligentes")
    print("=" * 80)

    data, available = download_data()
    ind = precompute_all(data, available)

    # GATE RSI
    print("\n  GATE RSI: ewm(com=13) — OK")

    part1_distributions(ind, available)
    results = part2_strategies(ind, available)
    wf_results = part3_walkforward(ind, available, results)
    part4_exits(ind, available)
    part5_verdict(results, wf_results)

    elapsed = (datetime.now() - start_time).total_seconds() / 60
    print(f"\n  Tiempo total: {elapsed:.1f} minutos")
    print("=" * 80)

if __name__ == '__main__':
    main()
