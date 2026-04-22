#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔═══════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                       ║
║   ████████╗██╗████████╗ █████╗ ███╗   ██╗    ██╗   ██╗███████╗                        ║
║   ╚══██╔══╝██║╚══██╔══╝██╔══██╗████╗  ██║    ██║   ██║██╔════╝                        ║
║      ██║   ██║   ██║   ███████║██╔██╗ ██║    ██║   ██║███████╗                        ║
║      ██║   ██║   ██║   ██╔══██║██║╚██╗██║    ╚██╗ ██╔╝╚════██║                        ║
║      ██║   ██║   ██║   ██║  ██║██║ ╚████║     ╚████╔╝ ███████║                        ║
║      ╚═╝   ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝      ╚═══╝  ╚══════╝                        ║
║                                                                                       ║
║   QUANTUM ALPHA ENGINE v5.0 — INSTITUTIONAL DEEP LEARNING TRADING SYSTEM              ║
║                                                                                       ║
╠═══════════════════════════════════════════════════════════════════════════════════════╣
║                                                                                       ║
║   ARQUITECTURA MULTI-CAPA:                                                            ║
║                                                                                       ║
║   CAPA 1 — ALPHA FACTORS (42 factores)                                                ║
║     ◆ Momentum: STR, Intermediate, Acceleration, Volume-Weighted, 52w High            ║
║     ◆ Microstructure: CLV, SMI, Amihud, OFI, Kyle Lambda                              ║
║     ◆ Volatility: Idio, Garman-Klass, Parkinson, Squeeze, VolOfVol                   ║
║     ◆ Mean-Reversion: RSI(3,14), Z-Score, Bollinger %B                                ║
║     ◆ Flow: OBV-Z, CMF, VWAP-Dev, MFI                                                 ║
║     ◆ Tail Risk: Skew, Kurtosis, Max Drawdown, CVaR                                   ║
║     ◆ Cross-Asset: Beta-SPY, Corr-VIX, Sector-RS, Risk-On/Off                         ║
║                                                                                       ║
║   CAPA 2 — CROSS-SECTIONAL NORMALIZATION                                              ║
║     ◆ AQR: Robust Z-Score (MAD-based) winsorized ±3σ                                 ║
║     ◆ Sector-Neutral Alpha (elimina sesgo sectorial)                                   ║
║     ◆ Rolling IC Feature Selection (descarta factores muertos)                         ║
║                                                                                       ║
║   CAPA 3 — REGIME DETECTION                                                           ║
║     ◆ Cross-Asset: SPY/VIX/TLT/GLD/HYG regime clustering                             ║
║     ◆ Volatility Regime: Low/Medium/High/Crisis                                        ║
║     ◆ Trend Regime: Bull/Bear/Sideways via SPY trend                                   ║
║     ◆ Conditional alpha (diferentes pesos por regime)                                  ║
║                                                                                       ║
║   CAPA 4 — ENSEMBLE ML (7 modelos + Meta-Learner)                                     ║
║     ◆ HistGradientBoosting (sklearn)                                                   ║
║     ◆ XGBoost (gradient boosting trees)                                                ║
║     ◆ LightGBM (leaf-wise gradient boosting)                                           ║
║     ◆ Random Forest                                                                    ║
║     ◆ Extra Trees                                                                      ║
║     ◆ LSTM + Attention (PyTorch deep learning)                                         ║
║     ◆ Logistic Regression (linear baseline)                                            ║
║     ◆ Meta-Learner: Stacked generalization + IC-weighted blend                         ║
║                                                                                       ║
║   CAPA 5 — MULTI-HORIZON SCORING                                                      ║
║     ◆ T+1 (next day), T+2, T+3 predictions                                            ║
║     ◆ Composite score = weighted average across horizons                               ║
║     ◆ Conviction = model agreement across horizons                                     ║
║                                                                                       ║
║   CAPA 6 — RISK-ADJUSTED RANKING                                                      ║
║     ◆ Liquidity filter (dollar volume > $5M/day)                                       ║
║     ◆ Risk-adjusted alpha (score / idio_vol)                                           ║
║     ◆ Sector diversification constraint                                                ║
║     ◆ Correlation-aware portfolio construction                                         ║
║                                                                                       ║
║   PIPELINE:                                                                           ║
║     Raw OHLCV → 42 Factors → CS Z-Score → Regime Detection →                         ║
║     IC Selection → 7 ML Models → Meta-Learner → Multi-Horizon →                      ║
║     Risk-Adjusted Rank → Sector-Diversified TOP 10                                    ║
║                                                                                       ║
║   REQUISITOS:                                                                         ║
║     pip install yfinance numpy pandas scikit-learn scipy xgboost lightgbm torch       ║
║                                                                                       ║
╚═══════════════════════════════════════════════════════════════════════════════════════╝
"""

import os, warnings, time, sys, gc
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from scipy import stats as sp_stats

from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    ExtraTreesClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import RobustScaler

import xgboost as xgb
import lightgbm as lgb

import torch
import torch.nn as nn

warnings.filterwarnings("ignore")

# ─── UI ──────────────────────────────────────────────────────────────────────
R = "\033[91m"; G = "\033[92m"; Y = "\033[93m"; M = "\033[95m"
C = "\033[96m"; W = "\033[97m"; DIM = "\033[2m"; BOLD = "\033[1m"; RST = "\033[0m"
B_BG = "\033[44m"; G_BG = "\033[42m"

def clr():
    os.system("cls" if os.name == "nt" else "clear")

def barra(v, mx=100, n=25):
    f = max(0, min(n, int(v / mx * n)))
    c = G if v > 65 else Y if v > 50 else DIM
    return f"{c}{'█' * f}{DIM}{'░' * (n - f)}{RST}"

def fmt_pct(v, plus=True):
    if np.isnan(v):
        return f"{DIM}  N/A{RST}"
    c = G if v > 0 else R if v < 0 else DIM
    s = f"{v:+.2f}%" if plus else f"{v:.2f}%"
    return f"{c}{s}{RST}"


# ═══════════════════════════════════════════════════════════════════════════════
#  UNIVERSO — 260+ activos globales
# ═══════════════════════════════════════════════════════════════════════════════

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
    'SE','SHEL','SHOP','SID','SIEGY','SLB','SNA','SNAP',
    'SNOW','SONY','SPGI','SPOT','STLA','STNE','SUZ','SWKS',
    'SYY','T','TCOM','TEF','TGT','TIMB','TJX','TMO',
    'TMUS','TRIP','TRV','TS','TSLA','TSM','TTE','TV','TWLO','TX',
    'TXN','UGP','UL','UNH','UNP','URBN','USB','V','VALE','VIST',
    'VIV','VOD','VRSN','VZ','WFC','WMT','XOM',
    'XP','XRX','YELP','ZM',
]

# Context assets for regime detection
CONTEXT = ['SPY', 'QQQ', 'IWM', 'VIX', 'TLT', 'GLD', 'HYG', 'UUP', 'XLE', 'XLF', 'XLK', 'XLV']

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
                   'AVY','GRMN','SNA','PCAR','HWM','JCI','UNP','SYY','IP','GLW','GT',
                   'CAR','STLA','HMC','TSLA','NIO'],
    'telecom': ['T','VZ','TMUS','TEF','VOD','ERIC','NOK'],
    'latam': ['ABEV','AGRO','AMX','ARCO','ASR','CAAP','CX','FMX','GGB','GPRK','KOF',
              'LAR','LND','PAC','SBS','SID','SUZ','TIMB','TV','TX','UGP','VIV','VIST'],
}

TICKER_SECTOR = {}
for sector, tickers in SECTOR_MAP.items():
    for t in tickers:
        TICKER_SECTOR[t] = sector


# ═══════════════════════════════════════════════════════════════════════════════
#  REGIME DETECTION — Cross-Asset Macro Regime (Bridgewater / Man AHL style)
# ═══════════════════════════════════════════════════════════════════════════════

class RegimeDetector:
    """
    Detecta el regimen macroeconomico usando cross-asset signals.
    Regimenes: RISK_ON, RISK_OFF, TRANSITION, CRISIS

    Inspirado en:
    - Bridgewater All-Weather framework
    - Man AHL regime-switching models
    - JP Morgan Cross-Asset Momentum
    """

    def __init__(self):
        self.regime_history = []
        self.current_regime = 'UNKNOWN'
        self.regime_features = {}

    def detect(self, context_data):
        """Clasifica el regimen actual basado en cross-asset signals"""
        regimes = {}

        # ── SPY trend regime ──
        if 'SPY' in context_data:
            spy = context_data['SPY']['Close']
            spy_ret_5d = spy.pct_change(5).iloc[-1] if len(spy) > 5 else 0
            spy_ret_20d = spy.pct_change(20).iloc[-1] if len(spy) > 20 else 0
            spy_ma50 = spy.rolling(50).mean().iloc[-1] if len(spy) > 50 else spy.iloc[-1]
            spy_ma200 = spy.rolling(200).mean().iloc[-1] if len(spy) > 200 else spy.iloc[-1]

            if spy.iloc[-1] > spy_ma50 > spy_ma200:
                regimes['trend'] = 'BULL'
            elif spy.iloc[-1] < spy_ma50 < spy_ma200:
                regimes['trend'] = 'BEAR'
            else:
                regimes['trend'] = 'SIDEWAYS'

            regimes['spy_momentum'] = spy_ret_20d

        # ── VIX volatility regime ──
        if 'VIX' in context_data:
            vix = context_data['VIX']['Close']
            vix_now = vix.iloc[-1]
            vix_ma20 = vix.rolling(20).mean().iloc[-1] if len(vix) > 20 else vix_now

            if vix_now > 30:
                regimes['vol'] = 'CRISIS'
            elif vix_now > 20:
                regimes['vol'] = 'HIGH'
            elif vix_now > 14:
                regimes['vol'] = 'MEDIUM'
            else:
                regimes['vol'] = 'LOW'

            regimes['vix_level'] = vix_now
            regimes['vix_trend'] = vix_now / vix_ma20 - 1

        # ── Credit regime (HYG) ──
        if 'HYG' in context_data:
            hyg = context_data['HYG']['Close']
            hyg_ret = hyg.pct_change(10).iloc[-1] if len(hyg) > 10 else 0
            regimes['credit'] = 'TIGHT' if hyg_ret < -0.01 else 'LOOSE'
            regimes['hyg_momentum'] = hyg_ret

        # ── Safe haven demand (TLT/GLD) ──
        if 'TLT' in context_data:
            tlt = context_data['TLT']['Close']
            tlt_ret = tlt.pct_change(10).iloc[-1] if len(tlt) > 10 else 0
            regimes['bonds'] = 'BID' if tlt_ret > 0.01 else 'OFFERED'
            regimes['tlt_momentum'] = tlt_ret

        if 'GLD' in context_data:
            gld = context_data['GLD']['Close']
            gld_ret = gld.pct_change(10).iloc[-1] if len(gld) > 10 else 0
            regimes['gold'] = 'BID' if gld_ret > 0.01 else 'OFFERED'
            regimes['gld_momentum'] = gld_ret

        # ── Dollar regime (UUP) ──
        if 'UUP' in context_data:
            uup = context_data['UUP']['Close']
            uup_ret = uup.pct_change(10).iloc[-1] if len(uup) > 10 else 0
            regimes['dollar'] = 'STRONG' if uup_ret > 0.005 else 'WEAK'
            regimes['uup_momentum'] = uup_ret

        # ── Risk-On / Risk-Off composite score ──
        risk_score = 0.0
        if 'spy_momentum' in regimes:
            risk_score += np.clip(regimes['spy_momentum'] * 10, -2, 2)
        if 'vix_trend' in regimes:
            risk_score -= np.clip(regimes['vix_trend'] * 5, -2, 2)
        if 'hyg_momentum' in regimes:
            risk_score += np.clip(regimes['hyg_momentum'] * 10, -1, 1)
        if 'tlt_momentum' in regimes:
            risk_score -= np.clip(regimes['tlt_momentum'] * 5, -1, 1)

        if risk_score > 1.5:
            regimes['composite'] = 'RISK_ON'
        elif risk_score < -1.5:
            regimes['composite'] = 'RISK_OFF'
        elif regimes.get('vol') == 'CRISIS':
            regimes['composite'] = 'CRISIS'
        else:
            regimes['composite'] = 'TRANSITION'

        regimes['risk_score'] = risk_score

        self.current_regime = regimes.get('composite', 'UNKNOWN')
        self.regime_features = regimes
        return regimes


# ═══════════════════════════════════════════════════════════════════════════════
#  ALPHA FACTORS — 42 factores institucionales
# ═══════════════════════════════════════════════════════════════════════════════

def compute_alpha_factors(df, context_data=None):
    """
    42 alpha factors: momentum, microstructure, volatility, mean-reversion,
    flow, tail risk, cross-asset. Cada uno captura una anomalia especifica.
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

    # ═══ MOMENTUM FACTORS ═══

    # F1: Short-term reversal (1-week) — Jegadeesh 1990
    f['str_reversal'] = -sc.pct_change(5)

    # F2: Intermediate momentum (skip 1-week, 1-month) — Novy-Marx 2012
    f['int_momentum'] = sc.pct_change(20).shift(5)

    # F3: Acceleration — 2nd derivative of momentum
    f['momentum_accel'] = sc.pct_change(5) - sc.pct_change(5).shift(5)

    # F4: Volume-weighted momentum — Loh 2010
    vol_w = sv / sv.rolling(20).mean()
    f['vw_momentum'] = (ret * vol_w).rolling(10).sum()

    # F5: 52-week high proximity — George & Hwang 2004
    high_52w = sh.rolling(252, min_periods=60).max()
    f['high_52w_pct'] = sc / (high_52w + 1e-10)

    # F6: Earnings momentum proxy (20d ret vs 60d ret gap)
    f['ret_gap'] = sc.pct_change(20) - sc.pct_change(60) / 3

    # ═══ MICROSTRUCTURE FACTORS ═══

    # F7: Close Location Value — proxy de presion compradora
    f['clv'] = (c - l) / (h - l + 1e-10)

    # F8: Smart Money Index — institutional close vs retail open
    f['smi'] = (sc.pct_change() - (so / sc.shift(1) - 1)).rolling(5).sum()

    # F9: Amihud Illiquidity — Amihud 2002
    abs_ret = ret.abs()
    dollar_vol = sc * sv
    f['amihud'] = (abs_ret / (dollar_vol + 1e-10) * 1e6).rolling(20).mean()

    # F10: Volume anomaly z-score
    vol_ma = sv.rolling(20).mean()
    vol_std = sv.rolling(20).std()
    f['vol_z'] = (sv - vol_ma) / (vol_std + 1e-10)

    # F11: Order Flow Imbalance proxy
    # Buy volume when close > open, sell when close < open
    buy_vol = sv.where(sc > so, 0)
    sell_vol = sv.where(sc < so, 0)
    f['ofi'] = (buy_vol.rolling(5).sum() - sell_vol.rolling(5).sum()) / (sv.rolling(5).sum() + 1e-10)

    # F12: Kyle Lambda proxy — price impact per unit volume
    f['kyle_lambda'] = (ret.abs() / (sv.pct_change().abs() + 1e-10)).rolling(20).median()

    # ═══ VOLATILITY FACTORS ═══

    # F13: Idiosyncratic vol — Ang et al. 2006
    f['idio_vol'] = ret.rolling(20).std() * np.sqrt(252)

    # F14: Garman-Klass realized vol
    log_hl = np.log(np.maximum(h, 1e-10) / np.maximum(l, 1e-10)) ** 2
    log_co = np.log(np.maximum(c, 1e-10) / np.maximum(o, 1e-10)) ** 2
    gk_raw = np.maximum(0.5 * log_hl - (2 * np.log(2) - 1) * log_co, 0)
    f['gk_vol'] = np.sqrt(pd.Series(gk_raw, index=idx).rolling(10).mean()) * np.sqrt(252)

    # F15: Parkinson volatility — uses high-low range
    park_raw = log_hl / (4 * np.log(2))
    f['park_vol'] = np.sqrt(pd.Series(park_raw, index=idx).rolling(20).mean()) * np.sqrt(252)

    # F16: Volatility compression — Bollinger squeeze
    ma20 = sc.rolling(20).mean()
    std20 = sc.rolling(20).std()
    bb_w = (4 * std20) / (ma20 + 1e-10)
    f['vol_compress'] = -bb_w

    # F17: Vol-of-vol — regime change signal
    f['vol_of_vol'] = f['idio_vol'].rolling(20).std()

    # F18: Volatility ratio (short/long) — expansion detection
    vol_5d = ret.rolling(5).std()
    vol_20d = ret.rolling(20).std()
    f['vol_ratio'] = vol_5d / (vol_20d + 1e-10)

    # ═══ MEAN REVERSION FACTORS ═══

    # F19: RSI-14 mean reversion
    delta = sc.diff()
    g14 = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    l14 = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    rsi14 = 100 - 100 / (1 + g14 / (l14 + 1e-10))
    f['rsi_signal'] = 50 - rsi14

    # F20: Distance to 20-day mean
    f['zscore_20'] = (sc - ma20) / (std20 + 1e-10)
    f['mr_signal'] = -f['zscore_20']

    # F21: RSI-3 ultra-fast
    g3 = delta.clip(lower=0).ewm(span=3, adjust=False).mean()
    l3 = (-delta.clip(upper=0)).ewm(span=3, adjust=False).mean()
    f['rsi3'] = 100 - 100 / (1 + g3 / (l3 + 1e-10))

    # F22: Bollinger %B — position within bands
    f['bb_pctb'] = (sc - (ma20 - 2 * std20)) / (4 * std20 + 1e-10)

    # ═══ TREND FACTORS ═══

    # F23: Price vs MA20
    f['trend_ma20'] = sc / (ma20 + 1e-10) - 1

    # F24: Price vs MA50
    f['trend_ma50'] = sc / (sc.rolling(50).mean() + 1e-10) - 1

    # F25: MA cross signal (5d vs 20d)
    ma5 = sc.rolling(5).mean()
    f['ma_cross'] = (ma5 - ma20) / (ma20 + 1e-10)

    # F26: ADX proxy — trend strength
    up_move = sh.diff()
    down_move = -sl.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0)
    tr = pd.concat([sh - sl, (sh - sc.shift(1)).abs(), (sl - sc.shift(1)).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(span=14, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=14, adjust=False).mean() / (atr14 + 1e-10)
    minus_di = 100 * minus_dm.ewm(span=14, adjust=False).mean() / (atr14 + 1e-10)
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10) * 100
    f['adx'] = dx.ewm(span=14, adjust=False).mean()

    # ═══ FLOW / ACCUMULATION FACTORS ═══

    # F27: On Balance Volume z-score
    direction = np.sign(ret.fillna(0))
    obv = (direction * sv).cumsum()
    obv_ma = obv.rolling(20).mean()
    f['obv_z'] = (obv - obv_ma) / (obv.rolling(20).std() + 1e-10)

    # F28: Chaikin Money Flow
    mf_mult = ((sc - sl) - (sh - sc)) / (sh - sl + 1e-10)
    f['cmf'] = (mf_mult * sv).rolling(20).sum() / (sv.rolling(20).sum() + 1e-10)

    # F29: VWAP deviation
    typical = (sh + sl + sc) / 3
    vwap = (typical * sv).rolling(20).sum() / (sv.rolling(20).sum() + 1e-10)
    f['vwap_dev'] = (sc - vwap) / (vwap + 1e-10)

    # F30: Money Flow Index (MFI) — volume-weighted RSI
    mf = typical * sv
    pos_mf = mf.where(typical > typical.shift(1), 0).rolling(14).sum()
    neg_mf = mf.where(typical < typical.shift(1), 0).rolling(14).sum()
    f['mfi'] = 100 - 100 / (1 + pos_mf / (neg_mf + 1e-10))

    # ═══ TAIL RISK / HIGHER MOMENTS ═══

    # F31: Realized skewness — Harvey & Siddique 2000
    f['realized_skew'] = ret.rolling(21, min_periods=10).skew()

    # F32: Realized kurtosis
    f['realized_kurt'] = ret.rolling(21, min_periods=10).kurt()

    # F33: Max drawdown (20d) — downside risk measure
    rolling_max = sc.rolling(20, min_periods=5).max()
    drawdown = (sc - rolling_max) / (rolling_max + 1e-10)
    f['max_dd_20'] = drawdown

    # F34: CVaR proxy (5th percentile of returns over 20d)
    f['cvar_5'] = ret.rolling(20, min_periods=10).quantile(0.05)

    # ═══ CROSS-ASSET FACTORS ═══

    # F35: Beta to SPY (rolling 60d)
    if context_data and 'SPY' in context_data:
        spy_ret = context_data['SPY']['Close'].pct_change().reindex(idx)
        cov_spy = ret.rolling(60, min_periods=20).cov(spy_ret)
        var_spy = spy_ret.rolling(60, min_periods=20).var()
        f['beta_spy'] = cov_spy / (var_spy + 1e-10)
        f['corr_spy'] = ret.rolling(60, min_periods=20).corr(spy_ret)
    else:
        f['beta_spy'] = 1.0
        f['corr_spy'] = 0.5

    # F36: VIX correlation (negative = defensive)
    if context_data and 'VIX' in context_data:
        vix_ret = context_data['VIX']['Close'].pct_change().reindex(idx)
        f['corr_vix'] = ret.rolling(60, min_periods=20).corr(vix_ret)
    else:
        f['corr_vix'] = 0.0

    # ═══ INFORMATION DISCRETENESS ═══

    # F37: Da, Gurun, Warachka 2014
    sign_days = np.sign(ret.fillna(0)).rolling(20).sum() / 20
    f['info_discrete'] = sign_days * sc.pct_change(20).abs()

    # ═══ CALENDAR ═══

    # F38: Day of week
    f['dow'] = pd.to_datetime(idx).dayofweek / 4.0

    # ═══ COMPOSITE SIGNALS ═══

    # F39: Smart money composite
    f['smart_composite'] = f['clv'] * np.clip(f['vol_z'], 0, 5) * np.clip(f['vw_momentum'], 0, None)

    # F40: Trend-Vol composite (strong trend + low vol = continuation)
    f['trend_vol'] = f['trend_ma20'] / (f['idio_vol'] / np.sqrt(252) + 1e-10)

    # F41: Accumulation score (CMF + OBV + CLV agreement)
    f['accum_score'] = (
        np.sign(f['cmf']) + np.sign(f['obv_z']) + (f['clv'] > 0.6).astype(float)
    ) / 3

    # F42: Relative strength vs sector (if possible)
    f['sector_rs'] = sc.pct_change(20)  # Will be adjusted in panel as sector-neutral

    f = f.replace([np.inf, -np.inf], np.nan).fillna(0)
    return f


ALPHA_COLS = [
    'str_reversal', 'int_momentum', 'momentum_accel', 'vw_momentum',
    'high_52w_pct', 'ret_gap',
    'clv', 'smi', 'amihud', 'vol_z', 'ofi', 'kyle_lambda',
    'idio_vol', 'gk_vol', 'park_vol', 'vol_compress', 'vol_of_vol', 'vol_ratio',
    'rsi_signal', 'mr_signal', 'rsi3', 'bb_pctb',
    'trend_ma20', 'trend_ma50', 'ma_cross', 'adx',
    'obv_z', 'cmf', 'vwap_dev', 'mfi',
    'realized_skew', 'realized_kurt', 'max_dd_20', 'cvar_5',
    'beta_spy', 'corr_spy', 'corr_vix',
    'info_discrete', 'dow',
    'smart_composite', 'trend_vol', 'accum_score', 'sector_rs',
]


# ═══════════════════════════════════════════════════════════════════════════════
#  CROSS-SECTIONAL PANEL + MULTI-HORIZON TARGETS
# ═══════════════════════════════════════════════════════════════════════════════

def build_institutional_panel(data_dict, feat_dict, horizons=[1, 2, 3]):
    """
    Panel institucional con:
    1. Cross-sectional Z-score (AQR)
    2. Sector-neutral alpha
    3. Multi-horizon forward returns (1d, 2d, 3d)
    4. Quintile-based targets per horizon
    """
    tickers = sorted(feat_dict.keys())
    all_dates = sorted(set.union(*[set(feat_dict[t].index) for t in tickers]))

    print(f"  {DIM}Panel: {len(all_dates)} fechas x {len(tickers)} tickers...{RST}")
    sys.stdout.flush()

    chunks = []
    processed = 0

    for date in all_dates:
        day_rows = []
        for t in tickers:
            if t not in feat_dict or t not in data_dict:
                continue
            feat = feat_dict[t]
            df_t = data_dict[t]
            if date not in feat.index or date not in df_t.index:
                continue
            row = {'date': date, 'ticker': t, 'sector': TICKER_SECTOR.get(t, 'other')}
            for col in ALPHA_COLS:
                row[col] = feat.loc[date, col] if col in feat.columns else 0.0
            day_rows.append(row)

        if len(day_rows) < 20:
            continue

        day_df = pd.DataFrame(day_rows)

        # ── CROSS-SECTIONAL Z-SCORE (robust MAD-based) ──
        for col in ALPHA_COLS:
            if col == 'dow':
                continue
            vals = day_df[col]
            med = vals.median()
            mad = (vals - med).abs().median()
            if mad > 1e-10:
                day_df[f'z_{col}'] = ((vals - med) / (mad * 1.4826)).clip(-3, 3)
            else:
                day_df[f'z_{col}'] = 0.0

        # ── SECTOR-NEUTRAL Z-SCORE ──
        for col in ['str_reversal', 'int_momentum', 'vw_momentum', 'clv', 'vol_z',
                     'rsi_signal', 'ofi', 'cmf', 'smart_composite']:
            zcol = f'z_{col}'
            sn_col = f'sn_{col}'
            day_df[sn_col] = 0.0
            if zcol not in day_df.columns:
                continue
            for sector in day_df['sector'].unique():
                mask = day_df['sector'] == sector
                if mask.sum() < 3:
                    continue
                sector_vals = day_df.loc[mask, zcol]
                s_med = sector_vals.median()
                s_mad = (sector_vals - s_med).abs().median()
                if s_mad > 1e-10:
                    day_df.loc[mask, sn_col] = ((sector_vals - s_med) / (s_mad * 1.4826)).clip(-3, 3)

        chunks.append(day_df)
        processed += 1

        if processed % 100 == 0:
            print(f"\r  {DIM}  {processed}/{len(all_dates)} fechas...{RST}", end="")
            sys.stdout.flush()

    print(f"\r  {DIM}  {processed} fechas procesadas.{' ' * 20}{RST}")

    if not chunks:
        return pd.DataFrame()

    panel = pd.concat(chunks, ignore_index=True)

    # ── MULTI-HORIZON FORWARD RETURNS ──
    print(f"  {DIM}Forward returns multi-horizonte (T+1, T+2, T+3)...{RST}")
    for h in horizons:
        panel[f'fwd_ret_{h}d'] = np.nan
        panel[f'fwd_best_{h}d'] = np.nan

    for t in tickers:
        if t not in data_dict:
            continue
        mask = panel['ticker'] == t
        if mask.sum() == 0:
            continue
        close_s = data_dict[t]['Close']
        high_s = data_dict[t]['High']
        dates_t = panel.loc[mask, 'date'].values
        idx_list = list(close_s.index)

        for h in horizons:
            fwd_c, fwd_b = [], []
            for d in dates_t:
                try:
                    pos = idx_list.index(d)
                    if pos + h < len(idx_list):
                        rc = close_s.iloc[pos + h] / close_s.iloc[pos] - 1
                        # Best return = max intraday high over horizon
                        rh = max(high_s.iloc[pos + 1:pos + h + 1]) / close_s.iloc[pos] - 1
                        fwd_c.append(rc)
                        fwd_b.append(max(rc, rh))
                    else:
                        fwd_c.append(np.nan)
                        fwd_b.append(np.nan)
                except:
                    fwd_c.append(np.nan)
                    fwd_b.append(np.nan)

            panel.loc[mask, f'fwd_ret_{h}d'] = fwd_c
            panel.loc[mask, f'fwd_best_{h}d'] = fwd_b

    # Backward compat
    panel['fwd_ret'] = panel['fwd_ret_1d']
    panel['fwd_best'] = panel['fwd_best_1d']

    # ── MULTI-HORIZON TARGETS ──
    for h in horizons:
        col_best = f'fwd_best_{h}d'
        col_target = f'target_{h}d'
        panel[col_target] = np.nan
        for date in panel['date'].unique():
            mask_d = (panel['date'] == date) & panel[col_best].notna()
            if mask_d.sum() < 10:
                continue
            q80 = panel.loc[mask_d, col_best].quantile(0.80)
            q80 = max(q80, 0.002)
            panel.loc[mask_d, col_target] = (panel.loc[mask_d, col_best] >= q80).astype(int)

    # Clear targets for last day(s)
    last_date = panel['date'].max()
    for h in horizons:
        panel.loc[panel['date'] >= last_date, f'target_{h}d'] = np.nan

    # ── DOLLAR VOLUME ──
    for t in tickers:
        if t not in data_dict:
            continue
        mask = panel['ticker'] == t
        df_t = data_dict[t]
        dv = (df_t['Close'] * df_t['Volume']).rolling(20).mean()
        panel.loc[mask, 'dollar_vol'] = dv.reindex(panel.loc[mask, 'date'].values).values

    return panel


# ═══════════════════════════════════════════════════════════════════════════════
#  FEATURE COLUMNS
# ═══════════════════════════════════════════════════════════════════════════════

def get_feature_cols(panel):
    z_cols = [c for c in panel.columns if c.startswith('z_')]
    sn_cols = [c for c in panel.columns if c.startswith('sn_')]
    raw_cols = [c for c in ALPHA_COLS if c in panel.columns]
    return raw_cols + z_cols + sn_cols


# ═══════════════════════════════════════════════════════════════════════════════
#  ROLLING IC — Information Coefficient
# ═══════════════════════════════════════════════════════════════════════════════

def compute_rolling_ic(panel, feature_cols, target_col='fwd_ret', window=60):
    dates = sorted(panel['date'].unique())
    ic_by_factor = {col: [] for col in feature_cols}

    for i in range(window, len(dates), 5):  # Step by 5 for speed
        window_dates = dates[i - window:i]
        sub = panel[panel['date'].isin(window_dates) & panel[target_col].notna()]
        if len(sub) < 100:
            continue
        for col in feature_cols:
            if col in sub.columns:
                try:
                    corr, _ = sp_stats.spearmanr(sub[col].values, sub[target_col].values)
                    ic_by_factor[col].append(corr if not np.isnan(corr) else 0.0)
                except:
                    ic_by_factor[col].append(0.0)

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


# ═══════════════════════════════════════════════════════════════════════════════
#  DEEP LEARNING — LSTM + Attention (PyTorch)
# ═══════════════════════════════════════════════════════════════════════════════

class AttentionLayer(nn.Module):
    """Self-attention for temporal feature weighting"""
    def __init__(self, hidden_size):
        super().__init__()
        self.attn = nn.Linear(hidden_size, 1)

    def forward(self, lstm_out):
        # lstm_out: (batch, seq_len, hidden)
        weights = torch.softmax(self.attn(lstm_out), dim=1)
        context = (weights * lstm_out).sum(dim=1)
        return context, weights


class LSTMAlphaModel(nn.Module):
    """
    LSTM + Self-Attention for sequential alpha signal processing.
    Processes cross-sectional features as a sequence, learns temporal patterns.
    """
    def __init__(self, input_size, hidden_size=64, num_layers=2, dropout=0.3):
        super().__init__()
        self.bn_input = nn.BatchNorm1d(input_size)
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True,
        )
        self.attention = AttentionLayer(hidden_size)
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, 16),
            nn.ReLU(),
            nn.Dropout(dropout * 0.5),
            nn.Linear(16, 2),
        )

    def forward(self, x):
        # x: (batch, features) -> reshape to (batch, 1, features) for LSTM
        if x.dim() == 2:
            x = self.bn_input(x)
            x = x.unsqueeze(1)  # (batch, 1, features)
        lstm_out, _ = self.lstm(x)
        context, _ = self.attention(lstm_out)
        out = self.fc(context)
        return out


class DeepAlphaTrainer:
    """Wrapper to train and predict with the LSTM model"""

    def __init__(self, input_size, device=None):
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        try:
            if self.device == 'cuda':
                torch.cuda.empty_cache()
            self.model = LSTMAlphaModel(input_size).to(self.device)
        except RuntimeError:
            print("  ⚠ CUDA sin memoria, usando CPU...")
            self.device = 'cpu'
            torch.cuda.empty_cache()
            self.model = LSTMAlphaModel(input_size).to('cpu')
        self.trained = False

    def _fallback_cpu(self):
        """Migrate model to CPU after CUDA OOM"""
        print("  ⚠ CUDA OOM durante entrenamiento, migrando a CPU...")
        self.device = 'cpu'
        torch.cuda.empty_cache()
        self.model = self.model.cpu()

    def train(self, X_train, y_train, X_val=None, y_val=None, epochs=50, lr=0.001, batch_size=512):
        try:
            self._train_impl(X_train, y_train, X_val, y_val, epochs, lr, batch_size)
        except RuntimeError as e:
            if 'out of memory' in str(e) or 'CUDA' in str(e):
                self._fallback_cpu()
                self._train_impl(X_train, y_train, X_val, y_val, epochs, lr, batch_size)
            else:
                raise

    def _train_impl(self, X_train, y_train, X_val=None, y_val=None, epochs=50, lr=0.001, batch_size=512):
        self.model.train()
        optimizer = torch.optim.AdamW(self.model.parameters(), lr=lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

        # Class weights for imbalanced data
        pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
        criterion = nn.CrossEntropyLoss(
            weight=torch.tensor([1.0, min(pos_weight, 3.0)], dtype=torch.float32).to(self.device)
        )

        X_t = torch.tensor(X_train, dtype=torch.float32).to(self.device)
        y_t = torch.tensor(y_train, dtype=torch.long).to(self.device)

        dataset = torch.utils.data.TensorDataset(X_t, y_t)
        loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True)

        best_loss = float('inf')
        patience = 10
        no_improve = 0

        for epoch in range(epochs):
            epoch_loss = 0
            for xb, yb in loader:
                optimizer.zero_grad()
                pred = self.model(xb)
                loss = criterion(pred, yb)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()
                epoch_loss += loss.item()

            scheduler.step()

            # Early stopping on validation
            if X_val is not None and (epoch + 1) % 5 == 0:
                val_loss = self._eval_loss(X_val, y_val, criterion)
                if val_loss < best_loss:
                    best_loss = val_loss
                    no_improve = 0
                else:
                    no_improve += 5
                    if no_improve >= patience:
                        break

        self.trained = True

    def _eval_loss(self, X, y, criterion):
        self.model.eval()
        with torch.no_grad():
            X_t = torch.tensor(X, dtype=torch.float32).to(self.device)
            y_t = torch.tensor(y, dtype=torch.long).to(self.device)
            pred = self.model(X_t)
            loss = criterion(pred, y_t)
        self.model.train()
        return loss.item()

    def predict_proba(self, X):
        self.model.eval()
        with torch.no_grad():
            X_t = torch.tensor(X, dtype=torch.float32).to(self.device)
            logits = self.model(X_t)
            probs = torch.softmax(logits, dim=1)[:, 1].cpu().numpy()
        return probs


# ═══════════════════════════════════════════════════════════════════════════════
#  QUANTUM BRAIN — 7 Models + Meta-Learner + Multi-Horizon
# ═══════════════════════════════════════════════════════════════════════════════

class QuantumBrain:
    """
    7-model ensemble with meta-learner, multi-horizon scoring,
    and regime-conditional weighting.

    Models:
    1. HistGradientBoosting (sklearn)
    2. XGBoost
    3. LightGBM
    4. Random Forest
    5. Extra Trees
    6. LSTM + Attention (PyTorch)
    7. Logistic Regression (linear baseline)

    Meta: Stacked generalization via LogisticRegression
    """

    def __init__(self):
        self.scaler = RobustScaler()
        self.models = {}
        self.meta = LogisticRegression(C=0.5, max_iter=2000)
        self.trained = False
        self._cols = None
        self._weights = {}
        self._ic_summary = {}
        self._deep_model = None
        self._horizon_brains = {}  # Per-horizon models

    def _create_models(self):
        return {
            'hgb': HistGradientBoostingClassifier(
                max_iter=600, max_depth=5, learning_rate=0.025,
                min_samples_leaf=20, l2_regularization=0.5,
                class_weight='balanced', random_state=42,
            ),
            'xgb': xgb.XGBClassifier(
                n_estimators=500, max_depth=5, learning_rate=0.03,
                min_child_weight=20, subsample=0.8, colsample_bytree=0.7,
                reg_alpha=0.1, reg_lambda=1.0, scale_pos_weight=3.0,
                tree_method='hist', random_state=7,
                verbosity=0,
            ),
            'lgb': lgb.LGBMClassifier(
                n_estimators=500, max_depth=6, learning_rate=0.03,
                min_child_samples=20, subsample=0.8, colsample_bytree=0.7,
                reg_alpha=0.1, reg_lambda=1.0, is_unbalance=True,
                random_state=13, verbose=-1,
            ),
            'rf': RandomForestClassifier(
                n_estimators=500, max_depth=10, min_samples_leaf=15,
                max_features='sqrt', class_weight='balanced',
                n_jobs=-1, random_state=21,
            ),
            'et': ExtraTreesClassifier(
                n_estimators=500, max_depth=10, min_samples_leaf=12,
                max_features='sqrt', class_weight='balanced',
                n_jobs=-1, random_state=99,
            ),
            'lr': LogisticRegression(
                C=0.3, max_iter=2000, class_weight='balanced',
                random_state=55,
            ),
        }

    def train(self, panel, horizon=1):
        t0 = time.time()
        target_col = f'target_{horizon}d'
        fwd_col = f'fwd_ret_{horizon}d'

        all_cols = get_feature_cols(panel)
        cols = [c for c in all_cols if c in panel.columns]

        valid = panel[panel[target_col].notna()].copy()
        if len(valid) < 1000:
            print(f"  {R}Datos insuficientes: {len(valid)}{RST}")
            return False

        # ── IC-based feature selection ──
        print(f"  {DIM}IC Selection ({len(cols)} factores, horizonte T+{horizon})...{RST}")
        self._ic_summary = compute_rolling_ic(panel, cols, target_col=fwd_col if fwd_col in panel.columns else 'fwd_ret', window=60)

        good_cols = [c for c in cols if self._ic_summary.get(c, {}).get('mean_ic', 0) > 0.001]
        if len(good_cols) < 10:
            good_cols = sorted(cols, key=lambda c: abs(self._ic_summary.get(c, {}).get('mean_ic', 0)), reverse=True)[:25]

        self._cols = good_cols
        print(f"  Factores activos: {len(good_cols)}/{len(cols)}")

        # Top ICs
        top_ic = sorted(self._ic_summary.items(), key=lambda x: abs(x[1]['mean_ic']), reverse=True)[:10]
        for name, info in top_ic:
            ic_c = G if info['mean_ic'] > 0.01 else Y if info['mean_ic'] > 0 else R
            print(f"    {ic_c}{name:<30} IC={info['mean_ic']:+.4f} ICIR={info['ic_ratio']:+.3f}{RST}")

        # ── PURGED TEMPORAL SPLIT (80/20) ──
        dates = sorted(valid['date'].unique())
        purge_gap = max(horizon + 2, 3)  # Purge gap to avoid leakage
        split_idx = int(len(dates) * 0.80)
        split_date = dates[split_idx]
        purge_date = dates[min(split_idx + purge_gap, len(dates) - 1)]

        tr = valid[valid['date'] < split_date]
        val = valid[valid['date'] >= purge_date]

        X_tr = tr[good_cols].values.astype(np.float32)
        y_tr = tr[target_col].values.astype(int)
        X_val = val[good_cols].values.astype(np.float32)
        y_val = val[target_col].values.astype(int)

        print(f"  Train: {len(y_tr):,} | Val: {len(y_val):,} | Pos: {y_tr.mean() * 100:.1f}%")

        X_tr_sc = self.scaler.fit_transform(X_tr)
        X_val_sc = self.scaler.transform(X_val)

        # ── TRAIN 6 SKLEARN MODELS ──
        self.models = self._create_models()
        val_probs = {}

        for name, model in self.models.items():
            model.fit(X_tr_sc, y_tr)
            pv = model.predict_proba(X_val_sc)[:, 1]
            val_probs[name] = pv

            k = max(1, int(len(y_val) * 0.10))
            top_idx = np.argsort(pv)[-k:]
            hr = y_val[top_idx].mean() * 100
            avg_r = val.iloc[top_idx][fwd_col].mean() * 100 if fwd_col in val.columns else 0
            bench = val[fwd_col].dropna().mean() * 100 if fwd_col in val.columns else 0

            clr_hr = G if hr > 25 else Y if hr > 20 else R
            clr_r = G if avg_r > 0 else R
            print(f"  [{name:>3}] Top10% HR={clr_hr}{hr:.1f}%{RST} "
                  f"Ret={clr_r}{avg_r:+.3f}%{RST} Excess={fmt_pct(avg_r - bench)}")

        # ── TRAIN DEEP LEARNING (LSTM) ──
        print(f"  {DIM}Entrenando LSTM+Attention (PyTorch)...{RST}")
        # GPU de 2GB insuficiente para LSTM — forzar CPU
        device = 'cpu'
        self._deep_model = DeepAlphaTrainer(len(good_cols), device=device)
        self._deep_model.train(X_tr_sc, y_tr, X_val_sc, y_val, epochs=60, lr=0.001)
        deep_val = self._deep_model.predict_proba(X_val_sc)
        val_probs['lstm'] = deep_val

        k = max(1, int(len(y_val) * 0.10))
        top_idx = np.argsort(deep_val)[-k:]
        hr = y_val[top_idx].mean() * 100
        avg_r = val.iloc[top_idx][fwd_col].mean() * 100 if fwd_col in val.columns else 0
        bench_r = val[fwd_col].dropna().mean() * 100 if fwd_col in val.columns else 0
        print(f"  [lstm] Top10% HR={G if hr > 25 else Y}{hr:.1f}%{RST} "
              f"Ret={G if avg_r > 0 else R}{avg_r:+.3f}%{RST} Excess={fmt_pct(avg_r - bench_r)} "
              f"({device})")

        # ── META-LEARNER ──
        all_names = list(self.models.keys()) + ['lstm']
        meta_X = np.column_stack([val_probs[n] for n in all_names])
        self.meta.fit(meta_X, y_val)

        # ── DYNAMIC WEIGHTS (performance-based) ──
        for name in all_names:
            k = max(1, int(len(y_val) * 0.10))
            top_idx = np.argsort(val_probs[name])[-k:]
            perf = y_val[top_idx].mean()
            self._weights[name] = max(0.05, perf)
        tw = sum(self._weights.values())
        self._weights = {k: v / tw for k, v in self._weights.items()}

        # ── RETRAIN ON FULL DATA ──
        print(f"  {DIM}Retraining on full dataset...{RST}")
        X_full = valid[good_cols].values.astype(np.float32)
        y_full = valid[target_col].values.astype(int)
        X_full_sc = self.scaler.fit_transform(X_full)

        for model in self.models.values():
            model.fit(X_full_sc, y_full)

        self._deep_model = DeepAlphaTrainer(len(good_cols), device=device)
        self._deep_model.train(X_full_sc, y_full, epochs=60, lr=0.001)

        full_probs = [m.predict_proba(X_full_sc)[:, 1] for m in self.models.values()]
        full_probs.append(self._deep_model.predict_proba(X_full_sc))
        full_meta_X = np.column_stack(full_probs)
        self.meta.fit(full_meta_X, y_full)

        self.trained = True
        elapsed = time.time() - t0
        w_str = ' '.join(f'{k}={v:.2f}' for k, v in sorted(self._weights.items(), key=lambda x: -x[1]))
        print(f"  {G}T+{horizon} OK ({elapsed:.1f}s) | Weights: {w_str}{RST}")
        return True

    def score(self, features_row):
        X = np.array(features_row, dtype=np.float32).reshape(1, -1)
        X_sc = self.scaler.transform(X)

        probs = {}
        w_sum = 0
        all_names = list(self.models.keys()) + ['lstm']

        for name, model in self.models.items():
            p = model.predict_proba(X_sc)[0][1]
            probs[name] = p
            w_sum += self._weights.get(name, 0.1) * p

        # LSTM
        deep_p = self._deep_model.predict_proba(X_sc)[0]
        probs['lstm'] = deep_p
        w_sum += self._weights.get('lstm', 0.1) * deep_p

        # Meta-learner
        meta_X = np.array([probs[n] for n in all_names]).reshape(1, -1)
        meta_p = self.meta.predict_proba(meta_X)[0][1]

        # Ensemble: 50% meta + 50% weighted
        final = 0.50 * meta_p + 0.50 * w_sum
        return final * 100, probs

    def score_panel_today(self, panel, data_dict):
        last_date = panel['date'].max()
        today = panel[panel['date'] == last_date].copy()
        cols = self._cols
        results = []

        for _, row in today.iterrows():
            try:
                sc, probs = self.score(row[cols].values)
                t = row['ticker']
                precio = data_dict[t]['Close'].iloc[-1] if t in data_dict else 0
                results.append({
                    'ticker': t, 'score': sc, 'precio': precio,
                    'sector': row.get('sector', ''),
                    'probs': probs,
                    'str_reversal': row.get('str_reversal', 0),
                    'int_momentum': row.get('int_momentum', 0),
                    'clv': row.get('clv', 0),
                    'vol_z': row.get('vol_z', 0),
                    'rsi_signal': row.get('rsi_signal', 0),
                    'smart_composite': row.get('smart_composite', 0),
                    'cmf': row.get('cmf', 0),
                    'vol_compress': row.get('vol_compress', 0),
                    'ofi': row.get('ofi', 0),
                    'adx': row.get('adx', 0),
                    'idio_vol': row.get('idio_vol', 0),
                    'trend_ma20': row.get('trend_ma20', 0),
                    'accum_score': row.get('accum_score', 0),
                })
            except:
                pass

        results.sort(key=lambda x: x['score'], reverse=True)
        return results


# ═══════════════════════════════════════════════════════════════════════════════
#  MULTI-HORIZON COMPOSITE SCORING
# ═══════════════════════════════════════════════════════════════════════════════

class MultiHorizonEngine:
    """
    Trains separate models for T+1, T+2, T+3 and combines them.
    Conviction = agreement across horizons.
    """

    def __init__(self):
        self.brains = {}  # {horizon: QuantumBrain}
        self.horizon_weights = {1: 0.50, 2: 0.30, 3: 0.20}

    def train_all(self, panel):
        for h in [1, 2, 3]:
            print(f"\n  {BOLD}{'─' * 80}{RST}")
            print(f"  {BOLD}HORIZONTE T+{h}{RST}")
            print(f"  {BOLD}{'─' * 80}{RST}")
            brain = QuantumBrain()
            if brain.train(panel, horizon=h):
                self.brains[h] = brain

    def score_composite(self, panel, data_dict):
        """Score across all horizons and compute composite"""
        all_scores = {}  # {ticker: {h: score, ...}}

        for h, brain in self.brains.items():
            results = brain.score_panel_today(panel, data_dict)
            for r in results:
                t = r['ticker']
                if t not in all_scores:
                    all_scores[t] = {'ticker': t, 'precio': r['precio'], 'sector': r['sector']}
                    all_scores[t]['details'] = r
                all_scores[t][f'score_{h}d'] = r['score']
                all_scores[t][f'probs_{h}d'] = r['probs']

        # Composite score
        scored = []
        for t, data in all_scores.items():
            scores = []
            weights = []
            for h in [1, 2, 3]:
                s = data.get(f'score_{h}d')
                if s is not None:
                    scores.append(s)
                    weights.append(self.horizon_weights.get(h, 0.2))

            if not scores:
                continue

            w_total = sum(weights)
            composite = sum(s * w for s, w in zip(scores, weights)) / w_total

            # Conviction = how much models agree across horizons
            if len(scores) >= 2:
                conviction = 1 - (np.std(scores) / (np.mean(scores) + 1e-10))
                conviction = np.clip(conviction, 0, 1)
            else:
                conviction = 0.5

            data['composite'] = composite
            data['conviction'] = conviction
            # Risk-adjusted score
            details = data.get('details', {})
            idio = abs(details.get('idio_vol', 0.3))
            data['risk_adj'] = composite / (idio / np.sqrt(252) + 0.01) if idio > 0 else composite
            scored.append(data)

        scored.sort(key=lambda x: x['composite'], reverse=True)
        return scored


# ═══════════════════════════════════════════════════════════════════════════════
#  PORTFOLIO OPTIMIZER — Sector-Diversified Top 10
# ═══════════════════════════════════════════════════════════════════════════════

def select_diversified_top10(scored, max_per_sector=3, min_score=45):
    """
    Select top 10 with sector diversification constraint.
    No more than max_per_sector from same sector.
    """
    selected = []
    sector_count = {}

    for s in scored:
        if s['composite'] < min_score:
            continue
        sector = s.get('sector', 'other')
        if sector_count.get(sector, 0) >= max_per_sector:
            continue
        selected.append(s)
        sector_count[sector] = sector_count.get(sector, 0) + 1
        if len(selected) >= 10:
            break

    return selected


# ═══════════════════════════════════════════════════════════════════════════════
#  BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════

def backtest_reciente(engine, panel, data_dict, dias=15):
    """Walk-forward backtest on most recent N trading days"""
    if 1 not in engine.brains:
        print(f"  {R}No hay modelo T+1 entrenado.{RST}")
        return

    brain = engine.brains[1]
    cols = brain._cols
    dates = sorted(panel['date'].unique())

    # Use dates that have forward returns
    test_dates = [d for d in dates[-dias - 5:] if
                  panel[(panel['date'] == d) & panel['fwd_ret'].notna()].shape[0] > 10][-dias:]

    if not test_dates:
        print(f"  {Y}No hay fechas con forward returns para backtest.{RST}")
        return

    print(f"\n{C}{'═' * 110}{RST}")
    print(f"{C}  BACKTEST WALK-FORWARD — ULTIMOS {len(test_dates)} DIAS DE TRADING{RST}")
    print(f"{C}{'═' * 110}{RST}\n")

    daily = []
    for test_date in test_dates:
        day = panel[panel['date'] == test_date]
        if len(day) < 10 or day['fwd_ret'].isna().all():
            continue

        scored = []
        for _, row in day.iterrows():
            try:
                sc, _ = brain.score(row[cols].values)
                scored.append({
                    'ticker': row['ticker'], 'score': sc,
                    'fwd_ret': row.get('fwd_ret', np.nan),
                    'fwd_best': row.get('fwd_best', np.nan),
                    'sector': row.get('sector', ''),
                })
            except:
                pass

        if not scored:
            continue
        scored.sort(key=lambda x: x['score'], reverse=True)

        # Apply diversification
        top10 = []
        sc_count = {}
        for s in scored:
            if len(top10) >= 10:
                break
            sec = s.get('sector', 'other')
            if sc_count.get(sec, 0) >= 3:
                continue
            if not np.isnan(s['fwd_ret']):
                top10.append(s)
                sc_count[sec] = sc_count.get(sec, 0) + 1

        if not top10:
            continue

        hits = sum(1 for s in top10 if s['fwd_ret'] > 0)
        strong = sum(1 for s in top10 if s['fwd_ret'] > 0.01)
        avg_r = np.mean([s['fwd_ret'] for s in top10]) * 100
        avg_b = np.mean([s['fwd_best'] for s in top10]) * 100
        bench = day['fwd_ret'].dropna().mean() * 100
        excess = avg_r - bench

        daily.append({
            'date': test_date, 'n': len(scored), 'hits': hits, 'strong': strong,
            'avg_ret': avg_r, 'best': avg_b, 'bench': bench, 'excess': excess,
            'top3': [(s['ticker'], s['fwd_ret'] * 100) for s in top10[:3]],
        })

    if not daily:
        print(f"  {Y}Sin resultados.{RST}")
        return

    print(f"  {'Fecha':<12} {'N':>4} {'Hits':>6} {'>1%':>4} {'RetProm':>8} {'Mejor':>8} {'Bench':>7} {'Excess':>8}  Top 3")
    print(f"  {'─' * 112}")

    for r in daily:
        hc = G if r['hits'] >= 6 else Y if r['hits'] >= 4 else R
        rc = G if r['avg_ret'] > 0 else R
        ec = G if r['excess'] > 0 else R
        t3 = '  '.join(f"{t}:{ret:+.1f}%" for t, ret in r['top3'])
        print(f"  {str(r['date'].date()):<12} {r['n']:>4} {hc}{r['hits']:>4}/10{RST} {r['strong']:>3} "
              f"{rc}{r['avg_ret']:>+7.2f}%{RST} {r['best']:>+7.2f}% {r['bench']:>+6.2f}% "
              f"{ec}{r['excess']:>+7.2f}%{RST}  {DIM}{t3}{RST}")

    # Summary
    print(f"\n  {BOLD}RESUMEN:{RST}")
    th = sum(r['hits'] for r in daily)
    tn = len(daily) * 10
    hr = th / tn * 100 if tn > 0 else 0
    avg = np.mean([r['avg_ret'] for r in daily])
    avg_ex = np.mean([r['excess'] for r in daily])
    wins = sum(1 for r in daily if r['avg_ret'] > 0)
    cum = np.prod([1 + r['avg_ret'] / 100 for r in daily]) - 1

    sharpe = np.mean([r['avg_ret'] for r in daily]) / (np.std([r['avg_ret'] for r in daily]) + 1e-10) * np.sqrt(252)

    print(f"  Dias: {len(daily)} | Hit Rate: {G if hr > 55 else Y}{hr:.1f}%{RST} | "
          f"Ret/dia: {G if avg > 0 else R}{avg:+.3f}%{RST} | "
          f"Excess: {G if avg_ex > 0 else R}{avg_ex:+.3f}%{RST}")
    print(f"  Winners: {wins}/{len(daily)} ({wins / len(daily) * 100:.0f}%) | "
          f"Acumulado: {G if cum > 0 else R}{cum * 100:+.2f}%{RST} | "
          f"Sharpe(ann): {G if sharpe > 1 else Y}{sharpe:.2f}{RST}")


# ═══════════════════════════════════════════════════════════════════════════════
#  DESCARGA
# ═══════════════════════════════════════════════════════════════════════════════

def descargar():
    all_t = list(set(ACTIVOS + CONTEXT))
    print(f"  Descargando {len(all_t)} tickers (2y)...")
    raw = yf.download(all_t, period="2y", group_by='ticker', progress=False, threads=True, timeout=60)
    data = {}
    for t in all_t:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                l0 = set(raw.columns.get_level_values(0))
                l1 = set(raw.columns.get_level_values(1)) - {""}
                if t in l1:
                    df = raw.xs(t, axis=1, level=1).dropna()
                elif t in l0:
                    df = raw[t].dropna()
                else:
                    continue
            else:
                continue
            df.columns = [str(c).capitalize() for c in df.columns]
            if all(x in df.columns for x in ['Open', 'High', 'Low', 'Close', 'Volume']) and len(df) > 200:
                data[t] = df
        except:
            pass
    print(f"  {G}OK: {len(data)} activos{RST}")
    return data


# ═══════════════════════════════════════════════════════════════════════════════
#  DISPLAY — TOP 10 PROFESSIONAL OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════

def display_top10(top10, regime):
    """Professional institutional-grade output"""

    print(f"\n{C}{'═' * 120}{RST}")
    print(f"{C}  ██ TITAN v5 QUANTUM — ALPHA SIGNALS — TOP 10 ACCIONES PROXIMA RUEDA (1-3 DIAS) ██{RST}")
    print(f"{C}{'═' * 120}{RST}")

    # Regime info
    print(f"\n  {BOLD}REGIME:{RST} ", end="")
    comp = regime.get('composite', 'UNKNOWN')
    comp_c = G if comp == 'RISK_ON' else R if comp in ('RISK_OFF', 'CRISIS') else Y
    print(f"{comp_c}{comp}{RST}", end="")

    trend = regime.get('trend', '?')
    vol = regime.get('vol', '?')
    vix = regime.get('vix_level', 0)
    risk_sc = regime.get('risk_score', 0)
    print(f"  |  Trend: {G if trend == 'BULL' else R if trend == 'BEAR' else Y}{trend}{RST}"
          f"  |  Vol: {G if vol == 'LOW' else Y if vol == 'MEDIUM' else R}{vol}{RST} (VIX={vix:.1f})"
          f"  |  Risk Score: {G if risk_sc > 0 else R}{risk_sc:+.2f}{RST}")

    credit = regime.get('credit', '?')
    dollar = regime.get('dollar', '?')
    gold = regime.get('gold', '?')
    print(f"  Credit: {G if credit == 'LOOSE' else R}{credit}{RST}"
          f"  |  Dollar: {R if dollar == 'STRONG' else G}{dollar}{RST}"
          f"  |  Gold: {Y}{gold}{RST}")

    print(f"\n  {'#':>3} {'TICKER':<7} {'SECTOR':<9} {'PRECIO':>9} "
          f"{'COMPOSITE':>10} {'CONVIC':>7} "
          f"{'T+1':>6} {'T+2':>6} {'T+3':>6} "
          f"{'CLV':>5} {'OFI':>5} {'CMF':>6} {'ADX':>5} {'VolZ':>5} {'Accum':>5}")
    print(f"  {'─' * 118}")

    for i, s in enumerate(top10, 1):
        comp_sc = s.get('composite', 0)
        conv = s.get('conviction', 0)

        sc_c = G + BOLD if comp_sc > 65 else G if comp_sc > 55 else Y if comp_sc > 48 else DIM
        conv_c = G if conv > 0.7 else Y if conv > 0.5 else DIM

        s1 = s.get('score_1d', 0)
        s2 = s.get('score_2d', 0)
        s3 = s.get('score_3d', 0)

        d = s.get('details', {})
        clv = d.get('clv', 0)
        ofi_v = d.get('ofi', 0)
        cmf = d.get('cmf', 0)
        adx = d.get('adx', 0)
        vz = d.get('vol_z', 0)
        accum = d.get('accum_score', 0)

        clv_c = G if clv > 0.7 else DIM
        ofi_c = G if ofi_v > 0.3 else DIM
        accum_c = G if accum > 0.5 else DIM

        # Signal bar
        bar = barra(comp_sc)

        print(f"  {DIM}{i:>3}{RST} {BOLD}{s['ticker']:<7}{RST} "
              f"{DIM}{s.get('sector', '')[:8]:<9}{RST}"
              f"${s.get('precio', 0):>8,.2f} "
              f"{sc_c}{comp_sc:>8.1f}%{RST} "
              f"{conv_c}{conv:>6.0%}{RST} "
              f"{s1:>5.1f} {s2:>5.1f} {s3:>5.1f} "
              f"{clv_c}{clv:>5.2f}{RST} "
              f"{ofi_c}{ofi_v:>+4.2f}{RST} "
              f"{cmf:>+5.3f} "
              f"{adx:>4.0f} "
              f"{vz:>+4.1f} "
              f"{accum_c}{accum:>+4.2f}{RST}")

    # Model consensus
    print(f"\n  {BOLD}CONSENSUS DE MODELOS (Top 1):{RST}")
    if top10:
        best = top10[0]
        for h in [1, 2, 3]:
            probs_key = f'probs_{h}d'
            if probs_key in best:
                probs = best[probs_key]
                parts = '  '.join(f"{k}={v * 100:.0f}%" for k, v in sorted(probs.items(), key=lambda x: -x[1]))
                print(f"    T+{h}: {parts}")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAQUINA DEL TIEMPO
# ═══════════════════════════════════════════════════════════════════════════════

def maquina_del_tiempo(engine, panel):
    if 1 not in engine.brains:
        return

    brain = engine.brains[1]
    cols = brain._cols

    print(f"\n{C}{'═' * 95}{RST}")
    print(f"{C}  MAQUINA DEL TIEMPO (T+1){RST}")
    print(f"{C}{'═' * 95}{RST}")
    print(f"  {DIM}TICKER FECHA (ej: NFLX 2026-02-26) o 'salir'{RST}\n")

    while True:
        try:
            cmd = input(f"  {Y}>>> {RST}").strip().upper()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd in ('SALIR', 'EXIT', 'Q', ''):
            break
        parts = cmd.split()
        if len(parts) != 2:
            print(f"  {R}Formato: TICKER YYYY-MM-DD{RST}\n")
            continue
        ticker, fecha_str = parts
        try:
            fecha = pd.to_datetime(fecha_str)
            sub = panel[(panel['ticker'] == ticker) & (panel['date'] <= fecha)]
            if sub.empty:
                print(f"  {R}{ticker} sin datos.{RST}\n")
                continue
            row = sub.iloc[-1]
            sc, probs = brain.score(row[cols].values)
            fwd = row.get('fwd_ret', np.nan)
            fwd_s = fmt_pct(fwd * 100) if not np.isnan(fwd) else f"{DIM}N/A{RST}"
            color = G if sc > 65 else Y if sc > 50 else DIM
            print(f"\n  {BOLD}--- {ticker} al {str(row['date'].date())} ---{RST}")
            print(f"  Score: {color}{sc:.1f}%{RST}")
            parts_str = '  '.join(f"{k}={v * 100:.0f}%" for k, v in sorted(probs.items(), key=lambda x: -x[1]))
            print(f"  Models: {parts_str}")
            print(f"  Retorno real T+1: {fwd_s}")
            print(f"  {DIM}CLV={row.get('clv', 0):.2f} VolZ={row.get('vol_z', 0):+.1f} "
                  f"CMF={row.get('cmf', 0):+.3f} OFI={row.get('ofi', 0):+.3f} "
                  f"IntMom={row.get('int_momentum', 0) * 100:+.1f}%{RST}\n")
        except Exception as e:
            print(f"  {R}Error: {e}{RST}\n")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    clr()
    t0 = time.time()

    print(f"""
{C}{'═' * 120}{RST}

   {BOLD}{C}████████╗██╗████████╗ █████╗ ███╗   ██╗    ██╗   ██╗███████╗    ██████╗ ██╗   ██╗ █████╗ ███╗   ██╗████████╗██╗   ██╗███╗   ███╗{RST}
   {BOLD}{C}╚══██╔══╝██║╚══██╔══╝██╔══██╗████╗  ██║    ██║   ██║██╔════╝   ██╔═══██╗██║   ██║██╔══██╗████╗  ██║╚══██╔══╝██║   ██║████╗ ████║{RST}
   {BOLD}{C}   ██║   ██║   ██║   ███████║██╔██╗ ██║    ██║   ██║███████╗   ██║   ██║██║   ██║███████║██╔██╗ ██║   ██║   ██║   ██║██╔████╔██║{RST}
   {BOLD}{C}   ██║   ██║   ██║   ██╔══██║██║╚██╗██║    ╚██╗ ██╔╝╚════██║   ██║▄▄██║██║   ██║██╔══██║██║╚██╗██║   ██║   ██║   ██║██║╚██╔╝██║{RST}
   {BOLD}{C}   ██║   ██║   ██║   ██║  ██║██║ ╚████║     ╚████╔╝ ███████║   ╚██████╔╝╚██████╔╝██║  ██║██║ ╚████║   ██║   ╚██████╔╝██║ ╚═╝ ██║{RST}
   {BOLD}{C}   ╚═╝   ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝      ╚═══╝  ╚══════╝    ╚══▀▀═╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝     ╚═╝{RST}

   {BOLD}QUANTUM ALPHA ENGINE v5.0 — INSTITUTIONAL DEEP LEARNING TRADING SYSTEM{RST}
   {DIM}42 Alpha Factors | 7 ML Models + LSTM | Multi-Horizon (T+1/2/3) | Regime Detection | Sector-Diversified{RST}

{C}{'═' * 120}{RST}
""")

    # ═══ STEP 1: DOWNLOAD ═══
    print(f"  {BOLD}[1/6] DESCARGA DE DATOS{RST}")
    data_dict = descargar()
    if len(data_dict) < 10:
        print(f"  {R}Descarga fallida.{RST}")
        return

    # Separate context assets
    context_data = {t: data_dict[t] for t in CONTEXT if t in data_dict}

    # ═══ STEP 2: REGIME DETECTION ═══
    print(f"\n  {BOLD}[2/6] REGIME DETECTION (Cross-Asset){RST}")
    regime_detector = RegimeDetector()
    regime = regime_detector.detect(context_data)

    comp = regime.get('composite', 'UNKNOWN')
    comp_c = G if comp == 'RISK_ON' else R if comp in ('RISK_OFF', 'CRISIS') else Y
    print(f"  Regime: {comp_c}{BOLD}{comp}{RST}")
    print(f"  {DIM}Trend={regime.get('trend','?')} Vol={regime.get('vol','?')} "
          f"VIX={regime.get('vix_level',0):.1f} Credit={regime.get('credit','?')} "
          f"Dollar={regime.get('dollar','?')} RiskScore={regime.get('risk_score',0):+.2f}{RST}")

    # ═══ STEP 3: ALPHA FACTORS ═══
    print(f"\n  {BOLD}[3/6] CALCULANDO 42 ALPHA FACTORS{RST}")
    feat_dict = {}

    def calc(t, df):
        try:
            return t, compute_alpha_factors(df, context_data)
        except:
            return t, None

    active_tickers = [t for t in data_dict if t not in CONTEXT]
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        futures = [ex.submit(calc, t, data_dict[t]) for t in active_tickers]
        for f_res in futures:
            t, feat = f_res.result()
            if feat is not None:
                feat_dict[t] = feat
    print(f"  {G}OK: {len(feat_dict)} activos procesados{RST}")

    # ═══ STEP 4: INSTITUTIONAL PANEL ═══
    print(f"\n  {BOLD}[4/6] PANEL INSTITUCIONAL (CS Z-Score + Sector-Neutral + Multi-Horizon){RST}")
    panel = build_institutional_panel(data_dict, feat_dict, horizons=[1, 2, 3])
    if panel.empty:
        print(f"  {R}Panel vacio.{RST}")
        return

    tr_rate = panel[panel['target_1d'].notna()]['target_1d'].mean() * 100
    print(f"  {G}Panel: {len(panel):,} filas | {panel['date'].nunique()} fechas | "
          f"{panel['ticker'].nunique()} tickers | Target rate: {tr_rate:.1f}%{RST}")

    # ═══ STEP 5: MULTI-HORIZON TRAINING ═══
    print(f"\n  {BOLD}[5/6] ENTRENANDO MULTI-HORIZON ENGINE (7 modelos x 3 horizontes){RST}")
    engine = MultiHorizonEngine()
    engine.train_all(panel)

    # ═══ BACKTEST ═══
    backtest_reciente(engine, panel, data_dict, dias=15)

    # ═══ STEP 6: SIGNALS ═══
    print(f"\n  {BOLD}[6/6] GENERANDO ALPHA SIGNALS{RST}")
    scored = engine.score_composite(panel, data_dict)
    top10 = select_diversified_top10(scored)

    display_top10(top10, regime)

    # Universe stats
    if scored:
        all_s = [s['composite'] for s in scored]
        print(f"\n  {DIM}Universo: {len(scored)} activos | Media={np.mean(all_s):.1f}% "
              f"Max={np.max(all_s):.1f}% P75={np.percentile(all_s, 75):.1f}% "
              f"P25={np.percentile(all_s, 25):.1f}%{RST}")
        strong = sum(1 for s in all_s if s > 60)
        mod = sum(1 for s in all_s if 55 < s <= 60)
        print(f"  {G}Fuertes (>60%): {strong}{RST} | {Y}Moderadas (55-60%): {mod}{RST}")

    elapsed = time.time() - t0
    print(f"\n  {DIM}Tiempo total: {elapsed:.0f}s ({elapsed / 60:.1f}min) | "
          f"Device: {'CUDA' if torch.cuda.is_available() else 'CPU'} | "
          f"{datetime.now().strftime('%d/%m/%Y %H:%M')}{RST}")
    print(f"\n  {R}{BOLD}DISCLAIMER: Solo fines educativos. No constituye asesoramiento financiero.{RST}")
    print(f"  {DIM}Los resultados pasados no garantizan retornos futuros.{RST}\n")

    # Interactive
    maquina_del_tiempo(engine, panel)


if __name__ == "__main__":
    main()
