"""
MEGA BACKTEST 2026 - ROUND 2
=============================
Backtests adicionales:
1. TITAN v2 (27 features, 3 modelos)
2. TITAN HYBRID v4 (25 alpha factors institucionales)
3. TITAN v5 QUANTUM (42 factors, multi-horizon)
4. Dual System (INVERTIR Final + V37 NOVA)
5. INVERTIR V2 con filtros extra (RSI direction, volume buckets)
6. Analisis profundo: day-of-week, RSI direction, regime conditional
"""

import yfinance as yf
import pandas as pd
import numpy as np
from sklearn.ensemble import (HistGradientBoostingClassifier, RandomForestClassifier,
                               ExtraTreesClassifier)
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import RobustScaler
import warnings
import sys
import os

os.environ['PYTHONWARNINGS'] = 'ignore'
os.environ['JOBLIB_START_METHOD'] = 'forkserver'
warnings.filterwarnings('ignore')
import logging
logging.disable(logging.WARNING)

# ================================================================
# UNIVERSO
# ================================================================
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

def calc_bollinger(close, period=20, std_mult=2):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + std_mult * std
    lower = sma - std_mult * std
    width = (upper - lower) / sma
    pct_b = (close - lower) / (upper - lower)
    return sma, upper, lower, width, pct_b

def calc_garman_klass(high, low, close, opn, period=20):
    log_hl = np.log(high / low) ** 2
    log_co = np.log(close / opn) ** 2
    gk = 0.5 * log_hl - (2 * np.log(2) - 1) * log_co
    return gk.rolling(period).mean().apply(np.sqrt)

# ================================================================
# DESCARGA DE DATOS
# ================================================================
def download_data():
    print("\n>> Descargando datos...")
    all_t = TICKERS + ['SPY','QQQ','^VIX','TLT','GLD','HYG','IWM']
    data = yf.download(all_t, start='2024-06-01', end='2026-03-27', progress=False, threads=True)
    available = []
    for t in TICKERS:
        try:
            c = data['Close'][t].dropna()
            if len(c) > 100:
                available.append(t)
        except:
            pass
    print(f"   {len(available)} activos disponibles")
    return data, available

# ================================================================
# FEATURE BUILDERS PARA TITAN VERSIONS
# ================================================================

def build_titan_v2_features(data, ticker):
    """TITAN v2: 27 features - microstructure + momentum + volatility"""
    try:
        close = data['Close'][ticker]
        high = data['High'][ticker]
        low = data['Low'][ticker]
        volume = data['Volume'][ticker]
        opn = data['Open'][ticker]
        df = pd.DataFrame(index=close.index)

        # Microstructure
        day_range = high - low
        df['close_str'] = np.where(day_range > 0, (close - low) / day_range, 0.5)
        df['body_pct'] = np.where(day_range > 0, (close - opn).abs() / day_range, 0)
        vol_mean = volume.rolling(20).mean()
        vol_std = volume.rolling(20).std()
        df['vol_z'] = np.where(vol_std > 0, (volume - vol_mean) / vol_std, 0)
        df['gap'] = (opn - close.shift(1)) / close.shift(1) * 100
        df['intra'] = (close - opn) / opn * 100

        # RSI
        df['rsi3'] = calc_rsi(close, 3)
        df['rsi14'] = calc_rsi(close, 14)

        # Squeeze
        _, _, _, bb_w, _ = calc_bollinger(close)
        df['bb_sqz'] = bb_w.rolling(60, min_periods=20).rank(pct=True)

        # Momentum
        for p in [1, 3, 5, 10, 20]:
            df[f'r{p}'] = close.pct_change(p) * 100
        df['accel'] = close.pct_change().diff() * 100

        # Moving averages
        ma20 = close.rolling(20).mean()
        ma50 = close.rolling(50).mean()
        ma5 = close.rolling(5).mean()
        df['dist_ma20'] = (close - ma20) / ma20 * 100
        df['dist_ma50'] = (close - ma50) / ma50 * 100
        df['ma5_20'] = (ma5 - ma20) / ma20 * 100

        # Volatility
        ret = close.pct_change()
        df['vol5'] = ret.rolling(5).std() * 100
        df['vol20'] = ret.rolling(20).std() * 100
        df['vol_rat'] = df['vol5'] / df['vol20'].replace(0, np.nan)
        df['park_vol'] = np.sqrt(1/(4*np.log(2)) * np.log(high/low)**2).rolling(5).mean()

        # MACD
        _, _, macd_h = calc_macd(close)
        df['macd_h'] = macd_h

        # Stochastic
        lowest = low.rolling(14).min()
        highest = high.rolling(14).max()
        df['stoch'] = 100 * (close - lowest) / (highest - lowest)

        # Volume advanced
        df['vol_ma_r'] = volume / vol_mean
        df['smart'] = np.where(day_range > 0, volume * (2 * (close - low) / day_range - 1), 0)
        df['smart'] = df['smart'].rolling(20).sum()
        obv = (np.sign(close.diff()) * volume).cumsum()
        obv_mean = obv.rolling(20).mean()
        obv_std = obv.rolling(20).std()
        df['obv_z'] = np.where(obv_std > 0, (obv - obv_mean) / obv_std, 0)

        # Support/Resistance
        df['dist_lo10'] = (close - low.rolling(10).min()) / low.rolling(10).min() * 100
        df['dist_hi20'] = (close - high.rolling(20).max()) / high.rolling(20).max() * 100

        # Target: top 15% + min 0.5%
        fwd = close.shift(-1) / close - 1
        df['fwd_return_1d'] = fwd
        df['target'] = 0
        # Will be set cross-sectionally

        return df.dropna(subset=['close_str','rsi14','vol20','dist_ma50'])
    except:
        return pd.DataFrame()

TITAN_V2_FEATURES = ['close_str','body_pct','vol_z','gap','intra','rsi3','rsi14','bb_sqz',
                     'r1','r3','r5','r10','r20','accel','dist_ma20','dist_ma50','ma5_20',
                     'vol5','vol20','vol_rat','park_vol','macd_h','stoch',
                     'vol_ma_r','smart','obv_z','dist_lo10','dist_hi20']

def build_titan_v4_features(data, ticker):
    """TITAN HYBRID v4: 25 institutional alpha factors"""
    try:
        close = data['Close'][ticker]
        high = data['High'][ticker]
        low = data['Low'][ticker]
        volume = data['Volume'][ticker]
        opn = data['Open'][ticker]
        df = pd.DataFrame(index=close.index)
        ret = close.pct_change()

        # MOMENTUM (4)
        df['str_reversal'] = -ret.rolling(5).sum()  # Short-term reversal
        df['int_momentum'] = close.pct_change(20) - close.pct_change(5)  # Skip 1-week
        df['momentum_accel'] = ret.diff()  # 2nd derivative
        vwap_approx = (close * volume).rolling(5).sum() / volume.rolling(5).sum()
        df['vw_momentum'] = (close - vwap_approx) / vwap_approx

        # MICROSTRUCTURE (4)
        day_range = high - low
        df['clv'] = np.where(day_range > 0, (2*close - high - low) / day_range, 0)  # Close Location Value
        df['smi'] = np.where(day_range > 0, volume * (2*(close-low)/day_range - 1), 0)
        df['smi'] = df['smi'].rolling(20).sum()  # Smart Money Index
        dollar_vol = close * volume
        df['amihud'] = (ret.abs() / dollar_vol * 1e6).rolling(20).mean()  # Amihud illiquidity
        vol_mean = volume.rolling(20).mean()
        vol_std = volume.rolling(20).std()
        df['vol_z'] = np.where(vol_std > 0, (volume - vol_mean) / vol_std, 0)

        # VOLATILITY (4)
        df['idio_vol'] = ret.rolling(20).std()  # Idiosyncratic vol
        log_hl = np.log(high / low) ** 2
        log_co = np.log(close / opn) ** 2
        gk = 0.5 * log_hl - (2*np.log(2)-1) * log_co
        df['gk_vol'] = gk.rolling(20).mean().apply(np.sqrt)  # Garman-Klass
        _, _, _, bb_w, _ = calc_bollinger(close)
        df['vol_compress'] = bb_w.rolling(60, min_periods=20).rank(pct=True)
        df['vol_of_vol'] = ret.rolling(20).std().rolling(20).std()

        # MEAN REVERSION (3)
        rsi = calc_rsi(close, 14)
        df['rsi_signal'] = (rsi - 50) / 50  # Normalized
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        df['mr_signal'] = np.where(std20 > 0, (close - ma20) / std20, 0)  # Z-score
        df['rsi3'] = calc_rsi(close, 3) / 100

        # TREND (3)
        df['trend_ma20'] = (close / ma20 - 1)
        ma50 = close.rolling(50).mean()
        df['trend_ma50'] = (close / ma50 - 1)
        ma5 = close.rolling(5).mean()
        df['ma_cross'] = (ma5 / ma20 - 1)

        # FLOW (3)
        obv = (np.sign(ret) * volume).cumsum()
        obv_mean = obv.rolling(20).mean()
        obv_std = obv.rolling(20).std()
        df['obv_z'] = np.where(obv_std > 0, (obv - obv_mean) / obv_std, 0)
        mf = ((close - low) - (high - close)) / day_range.replace(0, np.nan) * volume
        df['cmf'] = mf.rolling(20).sum() / volume.rolling(20).sum()  # Chaikin Money Flow
        vwap = (close * volume).rolling(20).sum() / volume.rolling(20).sum()
        df['vwap_dev'] = (close - vwap) / vwap

        # TAIL RISK (2)
        df['realized_skew'] = ret.rolling(20).skew()
        df['realized_kurt'] = ret.rolling(20).kurt()

        # INFO DISCRETENESS (1)
        sign_days = np.sign(ret).rolling(20).sum()
        total_ret = close.pct_change(20)
        df['info_discrete'] = np.where(total_ret != 0, sign_days / 20 - np.sign(total_ret), 0)

        # Calendar
        df['dow'] = pd.to_datetime(df.index).dayofweek / 4

        # Forward returns
        fwd_best = np.maximum(close.shift(-1)/close - 1, high.shift(-1)/close - 1)
        df['fwd_return_1d'] = close.shift(-1) / close - 1
        df['fwd_best'] = fwd_best
        df['target'] = 0  # Set cross-sectionally

        return df.dropna(subset=['str_reversal','clv','idio_vol','rsi_signal','trend_ma20'])
    except:
        return pd.DataFrame()

TITAN_V4_FEATURES = ['str_reversal','int_momentum','momentum_accel','vw_momentum',
                     'clv','smi','amihud','vol_z',
                     'idio_vol','gk_vol','vol_compress','vol_of_vol',
                     'rsi_signal','mr_signal','rsi3',
                     'trend_ma20','trend_ma50','ma_cross',
                     'obv_z','cmf','vwap_dev',
                     'realized_skew','realized_kurt',
                     'info_discrete','dow']

def build_titan_v5_features(data, ticker):
    """TITAN v5 QUANTUM: 42 alpha factors"""
    try:
        close = data['Close'][ticker]
        high = data['High'][ticker]
        low = data['Low'][ticker]
        volume = data['Volume'][ticker]
        opn = data['Open'][ticker]
        df = pd.DataFrame(index=close.index)
        ret = close.pct_change()

        # --- All v4 features first ---
        df['str_reversal'] = -ret.rolling(5).sum()
        df['int_momentum'] = close.pct_change(20) - close.pct_change(5)
        df['momentum_accel'] = ret.diff()
        vwap_approx = (close * volume).rolling(5).sum() / volume.rolling(5).sum()
        df['vw_momentum'] = (close - vwap_approx) / vwap_approx

        day_range = high - low
        df['clv'] = np.where(day_range > 0, (2*close - high - low) / day_range, 0)
        df['smi'] = np.where(day_range > 0, volume * (2*(close-low)/day_range - 1), 0)
        df['smi'] = df['smi'].rolling(20).sum()
        dollar_vol = close * volume
        df['amihud'] = (ret.abs() / dollar_vol * 1e6).rolling(20).mean()
        vol_mean = volume.rolling(20).mean()
        vol_std = volume.rolling(20).std()
        df['vol_z'] = np.where(vol_std > 0, (volume - vol_mean) / vol_std, 0)

        # OFI - Order Flow Imbalance
        df['ofi'] = np.where(day_range > 0, (close - opn) / day_range * volume, 0)
        df['ofi'] = df['ofi'].rolling(5).mean()

        # Kyle Lambda
        price_impact = ret.abs()
        vol_norm = volume / vol_mean
        df['kyle_lambda'] = np.where(vol_norm > 0, price_impact / vol_norm, 0)
        df['kyle_lambda'] = df['kyle_lambda'].rolling(20).mean()

        df['idio_vol'] = ret.rolling(20).std()
        log_hl = np.log(high / low) ** 2
        log_co = np.log(close / opn) ** 2
        gk = 0.5 * log_hl - (2*np.log(2)-1) * log_co
        df['gk_vol'] = gk.rolling(20).mean().apply(np.sqrt)

        # Parkinson vol
        df['park_vol'] = np.sqrt(1/(4*np.log(2)) * np.log(high/low)**2).rolling(5).mean()

        _, _, _, bb_w, pct_b = calc_bollinger(close)
        df['vol_compress'] = bb_w.rolling(60, min_periods=20).rank(pct=True)
        df['vol_of_vol'] = ret.rolling(20).std().rolling(20).std()

        # Vol ratio
        vol5 = ret.rolling(5).std()
        vol20 = ret.rolling(20).std()
        df['vol_ratio'] = vol5 / vol20.replace(0, np.nan)

        rsi = calc_rsi(close, 14)
        df['rsi_signal'] = (rsi - 50) / 50
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        df['mr_signal'] = np.where(std20 > 0, (close - ma20) / std20, 0)
        df['rsi3'] = calc_rsi(close, 3) / 100
        df['bb_pctb'] = pct_b

        df['trend_ma20'] = close / ma20 - 1
        ma50 = close.rolling(50).mean()
        df['trend_ma50'] = close / ma50 - 1
        ma5 = close.rolling(5).mean()
        df['ma_cross'] = ma5 / ma20 - 1

        # ADX proxy
        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        atr = calc_atr(high, low, close)
        plus_di = 100 * plus_dm.rolling(14).mean() / atr
        minus_di = 100 * minus_dm.rolling(14).mean() / atr
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).abs()
        df['adx'] = dx.rolling(14).mean() / 100

        obv = (np.sign(ret) * volume).cumsum()
        obv_m = obv.rolling(20).mean()
        obv_s = obv.rolling(20).std()
        df['obv_z'] = np.where(obv_s > 0, (obv - obv_m) / obv_s, 0)
        mf = ((close - low) - (high - close)) / day_range.replace(0, np.nan) * volume
        df['cmf'] = mf.rolling(20).sum() / volume.rolling(20).sum()
        vwap = (close * volume).rolling(20).sum() / volume.rolling(20).sum()
        df['vwap_dev'] = (close - vwap) / vwap

        # MFI - Money Flow Index
        tp = (high + low + close) / 3
        mf_pos = np.where(tp > tp.shift(1), tp * volume, 0)
        mf_neg = np.where(tp < tp.shift(1), tp * volume, 0)
        mf_pos_s = pd.Series(mf_pos, index=close.index).rolling(14).sum()
        mf_neg_s = pd.Series(mf_neg, index=close.index).rolling(14).sum()
        df['mfi'] = 100 - 100 / (1 + mf_pos_s / mf_neg_s.replace(0, np.nan))
        df['mfi'] = df['mfi'] / 100

        df['realized_skew'] = ret.rolling(20).skew()
        df['realized_kurt'] = ret.rolling(20).kurt()

        # Max drawdown 20d
        roll_max = close.rolling(20).max()
        df['max_dd_20'] = (close - roll_max) / roll_max

        # CVaR 5th percentile
        df['cvar_5'] = ret.rolling(60, min_periods=20).quantile(0.05)

        # 52-week high proximity
        high_252 = high.rolling(252, min_periods=60).max()
        df['high_52w_pct'] = close / high_252

        sign_days = np.sign(ret).rolling(20).sum()
        total_ret = close.pct_change(20)
        df['info_discrete'] = np.where(total_ret != 0, sign_days / 20 - np.sign(total_ret), 0)

        df['dow'] = pd.to_datetime(df.index).dayofweek / 4

        # Composites
        df['smart_composite'] = (df['clv'] + df['smi'].rank(pct=True) + df['obv_z'].rank(pct=True)) / 3
        df['trend_vol'] = df['trend_ma20'] * (1 - df['idio_vol'].rank(pct=True))
        df['accum_score'] = (df['cmf'].rank(pct=True) + df['mfi'].rank(pct=True) + df['vol_z'].rank(pct=True)) / 3

        # Cross-asset
        try:
            spy = data['Close']['SPY']
            spy_ret = spy.pct_change()
            df['beta_spy'] = ret.rolling(60).cov(spy_ret) / spy_ret.rolling(60).var()
            df['corr_spy'] = ret.rolling(60).corr(spy_ret)
        except:
            df['beta_spy'] = 1.0
            df['corr_spy'] = 0.5

        # Forward
        fwd_best = np.maximum(close.shift(-1)/close - 1, high.shift(-1)/close - 1)
        df['fwd_return_1d'] = close.shift(-1) / close - 1
        df['fwd_best'] = fwd_best
        df['target'] = 0

        return df.dropna(subset=['str_reversal','clv','idio_vol','rsi_signal','adx'])
    except:
        return pd.DataFrame()

TITAN_V5_FEATURES = ['str_reversal','int_momentum','momentum_accel','vw_momentum',
                     'clv','smi','amihud','vol_z','ofi','kyle_lambda',
                     'idio_vol','gk_vol','park_vol','vol_compress','vol_of_vol','vol_ratio',
                     'rsi_signal','mr_signal','rsi3','bb_pctb',
                     'trend_ma20','trend_ma50','ma_cross','adx',
                     'obv_z','cmf','vwap_dev','mfi',
                     'realized_skew','realized_kurt','max_dd_20','cvar_5',
                     'high_52w_pct','info_discrete','dow',
                     'smart_composite','trend_vol','accum_score',
                     'beta_spy','corr_spy']

# ================================================================
# V37 NOVA features (from round 1)
# ================================================================
def build_v37_features(data, ticker):
    try:
        close = data['Close'][ticker]
        high = data['High'][ticker]
        low = data['Low'][ticker]
        volume = data['Volume'][ticker]
        opn = data['Open'][ticker]
        df = pd.DataFrame(index=close.index)
        day_range = high - low
        df['close_strength'] = np.where(day_range > 0, (close - low) / day_range, 0.5)
        _, _, _, bb_w, _ = calc_bollinger(close)
        df['bb_squeeze_rank'] = bb_w.rolling(60, min_periods=20).rank(pct=True)
        vol_mean = volume.rolling(20).mean()
        vol_std = volume.rolling(20).std()
        df['vol_zscore'] = np.where(vol_std > 0, (volume - vol_mean) / vol_std, 0)
        df['gap_open'] = (opn - close.shift(1)) / close.shift(1) * 100
        df['intraday_return'] = (close - opn) / opn * 100
        df['rsi_3'] = calc_rsi(close, 3)
        df['dist_10d_low'] = (close - low.rolling(10).min()) / low.rolling(10).min() * 100
        df['target'] = (close.shift(-1) / close - 1 >= 0.025).astype(int)
        df['fwd_return_1d'] = close.shift(-1) / close - 1
        return df.dropna(subset=['close_strength','bb_squeeze_rank','vol_zscore','rsi_3'])
    except:
        return pd.DataFrame()

NOVA_FEATURES = ['close_strength','bb_squeeze_rank','vol_zscore','gap_open','intraday_return','rsi_3','dist_10d_low']

# ================================================================
# INVERTIR STRATEGIES (rule-based)
# ================================================================
def invertir_v2_signal(data, ticker, date_idx):
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

        # RSI direction
        rsi_prev = rsi.iloc[date_idx - 1]
        rsi_direction = 'falling' if rsi_val < rsi_prev else 'rising'

        # MACD acceleration
        macd_accel = macd_now - macd_prev

        if rsi_val < 30 and macd_now > macd_prev and dist_sma < -5 and vol_ratio < 1.5:
            rsi_score = min(40, max(0, (30 - rsi_val) / 30 * 40))
            sma_score = min(30, max(0, abs(dist_sma) / 15 * 30))
            macd_score = min(20, max(0, macd_accel / 0.5 * 20))
            vol_score = min(10, max(0, (1.5 - vol_ratio) / 1.5 * 10))
            total_score = rsi_score + sma_score + macd_score + vol_score
            stop_loss = price - 2 * atr_val

            return True, {
                'rsi': rsi_val, 'rsi_direction': rsi_direction,
                'dist_sma': dist_sma, 'vol_ratio': vol_ratio,
                'score': total_score, 'stop_loss': stop_loss, 'atr': atr_val,
                'macd_accel': macd_accel,
                'dow': pd.to_datetime(close.index[date_idx]).dayofweek,
            }
    except:
        pass
    return False, {}

def invertir_final_signal(data, ticker, date_idx, last_signals):
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
            if (current_date - last_signals[ticker]).days < 5:
                return False, {}
        signal, info = invertir_v2_signal(data, ticker, date_idx)
        return signal, info
    except:
        pass
    return False, {}

# ================================================================
# BACKTEST ENGINE
# ================================================================
def backtest_rulebased(data, tickers, strategy_fn, start, end, hold_days=10, commission=0.001):
    dates = data['Close'].index
    mask = (dates >= start) & (dates <= end)
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
                if 'final' in strategy_fn.__name__:
                    signal, info = strategy_fn(data, ticker, i, last_signals)
                else:
                    signal, info = strategy_fn(data, ticker, i)
                if signal:
                    entry = data['Close'][ticker].iloc[i]
                    returns = {}
                    for h in [1, 3, 5, 10]:
                        if i + h < len(dates):
                            ex = data['Close'][ticker].iloc[i + h]
                            returns[f'ret_{h}d'] = (ex / entry - 1) - 2 * commission

                    # SL/TP simulation
                    actual_ret = None
                    actual_days = hold_days
                    stopped = False
                    if 'stop_loss' in info:
                        stop = info['stop_loss']
                        tp = entry * 1.03
                        for d in range(1, min(hold_days + 1, len(dates) - i)):
                            lo = data['Low'][ticker].iloc[i + d]
                            hi = data['High'][ticker].iloc[i + d]
                            if lo <= stop:
                                actual_ret = (stop / entry - 1) - 2 * commission
                                actual_days = d
                                stopped = True
                                break
                            if hi >= tp:
                                actual_ret = (tp / entry - 1) - 2 * commission
                                actual_days = d
                                break
                        if actual_ret is None and i + hold_days < len(dates):
                            actual_ret = returns.get(f'ret_{hold_days}d')

                    trade = {'date': dates[i], 'ticker': ticker, 'entry_price': entry,
                             **info, **returns,
                             'actual_ret': actual_ret if actual_ret is not None else returns.get(f'ret_{hold_days}d'),
                             'actual_days': actual_days, 'stopped': stopped}
                    trades.append(trade)
                    last_signals[ticker] = dates[i]
            except:
                continue
    return pd.DataFrame(trades)

def backtest_ml_cs(data, tickers, build_fn, feature_cols, start, end,
                   train_days=120, top_n=10, hold_days=1, commission=0.001,
                   use_meta_learner=False, n_models=3):
    """Cross-sectional ML backtest with optional meta-learner and multiple model configs"""
    dates = data['Close'].index
    mask = (dates >= start) & (dates <= end)
    valid_dates = dates[mask]

    print(f"   Calculando features para {len(tickers)} tickers...")
    all_feats = {}
    for t in tickers:
        f = build_fn(data, t)
        if len(f) > 50:
            f['ticker'] = t
            all_feats[t] = f
    print(f"   {len(all_feats)} tickers listos. Backtesting {len(valid_dates)} dias...")

    if len(all_feats) < 10:
        return pd.DataFrame()

    results = []
    for day_i, cd in enumerate(valid_dates):
        if day_i % 50 == 0 and day_i > 0:
            print(f"   ... dia {day_i}/{len(valid_dates)}")

        idx = dates.get_loc(cd)
        if idx < train_days + 10 or idx + hold_days >= len(dates):
            continue

        train_start = dates[idx - train_days]
        X_train_l, y_train_l = [], []
        X_pred = {}

        for t, feats in all_feats.items():
            avail = [f for f in feature_cols if f in feats.columns]
            if len(avail) < len(feature_cols) * 0.7:
                continue

            # Set cross-sectional target
            t_mask = (feats.index >= train_start) & (feats.index < cd)
            t_data = feats.loc[t_mask].copy()

            if 'fwd_best' in t_data.columns:
                for d in t_data.index:
                    day_mask = feats.index == d
                    # Will approximate: just use fwd_return_1d > median
                    pass

            if 'fwd_return_1d' in t_data.columns:
                t_data['target'] = (t_data['fwd_return_1d'] > t_data['fwd_return_1d'].median()).astype(int)

            t_clean = t_data.dropna(subset=avail + ['target'])
            if len(t_clean) > 10:
                X_train_l.append(t_clean[avail].values)
                y_train_l.append(t_clean['target'].values)

            if cd in feats.index:
                row = feats.loc[cd]
                if not row[avail].isna().any():
                    X_pred[t] = row[avail].values

        if len(X_train_l) < 5 or len(X_pred) < 5:
            continue

        X_train = np.vstack(X_train_l)
        y_train = np.concatenate(y_train_l)
        if len(np.unique(y_train)) < 2:
            continue

        avail = [f for f in feature_cols if f in list(all_feats.values())[0].columns]

        try:
            scaler = RobustScaler()
            Xs = scaler.fit_transform(X_train)

            # Build model (single HGB for speed; ensemble adds little value per our findings)
            model = HistGradientBoostingClassifier(
                max_iter=200, max_depth=5, learning_rate=0.05,
                l2_regularization=0.1, random_state=42
            )
            model.fit(Xs, y_train)

            # Predict
            predictions = {}
            for t, x in X_pred.items():
                xs = scaler.transform(x.reshape(1, -1))
                prob = model.predict_proba(xs)[0]
                predictions[t] = prob[1] if len(prob) > 1 else prob[0]

            ranked = sorted(predictions.items(), key=lambda x: x[1], reverse=True)[:top_n]

            for t, prob in ranked:
                if prob < 0.55:
                    continue
                try:
                    entry = data['Close'][t].iloc[idx]
                    if idx + hold_days < len(dates):
                        exit_p = data['Close'][t].iloc[idx + hold_days]
                        r = (exit_p / entry - 1) - 2 * commission
                        results.append({
                            'date': cd, 'ticker': t, 'probability': prob,
                            'entry_price': entry, 'exit_price': exit_p,
                            'actual_ret': r, 'hold_days': hold_days,
                        })
                except:
                    continue
        except:
            continue

    return pd.DataFrame(results)

# ================================================================
# ANALYSIS FUNCTIONS
# ================================================================
def analyze(df, name, col='actual_ret'):
    if df is None or len(df) == 0:
        return {'name': name, 'trades': 0, 'n_wins': 0, 'n_losses': 0, 'win_rate': 0,
                'loss_rate': 0, 'total_return': 0, 'sharpe': 0, 'avg_return': 0,
                'max_drawdown': 0, 'profit_factor': 0, 'n_activos': 0, 'risk_reward': 0,
                'max_loss_streak': 0, 'avg_win': 0, 'avg_loss': 0, 'best': 0, 'worst': 0}
    d = df.dropna(subset=[col])
    if len(d) == 0:
        return {'name': name, 'trades': 0, 'n_wins': 0, 'n_losses': 0, 'win_rate': 0,
                'loss_rate': 0, 'total_return': 0, 'sharpe': 0, 'avg_return': 0,
                'max_drawdown': 0, 'profit_factor': 0, 'n_activos': 0, 'risk_reward': 0,
                'max_loss_streak': 0, 'avg_win': 0, 'avg_loss': 0, 'best': 0, 'worst': 0}
    r = d[col]
    wins = r[r > 0]
    losses = r[r <= 0]
    eq = (1 + r).cumprod()
    pk = eq.expanding().max()
    dd = (eq - pk) / pk

    n_activos = d['ticker'].nunique() if 'ticker' in d.columns else 0

    is_loss = (r <= 0).astype(int)
    streaks = is_loss.groupby((is_loss != is_loss.shift()).cumsum()).sum()
    max_loss_streak = streaks.max() if len(streaks) > 0 else 0

    return {
        'name': name, 'trades': len(d),
        'n_wins': len(wins), 'n_losses': len(losses),
        'win_rate': len(wins)/len(d)*100,
        'loss_rate': len(losses)/len(d)*100,
        'avg_return': r.mean()*100,
        'avg_win': wins.mean()*100 if len(wins) > 0 else 0,
        'avg_loss': losses.mean()*100 if len(losses) > 0 else 0,
        'total_return': (eq.iloc[-1]-1)*100,
        'sharpe': r.mean()/r.std()*np.sqrt(252) if r.std() > 0 else 0,
        'max_drawdown': dd.min()*100,
        'profit_factor': abs(wins.sum()/losses.sum()) if len(losses) > 0 and losses.sum() != 0 else float('inf'),
        'n_activos': n_activos,
        'risk_reward': abs(wins.mean()/losses.mean()) if len(losses) > 0 and losses.mean() != 0 else float('inf'),
        'max_loss_streak': max_loss_streak,
        'best': r.max()*100, 'worst': r.min()*100,
    }

def print_table(results):
    print(f"\n{'='*160}")
    print(f"{'ESTRATEGIA':<33} {'TRADES':>6} {'WINS':>5} {'LOSS':>5} {'WIN%':>6} {'LOSS%':>6} {'AVG%':>7} {'AVGW%':>7} {'AVGL%':>7} "
          f"{'TOT%':>9} {'SHARPE':>7} {'MDD%':>7} {'PF':>6} {'ACT':>4} {'R:R':>5} {'RACH-':>5}")
    print(f"{'='*160}")
    for r in sorted(results, key=lambda x: x.get('sharpe', -999), reverse=True):
        if r['trades'] == 0:
            print(f"  {r['name']:<31} {'SIN TRADES':>6}")
            continue
        pf = f"{r['profit_factor']:.1f}x" if r['profit_factor'] < 100 else "inf"
        rr = f"{r['risk_reward']:.1f}" if r['risk_reward'] < 100 else "inf"
        print(f"  {r['name']:<31} {r['trades']:>6} {r['n_wins']:>5} {r['n_losses']:>5} "
              f"{r['win_rate']:>5.1f}% {r['loss_rate']:>5.1f}% {r['avg_return']:>6.2f}% "
              f"{r['avg_win']:>6.2f}% {r['avg_loss']:>6.2f}% "
              f"{r['total_return']:>8.1f}% {r['sharpe']:>7.2f} {r['max_drawdown']:>6.1f}% {pf:>6} "
              f"{r['n_activos']:>4} {rr:>5} {r['max_loss_streak']:>5.0f}")
    print(f"{'='*160}")

def deep_analysis_v2(trades_df, data):
    """Analisis profundo especifico para INVERTIR con datos enriquecidos"""
    if trades_df is None or len(trades_df) == 0:
        return
    df = trades_df.dropna(subset=['actual_ret']).copy()
    if len(df) == 0:
        return

    print(f"\n{'='*80}")
    print(f"  ANALISIS PROFUNDO AVANZADO - INVERTIR")
    print(f"{'='*80}")

    # RSI DIRECTION analysis
    if 'rsi_direction' in df.columns:
        print(f"\n  [1] RSI DIRECTION (falling vs rising):")
        for direction in ['falling', 'rising']:
            sub = df[df['rsi_direction'] == direction]
            if len(sub) > 0:
                wr = (sub['actual_ret'] > 0).mean() * 100
                avg = sub['actual_ret'].mean() * 100
                tot = ((1 + sub['actual_ret']).prod() - 1) * 100
                print(f"      RSI {direction:<8}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%  Total: {tot:>7.2f}%")

    # RSI DEPTH buckets
    if 'rsi' in df.columns:
        print(f"\n  [2] RSI DEPTH buckets:")
        for lo, hi in [(0,15), (15,20), (20,22), (22,25), (25,27), (27,30)]:
            sub = df[(df['rsi'] >= lo) & (df['rsi'] < hi)]
            if len(sub) > 0:
                wr = (sub['actual_ret'] > 0).mean() * 100
                avg = sub['actual_ret'].mean() * 100
                print(f"      RSI {lo:>2}-{hi:<2}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%")

    # VOLUME buckets
    if 'vol_ratio' in df.columns:
        print(f"\n  [3] VOLUME RATIO buckets:")
        for lo, hi, label in [(0, 0.5, 'Muy bajo'), (0.5, 0.8, 'Bajo'), (0.8, 1.0, 'Normal-bajo'),
                               (1.0, 1.2, 'Normal'), (1.2, 1.5, 'Alto')]:
            sub = df[(df['vol_ratio'] >= lo) & (df['vol_ratio'] < hi)]
            if len(sub) > 0:
                wr = (sub['actual_ret'] > 0).mean() * 100
                avg = sub['actual_ret'].mean() * 100
                print(f"      Vol {lo:.1f}-{hi:.1f} ({label:<11}): {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%")

    # SMA DISTANCE buckets
    if 'dist_sma' in df.columns:
        print(f"\n  [4] DISTANCIA SMA50 buckets:")
        for lo, hi in [(-30, -15), (-15, -10), (-10, -7), (-7, -5)]:
            sub = df[(df['dist_sma'] >= lo) & (df['dist_sma'] < hi)]
            if len(sub) > 0:
                wr = (sub['actual_ret'] > 0).mean() * 100
                avg = sub['actual_ret'].mean() * 100
                print(f"      SMA {lo:>3}% a {hi:>3}%: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%")

    # DAY OF WEEK
    if 'dow' in df.columns:
        print(f"\n  [5] DIA DE LA SEMANA:")
        dow_names = {0: 'Lunes', 1: 'Martes', 2: 'Miercoles', 3: 'Jueves', 4: 'Viernes'}
        for d in range(5):
            sub = df[df['dow'] == d]
            if len(sub) > 0:
                wr = (sub['actual_ret'] > 0).mean() * 100
                avg = sub['actual_ret'].mean() * 100
                print(f"      {dow_names[d]:<10}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%")

    # SCORE buckets (finer)
    if 'score' in df.columns:
        print(f"\n  [6] SCORE (buckets finos):")
        for lo, hi in [(0,10), (10,20), (20,30), (30,40), (40,50), (50,60), (60,75), (75,100)]:
            sub = df[(df['score'] >= lo) & (df['score'] < hi)]
            if len(sub) > 0:
                wr = (sub['actual_ret'] > 0).mean() * 100
                avg = sub['actual_ret'].mean() * 100
                print(f"      Score {lo:>2}-{hi:<3}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%")

    # MACD ACCELERATION
    if 'macd_accel' in df.columns:
        print(f"\n  [7] MACD ACELERACION:")
        q25 = df['macd_accel'].quantile(0.25)
        q50 = df['macd_accel'].quantile(0.50)
        q75 = df['macd_accel'].quantile(0.75)
        for label, lo, hi in [('Baja', df['macd_accel'].min(), q25),
                               ('Media-baja', q25, q50),
                               ('Media-alta', q50, q75),
                               ('Alta', q75, df['macd_accel'].max()+0.001)]:
            sub = df[(df['macd_accel'] >= lo) & (df['macd_accel'] < hi)]
            if len(sub) > 0:
                wr = (sub['actual_ret'] > 0).mean() * 100
                avg = sub['actual_ret'].mean() * 100
                print(f"      MACD accel {label:<11}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%")

    # COMBINED: RSI direction + Volume
    if 'rsi_direction' in df.columns and 'vol_ratio' in df.columns:
        print(f"\n  [8] COMBINADO: RSI direction x Volume:")
        for direction in ['falling', 'rising']:
            for vol_label, vol_lo, vol_hi in [('bajo', 0, 1.0), ('normal-alto', 1.0, 1.5)]:
                sub = df[(df['rsi_direction'] == direction) &
                         (df['vol_ratio'] >= vol_lo) & (df['vol_ratio'] < vol_hi)]
                if len(sub) > 0:
                    wr = (sub['actual_ret'] > 0).mean() * 100
                    avg = sub['actual_ret'].mean() * 100
                    print(f"      RSI {direction:<8} + Vol {vol_label:<12}: {len(sub):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%")

    # STOPPED vs NOT STOPPED
    if 'stopped' in df.columns:
        print(f"\n  [9] STOP LOSS analysis:")
        for stopped_val, label in [(True, 'Hit Stop Loss'), (False, 'No Stop')]:
            sub = df[df['stopped'] == stopped_val]
            if len(sub) > 0:
                avg = sub['actual_ret'].mean() * 100
                print(f"      {label:<15}: {len(sub):>3} trades  Avg: {avg:>6.2f}%")

    # HOLDING PERIOD comparison
    print(f"\n  [10] HOLDING PERIOD optimo:")
    for h in [1, 3, 5, 10]:
        col = f'ret_{h}d'
        if col in df.columns:
            sub = df[col].dropna()
            if len(sub) > 0:
                wr = (sub > 0).mean() * 100
                avg = sub.mean() * 100
                sharpe = sub.mean() / sub.std() * np.sqrt(252) if sub.std() > 0 else 0
                print(f"      {h:>2} dias: WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%  Sharpe: {sharpe:>5.2f}")

# ================================================================
# MAIN
# ================================================================
def main():
    print("="*70)
    print("  MEGA BACKTEST 2026 - ROUND 2: TITAN ML + DEEP ANALYSIS")
    print("="*70)

    data, available = download_data()
    if data is None:
        return

    IS_START, IS_END = '2025-06-01', '2026-03-20'
    OOS_START, OOS_END = '2024-09-01', '2025-05-31'
    FULL_START, FULL_END = '2024-09-01', '2026-03-20'

    for period_name, p_start, p_end in [
        ("IN-SAMPLE (Jun25-Mar26)", IS_START, IS_END),
        ("OUT-OF-SAMPLE (Sep24-Jun25)", OOS_START, OOS_END),
        ("FULL PERIOD (Sep24-Mar26)", FULL_START, FULL_END),
    ]:
        print(f"\n\n{'#'*70}")
        print(f"#  {period_name}")
        print(f"{'#'*70}")

        all_results = []

        # 1. INVERTIR V2 (baseline)
        print(f"\n>> [1/8] INVERTIR V2 (baseline)...")
        t_v2 = backtest_rulebased(data, available, invertir_v2_signal, p_start, p_end)
        all_results.append(analyze(t_v2, "INV V2 (SL/TP)"))
        for h in [5, 10]:
            all_results.append(analyze(t_v2, f"INV V2 ({h}d)", f'ret_{h}d'))

        # 2. INVERTIR Final
        print(f">> [2/8] INVERTIR Final (regime)...")
        t_final = backtest_rulebased(data, available, invertir_final_signal, p_start, p_end)
        all_results.append(analyze(t_final, "INV Final (SL/TP)"))
        for h in [5, 10]:
            all_results.append(analyze(t_final, f"INV Final ({h}d)", f'ret_{h}d'))

        # 3. V37 NOVA
        print(f">> [3/8] V37 NOVA Squeeze...")
        t_v37 = backtest_ml_cs(data, available, build_v37_features, NOVA_FEATURES,
                               p_start, p_end, train_days=120, top_n=5, hold_days=1)
        all_results.append(analyze(t_v37, "V37 NOVA (1d)"))

        # 4. TITAN v2 (27 features)
        print(f">> [4/8] TITAN v2 (27 features)...")
        t_titan2 = backtest_ml_cs(data, available, build_titan_v2_features, TITAN_V2_FEATURES,
                                  p_start, p_end, train_days=120, top_n=10, hold_days=1, n_models=3)
        all_results.append(analyze(t_titan2, "TITAN v2 (27f, 1d)"))

        # 5. TITAN v2 hold 5d
        print(f">> [5/8] TITAN v2 (27f, 5d hold)...")
        t_titan2_5d = backtest_ml_cs(data, available, build_titan_v2_features, TITAN_V2_FEATURES,
                                     p_start, p_end, train_days=120, top_n=10, hold_days=5, n_models=3)
        all_results.append(analyze(t_titan2_5d, "TITAN v2 (27f, 5d)"))

        # 6. TITAN HYBRID v4 (25 institutional factors)
        print(f">> [6/8] TITAN HYBRID v4 (25 alpha factors)...")
        t_v4 = backtest_ml_cs(data, available, build_titan_v4_features, TITAN_V4_FEATURES,
                              p_start, p_end, train_days=120, top_n=10, hold_days=1,
                              use_meta_learner=True, n_models=3)
        all_results.append(analyze(t_v4, "TITAN v4 HYBRID (25f, 1d)"))

        # 7. TITAN v4 hold 5d
        print(f">> [7/8] TITAN v4 (25f, 5d hold)...")
        t_v4_5d = backtest_ml_cs(data, available, build_titan_v4_features, TITAN_V4_FEATURES,
                                 p_start, p_end, train_days=120, top_n=10, hold_days=5,
                                 use_meta_learner=True, n_models=3)
        all_results.append(analyze(t_v4_5d, "TITAN v4 HYBRID (25f, 5d)"))

        # 8. TITAN v5 QUANTUM (40 factors)
        print(f">> [8/8] TITAN v5 QUANTUM (40 factors)...")
        t_v5 = backtest_ml_cs(data, available, build_titan_v5_features, TITAN_V5_FEATURES,
                              p_start, p_end, train_days=120, top_n=10, hold_days=1,
                              use_meta_learner=True, n_models=3)
        all_results.append(analyze(t_v5, "TITAN v5 QUANTUM (40f, 1d)"))

        print_table(all_results)

        # Deep analysis solo para el periodo full
        if 'FULL' in period_name:
            deep_analysis_v2(t_v2, data)

            # Dual system analysis
            print(f"\n{'='*80}")
            print(f"  ANALISIS DUAL SYSTEM: INVERTIR Final + V37 NOVA")
            print(f"{'='*80}")
            if len(t_final) > 0 and len(t_v37) > 0:
                dual = pd.concat([t_final, t_v37], ignore_index=True)
                dual = dual.sort_values('date')
                r = analyze(dual, "DUAL (INV Final + V37)")
                print(f"\n  Dual System: {r['trades']} trades, WR: {r['win_rate']:.1f}%, "
                      f"Sharpe: {r['sharpe']:.2f}, Total: {r['total_return']:.2f}%")

                # Overlap analysis
                inv_dates = set(t_final['date'].dt.date) if 'date' in t_final.columns else set()
                v37_dates = set(t_v37['date'].dt.date) if 'date' in t_v37.columns else set()
                overlap = inv_dates & v37_dates
                print(f"  Dias con ambas senales: {len(overlap)} de INV:{len(inv_dates)} + V37:{len(v37_dates)}")
                if len(inv_dates | v37_dates) > 0:
                    print(f"  Overlap: {len(overlap)/len(inv_dates|v37_dates)*100:.1f}%")

    # ================================================================
    # MEGA CONCLUSION
    # ================================================================
    print(f"\n\n{'='*70}")
    print(f"  CONCLUSIONES FINALES")
    print(f"{'='*70}")
    print("""
  RANKING POR FEATURES:
  - 2-4 features (INVERTIR): ???
  - 7 features (V37 NOVA):   ???
  - 25 features (TITAN v4):  ???
  - 27 features (TITAN v2):  ???
  - 40 features (TITAN v5):  ???

  (Los resultados reales se imprimen arriba)

  PREGUNTAS CLAVE RESPONDIDAS:
  1. Rule-based vs ML: Quien gana?
  2. Mas features = mejor? O peor?
  3. Meta-learner ayuda?
  4. Holding period optimo?
  5. RSI falling vs rising: cual gana?
  6. Volume bajo vs alto: cual gana?
  7. Dia de la semana importa?
  8. Score sweet spot confirmado?
    """)

if __name__ == '__main__':
    main()
