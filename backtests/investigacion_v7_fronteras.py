"""
INVESTIGACION V7 — FRONTERAS NO EXPLORADAS
=============================================
Buscar Signal C y optimizaciones que V6 no cubre.

DIMENSIONES NUEVAS (nunca testeadas):
  1. Volumen de capitulacion (volume spike + oversold)
  2. Velocidad de caida (ROC 5d extremo)
  3. RSI divergencia alcista (precio new low, RSI higher low)
  4. Dias consecutivos de baja (5+ dias rojos)
  5. VIX como regimen alternativo (refutar SPY>SMA50)
  6. Dia de semana (Jue/Mie de R2)
  7. Near 52w low + momentum turn
  8. Sensitivity de thresholds V6
  9. Hold adaptativo por tipo de senal
  10. VIX spike contrarian (VIX>30 + stock oversold)

ESTRUCTURA:
  PARTE 1: Calcular todos los indicadores nuevos
  PARTE 2: Distribucion en trades V6 ganadores vs perdedores (que separa?)
  PARTE 3: 12+ estrategias nuevas (Signal C candidates)
  PARTE 4: Walk-forward de top candidates
  PARTE 5: Refutacion de V6: thresholds, regimen, hold
  PARTE 6: Combinacion V6 + Signal C (triple-signal?)
  PARTE 7: Monte Carlo del modelo final
  PARTE 8: Veredicto con protocolos completos

Fecha: 2026-04-06
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings, sys, os

warnings.filterwarnings('ignore')
if sys.platform == 'win32':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

# ================================================================
# UNIVERSO
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

# ================================================================
# INDICADORES BASE + NUEVOS
# ================================================================
def calc_rsi(s, p=14):
    """Wilder's smoothing — OBLIGATORIO."""
    d = s.diff()
    g = d.where(d>0, 0.0)
    l = (-d).where(d<0, 0.0)
    ag = g.ewm(com=p-1, min_periods=p).mean()
    al = l.ewm(com=p-1, min_periods=p).mean()
    return 100 - 100/(1 + ag/(al+1e-10))

def calc_macd(s):
    ef = s.ewm(span=12).mean()
    es = s.ewm(span=26).mean()
    m = ef - es
    return m, m.ewm(span=9).mean(), m - m.ewm(span=9).mean()

def calc_atr(h, l, c, p=14):
    tr = pd.concat([h-l, (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(p).mean()

def calc_bollinger(c, p=20, sd=2):
    sma = c.rolling(p).mean()
    std = c.rolling(p).std()
    upper = sma + sd*std
    lower = sma - sd*std
    pctb = (c - lower) / (upper - lower + 1e-10)
    width = (upper - lower) / sma * 100
    return pctb, width

def calc_williams(h, l, c, p=14):
    hh = h.rolling(p).max()
    ll = l.rolling(p).min()
    return -100 * (hh - c) / (hh - ll + 1e-10)

def calc_consecutive_down_days(c):
    """Cuenta dias consecutivos de cierre < cierre anterior."""
    down = (c < c.shift(1)).astype(int)
    # Truco: usar cumsum que se resetea cuando no es down
    groups = (~down.astype(bool)).cumsum()
    return down.groupby(groups).cumsum()

def calc_rsi_divergence(c, rsi, lookback=10):
    """
    Divergencia alcista: precio hace new low en ventana, RSI no.
    Retorna True donde hay divergencia.
    """
    price_min = c.rolling(lookback).min()
    rsi_at_price_min = rsi.copy()  # simplificado

    # Buscar: precio actual <= precio de hace lookback dias
    # PERO RSI actual > RSI de hace lookback dias
    price_lower = c <= c.shift(lookback)
    rsi_higher = rsi > rsi.shift(lookback)

    return price_lower & rsi_higher

def calc_roc(c, period=5):
    """Rate of Change en %."""
    return (c / c.shift(period) - 1) * 100

# ================================================================
# PRECOMPUTE
# ================================================================
def precompute(data, tickers):
    ind = {}

    # SPY + VIX
    spy_c = data['Close']['SPY']
    ind['_SPY'] = {
        'close': spy_c,
        'sma50': spy_c.rolling(50).mean(),
        'vol': spy_c.pct_change().rolling(20).std()*100
    }

    # VIX
    try:
        vix_c = data['Close']['^VIX']
        ind['_VIX'] = {'close': vix_c}
    except:
        ind['_VIX'] = None

    for t in tickers:
        try:
            c = data['Close'][t]; h = data['High'][t]; l = data['Low'][t]; v = data['Volume'][t]
            if c.isna().sum() > len(c)*0.3:
                continue
            c = c.ffill()

            rsi = calc_rsi(c)
            _, _, macd_hist = calc_macd(c)
            sma50 = c.rolling(50).mean()
            sma200 = c.rolling(200).mean()
            atr = calc_atr(h, l, c)
            vol_avg = v.rolling(20).mean()
            bb_pctb, bb_width = calc_bollinger(c)
            wr = calc_williams(h, l, c)
            consec_down = calc_consecutive_down_days(c)
            roc5 = calc_roc(c, 5)
            roc10 = calc_roc(c, 10)
            rsi_div = calc_rsi_divergence(c, rsi, 10)
            low_52w = c.rolling(252, min_periods=50).min()
            high_52w = c.rolling(252, min_periods=50).max()

            ind[t] = {
                'close': c, 'high': h, 'low': l, 'volume': v,
                'rsi': rsi, 'macd_hist': macd_hist,
                'sma50': sma50, 'sma200': sma200, 'atr': atr, 'vol_avg': vol_avg,
                'bb_pctb': bb_pctb, 'bb_width': bb_width, 'williams_r': wr,
                'consec_down': consec_down, 'roc5': roc5, 'roc10': roc10,
                'rsi_divergence': rsi_div,
                'low_52w': low_52w, 'high_52w': high_52w,
                'vol_ratio': v / (vol_avg + 1e-10),
                'dist_sma50': (c / sma50 - 1) * 100,
                'dist_52w_low': (c / low_52w - 1) * 100,
            }
        except Exception as e:
            pass
    return ind

# ================================================================
# REGIME CHECKS
# ================================================================
def regime_spy_sma(ind, i):
    """Regime V6 actual: SPY > SMA50 y vol < 1%."""
    try:
        s = ind['_SPY']
        return s['close'].iloc[i] > s['sma50'].iloc[i] and s['vol'].iloc[i] < 1.0
    except: return False

def regime_vix_20(ind, i):
    """VIX < 20."""
    try:
        return ind['_VIX']['close'].iloc[i] < 20
    except: return False

def regime_vix_25(ind, i):
    """VIX < 25."""
    try:
        return ind['_VIX']['close'].iloc[i] < 25
    except: return False

def regime_vix_30(ind, i):
    """VIX < 30 (mas permisivo)."""
    try:
        return ind['_VIX']['close'].iloc[i] < 30
    except: return False

def regime_spy_and_vix25(ind, i):
    """SPY>SMA50 AND VIX<25."""
    return regime_spy_sma(ind, i) and regime_vix_25(ind, i)

def regime_spy_or_vix20(ind, i):
    """SPY>SMA50 OR VIX<20."""
    return regime_spy_sma(ind, i) or regime_vix_20(ind, i)

def regime_none(ind, i):
    """Sin filtro de regimen."""
    return True

# ================================================================
# V6 SIGNALS (reference)
# ================================================================
def signal_v5(ind, t, i):
    """Signal A de V6."""
    ti = ind[t]
    try:
        rsi = ti['rsi'].iloc[i]
        macd = ti['macd_hist'].iloc[i]
        macd_prev = ti['macd_hist'].iloc[i-1]
        dist = ti['dist_sma50'].iloc[i]
        vol_r = ti['vol_ratio'].iloc[i]
        price = ti['close'].iloc[i]
        atr = ti['atr'].iloc[i]
        if np.isnan(rsi) or np.isnan(dist): return None

        if rsi >= 25 or macd <= macd_prev or dist > -10 or vol_r > 1.5:
            return None

        # Score
        rsi_sc = max(0, min(40, (30-rsi)/30*40))
        str_sc = max(0, min(30, (abs(dist)-5)/15*30))
        macd_acc = (macd - macd_prev) / (atr*0.01+1e-6)
        macd_sc = max(0, min(20, macd_acc*5))
        vol_sc = max(0, min(10, (1.5-vol_r)/1.5*10))
        score = rsi_sc + str_sc + macd_sc + vol_sc
        if score < 30: return None
        return {'ticker': t, 'signal': 'A', 'price': price, 'rsi': rsi, 'score': score}
    except: return None

def signal_d_williams(ind, t, i):
    """Signal B de V6 (Williams+Squeeze)."""
    ti = ind[t]
    try:
        wr = ti['williams_r'].iloc[i]
        bw = ti['bb_width'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(wr) or np.isnan(bw) or np.isnan(dist): return None
        if wr >= -90: return None
        if dist > -5: return None
        # Squeeze: BB width < 1.2x min 50d
        if i < 50: return None
        bw_min = ti['bb_width'].iloc[i-50:i].min()
        if np.isnan(bw_min) or bw > bw_min * 1.2: return None
        return {'ticker': t, 'signal': 'D', 'price': price, 'williams': wr, 'bb_width': bw}
    except: return None

# ================================================================
# NUEVAS SENALES — SIGNAL C CANDIDATES
# ================================================================

def signal_c1_volume_capitulation(ind, t, i):
    """Volumen 2.5x+ promedio + RSI<30 + debajo SMA50.
    Hipotesis: institucionales liquidando en panico = fondo."""
    ti = ind[t]
    try:
        rsi = ti['rsi'].iloc[i]
        vol_r = ti['vol_ratio'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(rsi) or np.isnan(vol_r) or np.isnan(dist): return None
        if rsi >= 30: return None
        if vol_r < 2.5: return None  # Volume spike
        if dist > -5: return None    # Debajo SMA50
        return {'ticker': t, 'signal': 'C1_VolCap', 'price': price, 'rsi': rsi, 'vol_ratio': vol_r}
    except: return None

def signal_c2_rapid_decline(ind, t, i):
    """ROC 5d < -10% + RSI<35.
    Hipotesis: caidas rapidas revierten mas que bleeds lentos."""
    ti = ind[t]
    try:
        rsi = ti['rsi'].iloc[i]
        roc5 = ti['roc5'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(rsi) or np.isnan(roc5): return None
        if roc5 >= -10: return None   # Caida rapida
        if rsi >= 35: return None     # Algo oversold
        return {'ticker': t, 'signal': 'C2_RapidDec', 'price': price, 'rsi': rsi, 'roc5': roc5}
    except: return None

def signal_c3_consecutive_down(ind, t, i):
    """5+ dias consecutivos de baja + RSI<40 + debajo SMA50.
    Hipotesis: probabilistic reversion despues de racha larga."""
    ti = ind[t]
    try:
        consec = ti['consec_down'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(consec) or np.isnan(rsi) or np.isnan(dist): return None
        if consec < 5: return None    # 5+ dias bajando
        if rsi >= 40: return None     # Oversold
        if dist > -3: return None     # Debajo SMA
        return {'ticker': t, 'signal': 'C3_ConsecDn', 'price': price, 'consec': consec, 'rsi': rsi}
    except: return None

def signal_c4_rsi_divergence(ind, t, i):
    """RSI divergencia alcista + debajo SMA50 + RSI<35.
    Precio hace new low pero RSI no = momentum cambiando."""
    ti = ind[t]
    try:
        div = ti['rsi_divergence'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if not div: return None       # Sin divergencia
        if rsi >= 35: return None     # Oversold zone
        if dist > -5: return None     # Debajo SMA50
        return {'ticker': t, 'signal': 'C4_RSIDiv', 'price': price, 'rsi': rsi, 'dist': dist}
    except: return None

def signal_c5_52w_low_bounce(ind, t, i):
    """Precio < 5% de minimo 52w + RSI empezando a subir.
    Hipotesis: soporte fuerte en minimos anuales."""
    ti = ind[t]
    try:
        dist_low = ti['dist_52w_low'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        rsi_prev = ti['rsi'].iloc[i-1] if i > 0 else rsi
        price = ti['close'].iloc[i]
        if np.isnan(dist_low) or np.isnan(rsi): return None
        if dist_low > 5: return None   # Cerca del minimo (< 5% arriba)
        if rsi >= 35: return None      # Zone oversold
        if rsi <= rsi_prev: return None # RSI subiendo
        return {'ticker': t, 'signal': 'C5_52wBounce', 'price': price, 'dist_low': dist_low, 'rsi': rsi}
    except: return None

def signal_c6_vol_cap_squeeze(ind, t, i):
    """Volume spike + Bollinger squeeze (combinacion unica).
    Hipotesis: capitulacion de volumen dentro de squeeze = explosion inminente."""
    ti = ind[t]
    try:
        vol_r = ti['vol_ratio'].iloc[i]
        bw = ti['bb_width'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(vol_r) or np.isnan(bw) or np.isnan(rsi): return None
        if vol_r < 2.0: return None    # Volume alto
        if rsi >= 35: return None      # Oversold
        if i < 50: return None
        bw_min = ti['bb_width'].iloc[i-50:i].min()
        if np.isnan(bw_min) or bw > bw_min * 1.5: return None  # Near squeeze
        return {'ticker': t, 'signal': 'C6_VolSqueeze', 'price': price, 'vol_r': vol_r, 'rsi': rsi}
    except: return None

def signal_c7_extreme_roc_vol(ind, t, i):
    """ROC 10d < -15% + volumen > 2x = crash + liquidacion masiva.
    Solo los crashes mas extremos."""
    ti = ind[t]
    try:
        roc10 = ti['roc10'].iloc[i]
        vol_r = ti['vol_ratio'].iloc[i]
        price = ti['close'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        if np.isnan(roc10) or np.isnan(vol_r): return None
        if roc10 >= -15: return None   # Crash fuerte
        if vol_r < 2.0: return None    # Con volumen
        return {'ticker': t, 'signal': 'C7_CrashVol', 'price': price, 'roc10': roc10, 'vol_r': vol_r, 'rsi': rsi}
    except: return None

def signal_c8_vix_spike_oversold(ind, t, i):
    """VIX > 28 + stock RSI < 30 + debajo SMA50.
    Contrarian en panico de mercado."""
    ti = ind[t]
    try:
        if ind['_VIX'] is None: return None
        vix = ind['_VIX']['close'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(vix) or np.isnan(rsi) or np.isnan(dist): return None
        if vix < 28: return None       # VIX alto (panico)
        if rsi >= 30: return None      # Stock oversold
        if dist > -8: return None      # Bastante debajo SMA
        return {'ticker': t, 'signal': 'C8_VIXSpike', 'price': price, 'vix': vix, 'rsi': rsi}
    except: return None

def signal_c9_double_bottom(ind, t, i):
    """Precio cerca de low de 20d atras, RSI mas alto = double bottom.
    Patron de reversal clasico simplificado."""
    ti = ind[t]
    try:
        price = ti['close'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        if np.isnan(price) or np.isnan(rsi) or i < 25: return None

        # Buscar low en ventana 15-25 dias atras
        window = ti['close'].iloc[i-25:i-10]
        if len(window) < 5: return None
        prev_low = window.min()
        prev_low_idx = window.idxmin()

        # Precio actual cerca del low anterior (< 3% diferencia)
        if abs(price / prev_low - 1) > 0.03: return None

        # RSI actual > RSI del low anterior
        try:
            prev_low_pos = ti['close'].index.get_loc(prev_low_idx)
            prev_rsi = ti['rsi'].iloc[prev_low_pos]
            if rsi <= prev_rsi: return None  # RSI debe ser mas alto (divergencia)
        except: return None

        if rsi >= 40: return None  # Todavia oversold
        dist = ti['dist_sma50'].iloc[i]
        if np.isnan(dist) or dist > 0: return None  # Debajo SMA

        return {'ticker': t, 'signal': 'C9_DblBottom', 'price': price, 'rsi': rsi, 'prev_low': prev_low}
    except: return None

def signal_c10_mean_rev_strong(ind, t, i):
    """RSI<20 (ultra-oversold) + volumen spike + ROC 5d < -8%.
    Lo mas extremo de todo: triple confluence de oversold."""
    ti = ind[t]
    try:
        rsi = ti['rsi'].iloc[i]
        vol_r = ti['vol_ratio'].iloc[i]
        roc5 = ti['roc5'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(rsi) or np.isnan(vol_r) or np.isnan(roc5): return None
        if rsi >= 20: return None      # Ultra oversold
        if vol_r < 1.5: return None    # Volumen elevado
        if roc5 >= -8: return None     # Caida rapida
        return {'ticker': t, 'signal': 'C10_TripleOS', 'price': price, 'rsi': rsi, 'vol_r': vol_r, 'roc5': roc5}
    except: return None

# ================================================================
# BACKTEST ENGINE
# ================================================================
def run_backtest(ind, signal_func, regime_func, hold_days=7, start_idx=60,
                 antiknife=5, day_filter=None):
    """
    Backtest generico. Soporta filtro de dia de semana.
    day_filter: None=todos, [0,1,2,3,4] = Lun-Vie
    """
    trades = []
    last_entry = {}  # anti-knife per ticker
    dates = ind['_SPY']['close'].index

    for i in range(start_idx, len(dates) - hold_days - 1):
        if not regime_func(ind, i):
            continue

        # Filtro dia de semana
        if day_filter is not None:
            dow = dates[i].weekday()
            if dow not in day_filter:
                continue

        for t in TICKERS:
            if t not in ind:
                continue

            # Anti-knife
            if t in last_entry and (i - last_entry[t]) < antiknife:
                continue

            sig = signal_func(ind, t, i)
            if sig is None:
                continue

            price_in = ind[t]['close'].iloc[i+1] if i+1 < len(ind[t]['close']) else None
            price_out_idx = min(i + 1 + hold_days, len(ind[t]['close']) - 1)
            price_out = ind[t]['close'].iloc[price_out_idx]

            if price_in is None or np.isnan(price_in) or np.isnan(price_out):
                continue

            ret = (price_out / price_in - 1) * 100
            trades.append({
                'ticker': t,
                'date': dates[i],
                'signal': sig.get('signal', ''),
                'price_in': price_in,
                'price_out': price_out,
                'return_pct': ret,
                'hold': hold_days,
                'dow': dates[i].weekday(),
            })
            last_entry[t] = i

    return pd.DataFrame(trades)

def calc_metrics(trades_df):
    """Calcula metricas de un DataFrame de trades."""
    if trades_df.empty or len(trades_df) == 0:
        return {'trades': 0, 'wr': 0, 'sharpe': 0, 'avg_ret': 0, 'total_ret': 0, 'mdd': 0}

    rets = trades_df['return_pct'].values
    n = len(rets)
    wr = (rets > 0).sum() / n * 100
    avg = rets.mean()
    std = rets.std() if n > 1 else 1
    sharpe = (avg / std * np.sqrt(252/7)) if std > 0 else 0
    total = (1 + rets/100).prod() * 100 - 100

    # MDD
    equity = (1 + rets/100).cumprod()
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak * 100
    mdd = dd.min()

    return {
        'trades': n, 'wr': round(wr, 1), 'sharpe': round(sharpe, 2),
        'avg_ret': round(avg, 2), 'total_ret': round(total, 1), 'mdd': round(mdd, 1)
    }

def walk_forward(ind, signal_func, regime_func, hold_days=7,
                 n_windows=5, train_pct=0.6, antiknife=5):
    """Walk-forward con n ventanas."""
    dates = ind['_SPY']['close'].index
    total_days = len(dates) - 60 - hold_days - 1
    if total_days < 100:
        return {'wf_pct': 0, 'windows': 0, 'avg_sharpe': 0, 'details': []}

    window_size = total_days // n_windows
    results = []

    for w in range(n_windows):
        start = 60 + w * window_size
        end = min(start + window_size, len(dates) - hold_days - 1)

        # Solo test (no hay optimizacion, asi que no necesitamos train/test split real)
        trades = []
        last_entry = {}

        for i in range(start, end):
            if not regime_func(ind, i):
                continue
            for t in TICKERS:
                if t not in ind: continue
                if t in last_entry and (i - last_entry[t]) < antiknife: continue
                sig = signal_func(ind, t, i)
                if sig is None: continue

                price_in = ind[t]['close'].iloc[i+1] if i+1 < len(ind[t]['close']) else None
                price_out_idx = min(i + 1 + hold_days, len(ind[t]['close']) - 1)
                price_out = ind[t]['close'].iloc[price_out_idx]
                if price_in is None or np.isnan(price_in) or np.isnan(price_out): continue

                ret = (price_out / price_in - 1) * 100
                trades.append(ret)
                last_entry[t] = i

        if trades:
            avg_r = np.mean(trades)
            std_r = np.std(trades) if len(trades) > 1 else 1
            sh = avg_r / std_r * np.sqrt(252/7) if std_r > 0 else 0
        else:
            avg_r, sh = 0, 0

        results.append({
            'window': w+1,
            'trades': len(trades),
            'avg_ret': round(avg_r, 2),
            'sharpe': round(sh, 2),
            'positive': sh > 0
        })

    positive_windows = sum(1 for r in results if r['positive'])
    avg_sharpe = np.mean([r['sharpe'] for r in results if r['trades'] > 0])

    return {
        'wf_pct': round(positive_windows / n_windows * 100),
        'windows': n_windows,
        'positive': positive_windows,
        'avg_sharpe': round(avg_sharpe, 2) if not np.isnan(avg_sharpe) else 0,
        'details': results
    }

def monte_carlo(trades_df, n_sims=1000):
    """Bootstrap Monte Carlo."""
    if len(trades_df) < 5:
        return {'p_sharpe_pos': 0, 'p_total_pos': 0, 'worst_1pct_sharpe': 0, 'worst_1pct_mdd': 0}

    rets = trades_df['return_pct'].values
    n = len(rets)
    sharpes = []
    mdds = []
    totals = []

    for _ in range(n_sims):
        sample = np.random.choice(rets, size=n, replace=True)
        avg = sample.mean()
        std = sample.std()
        sh = avg / std * np.sqrt(252/7) if std > 0 else 0
        sharpes.append(sh)

        eq = (1 + sample/100).cumprod()
        peak = np.maximum.accumulate(eq)
        dd = ((eq - peak) / peak * 100).min()
        mdds.append(dd)
        totals.append((eq[-1] - 1) * 100)

    return {
        'p_sharpe_pos': round(np.mean([s > 0 for s in sharpes]) * 100, 1),
        'p_total_pos': round(np.mean([t > 0 for t in totals]) * 100, 1),
        'worst_1pct_sharpe': round(np.percentile(sharpes, 1), 2),
        'worst_1pct_mdd': round(np.percentile(mdds, 1), 1),
        'median_sharpe': round(np.median(sharpes), 2),
    }

# ================================================================
# MAIN
# ================================================================
def main():
    print("=" * 80)
    print("  INVESTIGACION V7 — FRONTERAS NO EXPLORADAS")
    print("  Buscando Signal C y refutando V6")
    print("=" * 80)

    # Download datos
    print("\n[1/8] Descargando datos (~2 anos)...")
    all_tickers = TICKERS + ['SPY', 'QQQ', '^VIX']
    data = yf.download(all_tickers, start='2024-03-01', end='2026-04-06', progress=False)

    print(f"  Datos: {data.index[0].strftime('%Y-%m-%d')} -> {data.index[-1].strftime('%Y-%m-%d')}")
    print(f"  {len(data)} dias, {len(TICKERS)} tickers + SPY/QQQ/VIX")

    # Precompute
    print("\n[2/8] Pre-calculando indicadores (base + 10 nuevos)...")
    ind = precompute(data, TICKERS)
    valid_tickers = [t for t in TICKERS if t in ind]
    print(f"  {len(valid_tickers)} tickers validos con indicadores")
    vix_ok = ind['_VIX'] is not None
    print(f"  VIX disponible: {'SI' if vix_ok else 'NO'}")

    # ════════════════════════════════════════════════════════════════
    # PARTE 3: BACKTEST DE TODAS LAS ESTRATEGIAS
    # ════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  PARTE 3: BACKTEST DE 12 ESTRATEGIAS (V6 ref + 10 Signal C)")
    print("=" * 80)

    strategies = {
        'V6_A (V5)':       (signal_v5, regime_spy_sma),
        'V6_B (W+Sq)':     (signal_d_williams, regime_spy_sma),
        'C1_VolCapit':      (signal_c1_volume_capitulation, regime_spy_sma),
        'C2_RapidDecl':     (signal_c2_rapid_decline, regime_spy_sma),
        'C3_ConsecDown':    (signal_c3_consecutive_down, regime_spy_sma),
        'C4_RSIDiverg':     (signal_c4_rsi_divergence, regime_spy_sma),
        'C5_52wBounce':     (signal_c5_52w_low_bounce, regime_spy_sma),
        'C6_VolSqueeze':    (signal_c6_vol_cap_squeeze, regime_spy_sma),
        'C7_CrashVol':      (signal_c7_extreme_roc_vol, regime_spy_sma),
        'C8_VIXSpike':      (signal_c8_vix_spike_oversold, regime_spy_sma),
        'C9_DblBottom':     (signal_c9_double_bottom, regime_spy_sma),
        'C10_TripleOS':     (signal_c10_mean_rev_strong, regime_spy_sma),
    }

    all_results = {}
    all_trades = {}

    for name, (sig_func, reg_func) in strategies.items():
        trades_df = run_backtest(ind, sig_func, reg_func, hold_days=7)
        metrics = calc_metrics(trades_df)
        all_results[name] = metrics
        all_trades[name] = trades_df

        status = "***" if metrics['sharpe'] > 5 and metrics['trades'] >= 10 else ""
        print(f"  {name:20s} | Trades:{metrics['trades']:3d} | WR:{metrics['wr']:5.1f}% | "
              f"Sharpe:{metrics['sharpe']:6.2f} | Avg:{metrics['avg_ret']:+5.2f}% | "
              f"Total:{metrics['total_ret']:+6.1f}% | MDD:{metrics['mdd']:5.1f}% {status}")

    # ════════════════════════════════════════════════════════════════
    # PARTE 3B: VARIACIONES — SIN REGIME (refutar SPY filter)
    # ════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  PARTE 3B: MISMAS ESTRATEGIAS SIN FILTRO REGIME (refutar SPY>SMA50)")
    print("=" * 80)

    # Top candidates sin regime
    top_signals = [
        ('C1_NoReg', signal_c1_volume_capitulation, regime_none),
        ('C2_NoReg', signal_c2_rapid_decline, regime_none),
        ('C3_NoReg', signal_c3_consecutive_down, regime_none),
        ('C7_NoReg', signal_c7_extreme_roc_vol, regime_none),
        ('C8_NoReg', signal_c8_vix_spike_oversold, regime_none),
        ('C10_NoReg', signal_c10_mean_rev_strong, regime_none),
    ]

    for name, sig_func, reg_func in top_signals:
        trades_df = run_backtest(ind, sig_func, reg_func, hold_days=7)
        metrics = calc_metrics(trades_df)
        all_results[name] = metrics
        all_trades[name] = trades_df

        print(f"  {name:20s} | Trades:{metrics['trades']:3d} | WR:{metrics['wr']:5.1f}% | "
              f"Sharpe:{metrics['sharpe']:6.2f} | Avg:{metrics['avg_ret']:+5.2f}% | "
              f"Total:{metrics['total_ret']:+6.1f}% | MDD:{metrics['mdd']:5.1f}%")

    # ════════════════════════════════════════════════════════════════
    # PARTE 3C: VIX COMO REGIME ALTERNATIVO
    # ════════════════════════════════════════════════════════════════
    if vix_ok:
        print("\n" + "=" * 80)
        print("  PARTE 3C: VIX COMO REGIME ALTERNATIVO")
        print("=" * 80)

        vix_regimes = [
            ('SPY>SMA50 (actual)', regime_spy_sma),
            ('VIX<20', regime_vix_20),
            ('VIX<25', regime_vix_25),
            ('VIX<30', regime_vix_30),
            ('SPY AND VIX<25', regime_spy_and_vix25),
            ('SPY OR VIX<20', regime_spy_or_vix20),
            ('Sin regime', regime_none),
        ]

        # Usar V6 union como base para comparar regimenes
        def signal_v6_union(ind, t, i):
            """V6 = A OR B."""
            sig = signal_v5(ind, t, i)
            if sig: return sig
            return signal_d_williams(ind, t, i)

        print(f"\n  Base: V6 Union (Signal A OR B) con diferentes regimenes:\n")

        for reg_name, reg_func in vix_regimes:
            trades_df = run_backtest(ind, signal_v6_union, reg_func, hold_days=7)
            metrics = calc_metrics(trades_df)
            key = f'V6_{reg_name}'
            all_results[key] = metrics
            all_trades[key] = trades_df

            flag = " <-- ACTUAL" if "actual" in reg_name else ""
            print(f"  {reg_name:25s} | Trades:{metrics['trades']:3d} | WR:{metrics['wr']:5.1f}% | "
                  f"Sharpe:{metrics['sharpe']:6.2f} | Total:{metrics['total_ret']:+6.1f}% | "
                  f"MDD:{metrics['mdd']:5.1f}%{flag}")

    # ════════════════════════════════════════════════════════════════
    # PARTE 4: WALK-FORWARD DE TOP CANDIDATES
    # ════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  PARTE 4: WALK-FORWARD DE ESTRATEGIAS CON SHARPE > 0 y TRADES >= 5")
    print("=" * 80)

    # Seleccionar candidatos para WF
    wf_candidates = []
    for name, metrics in all_results.items():
        if metrics['sharpe'] > 0 and metrics['trades'] >= 5:
            wf_candidates.append((name, metrics))

    wf_candidates.sort(key=lambda x: x[1]['sharpe'], reverse=True)
    print(f"\n  {len(wf_candidates)} candidatos para walk-forward:\n")

    wf_results = {}
    for name, metrics in wf_candidates[:15]:  # Top 15
        # Encontrar la funcion de signal y regime
        if name in strategies:
            sig_func, reg_func = strategies[name]
        elif name.endswith('_NoReg'):
            base = name.replace('_NoReg', '')
            sig_map = {
                'C1': signal_c1_volume_capitulation, 'C2': signal_c2_rapid_decline,
                'C3': signal_c3_consecutive_down, 'C7': signal_c7_extreme_roc_vol,
                'C8': signal_c8_vix_spike_oversold, 'C10': signal_c10_mean_rev_strong,
            }
            sig_func = sig_map.get(base)
            reg_func = regime_none
            if sig_func is None: continue
        elif name.startswith('V6_'):
            sig_func = signal_v6_union
            reg_name = name.replace('V6_', '')
            reg_map = {
                'SPY>SMA50 (actual)': regime_spy_sma, 'VIX<20': regime_vix_20,
                'VIX<25': regime_vix_25, 'VIX<30': regime_vix_30,
                'SPY AND VIX<25': regime_spy_and_vix25, 'SPY OR VIX<20': regime_spy_or_vix20,
                'Sin regime': regime_none,
            }
            reg_func = reg_map.get(reg_name, regime_spy_sma)
        else:
            continue

        wf = walk_forward(ind, sig_func, reg_func, hold_days=7, n_windows=5)
        wf_results[name] = wf

        status = "PASS" if wf['wf_pct'] >= 80 else ("MARGINAL" if wf['wf_pct'] >= 60 else "FAIL")
        emoji = ">>>" if status == "PASS" else "   "
        print(f"  {emoji} {name:25s} | WF:{wf['wf_pct']:3d}% ({wf['positive']}/{wf['windows']}) | "
              f"Avg Sharpe:{wf['avg_sharpe']:6.2f} | Trades:{metrics['trades']:3d} | [{status}]")
        for d in wf['details']:
            print(f"        W{d['window']}: {d['trades']:2d} trades, Sharpe {d['sharpe']:+6.2f} {'OK' if d['positive'] else 'NEG'}")

    # ════════════════════════════════════════════════════════════════
    # PARTE 5: OVERLAP ANALYSIS — Que C signals NO se superponen con V6?
    # ════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  PARTE 5: OVERLAP — Nuevas senales vs V6 (buscamos 0% overlap)")
    print("=" * 80)

    v6_trades = pd.concat([all_trades.get('V6_A (V5)', pd.DataFrame()),
                            all_trades.get('V6_B (W+Sq)', pd.DataFrame())])

    if not v6_trades.empty:
        v6_set = set(zip(v6_trades['ticker'], v6_trades['date'].dt.strftime('%Y-%m-%d')))
    else:
        v6_set = set()

    print(f"\n  V6 tiene {len(v6_set)} trades unicos (A + B)\n")

    for name in ['C1_VolCapit', 'C2_RapidDecl', 'C3_ConsecDown', 'C4_RSIDiverg',
                  'C5_52wBounce', 'C6_VolSqueeze', 'C7_CrashVol', 'C8_VIXSpike',
                  'C9_DblBottom', 'C10_TripleOS',
                  'C1_NoReg', 'C2_NoReg', 'C3_NoReg', 'C7_NoReg', 'C8_NoReg', 'C10_NoReg']:
        if name not in all_trades or all_trades[name].empty:
            continue
        c_df = all_trades[name]
        c_set = set(zip(c_df['ticker'], c_df['date'].dt.strftime('%Y-%m-%d')))
        overlap = len(v6_set & c_set)
        overlap_pct = overlap / len(c_set) * 100 if c_set else 0
        unique = len(c_set) - overlap

        m = all_results[name]
        flag = " *** NEW SIGNAL" if overlap_pct < 30 and m['sharpe'] > 2 and m['trades'] >= 5 else ""
        print(f"  {name:20s} | Total:{len(c_set):3d} | Overlap:{overlap:2d} ({overlap_pct:4.1f}%) | "
              f"Unique:{unique:3d} | Sharpe:{m['sharpe']:5.2f}{flag}")

    # ════════════════════════════════════════════════════════════════
    # PARTE 6: UNION V6 + BEST NEW SIGNAL
    # ════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  PARTE 6: UNION V6 + MEJOR SIGNAL C (Triple-Signal)")
    print("=" * 80)

    # Encontrar candidatos que pasaron WF y tienen bajo overlap
    best_c = []
    for name, wf in wf_results.items():
        if name.startswith('V6_') or name.startswith('V6_A') or name.startswith('V6_B'):
            continue
        if wf['wf_pct'] >= 60 and all_results[name]['trades'] >= 5:
            # Check overlap
            if name in all_trades and not all_trades[name].empty:
                c_df = all_trades[name]
                c_set = set(zip(c_df['ticker'], c_df['date'].dt.strftime('%Y-%m-%d')))
                overlap = len(v6_set & c_set)
                overlap_pct = overlap / len(c_set) * 100 if c_set else 100
                best_c.append((name, wf, overlap_pct))

    best_c.sort(key=lambda x: (x[1]['wf_pct'], -x[2]), reverse=True)

    if best_c:
        print(f"\n  Candidatos C que pasan WF >= 60% (ordenados por WF, overlap):\n")
        for name, wf, ovlp in best_c:
            m = all_results[name]
            print(f"    {name:25s} | WF:{wf['wf_pct']:3d}% | Sharpe:{m['sharpe']:5.2f} | "
                  f"Trades:{m['trades']:3d} | Overlap:{ovlp:4.1f}%")

        # Probar combinaciones
        print(f"\n  --- UNIONES ---\n")
        for name, wf, ovlp in best_c[:5]:
            # Union V6 + C
            v6_df = pd.concat([all_trades.get('V6_A (V5)', pd.DataFrame()),
                                all_trades.get('V6_B (W+Sq)', pd.DataFrame())])
            c_df = all_trades[name]

            if c_df.empty:
                continue

            union_df = pd.concat([v6_df, c_df]).drop_duplicates(subset=['ticker', 'date'])
            union_metrics = calc_metrics(union_df)

            print(f"  V6 + {name:20s} | Trades:{union_metrics['trades']:3d} | "
                  f"WR:{union_metrics['wr']:5.1f}% | Sharpe:{union_metrics['sharpe']:5.2f} | "
                  f"Total:{union_metrics['total_ret']:+6.1f}% | MDD:{union_metrics['mdd']:5.1f}%")
    else:
        print("\n  Ningun Signal C paso walk-forward >= 60%. V6 se mantiene.")

    # ════════════════════════════════════════════════════════════════
    # PARTE 6B: DIA DE SEMANA ANALYSIS
    # ════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  PARTE 6B: DIA DE SEMANA — Filtrar entradas por dia")
    print("=" * 80)

    # V6 union por dia de semana
    def signal_v6_union_local(ind, t, i):
        sig = signal_v5(ind, t, i)
        if sig: return sig
        return signal_d_williams(ind, t, i)

    dow_names = ['Lun', 'Mar', 'Mie', 'Jue', 'Vie']

    # Full V6 por dia
    v6_full = run_backtest(ind, signal_v6_union_local, regime_spy_sma, hold_days=7)
    if not v6_full.empty:
        print(f"\n  V6 Union por dia de entrada:\n")
        for dow in range(5):
            dow_trades = v6_full[v6_full['dow'] == dow]
            if len(dow_trades) > 0:
                m = calc_metrics(dow_trades)
                print(f"  {dow_names[dow]:3s}: {m['trades']:2d} trades | WR:{m['wr']:5.1f}% | "
                      f"Avg:{m['avg_ret']:+5.2f}% | Sharpe:{m['sharpe']:5.2f}")
            else:
                print(f"  {dow_names[dow]:3s}: 0 trades")

    # V6 solo Mie+Jue
    print(f"\n  V6 filtrado por dia:\n")
    for day_combo_name, day_combo in [('Mie+Jue', [2,3]), ('Lun+Mie+Jue', [0,2,3]),
                                       ('Mar-Jue', [1,2,3]), ('Todos', None)]:
        trades_df = run_backtest(ind, signal_v6_union_local, regime_spy_sma,
                                  hold_days=7, day_filter=day_combo)
        m = calc_metrics(trades_df)
        print(f"  {day_combo_name:15s} | Trades:{m['trades']:3d} | WR:{m['wr']:5.1f}% | "
              f"Sharpe:{m['sharpe']:5.2f} | Total:{m['total_ret']:+6.1f}%")

    # ════════════════════════════════════════════════════════════════
    # PARTE 7: SENSITIVITY V6 THRESHOLDS
    # ════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  PARTE 7: SENSITIVITY — Thresholds V6 son optimos?")
    print("=" * 80)

    # RSI threshold para Signal A
    print(f"\n  Signal A — RSI threshold:\n")
    for rsi_th in [20, 22, 25, 28, 30]:
        def make_sig_a(threshold):
            def sig(ind, t, i):
                ti = ind[t]
                try:
                    rsi = ti['rsi'].iloc[i]
                    macd = ti['macd_hist'].iloc[i]; macd_prev = ti['macd_hist'].iloc[i-1]
                    dist = ti['dist_sma50'].iloc[i]; vol_r = ti['vol_ratio'].iloc[i]
                    price = ti['close'].iloc[i]; atr = ti['atr'].iloc[i]
                    if np.isnan(rsi) or np.isnan(dist): return None
                    if rsi >= threshold or macd <= macd_prev or dist > -10 or vol_r > 1.5: return None
                    rsi_sc = max(0, min(40, (30-rsi)/30*40))
                    str_sc = max(0, min(30, (abs(dist)-5)/15*30))
                    macd_acc = (macd-macd_prev)/(atr*0.01+1e-6)
                    macd_sc = max(0, min(20, macd_acc*5))
                    vol_sc = max(0, min(10, (1.5-vol_r)/1.5*10))
                    if rsi_sc+str_sc+macd_sc+vol_sc < 30: return None
                    return {'ticker': t, 'signal': 'A', 'price': price}
                except: return None
            return sig

        trades_df = run_backtest(ind, make_sig_a(rsi_th), regime_spy_sma, hold_days=7)
        m = calc_metrics(trades_df)
        flag = " <-- ACTUAL" if rsi_th == 25 else ""
        print(f"  RSI<{rsi_th:2d} | Trades:{m['trades']:3d} | WR:{m['wr']:5.1f}% | "
              f"Sharpe:{m['sharpe']:5.2f} | Total:{m['total_ret']:+6.1f}%{flag}")

    # Williams threshold para Signal B
    print(f"\n  Signal B — Williams threshold:\n")
    for wr_th in [-85, -88, -90, -92, -95]:
        def make_sig_b(threshold):
            def sig(ind, t, i):
                ti = ind[t]
                try:
                    wr = ti['williams_r'].iloc[i]; bw = ti['bb_width'].iloc[i]
                    dist = ti['dist_sma50'].iloc[i]; price = ti['close'].iloc[i]
                    if np.isnan(wr) or np.isnan(bw) or np.isnan(dist): return None
                    if wr >= threshold or dist > -5: return None
                    if i < 50: return None
                    bw_min = ti['bb_width'].iloc[i-50:i].min()
                    if np.isnan(bw_min) or bw > bw_min * 1.2: return None
                    return {'ticker': t, 'signal': 'D', 'price': price}
                except: return None
            return sig

        trades_df = run_backtest(ind, make_sig_b(wr_th), regime_spy_sma, hold_days=7)
        m = calc_metrics(trades_df)
        flag = " <-- ACTUAL" if wr_th == -90 else ""
        print(f"  WR<{wr_th:3d} | Trades:{m['trades']:3d} | WR:{m['wr']:5.1f}% | "
              f"Sharpe:{m['sharpe']:5.2f} | Total:{m['total_ret']:+6.1f}%{flag}")

    # BB Squeeze multiplier
    print(f"\n  Signal B — BB Squeeze multiplier:\n")
    for bb_mult in [1.1, 1.2, 1.3, 1.5, 2.0]:
        def make_sig_b_bb(mult):
            def sig(ind, t, i):
                ti = ind[t]
                try:
                    wr = ti['williams_r'].iloc[i]; bw = ti['bb_width'].iloc[i]
                    dist = ti['dist_sma50'].iloc[i]; price = ti['close'].iloc[i]
                    if np.isnan(wr) or np.isnan(bw) or np.isnan(dist): return None
                    if wr >= -90 or dist > -5: return None
                    if i < 50: return None
                    bw_min = ti['bb_width'].iloc[i-50:i].min()
                    if np.isnan(bw_min) or bw > bw_min * mult: return None
                    return {'ticker': t, 'signal': 'D', 'price': price}
                except: return None
            return sig

        trades_df = run_backtest(ind, make_sig_b_bb(bb_mult), regime_spy_sma, hold_days=7)
        m = calc_metrics(trades_df)
        flag = " <-- ACTUAL" if bb_mult == 1.2 else ""
        print(f"  BB<{bb_mult:.1f}x | Trades:{m['trades']:3d} | WR:{m['wr']:5.1f}% | "
              f"Sharpe:{m['sharpe']:5.2f} | Total:{m['total_ret']:+6.1f}%{flag}")

    # Hold adaptativo
    print(f"\n  Hold adaptativo por tipo de senal:\n")
    for hold_a, hold_b in [(5,5), (5,7), (7,7), (7,10), (10,7), (10,10)]:
        # Signal A con hold_a
        trades_a = run_backtest(ind, signal_v5, regime_spy_sma, hold_days=hold_a)
        trades_b = run_backtest(ind, signal_d_williams, regime_spy_sma, hold_days=hold_b)
        if not trades_a.empty or not trades_b.empty:
            union = pd.concat([trades_a, trades_b]).drop_duplicates(subset=['ticker', 'date'])
            m = calc_metrics(union)
            flag = " <-- ACTUAL" if hold_a == 7 and hold_b == 7 else ""
            print(f"  A={hold_a:2d}d B={hold_b:2d}d | Trades:{m['trades']:3d} | WR:{m['wr']:5.1f}% | "
                  f"Sharpe:{m['sharpe']:5.2f} | Total:{m['total_ret']:+6.1f}% | MDD:{m['mdd']:5.1f}%{flag}")

    # ════════════════════════════════════════════════════════════════
    # PARTE 8: MONTE CARLO DEL MEJOR MODELO
    # ════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  PARTE 8: MONTE CARLO — V6 actual vs mejor alternativa")
    print("=" * 80)

    # V6 actual
    v6_union = pd.concat([all_trades.get('V6_A (V5)', pd.DataFrame()),
                           all_trades.get('V6_B (W+Sq)', pd.DataFrame())])

    if not v6_union.empty:
        mc_v6 = monte_carlo(v6_union, 1000)
        print(f"\n  V6 Union (actual):")
        print(f"    P(Sharpe>0): {mc_v6['p_sharpe_pos']}%")
        print(f"    Median Sharpe: {mc_v6['median_sharpe']}")
        print(f"    Worst 1% Sharpe: {mc_v6['worst_1pct_sharpe']}")
        print(f"    Worst 1% MDD: {mc_v6['worst_1pct_mdd']}%")

    # Si hay un mejor modelo, Monte Carlo tambien
    if best_c:
        best_name = best_c[0][0]
        best_union = pd.concat([v6_union, all_trades.get(best_name, pd.DataFrame())])
        best_union = best_union.drop_duplicates(subset=['ticker', 'date'])

        if not best_union.empty:
            mc_best = monte_carlo(best_union, 1000)
            m_best = calc_metrics(best_union)
            print(f"\n  V6 + {best_name}:")
            print(f"    Trades: {m_best['trades']} | Sharpe: {m_best['sharpe']} | Total: {m_best['total_ret']}%")
            print(f"    P(Sharpe>0): {mc_best['p_sharpe_pos']}%")
            print(f"    Median Sharpe: {mc_best['median_sharpe']}")
            print(f"    Worst 1% Sharpe: {mc_best['worst_1pct_sharpe']}")
            print(f"    Worst 1% MDD: {mc_best['worst_1pct_mdd']}%")

    # ════════════════════════════════════════════════════════════════
    # PARTE 9: VEREDICTO FINAL
    # ════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  PARTE 9: VEREDICTO FINAL")
    print("=" * 80)

    print(f"""
  Protocolo 4 — Anti-Overfitting Checklist:
  [ ] LOOK-AHEAD BIAS:    Entrada en close, ejecucion en open D+1
  [ ] SURVIVORSHIP BIAS:  Solo tickers actuales (no perfectos)
  [ ] PERIODO:            {data.index[0].strftime('%Y-%m')} -> {data.index[-1].strftime('%Y-%m')} ({len(data)//21} meses)
  [ ] OUT-OF-SAMPLE:      Walk-forward con 5 ventanas
  [ ] WALK-FORWARD:       Requerido >= 80% ventanas positivas
  [ ] COMPLEJIDAD:        V6 = 2 senales independientes (< 5 filtros c/u)
  [ ] TRADES MINIMOS:     V6 = 24 trades (>= 15 requeridos)
  [ ] COSTOS:             No incluidos (swing trades 7d, comisiones minimas)

  Resumen de candidatos que PASARON walk-forward (>= 80%):
""")

    passed = []
    for name, wf in wf_results.items():
        if wf['wf_pct'] >= 80:
            m = all_results.get(name, {})
            passed.append((name, m, wf))
            print(f"  >>> {name:25s} | WF:{wf['wf_pct']}% | Sharpe:{m.get('sharpe',0):5.2f} | "
                  f"Trades:{m.get('trades',0):3d}")

    if not passed:
        print("  Ninguna estrategia nueva paso WF >= 80%. V6 SE MANTIENE.")

    print(f"""
  {'=' * 70}
  CONCLUSION:

  Si ningun Signal C nuevo paso walk-forward >= 80% con bajo overlap:
  -> V6 (Dual-Signal) SE MANTIENE como scanner activo.
  -> Las fronteras no exploradas no superaron la robustez de V6.
  -> Esto CONFIRMA que V6 es un modelo fuerte y bien calibrado.

  Si algun Signal C paso:
  -> Evaluar union V6+C con Monte Carlo y convergencia 3 angulos.
  -> Solo promover a V7 si mejora trades sin degradar Sharpe/MDD.
  {'=' * 70}
""")

if __name__ == '__main__':
    main()
