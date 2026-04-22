"""
╔══════════════════════════════════════════════════════════════════════╗
║           MEGA BACKTEST 2026 - ANÁLISIS COMPLETO DE ESTRATEGIAS     ║
║                    Reconstrucción del Proyecto TITAN                 ║
╚══════════════════════════════════════════════════════════════════════╝

Compara TODAS las estrategias:
1. INVERTIR Original (RSI<30 + MACD up)
2. INVERTIR V2 (+ SMA50 filter + Volume filter + Scoring)
3. INVERTIR Final (V2 + SPY regime + anti-knife)
4. V37 NOVA Squeeze (7 features ML)
5. ML Brain v11 (9 features, 5-model ensemble)
6. ML v39 (44 features, 3-model ensemble)
7. ML v22/QUANT PRO (62+ features)
8. TITAN V97 (anomaly detection)
9. Dual System (INVERTIR + V37)

Períodos:
- In-Sample:  Jun 2025 - Mar 2026
- Out-Sample: Sep 2024 - Jun 2025
- Full:       Sep 2024 - Mar 2026
"""

import yfinance as yf
import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier, ExtraTreesClassifier
from sklearn.preprocessing import RobustScaler
from datetime import datetime, timedelta
import warnings
import sys
import os

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════
# UNIVERSO DE ACTIVOS
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
# DESCARGA DE DATOS
# ═══════════════════════════════════════════════════
def download_data(start='2024-06-01', end='2026-03-27'):
    """Descarga datos para todos los tickers + contexto"""
    print(f"\n📥 Descargando datos de {len(TICKERS)} activos + {len(CONTEXT_TICKERS)} contexto...")
    print(f"   Período: {start} → {end}")

    all_tickers = TICKERS + CONTEXT_TICKERS
    data = yf.download(all_tickers, start=start, end=end, progress=False, threads=True)

    if isinstance(data.columns, pd.MultiIndex):
        # Verificar qué tickers tienen datos
        available = []
        for t in TICKERS:
            try:
                close = data['Close'][t].dropna()
                if len(close) > 100:
                    available.append(t)
            except:
                pass
        print(f"   ✅ {len(available)} activos con datos suficientes")
        return data, available
    else:
        print("   ❌ Error en formato de datos")
        return None, []

# ═══════════════════════════════════════════════════
# INDICADORES TÉCNICOS
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
    macd_hist = macd - macd_signal
    return macd, macd_signal, macd_hist

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

def calc_stochastic(high, low, close, k_period=14, d_period=3):
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(d_period).mean()
    return k, d

# ═══════════════════════════════════════════════════
# ESTRATEGIA 1: INVERTIR ORIGINAL
# ═══════════════════════════════════════════════════
def strategy_invertir_original(data, ticker, date_idx):
    """RSI<30 + MACD histogram subiendo"""
    try:
        close = data['Close'][ticker]
        rsi = calc_rsi(close)
        _, _, macd_hist = calc_macd(close)

        rsi_val = rsi.iloc[date_idx]
        macd_now = macd_hist.iloc[date_idx]
        macd_prev = macd_hist.iloc[date_idx - 1]

        if rsi_val < 30 and macd_now > macd_prev:
            return True, {'rsi': rsi_val, 'macd_hist': macd_now}
    except:
        pass
    return False, {}

# ═══════════════════════════════════════════════════
# ESTRATEGIA 2: INVERTIR V2
# ═══════════════════════════════════════════════════
def strategy_invertir_v2(data, ticker, date_idx):
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

        if rsi_val < 30 and macd_now > macd_prev and dist_sma < -5 and vol_ratio < 1.5:
            # Scoring
            rsi_score = min(40, max(0, (30 - rsi_val) / 30 * 40))
            sma_score = min(30, max(0, abs(dist_sma) / 15 * 30))
            macd_accel = macd_now - macd_prev
            macd_score = min(20, max(0, macd_accel / 0.5 * 20))
            vol_score = min(10, max(0, (1.5 - vol_ratio) / 1.5 * 10))
            total_score = rsi_score + sma_score + macd_score + vol_score

            stop_loss = price - 2 * atr_val

            return True, {
                'rsi': rsi_val, 'dist_sma': dist_sma, 'vol_ratio': vol_ratio,
                'score': total_score, 'stop_loss': stop_loss, 'atr': atr_val
            }
    except:
        pass
    return False, {}

# ═══════════════════════════════════════════════════
# ESTRATEGIA 3: INVERTIR FINAL (V2 + regime + anti-knife)
# ═══════════════════════════════════════════════════
def strategy_invertir_final(data, ticker, date_idx, last_signals):
    """V2 + SPY>SMA50 + SPY vol<1% + anti-knife 5 days"""
    try:
        # Primero verificar regime SPY
        spy_close = data['Close']['SPY']
        spy_sma50 = spy_close.rolling(50).mean()
        spy_ret = spy_close.pct_change()
        spy_vol = spy_ret.rolling(20).std() * 100

        if spy_close.iloc[date_idx] < spy_sma50.iloc[date_idx]:
            return False, {}
        if spy_vol.iloc[date_idx] > 1.0:
            return False, {}

        # Anti-knife: no repetir ticker en 5 días
        current_date = data['Close'].index[date_idx]
        if ticker in last_signals:
            days_since = (current_date - last_signals[ticker]).days
            if days_since < 5:
                return False, {}

        # Señal base V2
        signal, info = strategy_invertir_v2(data, ticker, date_idx)
        return signal, info
    except:
        pass
    return False, {}

# ═══════════════════════════════════════════════════
# ESTRATEGIA 4: V37 NOVA SQUEEZE (ML)
# ═══════════════════════════════════════════════════
def build_v37_features(data, ticker):
    """Calcula las 7 features de PROJECT NOVA"""
    try:
        close = data['Close'][ticker]
        high = data['High'][ticker]
        low = data['Low'][ticker]
        volume = data['Volume'][ticker]
        opn = data['Open'][ticker]

        df = pd.DataFrame(index=close.index)

        # 1. Close strength
        day_range = high - low
        df['close_strength'] = np.where(day_range > 0, (close - low) / day_range, 0.5)

        # 2. BB squeeze rank
        _, _, _, bb_width, _ = calc_bollinger(close)
        df['bb_squeeze_rank'] = bb_width.rolling(60).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) >= 60 else 0.5,
            raw=False
        )

        # 3. Volume Z-score
        vol_mean = volume.rolling(20).mean()
        vol_std = volume.rolling(20).std()
        df['vol_zscore'] = np.where(vol_std > 0, (volume - vol_mean) / vol_std, 0)

        # 4. Gap open
        df['gap_open'] = (opn - close.shift(1)) / close.shift(1) * 100

        # 5. Intraday return
        df['intraday_return'] = (close - opn) / opn * 100

        # 6. RSI(3)
        df['rsi_3'] = calc_rsi(close, 3)

        # 7. Distance to 10d low
        low_10 = low.rolling(10).min()
        df['dist_10d_low'] = (close - low_10) / low_10 * 100

        # Target: >2.5% next day
        df['target'] = (close.shift(-1) / close - 1 >= 0.025).astype(int)
        df.loc[df.index[-1], 'target'] = np.nan

        # Forward return for backtest
        df['fwd_return_1d'] = close.shift(-1) / close - 1

        return df.dropna(subset=['close_strength','bb_squeeze_rank','vol_zscore','rsi_3'])
    except:
        return pd.DataFrame()

NOVA_FEATURES = ['close_strength','bb_squeeze_rank','vol_zscore','gap_open','intraday_return','rsi_3','dist_10d_low']

# ═══════════════════════════════════════════════════
# ESTRATEGIA 5: ML BRAIN v11 (9 features)
# ═══════════════════════════════════════════════════
def build_brain_features(data, ticker):
    """9 features del ML BRAIN"""
    try:
        close = data['Close'][ticker]
        high = data['High'][ticker]
        low = data['Low'][ticker]
        volume = data['Volume'][ticker]

        df = pd.DataFrame(index=close.index)

        # 1. RSI(14)
        df['rsi_14'] = calc_rsi(close, 14)

        # 2. BB position
        _, _, _, _, pct_b = calc_bollinger(close)
        df['bb_position'] = pct_b

        # 3-4. Distance to MA
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        df['dist_sma50'] = (close - sma50) / sma50 * 100
        df['dist_sma200'] = (close - sma200) / sma200 * 100

        # 5. Momentum 5d
        df['momentum_5d'] = close.pct_change(5) * 100

        # 6. Stochastic K
        k, _ = calc_stochastic(high, low, close)
        df['stoch_k'] = k

        # 7. ADX proxy (simplified)
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
        atr = calc_atr(high, low, close)
        plus_di = 100 * plus_dm.rolling(14).mean() / atr
        minus_di = 100 * minus_dm.rolling(14).mean() / atr
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).abs()
        df['adx'] = dx.rolling(14).mean()

        # 8. Volume relative
        df['vol_relative'] = volume / volume.rolling(20).mean()

        # 9. MACD histogram
        _, _, macd_hist = calc_macd(close)
        df['macd_hist'] = macd_hist

        # Target: >=3% in 5 days
        fwd_5d = close.shift(-5) / close - 1
        df['target'] = (fwd_5d >= 0.03).astype(int)
        df['fwd_return_1d'] = close.shift(-1) / close - 1
        df['fwd_return_5d'] = fwd_5d

        return df.dropna(subset=['rsi_14','bb_position','dist_sma50','adx'])
    except:
        return pd.DataFrame()

BRAIN_FEATURES = ['rsi_14','bb_position','dist_sma50','dist_sma200','momentum_5d','stoch_k','adx','vol_relative','macd_hist']

# ═══════════════════════════════════════════════════
# ESTRATEGIA 6: ML v39 (44 features simplified to ~20 core)
# ═══════════════════════════════════════════════════
def build_v39_features(data, ticker):
    """Core features from v39 multi-factor system"""
    try:
        close = data['Close'][ticker]
        high = data['High'][ticker]
        low = data['Low'][ticker]
        volume = data['Volume'][ticker]

        df = pd.DataFrame(index=close.index)

        # Momentum returns
        for p in [1, 3, 5, 10, 20]:
            df[f'ret_{p}d'] = close.pct_change(p) * 100

        # MA ratios
        for p in [5, 10, 20, 50]:
            ma = close.rolling(p).mean()
            df[f'ma{p}_ratio'] = close / ma - 1

        # RSI variants
        df['rsi_7'] = calc_rsi(close, 7)
        df['rsi_14'] = calc_rsi(close, 14)

        # MACD
        _, _, macd_hist = calc_macd(close)
        df['macd_hist'] = macd_hist

        # Bollinger
        _, _, _, bb_width, pct_b = calc_bollinger(close)
        df['bb_width'] = bb_width
        df['bb_pct_b'] = pct_b

        # Volatility
        df['vol_5d'] = close.pct_change().rolling(5).std() * 100
        df['vol_20d'] = close.pct_change().rolling(20).std() * 100
        df['vol_ratio'] = df['vol_5d'] / df['vol_20d']

        # Stochastic
        k, d = calc_stochastic(high, low, close)
        df['stoch_k'] = k
        df['stoch_d'] = d

        # Volume
        df['v_ratio'] = volume / volume.rolling(20).mean()

        # OBV simplified
        obv = (np.sign(close.diff()) * volume).cumsum()
        df['obv_slope'] = obv.pct_change(5) * 100

        # SPY context
        try:
            spy = data['Close']['SPY']
            spy_rsi = calc_rsi(spy, 14)
            df['spy_rsi'] = spy_rsi
            df['spy_trend'] = (spy / spy.rolling(50).mean() - 1) * 100
        except:
            df['spy_rsi'] = 50
            df['spy_trend'] = 0

        # Target
        df['target'] = (close.shift(-1) / close - 1 > close.pct_change().rolling(60).apply(lambda x: np.percentile(x.dropna(), 90), raw=False)).astype(int)
        df['fwd_return_1d'] = close.shift(-1) / close - 1

        return df.dropna(subset=['ret_1d','rsi_14','bb_width','vol_20d'])
    except:
        return pd.DataFrame()

V39_FEATURES = ['ret_1d','ret_3d','ret_5d','ret_10d','ret_20d',
                'ma5_ratio','ma10_ratio','ma20_ratio','ma50_ratio',
                'rsi_7','rsi_14','macd_hist','bb_width','bb_pct_b',
                'vol_5d','vol_20d','vol_ratio','stoch_k','stoch_d',
                'v_ratio','obv_slope','spy_rsi','spy_trend']

# ═══════════════════════════════════════════════════
# ESTRATEGIA 7: TITAN v97 (Anomaly/Surge)
# ═══════════════════════════════════════════════════
def build_v97_features(data, ticker):
    """8 features de TITAN-OMEGA"""
    try:
        close = data['Close'][ticker]
        high = data['High'][ticker]
        low = data['Low'][ticker]
        volume = data['Volume'][ticker]
        opn = data['Open'][ticker]

        df = pd.DataFrame(index=close.index)

        # C2H ratio (institutional strength)
        day_range = high - low
        df['c2h_ratio'] = np.where(day_range > 0, (close - low) / day_range, 0.5)

        # Volume Z-score
        vol_mean = volume.rolling(20).mean()
        vol_std = volume.rolling(20).std()
        df['vol_zscore'] = np.where(vol_std > 0, (volume - vol_mean) / vol_std, 0)

        # BB squeeze
        _, _, _, bb_width, _ = calc_bollinger(close)
        df['bb_squeeze'] = bb_width.rolling(60).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) >= 60 else 0.5,
            raw=False
        )

        # Acceleration (2nd derivative)
        ret = close.pct_change()
        df['acceleration'] = ret.diff() * 100

        # Parkinson volatility
        df['parkinson_vol'] = np.sqrt(1/(4*np.log(2)) * (np.log(high/low))**2).rolling(5).mean()

        # Gap
        df['gap_pct'] = (opn - close.shift(1)) / close.shift(1) * 100

        # RSI(3) momentum
        df['rsi_3'] = calc_rsi(close, 3)

        # Distance to high
        high_20 = high.rolling(20).max()
        df['dist_high'] = (close - high_20) / high_20 * 100

        # Target: >2.5% next day
        df['target'] = (close.shift(-1) / close - 1 >= 0.025).astype(int)
        df['fwd_return_1d'] = close.shift(-1) / close - 1

        return df.dropna(subset=['c2h_ratio','bb_squeeze','parkinson_vol'])
    except:
        return pd.DataFrame()

V97_FEATURES = ['c2h_ratio','vol_zscore','bb_squeeze','acceleration','parkinson_vol','gap_pct','rsi_3','dist_high']

# ═══════════════════════════════════════════════════
# MOTOR DE BACKTEST
# ═══════════════════════════════════════════════════
def backtest_rulebased(data, tickers, strategy_fn, start_date, end_date, hold_days=5, commission=0.001, **kwargs):
    """Backtest para estrategias rule-based (invertir, v2, final)"""
    dates = data['Close'].index
    mask = (dates >= start_date) & (dates <= end_date)
    valid_dates = dates[mask]

    trades = []
    last_signals = {}  # Para anti-knife

    for i in range(len(dates)):
        if dates[i] not in valid_dates.values:
            continue
        if i < 55 or i + hold_days >= len(dates):
            continue

        for ticker in tickers:
            try:
                if strategy_fn.__name__ == 'strategy_invertir_final':
                    signal, info = strategy_fn(data, ticker, i, last_signals)
                else:
                    signal, info = strategy_fn(data, ticker, i)

                if signal:
                    entry_price = data['Close'][ticker].iloc[i]

                    # Calcular returns a distintos horizontes
                    returns = {}
                    for h in [1, 3, 5, 10]:
                        if i + h < len(dates):
                            exit_price = data['Close'][ticker].iloc[i + h]
                            ret = (exit_price / entry_price - 1) - 2 * commission
                            returns[f'ret_{h}d'] = ret

                    # Stop loss check (para V2)
                    stopped = False
                    actual_ret = None
                    actual_days = hold_days
                    if 'stop_loss' in info and 'atr' in info:
                        stop = info['stop_loss']
                        tp = entry_price * 1.03  # Take profit 3%
                        for d in range(1, min(hold_days + 1, len(dates) - i)):
                            low_d = data['Low'][ticker].iloc[i + d]
                            high_d = data['High'][ticker].iloc[i + d]
                            close_d = data['Close'][ticker].iloc[i + d]
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

def backtest_ml_crosssectional(data, tickers, build_features_fn, feature_cols, start_date, end_date,
                                train_days=120, top_n=10, hold_days=1, commission=0.001):
    """Backtest cross-sectional para estrategias ML: entrena, rankea, selecciona top N cada día"""
    dates = data['Close'].index
    mask = (dates >= start_date) & (dates <= end_date)
    valid_dates = dates[mask]

    # Pre-compute features para todos los tickers
    print(f"   Calculando features para {len(tickers)} tickers...")
    all_features = {}
    for t in tickers:
        feats = build_features_fn(data, t)
        if len(feats) > 50:
            feats['ticker'] = t
            all_features[t] = feats

    if len(all_features) < 10:
        print(f"   ❌ Solo {len(all_features)} tickers con datos suficientes")
        return pd.DataFrame()

    print(f"   {len(all_features)} tickers listos. Backtesting {len(valid_dates)} días...")

    daily_results = []

    for day_i, current_date in enumerate(valid_dates):
        if day_i % 50 == 0 and day_i > 0:
            print(f"   ... día {day_i}/{len(valid_dates)}")

        idx_in_dates = dates.get_loc(current_date)
        if idx_in_dates < train_days + 10 or idx_in_dates + hold_days >= len(dates):
            continue

        # Construir dataset de entrenamiento (últimos train_days)
        train_start = dates[idx_in_dates - train_days]

        X_train_list, y_train_list = [], []
        X_pred = {}

        for t, feats in all_features.items():
            # Training data
            t_mask = (feats.index >= train_start) & (feats.index < current_date)
            t_data = feats.loc[t_mask]

            available_features = [f for f in feature_cols if f in t_data.columns]
            if len(available_features) < len(feature_cols) * 0.8:
                continue

            t_clean = t_data.dropna(subset=available_features + ['target'])
            if len(t_clean) > 10:
                X_train_list.append(t_clean[available_features].values)
                y_train_list.append(t_clean['target'].values)

            # Prediction data (today)
            if current_date in feats.index:
                row = feats.loc[current_date]
                if not row[available_features].isna().any():
                    X_pred[t] = row[available_features].values

        if len(X_train_list) < 5 or len(X_pred) < 5:
            continue

        X_train = np.vstack(X_train_list)
        y_train = np.concatenate(y_train_list)

        # Verificar que hay ambas clases
        if len(np.unique(y_train)) < 2:
            continue

        available_features = [f for f in feature_cols if f in list(all_features.values())[0].columns]

        try:
            # Entrenar modelo
            scaler = RobustScaler()
            X_train_scaled = scaler.fit_transform(X_train)

            model = HistGradientBoostingClassifier(
                max_iter=200, max_depth=5, learning_rate=0.05,
                l2_regularization=0.1, random_state=42
            )
            model.fit(X_train_scaled, y_train)

            # Predecir para todos los tickers
            predictions = {}
            for t, x in X_pred.items():
                x_scaled = scaler.transform(x.reshape(1, -1))
                prob = model.predict_proba(x_scaled)[0]
                predictions[t] = prob[1] if len(prob) > 1 else prob[0]

            # Rankear y seleccionar top N
            ranked = sorted(predictions.items(), key=lambda x: x[1], reverse=True)[:top_n]

            for t, prob in ranked:
                if prob < 0.5:  # Mínimo 50% confianza
                    continue
                try:
                    entry = data['Close'][t].iloc[idx_in_dates]
                    if idx_in_dates + hold_days < len(dates):
                        exit_p = data['Close'][t].iloc[idx_in_dates + hold_days]
                        ret = (exit_p / entry - 1) - 2 * commission

                        daily_results.append({
                            'date': current_date,
                            'ticker': t,
                            'probability': prob,
                            'entry_price': entry,
                            'exit_price': exit_p,
                            'ret_1d': ret if hold_days == 1 else None,
                            'actual_ret': ret,
                            'hold_days': hold_days,
                        })
                except:
                    continue
        except:
            continue

    return pd.DataFrame(daily_results)

# ═══════════════════════════════════════════════════
# ANÁLISIS DE RESULTADOS
# ═══════════════════════════════════════════════════
def analyze_results(trades_df, strategy_name, hold_col='actual_ret'):
    """Analisis completo de una estrategia"""
    if trades_df is None or len(trades_df) == 0:
        return {'name': strategy_name, 'trades': 0, 'error': 'Sin trades'}

    df = trades_df.dropna(subset=[hold_col])
    if len(df) == 0:
        return {'name': strategy_name, 'trades': 0, 'error': 'Sin returns'}

    returns = df[hold_col]
    wins = returns[returns > 0]
    losses = returns[returns <= 0]

    # Equity curve
    equity = (1 + returns).cumprod()
    peak = equity.expanding().max()
    drawdown = (equity - peak) / peak

    # Activos unicos
    n_activos = df['ticker'].nunique() if 'ticker' in df.columns else 0

    # Racha maxima de perdidas
    is_loss = (returns <= 0).astype(int)
    streaks = is_loss.groupby((is_loss != is_loss.shift()).cumsum()).sum()
    max_loss_streak = streaks.max() if len(streaks) > 0 else 0

    results = {
        'name': strategy_name,
        'trades': len(df),
        'n_wins': len(wins),
        'n_losses': len(losses),
        'win_rate': len(wins) / len(df) * 100,
        'loss_rate': len(losses) / len(df) * 100,
        'avg_return': returns.mean() * 100,
        'median_return': returns.median() * 100,
        'total_return': (equity.iloc[-1] - 1) * 100 if len(equity) > 0 else 0,
        'avg_win': wins.mean() * 100 if len(wins) > 0 else 0,
        'avg_loss': losses.mean() * 100 if len(losses) > 0 else 0,
        'max_drawdown': drawdown.min() * 100,
        'profit_factor': abs(wins.sum() / losses.sum()) if len(losses) > 0 and losses.sum() != 0 else float('inf'),
        'sharpe': returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0,
        'best_trade': returns.max() * 100,
        'worst_trade': returns.min() * 100,
        'std_return': returns.std() * 100,
        'n_activos': n_activos,
        'max_loss_streak': max_loss_streak,
        'total_loss_pct': (losses.sum() / (wins.sum() + abs(losses.sum())) * 100) if (wins.sum() + abs(losses.sum())) > 0 else 0,
        'expectancy': returns.mean() * 100,  # expectancy per trade
        'risk_reward': abs(wins.mean() / losses.mean()) if len(losses) > 0 and losses.mean() != 0 else float('inf'),
    }

    return results

def print_results(results_list):
    """Imprime tabla comparativa de resultados"""
    print("\n" + "=" * 155)
    print(f"{'ESTRATEGIA':<28} {'TRADES':>6} {'WINS':>5} {'LOSS':>5} {'WIN%':>6} {'LOSS%':>6} {'AVG%':>7} {'TOT%':>9} {'SHARPE':>7} {'MDD%':>7} {'PF':>6} "
          f"{'ACTIVOS':>7} {'R:R':>5} {'RACHA-':>6} {'BEST%':>7} {'WORST%':>7}")
    print("=" * 155)

    # Ordenar por sharpe
    sorted_results = sorted(results_list, key=lambda x: x.get('sharpe', -999), reverse=True)

    for r in sorted_results:
        if r.get('error'):
            print(f"  {r['name']:<26} {'ERROR':>6}  {r['error']}")
            continue
        pf = f"{r['profit_factor']:.1f}x" if r['profit_factor'] < 100 else "inf"
        rr = f"{r['risk_reward']:.1f}" if r['risk_reward'] < 100 else "inf"
        print(f"  {r['name']:<26} {r['trades']:>6} {r['n_wins']:>5} {r['n_losses']:>5} "
              f"{r['win_rate']:>5.1f}% {r['loss_rate']:>5.1f}% {r['avg_return']:>6.2f}% "
              f"{r['total_return']:>8.1f}% {r['sharpe']:>7.2f} {r['max_drawdown']:>6.1f}% {pf:>6} "
              f"{r['n_activos']:>7} {rr:>5} {r['max_loss_streak']:>6.0f} "
              f"{r['best_trade']:>6.2f}% {r['worst_trade']:>6.2f}%")

    print("=" * 155)

def deep_analysis(trades_df, strategy_name):
    """Análisis profundo de una estrategia"""
    if trades_df is None or len(trades_df) == 0:
        return

    df = trades_df.dropna(subset=['actual_ret'])
    if len(df) == 0:
        return

    print(f"\n{'─'*80}")
    print(f"  ANÁLISIS PROFUNDO: {strategy_name}")
    print(f"{'─'*80}")

    # Por ticker
    print(f"\n  TOP 10 Tickers (más trades):")
    ticker_stats = df.groupby('ticker').agg(
        trades=('actual_ret', 'count'),
        win_rate=('actual_ret', lambda x: (x > 0).mean() * 100),
        avg_ret=('actual_ret', lambda x: x.mean() * 100),
        total_ret=('actual_ret', lambda x: ((1+x).prod()-1)*100)
    ).sort_values('trades', ascending=False).head(10)

    for t, row in ticker_stats.iterrows():
        print(f"    {t:<8} Trades: {row['trades']:>3}  WR: {row['win_rate']:>5.1f}%  Avg: {row['avg_ret']:>6.2f}%  Total: {row['total_ret']:>7.2f}%")

    # Por mes
    if 'date' in df.columns:
        df['month'] = pd.to_datetime(df['date']).dt.to_period('M')
        print(f"\n  Rendimiento mensual:")
        monthly = df.groupby('month').agg(
            trades=('actual_ret', 'count'),
            win_rate=('actual_ret', lambda x: (x > 0).mean() * 100),
            avg_ret=('actual_ret', lambda x: x.mean() * 100),
            total_ret=('actual_ret', lambda x: ((1+x).prod()-1)*100)
        )
        for m, row in monthly.iterrows():
            bar = "█" * int(max(0, row['total_ret']))
            neg_bar = "░" * int(max(0, -row['total_ret']))
            print(f"    {str(m):<8} Trades: {row['trades']:>3}  WR: {row['win_rate']:>5.1f}%  Total: {row['total_ret']:>7.2f}% {bar}{neg_bar}")

    # RSI distribution (si existe)
    if 'rsi' in df.columns:
        print(f"\n  Distribución por RSI:")
        bins = [(0, 15), (15, 20), (20, 25), (25, 30)]
        for lo, hi in bins:
            subset = df[(df['rsi'] >= lo) & (df['rsi'] < hi)]
            if len(subset) > 0:
                wr = (subset['actual_ret'] > 0).mean() * 100
                avg = subset['actual_ret'].mean() * 100
                print(f"    RSI {lo:>2}-{hi:<2}: {len(subset):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%")

    # Score distribution (si existe)
    if 'score' in df.columns:
        print(f"\n  Distribución por Score:")
        bins = [(0, 25), (25, 50), (50, 75), (75, 100)]
        for lo, hi in bins:
            subset = df[(df['score'] >= lo) & (df['score'] < hi)]
            if len(subset) > 0:
                wr = (subset['actual_ret'] > 0).mean() * 100
                avg = subset['actual_ret'].mean() * 100
                print(f"    Score {lo:>2}-{hi:<2}: {len(subset):>3} trades  WR: {wr:>5.1f}%  Avg: {avg:>6.2f}%")

# ═══════════════════════════════════════════════════
# EJECUCIÓN PRINCIPAL
# ═══════════════════════════════════════════════════
def main():
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║        MEGA BACKTEST 2026 - PROYECTO TITAN RECARGADO       ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    # Descargar datos
    data, available_tickers = download_data('2024-06-01', '2026-03-27')
    if data is None:
        print("Error descargando datos")
        return

    # ═══════════════════════════════════════════════
    # PERÍODO IN-SAMPLE: Jun 2025 - Mar 2026
    # ═══════════════════════════════════════════════
    IS_START = '2025-06-01'
    IS_END = '2026-03-20'

    # PERÍODO OUT-OF-SAMPLE: Sep 2024 - Jun 2025
    OOS_START = '2024-09-01'
    OOS_END = '2025-05-31'

    for period_name, p_start, p_end in [("IN-SAMPLE (Jun25-Mar26)", IS_START, IS_END),
                                          ("OUT-OF-SAMPLE (Sep24-Jun25)", OOS_START, OOS_END)]:
        print(f"\n\n{'#'*80}")
        print(f"#  PERÍODO: {period_name}")
        print(f"{'#'*80}")

        all_results = []
        all_trades = {}

        # ── 1. INVERTIR ORIGINAL ──
        print(f"\n🔍 [1/7] INVERTIR Original (RSI<30 + MACD up)...")
        trades_orig = backtest_rulebased(data, available_tickers, strategy_invertir_original, p_start, p_end, hold_days=5)
        all_trades['INVERTIR Original'] = trades_orig

        for hold in [1, 3, 5, 10]:
            col = f'ret_{hold}d'
            if col in trades_orig.columns:
                r = analyze_results(trades_orig, f"INV Original ({hold}d)", hold_col=col)
                all_results.append(r)

        # ── 2. INVERTIR V2 ──
        print(f"🔍 [2/7] INVERTIR V2 (+ SMA50 + Vol filter + Scoring)...")
        trades_v2 = backtest_rulebased(data, available_tickers, strategy_invertir_v2, p_start, p_end, hold_days=10)
        all_trades['INVERTIR V2'] = trades_v2

        for hold in [1, 3, 5, 10]:
            col = f'ret_{hold}d'
            if col in trades_v2.columns:
                r = analyze_results(trades_v2, f"INV V2 ({hold}d)", hold_col=col)
                all_results.append(r)
        r = analyze_results(trades_v2, "INV V2 (SL/TP)", hold_col='actual_ret')
        all_results.append(r)

        # ── 3. INVERTIR FINAL ──
        print(f"🔍 [3/7] INVERTIR Final (V2 + Regime + Anti-knife)...")
        trades_final = backtest_rulebased(data, available_tickers, strategy_invertir_final, p_start, p_end, hold_days=10)
        all_trades['INVERTIR Final'] = trades_final

        r = analyze_results(trades_final, "INV Final (SL/TP)", hold_col='actual_ret')
        all_results.append(r)
        for hold in [5, 10]:
            col = f'ret_{hold}d'
            if col in trades_final.columns:
                r = analyze_results(trades_final, f"INV Final ({hold}d)", hold_col=col)
                all_results.append(r)

        # ── 4. V37 NOVA SQUEEZE (ML) ──
        print(f"🔍 [4/7] V37 NOVA Squeeze (7 features ML)...")
        trades_v37 = backtest_ml_crosssectional(
            data, available_tickers, build_v37_features, NOVA_FEATURES,
            p_start, p_end, train_days=120, top_n=5, hold_days=1
        )
        r = analyze_results(trades_v37, "V37 NOVA Squeeze (1d)", hold_col='actual_ret')
        all_results.append(r)
        all_trades['V37 NOVA'] = trades_v37

        # ── 5. ML BRAIN v11 (9 features) ──
        print(f"🔍 [5/7] ML BRAIN v11 (9 features, T+5)...")
        trades_brain = backtest_ml_crosssectional(
            data, available_tickers, build_brain_features, BRAIN_FEATURES,
            p_start, p_end, train_days=120, top_n=10, hold_days=5
        )
        r = analyze_results(trades_brain, "ML BRAIN v11 (5d)", hold_col='actual_ret')
        all_results.append(r)
        all_trades['ML BRAIN'] = trades_brain

        # ── 6. ML v39 (20+ features) ──
        print(f"🔍 [6/7] ML v39 Multi-Factor (20+ features)...")
        trades_v39 = backtest_ml_crosssectional(
            data, available_tickers, build_v39_features, V39_FEATURES,
            p_start, p_end, train_days=120, top_n=10, hold_days=1
        )
        r = analyze_results(trades_v39, "ML v39 MultiFactor (1d)", hold_col='actual_ret')
        all_results.append(r)
        all_trades['ML v39'] = trades_v39

        # ── 7. TITAN v97 (Anomaly) ──
        print(f"🔍 [7/7] TITAN v97 Anomaly (8 features)...")
        trades_v97 = backtest_ml_crosssectional(
            data, available_tickers, build_v97_features, V97_FEATURES,
            p_start, p_end, train_days=120, top_n=5, hold_days=1
        )
        r = analyze_results(trades_v97, "TITAN v97 Anomaly (1d)", hold_col='actual_ret')
        all_results.append(r)
        all_trades['TITAN v97'] = trades_v97

        # ── RESULTADOS ──
        print_results(all_results)

        # Deep analysis de las principales
        for name in ['INVERTIR Original', 'INVERTIR V2', 'INVERTIR Final']:
            if name in all_trades and len(all_trades[name]) > 0:
                deep_analysis(all_trades[name], name)

    # ═══════════════════════════════════════════════
    # ANÁLISIS CRUZADO Y CONCLUSIONES
    # ═══════════════════════════════════════════════
    print(f"\n\n{'#'*80}")
    print(f"#  ANÁLISIS CRUZADO: RULE-BASED vs ML")
    print(f"{'#'*80}")

    print("""

  ╔════════════════════════════════════════════════════════════════╗
  ║                    CONCLUSIONES DEL BACKTEST                  ║
  ╠════════════════════════════════════════════════════════════════╣
  ║                                                                ║
  ║  Los resultados se imprimen arriba. Compará:                   ║
  ║                                                                ║
  ║  1. Rule-based (INVERTIR Original/V2/Final) vs ML             ║
  ║  2. Simplicidad (2-4 filtros) vs Complejidad (20+ features)   ║
  ║  3. In-Sample vs Out-of-Sample (robustez)                     ║
  ║  4. Holding period óptimo (1d vs 5d vs 10d)                   ║
  ║  5. Efecto de filtros adicionales (SMA50, Volume, Regime)     ║
  ║                                                                ║
  ║  La hipótesis: INVERTIR V2 (4 filtros) > ML complejo          ║
  ║                                                                ║
  ╚════════════════════════════════════════════════════════════════╝
    """)

if __name__ == '__main__':
    main()
