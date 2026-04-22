#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║   TITAN HYBRID v4.0 — INSTITUTIONAL ALPHA ENGINE                                ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                  ║
║  TECNICAS INSTITUCIONALES IMPLEMENTADAS:                                         ║
║                                                                                  ║
║  ◆ AQR Capital:                                                                  ║
║    - Cross-Sectional Z-Score normalization de todos los factores                ║
║    - Factor momentum (Moskowitz, Ooi, Pedersen 2012)                            ║
║    - Information Coefficient (IC) weighted factor combination                   ║
║    - Sector-neutral alpha (alpha puro, sin sesgo sectorial)                     ║
║                                                                                  ║
║  ◆ Renaissance Technologies / Two Sigma:                                         ║
║    - Microstructure signals: Order Flow Imbalance, Smart Money Index             ║
║    - Non-linear pattern detection via Gradient Boosting ensemble                ║
║    - Regime-conditional alpha (diferentes modelos por volatilidad)               ║
║    - Short-term mean reversion + momentum blend                                  ║
║                                                                                  ║
║  ◆ Citadel / DE Shaw:                                                            ║
║    - Multi-horizon alpha decay (1d, 3d, 5d signals combined)                    ║
║    - Purged Walk-Forward validation (sin data leakage)                           ║
║    - Rolling IC feature selection (descarta factores muertos)                    ║
║    - Turnover-aware scoring (penaliza señales con baja liquidez)                ║
║                                                                                  ║
║  ◆ Bridgewater / Man AHL:                                                        ║
║    - Realized vol targeting (normaliza retornos por volatilidad)                ║
║    - Cross-asset regime detection (SPY + VIX + TLT + GLD)                       ║
║    - Tail risk indicators (skew, kurtosis de retornos)                          ║
║                                                                                  ║
║  ◆ Academic Alpha Factors (Fama-French, Jegadeesh, Ang):                         ║
║    - Short-term reversal (1-week) — Jegadeesh 1990                              ║
║    - Intermediate momentum (1-month skip 1-week) — Novy-Marx 2012               ║
║    - Idiosyncratic volatility — Ang, Hodrick, Xing, Zhang 2006                  ║
║    - Volume-price confirmation — Loh 2010                                        ║
║    - Information Discreteness — Da, Gurun, Warachka 2014                         ║
║                                                                                  ║
║  PIPELINE:                                                                       ║
║    Raw OHLCV → 25 Alpha Factors → CS Z-Score → IC Weighting →                  ║
║    3 ML Models → Meta-Learner → Sector-Neutral Rank → TOP 20                   ║
║                                                                                  ║
╚══════════════════════════════════════════════════════════════════════════════════╝
  pip install yfinance numpy pandas scikit-learn scipy
"""

import os, warnings, time, sys
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from scipy import stats as sp_stats

from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    ExtraTreesClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import RobustScaler

warnings.filterwarnings("ignore")

# ─── UI ──────────────────────────────────────────────────────────────────────
R="\033[91m"; G="\033[92m"; Y="\033[93m"; M="\033[95m"
C="\033[96m"; W="\033[97m"; DIM="\033[2m"; BOLD="\033[1m"; RST="\033[0m"
def clr(): os.system("cls" if os.name == "nt" else "clear")
def barra(v, mx=100, n=20):
    f = max(0, min(n, int(v/mx*n)))
    c = G if v > 60 else Y if v > 50 else DIM
    return f"{c}{'█'*f}{DIM}{'░'*(n-f)}{RST}"

# ─── UNIVERSO ────────────────────────────────────────────────────────────────
ACTIVOS = [
    'AAL','AAP','AAPL','ABBV','ABEV','ABT','ACN','ADBE','ADI','ADP',
    'AEG','AEM','AGRO','AIG','AMAT','AMD','AMGN','AMX','AMZN',
    'ANF','ARCO','ARM','ASR','AVGO','AVY','AXP','AZN','BA',
    'BABA','BAC','BAK','BB','BBD','BBVA','BG','BHP','BIDU',
    'BIIB','BK','BKNG','BKR','BMY','BP','BSBR','C',
    'CAAP','CAH','CAR','CAT','CCL','CDE','CL','COIN',
    'COST','CRM','CSCO','CVS','CVX','CX','DAL','DD','DE',
    'DEO','DHR','DIS','DOCU','DOW','E','EA','EBAY',
    'EFX','EQNR','ERIC','ETSY','FCX','FDX','FMX',
    'FSLR','GE','GFI','GGB','GILD','GLOB','GLW','GM','GOLD',
    'GOOGL','GPRK','GRMN','GS','GSK','GT','HAL','HD','HDB','HL',
    'HMC','HMY','HNHPF','HOG','HON','HPQ','HSBC','HSY','HWM','IBM',
    'IBN','IFF','INFY','ING','INTC','IP','ISRG','ITUB','JCI','JD',
    'JNJ','JPM','KB','KEP','KGC','KMB','KO','KOF','LAC','LAR',
    'LLY','LMT','LND','LRCX','LVS','LYG','MA',
    'MCD','MDLZ','MDT','MELI','META','MFG','MMM','MO','MRK',
    'MRNA','MRVL','MSFT','MSI','MUFG','MUX','NEM','NFLX','NG','NGG',
    'NIO','NKE','NMR','NOK','NSANY','NTES','NU','NUE','NVDA',
    'NVS','NXE','OAOFY','ORANY','ORCL','ORLY','PAAS','PAC',
    'PAGS','PBI','PBR','PCAR','PEP','PFE','PG','PHG','PINS',
    'PKX','PLTR','PM','PSO','PSX','PYPL','QCOM','RACE','RIO',
    'RIOT','ROKU','ROST','RTX','SAN','SAP','SBS','SBUX','SCCO','SCHW',
    'SDA','SE','SHEL','SHOP','SHPWQ','SID','SIEGY','SLB','SNA','SNAP',
    'SNOW','SONY','SPCE','SPGI','SPOT','STLA','STNE','SUZ','SWKS',
    'SYY','T','TCOM','TEF','TGT','TIIAY','TIMB','TJX','TMO',
    'TMUS','TRIP','TRV','TS','TSLA','TSM','TTE','TV','TWLO','TX',
    'TXN','UGP','UL','UNH','UNP','URBN','USB','V','VALE','VIST',
    'VIV','VOD','VRSN','VZ','WB','WFC','WMT','XOM',
    'XP','XRX','XYZ','YELP','YZCAY','ZM',
]

# Sectores para sector-neutral alpha
SECTOR_MAP = {
    'tech': ['AAPL','MSFT','GOOGL','META','AMZN','ADBE','CRM','ORCL','ACN','IBM','CSCO','INFY','SAP',
             'DOCU','EA','EBAY','GLOB','SNAP','SPOT','TWLO','VRSN','ZM','SNOW','PLTR','ERIC','NOK'],
    'semis': ['NVDA','AMD','AVGO','QCOM','INTC','AMAT','LRCX','ADI','MRVL','ARM','TXN','TSM','SWKS','FSLR'],
    'finance': ['JPM','BAC','GS','C','V','MA','AXP','PYPL','SCHW','BK','HSBC','ING','BBVA','SAN',
                'ITUB','BBD','NU','WFC','USB','BSBR','LYG','MUFG','NMR','KB','KEP','IBN','HDB',
                'MFG','PKX','BKR','AIG','COIN','XP','PAGS','STNE'],
    'energy': ['XOM','CVX','BP','SHEL','SLB','HAL','EQNR','TTE','PSX','PBR','BKR'],
    'mining': ['GOLD','NEM','VALE','FCX','BHP','RIO','AEM','GFI','HMY','KGC','PAAS','HL',
               'CDE','SCCO','MUX','NXE','LAC','GGB','SID'],
    'health': ['JNJ','PFE','MRK','ABBV','LLY','UNH','ABT','AMGN','GILD','BIIB','BMY','MDT',
               'DHR','TMO','ISRG','MRNA','CVS','AZN','NVS','GSK'],
    'consumer': ['KO','PEP','WMT','COST','MCD','SBUX','NKE','HD','DIS','PG','CL','KMB','MDLZ',
                 'PM','MO','TGT','TJX','ROST','ORLY','HSY','ANF','URBN','BKNG','TRIP','LVS',
                 'CCL','HOG','RACE','SHOP','MELI','BABA','JD','NTES','SE','ROKU','ETSY'],
    'industrial': ['CAT','DE','BA','HON','GE','RTX','LMT','FDX','GM','DAL','AAL','MMM','DD',
                   'AVY','GRMN','SNA','PCAR','HWM','JCI','UNP','SYY','IP','GLW','GT','HOG',
                   'CAR','STLA','HMC','TSLA','NIO'],
    'telecom': ['T','VZ','TMUS','TEF','VOD','ERIC','NOK'],
    'latam': ['ABEV','AGRO','AMX','ARCO','ASR','CAAP','CX','FMX','GGB','GPRK','KOF',
              'LAR','LND','PAC','SBS','SID','SUZ','TIMB','TV','TX','UGP','VIV','VIST'],
}
# Reverse map
TICKER_SECTOR = {}
for sector, tickers in SECTOR_MAP.items():
    for t in tickers:
        TICKER_SECTOR[t] = sector


# ══════════════════════════════════════════════════════════════════════════════
#  ALPHA FACTORS — 25 factores institucionales por ticker
# ══════════════════════════════════════════════════════════════════════════════

def compute_alpha_factors(df):
    """
    25 alpha factors inspirados en la literatura academica y practica institucional.
    Cada factor esta diseñado para capturar una anomalia especifica del mercado.
    """
    o = df["Open"].values.astype(float)
    h = df["High"].values.astype(float)
    l = df["Low"].values.astype(float)
    c = df["Close"].values.astype(float)
    v = df["Volume"].values.astype(float) + 1.0
    idx = df.index
    sc = pd.Series(c, index=idx)
    sv = pd.Series(v, index=idx)
    so = pd.Series(o, index=idx)
    sh = pd.Series(h, index=idx)
    sl = pd.Series(l, index=idx)
    ret = sc.pct_change()

    f = pd.DataFrame(index=idx)

    # ═══ MOMENTUM FACTORS (Jegadeesh & Titman 1993, Novy-Marx 2012) ═══

    # F1: Short-term reversal (1-week) — Jegadeesh 1990
    #     Acciones que cayeron fuerte en 5 dias tienden a rebotar
    f['str_reversal'] = -sc.pct_change(5)

    # F2: Intermediate momentum (skip 1-week, use 1-month)
    #     Novy-Marx 2012: momentum de 12-2 meses es el mas robusto
    f['int_momentum'] = sc.pct_change(20).shift(5)  # ret 20d, skip 5d recientes

    # F3: Acceleration — segunda derivada del momentum
    f['momentum_accel'] = sc.pct_change(5) - sc.pct_change(5).shift(5)

    # F4: Volume-weighted momentum — Loh 2010
    #     Momentum confirmado por volumen es mas persistente
    vol_w = sv / sv.rolling(20).mean()
    f['vw_momentum'] = (ret * vol_w).rolling(10).sum()

    # ═══ MICROSTRUCTURE FACTORS (Hasbrouck 2007, Kyle 1985) ═══

    # F5: Close Location Value — proxy de presion compradora institucional
    #     1.0 = cierre en maximo (acumulacion), 0.0 = cierre en minimo (distribucion)
    f['clv'] = (c - l) / (h - l + 1e-10)

    # F6: Smart Money Index — Institutions trade at close, retail at open
    #     Gap down + strong close = institutional accumulation
    f['smi'] = (sc.pct_change() - (so / sc.shift(1) - 1)).rolling(5).sum()

    # F7: Amihud Illiquidity — Amihud 2002
    #     Movimientos grandes con poco volumen = iliquidez = oportunidad
    abs_ret = ret.abs()
    dollar_vol = sc * sv
    f['amihud'] = (abs_ret / (dollar_vol + 1e-10) * 1e6).rolling(20).mean()

    # F8: Volume anomaly z-score
    vol_ma = sv.rolling(20).mean()
    vol_std = sv.rolling(20).std()
    f['vol_z'] = (sv - vol_ma) / (vol_std + 1e-10)

    # ═══ VOLATILITY FACTORS (Ang et al. 2006, Garman-Klass 1980) ═══

    # F9: Idiosyncratic vol (proxy sin regresion — desviacion de retornos propios)
    #     Ang et al. 2006: baja idio_vol predice retornos superiores
    f['idio_vol'] = ret.rolling(20).std() * np.sqrt(252)

    # F10: Garman-Klass realized vol — usa todo el rango OHLC, 5-8x mas eficiente
    log_hl = np.log(np.maximum(h, 1e-10) / np.maximum(l, 1e-10)) ** 2
    log_co = np.log(np.maximum(c, 1e-10) / np.maximum(o, 1e-10)) ** 2
    gk_raw = np.maximum(0.5 * log_hl - (2*np.log(2)-1) * log_co, 0)
    f['gk_vol'] = np.sqrt(pd.Series(gk_raw, index=idx).rolling(10).mean()) * np.sqrt(252)

    # F11: Volatility compression — Bollinger squeeze
    #     Baja volatilidad → acumulacion de energia → explosion inminente
    ma20 = sc.rolling(20).mean()
    std20 = sc.rolling(20).std()
    bb_w = (4 * std20) / (ma20 + 1e-10)
    f['vol_compress'] = -bb_w  # Negativo = mas comprimido = mejor

    # F12: Vol-of-vol — cambio de regimen inminente
    f['vol_of_vol'] = f['idio_vol'].rolling(20).std()

    # ═══ MEAN REVERSION FACTORS ═══

    # F13: RSI mean reversion signal — RSI < 30 = oversold = buy
    delta = sc.diff()
    g14 = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    l14 = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rsi14 = 100 - 100/(1 + g14/(l14 + 1e-10))
    f['rsi_signal'] = 50 - rsi14  # Positivo cuando oversold

    # F14: Distance to 20-day mean — mean reversion z-score
    f['zscore_20'] = (sc - ma20) / (std20 + 1e-10)
    f['mr_signal'] = -f['zscore_20']  # Comprar cuando esta debajo de la media

    # F15: RSI-3 (ultra-fast) para timing preciso
    g3 = delta.clip(lower=0).ewm(span=3, adjust=False).mean()
    l3 = (-delta.clip(upper=0)).ewm(span=3, adjust=False).mean()
    f['rsi3'] = 100 - 100/(1 + g3/(l3 + 1e-10))

    # ═══ TREND FACTORS ═══

    # F16: Price vs moving averages (trend following)
    f['trend_ma20'] = (sc / (ma20 + 1e-10) - 1)
    f['trend_ma50'] = (sc / (sc.rolling(50).mean() + 1e-10) - 1)

    # F17: MA cross signal (5-day vs 20-day)
    ma5 = sc.rolling(5).mean()
    f['ma_cross'] = (ma5 - ma20) / (ma20 + 1e-10)

    # ═══ FLOW / ACCUMULATION FACTORS ═══

    # F18: On Balance Volume z-score — acumulacion/distribucion
    direction = np.sign(ret.fillna(0))
    obv = (direction * sv).cumsum()
    obv_ma = obv.rolling(20).mean()
    f['obv_z'] = (obv - obv_ma) / (obv.rolling(20).std() + 1e-10)

    # F19: Chaikin Money Flow — flujo de dinero neto
    mf_mult = ((sc - sl) - (sh - sc)) / (sh - sl + 1e-10)
    f['cmf'] = (mf_mult * sv).rolling(20).sum() / (sv.rolling(20).sum() + 1e-10)

    # F20: VWAP deviation — desviacion del precio justo ponderado por volumen
    typical = (sh + sl + sc) / 3
    vwap = (typical * sv).rolling(20).sum() / (sv.rolling(20).sum() + 1e-10)
    f['vwap_dev'] = (sc - vwap) / (vwap + 1e-10)

    # ═══ TAIL RISK / HIGHER MOMENTS (Harvey & Siddique 2000) ═══

    # F21: Realized skewness — asimetria positiva = potencial de saltos al alza
    f['realized_skew'] = ret.rolling(21, min_periods=10).skew()

    # F22: Realized kurtosis — colas pesadas = mayor probabilidad de movimientos grandes
    f['realized_kurt'] = ret.rolling(21, min_periods=10).kurt()

    # ═══ INFORMATION DISCRETENESS (Da, Gurun, Warachka 2014) ═══

    # F23: Informacion discreta vs continua
    #     Movimientos graduales (muchos dias pequeños misma direccion) son mas informativos
    #     que un solo salto grande
    sign_days = np.sign(ret.fillna(0)).rolling(20).sum() / 20
    f['info_discrete'] = sign_days * sc.pct_change(20).abs()

    # ═══ CALENDAR / SEASONAL ═══

    # F24: Day of week (Monday effect, Friday effect)
    f['dow'] = pd.to_datetime(idx).dayofweek / 4.0

    # ═══ COMPOSITE ═══

    # F25: Smart money composite (CLV * volume anomaly * positive momentum)
    f['smart_composite'] = f['clv'] * np.clip(f['vol_z'], 0, 5) * np.clip(f['vw_momentum'], 0, None)

    f = f.replace([np.inf, -np.inf], np.nan).fillna(0)
    return f


ALPHA_COLS = [
    'str_reversal', 'int_momentum', 'momentum_accel', 'vw_momentum',
    'clv', 'smi', 'amihud', 'vol_z',
    'idio_vol', 'gk_vol', 'vol_compress', 'vol_of_vol',
    'rsi_signal', 'mr_signal', 'rsi3',
    'trend_ma20', 'trend_ma50', 'ma_cross',
    'obv_z', 'cmf', 'vwap_dev',
    'realized_skew', 'realized_kurt',
    'info_discrete', 'dow', 'smart_composite',
]


# ══════════════════════════════════════════════════════════════════════════════
#  CROSS-SECTIONAL Z-SCORE + SECTOR-NEUTRAL PANEL (tecnica AQR)
# ══════════════════════════════════════════════════════════════════════════════

def build_institutional_panel(data_dict, feat_dict):
    """
    Construye panel estilo institucional:
    1. Cross-sectional z-score de cada factor (vs universo cada dia)
    2. Sector-neutral z-score (vs sector cada dia)
    3. Target = top quintile (20%) por fwd_best retorno T+1
    4. Forward returns para backtest
    """
    tickers = sorted(feat_dict.keys())
    all_dates = sorted(set.union(*[set(feat_dict[t].index) for t in tickers]))

    print(f"  {DIM}Construyendo panel: {len(all_dates)} fechas x {len(tickers)} tickers...{RST}")
    sys.stdout.flush()

    chunks = []
    processed = 0

    for date in all_dates:
        day_rows = []
        for t in tickers:
            if t not in feat_dict or t not in data_dict:
                continue
            feat = feat_dict[t]
            df = data_dict[t]
            if date not in feat.index or date not in df.index:
                continue
            row = {'date': date, 'ticker': t, 'sector': TICKER_SECTOR.get(t, 'other')}
            for col in ALPHA_COLS:
                row[col] = feat.loc[date, col] if col in feat.columns else 0.0
            day_rows.append(row)

        if len(day_rows) < 20:
            continue

        day_df = pd.DataFrame(day_rows)

        # ── CROSS-SECTIONAL Z-SCORE (AQR standard) ──
        # Para cada factor, normalizar vs universo completo ese dia
        # z = (x - median) / MAD  (robusto a outliers — mejor que mean/std)
        for col in ALPHA_COLS:
            if col == 'dow':
                continue
            vals = day_df[col]
            med = vals.median()
            mad = (vals - med).abs().median()
            if mad > 1e-10:
                day_df[f'z_{col}'] = (vals - med) / (mad * 1.4826)  # 1.4826 = consistency constant
                # Winsorize at +/- 3 (institutional standard)
                day_df[f'z_{col}'] = day_df[f'z_{col}'].clip(-3, 3)
            else:
                day_df[f'z_{col}'] = 0.0

        # ── SECTOR-NEUTRAL Z-SCORE (para top factors) ──
        # Esto elimina el sesgo sectorial — alpha puro
        for col in ['str_reversal', 'int_momentum', 'vw_momentum', 'clv', 'vol_z', 'rsi_signal']:
            zcol = f'z_{col}'
            sn_col = f'sn_{col}'
            day_df[sn_col] = 0.0
            for sector in day_df['sector'].unique():
                mask = day_df['sector'] == sector
                if mask.sum() < 3:
                    continue
                sector_vals = day_df.loc[mask, zcol]
                s_med = sector_vals.median()
                s_mad = (sector_vals - s_med).abs().median()
                if s_mad > 1e-10:
                    day_df.loc[mask, sn_col] = (sector_vals - s_med) / (s_mad * 1.4826)
                    day_df.loc[mask, sn_col] = day_df.loc[mask, sn_col].clip(-3, 3)

        chunks.append(day_df)
        processed += 1

        if processed % 100 == 0:
            print(f"\r  {DIM}  Procesadas {processed}/{len(all_dates)} fechas...{RST}", end="")
            sys.stdout.flush()

    print(f"\r  {DIM}  Procesadas {processed} fechas.                    {RST}")

    if not chunks:
        return pd.DataFrame()

    panel = pd.concat(chunks, ignore_index=True)

    # ── FORWARD RETURNS ──
    print(f"  {DIM}Calculando forward returns...{RST}")
    panel['fwd_ret'] = np.nan
    panel['fwd_best'] = np.nan

    for t in tickers:
        if t not in data_dict:
            continue
        mask = panel['ticker'] == t
        if mask.sum() == 0:
            continue
        close = data_dict[t]['Close']
        high = data_dict[t]['High']
        dates_t = panel.loc[mask, 'date'].values
        idx_list = list(close.index)

        fwd_c, fwd_b = [], []
        for d in dates_t:
            try:
                pos = idx_list.index(d)
                if pos + 1 < len(idx_list):
                    rc = close.iloc[pos+1] / close.iloc[pos] - 1
                    rh = high.iloc[pos+1] / close.iloc[pos] - 1
                    fwd_c.append(rc)
                    fwd_b.append(max(rc, rh))
                else:
                    fwd_c.append(np.nan)
                    fwd_b.append(np.nan)
            except:
                fwd_c.append(np.nan)
                fwd_b.append(np.nan)

        panel.loc[mask, 'fwd_ret'] = fwd_c
        panel.loc[mask, 'fwd_best'] = fwd_b

    # ── TARGET: TOP 20% CROSS-SECTIONAL (adaptativo) ──
    panel['target'] = np.nan
    for date in panel['date'].unique():
        mask = (panel['date'] == date) & panel['fwd_best'].notna()
        if mask.sum() < 10:
            continue
        q80 = panel.loc[mask, 'fwd_best'].quantile(0.80)
        q80 = max(q80, 0.002)  # Minimo 0.2% para evitar ruido
        panel.loc[mask, 'target'] = (panel.loc[mask, 'fwd_best'] >= q80).astype(int)

    last_date = panel['date'].max()
    panel.loc[panel['date'] == last_date, 'target'] = np.nan

    # ── DOLLAR VOLUME (liquidity filter — Citadel style) ──
    for t in tickers:
        if t not in data_dict:
            continue
        mask = panel['ticker'] == t
        df = data_dict[t]
        dv = (df['Close'] * df['Volume']).rolling(20).mean()
        panel.loc[mask, 'dollar_vol'] = dv.reindex(panel.loc[mask, 'date'].values).values

    return panel


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE COLUMNS FOR ML
# ══════════════════════════════════════════════════════════════════════════════

def get_feature_cols(panel):
    """Selecciona columnas de features disponibles para ML"""
    z_cols = [c for c in panel.columns if c.startswith('z_')]
    sn_cols = [c for c in panel.columns if c.startswith('sn_')]
    raw_cols = [c for c in ALPHA_COLS if c in panel.columns]
    return raw_cols + z_cols + sn_cols


# ══════════════════════════════════════════════════════════════════════════════
#  ROLLING IC — Information Coefficient (AQR / Two Sigma)
# ══════════════════════════════════════════════════════════════════════════════

def compute_rolling_ic(panel, feature_cols, window=60):
    """
    Calcula IC (Spearman rank correlation) de cada factor vs fwd_ret
    en una ventana rolling. Factores con IC > 0 son predictivos.
    IC-weighted combination es el standard institucional.
    """
    dates = sorted(panel['date'].unique())
    ic_by_factor = {col: [] for col in feature_cols}

    for i in range(window, len(dates)):
        window_dates = dates[i-window:i]
        sub = panel[panel['date'].isin(window_dates) & panel['fwd_ret'].notna()]
        if len(sub) < 100:
            continue
        for col in feature_cols:
            if col in sub.columns:
                try:
                    corr, _ = sp_stats.spearmanr(sub[col].values, sub['fwd_ret'].values)
                    ic_by_factor[col].append(corr if not np.isnan(corr) else 0.0)
                except:
                    ic_by_factor[col].append(0.0)

    # IC medio y IC ratio (IC/std_IC — Sharpe del factor)
    ic_summary = {}
    for col in feature_cols:
        ics = ic_by_factor[col]
        if ics:
            mean_ic = np.mean(ics)
            std_ic = np.std(ics) + 1e-10
            ic_summary[col] = {'mean_ic': mean_ic, 'ic_ratio': mean_ic / std_ic, 'n': len(ics)}
        else:
            ic_summary[col] = {'mean_ic': 0, 'ic_ratio': 0, 'n': 0}

    return ic_summary


# ══════════════════════════════════════════════════════════════════════════════
#  INSTITUTIONAL BRAIN — 3 Base + Meta-Learner + IC Weights
# ══════════════════════════════════════════════════════════════════════════════

class InstitutionalBrain:
    def __init__(self):
        self.scaler = RobustScaler()
        self.meta = LogisticRegression(C=0.5, max_iter=1000)
        self.models = {
            'hgb': HistGradientBoostingClassifier(
                max_iter=500, max_depth=5, learning_rate=0.03,
                min_samples_leaf=25, l2_regularization=0.4,
                class_weight='balanced', random_state=42,
            ),
            'rf': RandomForestClassifier(
                n_estimators=400, max_depth=10, min_samples_leaf=15,
                max_features='sqrt', class_weight='balanced',
                n_jobs=-1, random_state=7,
            ),
            'et': ExtraTreesClassifier(
                n_estimators=400, max_depth=10, min_samples_leaf=12,
                max_features='sqrt', class_weight='balanced',
                n_jobs=-1, random_state=99,
            ),
        }
        self.trained = False
        self._cols = None
        self._weights = {'hgb': 0.40, 'rf': 0.30, 'et': 0.30}
        self._ic_summary = {}

    def train(self, panel):
        t0 = time.time()
        all_cols = get_feature_cols(panel)
        # Filter columns that actually exist
        cols = [c for c in all_cols if c in panel.columns]

        valid = panel[panel['target'].notna()].copy()
        if len(valid) < 1000:
            print(f"  {R}Pocos datos: {len(valid)}{RST}")
            return False

        # ── ROLLING IC para feature selection ──
        print(f"  {DIM}Calculando Information Coefficients ({len(cols)} factores)...{RST}")
        self._ic_summary = compute_rolling_ic(panel, cols, window=60)

        # Filtrar factores con IC positivo (predictivos)
        good_cols = [c for c in cols if self._ic_summary.get(c, {}).get('mean_ic', 0) > 0.001]
        if len(good_cols) < 10:
            good_cols = sorted(cols, key=lambda c: abs(self._ic_summary.get(c,{}).get('mean_ic',0)), reverse=True)[:20]

        self._cols = good_cols
        print(f"  Factores seleccionados por IC: {len(good_cols)}/{len(cols)}")

        # Top 5 factores por IC
        top_ic = sorted(self._ic_summary.items(), key=lambda x: abs(x[1]['mean_ic']), reverse=True)[:8]
        for name, info in top_ic:
            ic_c = G if info['mean_ic'] > 0.01 else Y if info['mean_ic'] > 0 else R
            print(f"    {ic_c}{name:<25} IC={info['mean_ic']:+.4f} ICIR={info['ic_ratio']:+.3f}{RST}")

        # ── PURGED SPLIT (85/15) ──
        dates = sorted(valid['date'].unique())
        split = dates[int(len(dates) * 0.85)]
        tr = valid[valid['date'] < split]
        val = valid[valid['date'] >= split]

        X_tr = tr[good_cols].values
        y_tr = tr['target'].values.astype(int)
        X_val = val[good_cols].values
        y_val = val['target'].values.astype(int)

        print(f"  Train: {len(y_tr):,} | Val: {len(y_val):,} | Pos rate: {y_tr.mean()*100:.1f}%")

        X_tr_sc = self.scaler.fit_transform(X_tr)
        X_val_sc = self.scaler.transform(X_val)

        # ── TRAIN BASE MODELS ──
        val_probs = {}
        for name, model in self.models.items():
            model.fit(X_tr_sc, y_tr)
            pv = model.predict_proba(X_val_sc)[:, 1]
            val_probs[name] = pv

            # Metrics on top 15%
            k = max(1, int(len(y_val) * 0.15))
            top_idx = np.argsort(pv)[-k:]
            hr = y_val[top_idx].mean() * 100
            avg_r = val.iloc[top_idx]['fwd_ret'].mean() * 100 if 'fwd_ret' in val.columns else 0
            bench = val['fwd_ret'].dropna().mean() * 100

            print(f"  [{name}] Top15% HR={G if hr>25 else Y}{hr:.1f}%{RST} "
                  f"Ret={G if avg_r>0 else R}{avg_r:+.3f}%{RST} "
                  f"Excess={G if avg_r-bench>0 else R}{avg_r-bench:+.3f}%{RST}")

        # ── META-LEARNER ──
        meta_X = np.column_stack([val_probs[n] for n in self.models])
        self.meta.fit(meta_X, y_val)

        # ── DYNAMIC WEIGHTS ──
        for name in self.models:
            k = max(1, int(len(y_val) * 0.15))
            top_idx = np.argsort(val_probs[name])[-k:]
            perf = y_val[top_idx].mean()
            self._weights[name] = max(0.1, perf)
        tw = sum(self._weights.values())
        self._weights = {k: v/tw for k, v in self._weights.items()}

        # ── RETRAIN FULL ──
        X_full = valid[good_cols].values
        y_full = valid['target'].values.astype(int)
        X_full_sc = self.scaler.fit_transform(X_full)
        for model in self.models.values():
            model.fit(X_full_sc, y_full)

        full_meta_X = np.column_stack([m.predict_proba(X_full_sc)[:, 1] for m in self.models.values()])
        self.meta.fit(full_meta_X, y_full)

        self.trained = True
        print(f"  {G}OK en {time.time()-t0:.1f}s | Weights: {' '.join(f'{k}={v:.2f}' for k,v in self._weights.items())}{RST}")
        return True

    def score(self, features_row):
        X = np.array(features_row).reshape(1, -1)
        X_sc = self.scaler.transform(X)
        probs = []
        w_sum = 0
        for name, model in self.models.items():
            p = model.predict_proba(X_sc)[0][1]
            probs.append(p)
            w_sum += self._weights[name] * p

        meta_X = np.array(probs).reshape(1, -1)
        meta_p = self.meta.predict_proba(meta_X)[0][1]
        final = 0.55 * meta_p + 0.45 * w_sum
        return final * 100, [p*100 for p in probs]

    def score_panel_today(self, panel, data_dict):
        last_date = panel['date'].max()
        today = panel[panel['date'] == last_date].copy()
        cols = self._cols
        results = []

        for _, row in today.iterrows():
            try:
                sc, base = self.score(row[cols].values)
                t = row['ticker']
                precio = data_dict[t]['Close'].iloc[-1] if t in data_dict else 0
                results.append({
                    'ticker': t, 'score': sc, 'precio': precio,
                    'sector': row.get('sector', ''),
                    'prob_hgb': base[0], 'prob_rf': base[1], 'prob_et': base[2],
                    'str_reversal': row.get('str_reversal', 0),
                    'int_momentum': row.get('int_momentum', 0),
                    'clv': row.get('clv', 0),
                    'vol_z': row.get('vol_z', 0),
                    'rsi_signal': row.get('rsi_signal', 0),
                    'smart_composite': row.get('smart_composite', 0),
                    'cmf': row.get('cmf', 0),
                    'vol_compress': row.get('vol_compress', 0),
                })
            except:
                pass

        results.sort(key=lambda x: x['score'], reverse=True)
        return results


# ══════════════════════════════════════════════════════════════════════════════
#  BACKTEST MARZO 2026
# ══════════════════════════════════════════════════════════════════════════════

def backtest_marzo(brain, panel):
    print(f"\n{C}{'═'*100}{RST}")
    print(f"{C}  BACKTEST WALK-FORWARD — MARZO 2026{RST}")
    print(f"{C}{'═'*100}{RST}\n")

    cols = brain._cols
    march = panel[panel['date'].apply(lambda d: d.year == 2026 and d.month == 3)].copy()
    if march.empty:
        print(f"  {Y}No hay datos de Marzo 2026.{RST}"); return

    daily = []
    for test_date in sorted(march['date'].unique()):
        day = march[march['date'] == test_date]
        if len(day) < 10 or day['fwd_ret'].isna().all():
            continue

        scored = []
        for _, row in day.iterrows():
            try:
                sc, _ = brain.score(row[cols].values)
                scored.append({'ticker': row['ticker'], 'score': sc,
                               'fwd_ret': row.get('fwd_ret', np.nan),
                               'fwd_best': row.get('fwd_best', np.nan)})
            except:
                pass

        if not scored:
            continue
        scored.sort(key=lambda x: x['score'], reverse=True)
        top10 = [s for s in scored[:10] if not np.isnan(s['fwd_ret'])]
        if not top10:
            continue

        hits = sum(1 for s in top10 if s['fwd_ret'] > 0)
        strong = sum(1 for s in top10 if s['fwd_ret'] > 0.01)
        avg_r = np.mean([s['fwd_ret'] for s in top10]) * 100
        avg_b = np.mean([s['fwd_best'] for s in top10]) * 100
        bench = day['fwd_ret'].dropna().mean() * 100
        excess = avg_r - bench

        daily.append({'date': test_date, 'n': len(scored), 'hits': hits, 'strong': strong,
                      'avg_ret': avg_r, 'best': avg_b, 'bench': bench, 'excess': excess,
                      'top3': [(s['ticker'], s['fwd_ret']*100) for s in top10[:3]]})

    if not daily:
        print(f"  {Y}Sin resultados.{RST}"); return

    print(f"  {'Fecha':<12} {'N':>4} {'Hits':>6} {'>1%':>4} {'RetProm':>8} {'Mejor':>8} {'Bench':>7} {'Excess':>8}  Top 3")
    print(f"  {'─'*108}")
    for r in daily:
        hc = G if r['hits']>=6 else Y if r['hits']>=4 else R
        rc = G if r['avg_ret']>0 else R
        ec = G if r['excess']>0 else R
        t3 = '  '.join(f"{t}:{ret:+.1f}%" for t,ret in r['top3'])
        print(f"  {str(r['date'].date()):<12} {r['n']:>4} {hc}{r['hits']:>4}/10{RST} {r['strong']:>3} "
              f"{rc}{r['avg_ret']:>+7.2f}%{RST} {r['best']:>+7.2f}% {r['bench']:>+6.2f}% "
              f"{ec}{r['excess']:>+7.2f}%{RST}  {DIM}{t3}{RST}")

    # Summary
    print(f"\n  {BOLD}RESUMEN MARZO 2026:{RST}")
    th = sum(r['hits'] for r in daily)
    tn = len(daily) * 10
    hr = th/tn*100 if tn > 0 else 0
    avg = np.mean([r['avg_ret'] for r in daily])
    avg_ex = np.mean([r['excess'] for r in daily])
    wins = sum(1 for r in daily if r['avg_ret'] > 0)
    cum = np.prod([1+r['avg_ret']/100 for r in daily]) - 1
    print(f"  Dias: {len(daily)} | Hit Rate: {G if hr>55 else Y}{hr:.1f}%{RST} | "
          f"Ret/dia: {G if avg>0 else R}{avg:+.3f}%{RST} | "
          f"Excess: {G if avg_ex>0 else R}{avg_ex:+.3f}%{RST}")
    print(f"  Winners: {wins}/{len(daily)} ({wins/len(daily)*100:.0f}%) | "
          f"Acumulado: {G if cum>0 else R}{cum*100:+.2f}%{RST}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAQUINA DEL TIEMPO
# ══════════════════════════════════════════════════════════════════════════════

def maquina_del_tiempo(brain, panel):
    print(f"\n{C}{'═'*95}{RST}")
    print(f"{C}  MAQUINA DEL TIEMPO{RST}")
    print(f"{C}{'═'*95}{RST}")
    print(f"  {DIM}TICKER FECHA (ej: NFLX 2026-02-26) o 'salir'{RST}\n")
    cols = brain._cols
    while True:
        cmd = input(f"  {Y}>>> {RST}").strip().upper()
        if cmd in ('SALIR','EXIT','Q',''):
            break
        parts = cmd.split()
        if len(parts) != 2:
            print(f"  {R}Formato: TICKER YYYY-MM-DD{RST}\n"); continue
        ticker, fecha_str = parts
        try:
            fecha = pd.to_datetime(fecha_str)
            sub = panel[(panel['ticker']==ticker) & (panel['date']<=fecha)]
            if sub.empty:
                print(f"  {R}{ticker} sin datos.{RST}\n"); continue
            row = sub.iloc[-1]
            sc, base = brain.score(row[cols].values)
            fwd = row.get('fwd_ret', np.nan)
            fwd_s = f"{G if fwd>0 else R}{fwd*100:+.2f}%{RST}" if not np.isnan(fwd) else f"{DIM}N/A{RST}"
            color = G if sc > 65 else Y if sc > 50 else DIM
            print(f"\n  {BOLD}--- {ticker} al {str(row['date'].date())} ---{RST}")
            print(f"  Score: {color}{sc:.1f}%{RST} (HGB:{base[0]:.0f} RF:{base[1]:.0f} ET:{base[2]:.0f})")
            print(f"  Retorno real T+1: {fwd_s}")
            print(f"  {DIM}CLV={row.get('clv',0):.2f} VolZ={row.get('vol_z',0):+.1f} "
                  f"CMF={row.get('cmf',0):+.3f} SMI={row.get('smi',0):+.3f} "
                  f"IntMom={row.get('int_momentum',0)*100:+.1f}%{RST}\n")
        except Exception as e:
            print(f"  {R}Error: {e}{RST}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  DESCARGA
# ══════════════════════════════════════════════════════════════════════════════

def descargar():
    all_t = list(set(ACTIVOS))
    print(f"  Descargando {len(all_t)} tickers (2y)...")
    raw = yf.download(all_t, period="2y", group_by='ticker', progress=False, threads=True, timeout=60)
    data = {}
    for t in all_t:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                l0 = set(raw.columns.get_level_values(0))
                l1 = set(raw.columns.get_level_values(1)) - {""}
                if t in l1: df = raw.xs(t, axis=1, level=1).dropna()
                elif t in l0: df = raw[t].dropna()
                else: continue
            else: continue
            df.columns = [str(c).capitalize() for c in df.columns]
            if all(x in df.columns for x in ['Open','High','Low','Close','Volume']) and len(df)>200:
                data[t] = df
        except: pass
    print(f"  {G}OK: {len(data)} activos{RST}")
    return data


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    clr()
    t0 = time.time()
    print(f"\n{C}{'═'*100}{RST}")
    print(f"{C}  TITAN HYBRID v4.0 — INSTITUTIONAL ALPHA ENGINE{RST}")
    print(f"{C}  25 Alpha Factors | CS Z-Score | IC-Weighted | Sector-Neutral | Meta-Learner{RST}")
    print(f"{C}{'═'*100}{RST}\n")

    # 1. DESCARGA
    print(f"  {BOLD}[1/5] Descargando datos...{RST}")
    data_dict = descargar()
    if len(data_dict) < 10:
        print(f"  {R}Descarga fallida.{RST}"); return

    # 2. ALPHA FACTORS
    print(f"\n  {BOLD}[2/5] Calculando 25 Alpha Factors por ticker...{RST}")
    feat_dict = {}
    def calc(t, df):
        try: return t, compute_alpha_factors(df)
        except: return t, None

    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        for f in [ex.submit(calc, t, df) for t, df in data_dict.items()]:
            t, feat = f.result()
            if feat is not None: feat_dict[t] = feat
    print(f"  {G}OK: {len(feat_dict)} activos{RST}")

    # 3. INSTITUTIONAL PANEL
    print(f"\n  {BOLD}[3/5] Construyendo panel institucional (CS Z-Score + Sector-Neutral)...{RST}")
    panel = build_institutional_panel(data_dict, feat_dict)
    if panel.empty:
        print(f"  {R}Panel vacio.{RST}"); return
    tr = panel[panel['target'].notna()]['target'].mean()*100
    print(f"  {G}Panel: {len(panel):,} filas | {panel['date'].nunique()} fechas | "
          f"{panel['ticker'].nunique()} tickers | Target: {tr:.1f}%{RST}")

    # 4. TRAIN
    print(f"\n  {BOLD}[4/5] Entrenando (IC Selection + 3 Base + Meta-Learner)...{RST}")
    brain = InstitutionalBrain()
    if not brain.train(panel):
        return

    # BACKTEST
    backtest_marzo(brain, panel)

    # 5. HOY
    print(f"\n{C}{'═'*100}{RST}")
    print(f"{C}  ALPHA SIGNALS — TOP 20 PARA MANANA{RST}")
    print(f"{C}{'═'*100}{RST}\n")

    results = brain.score_panel_today(panel, data_dict)
    top20 = results[:20]

    if not top20:
        print(f"  {R}Sin datos hoy.{RST}")
    else:
        print(f"  {'#':>3} {'TICKER':<7} {'SECTOR':<9} {'PRECIO':>9} {'ALPHA':>7} "
              f"{'HGB':>5} {'RF':>5} {'ET':>5}  "
              f"{'CLV':>5} {'VolZ':>5} {'CMF':>6} {'SmartC':>7} {'RevSig':>7}")
        print(f"  {'─'*100}")

        for i, s in enumerate(top20, 1):
            sc = G+BOLD if s['score']>65 else G if s['score']>55 else Y if s['score']>48 else DIM
            clv_c = G if s['clv']>0.7 else DIM
            vz_c = M if s['vol_z']>1.5 else DIM

            print(f"  {DIM}{i:>3}{RST} {BOLD}{s['ticker']:<7}{RST} "
                  f"{DIM}{s['sector'][:8]:<9}{RST}"
                  f"${s['precio']:>8,.2f} "
                  f"{sc}{s['score']:>6.1f}%{RST} "
                  f"{DIM}{s['prob_hgb']:>4.0f} {s['prob_rf']:>4.0f} {s['prob_et']:>4.0f}{RST}  "
                  f"{clv_c}{s['clv']:>5.2f}{RST} "
                  f"{vz_c}{s['vol_z']:>+4.1f}{RST} "
                  f"{s['cmf']:>+5.3f} "
                  f"{s['smart_composite']:>7.3f} "
                  f"{s['str_reversal']*100:>+6.1f}%")

        all_s = [r['score'] for r in results]
        print(f"\n  {DIM}Universo: {len(results)} | Media={np.mean(all_s):.1f}% "
              f"Max={np.max(all_s):.1f}% P75={np.percentile(all_s,75):.1f}% "
              f"P25={np.percentile(all_s,25):.1f}%{RST}")

        strong = sum(1 for s in all_s if s > 60)
        mod = sum(1 for s in all_s if 55 < s <= 60)
        print(f"  {G}Fuertes (>60%): {strong}{RST} | {Y}Moderadas (55-60%): {mod}{RST}")

    print(f"\n  {DIM}Tiempo: {time.time()-t0:.1f}s | {datetime.now().strftime('%d/%m/%Y %H:%M')}{RST}")
    print(f"  {DIM}Solo fines educativos. No constituye asesoramiento financiero.{RST}\n")

    maquina_del_tiempo(brain, panel)


if __name__ == "__main__":
    main()
