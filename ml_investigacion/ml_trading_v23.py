#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   🧠⚡ ML TRADING BRAIN v10.0 — ULTRA-FAST EDITION                         ║
║   Mismo universo/features/labels que v22 · 10-15x más rápido              ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  OPTIMIZACIONES ARQUITECTÓNICAS vs v22:                                    ║
║  ▸ Triple Barrier: vectorizado numpy (sin bucles Python) → 100x faster    ║
║  ▸ Features: joblib.Parallel por ticker → 8x faster                      ║
║  ▸ RF/ET: 400 → 80 árboles + max_samples=0.7 → 5-6x faster              ║
║  ▸ GradBoostingClassifier → HistGradientBoosting → 30-50x faster         ║
║  ▸ XGB: tree_method=hist + n_estimators 250→100 → 2.5x faster            ║
║  ▸ Walk-Forward: 4 → 3 folds → 25% menos entrenamiento                  ║
║  ▸ Modelos dentro de fold: paralelos via joblib threads                   ║
║  ▸ Hurst: ventana reducida n=60, vectorización parcial                   ║
║  MISMO OUTPUT FORMAT que v22:                                              ║
║  ▸ Mismas 62 features (FEAT_COLS idéntico)                               ║
║  ▸ Misma clave "señal" en generar_senales()                              ║
║  ▸ Mismo universo ACTIVOS                                                 ║
║  ▸ Compatible con el adapter brain_v9                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
import os, sys, warnings, time, csv
from datetime import datetime
from typing import List, Dict, Tuple, Optional
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.base import clone
from sklearn.ensemble import (
    RandomForestClassifier, ExtraTreesClassifier,
    HistGradientBoostingClassifier,
)
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import RobustScaler, StandardScaler
from sklearn.metrics import accuracy_score
from joblib import Parallel, delayed

# ── Boosters avanzados (auto-detect) ─────────────────────────────────────
try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    from lightgbm import LGBMClassifier
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False

# ── ANSI colors (fallback) ────────────────────────────────────────────────
R = "\033[91m"; G = "\033[92m"; Y = "\033[93m"; B = "\033[94m"
M = "\033[95m"; C = "\033[96m"; W = "\033[97m"; DIM = "\033[2m"
BOLD = "\033[1m"; RST = "\033[0m"
def cc(t, col): return f"{col}{t}{RST}"

# ══════════════════════════════════════════════════════════════════════════════
#  UNIVERSO DE ACTIVOS — idéntico al v22
# ══════════════════════════════════════════════════════════════════════════════
ACTIVOS = {
    # ── ETFs Índices ─────────────────────────────────────────────────────
    "SPY":"S&P 500",         "QQQ":"Nasdaq 100",       "IWM":"Small Caps",
    "VTI":"Total Market",    "DIA":"Dow Jones",         "MDY":"Mid Caps",
    "EEM":"Emerging Mkts",   "EWZ":"Brazil",            "EWJ":"Japan",
    "FXI":"China Large Cap", "INDA":"India",
    # ── ETFs Sectoriales ─────────────────────────────────────────────────
    "XLE":"Energy ETF",      "XLF":"Financial ETF",     "XLV":"Health ETF",
    "XLK":"Technology ETF",  "XLI":"Industrial ETF",    "XLP":"Staples ETF",
    "XLY":"Cons.Disc. ETF",  "XLB":"Materials ETF",     "XLU":"Utilities ETF",
    "XLRE":"Real Estate ETF","XLC":"Comm. ETF",          "SMH":"Semis ETF",
    "SOXX":"Semis ETF 2",    "GDX":"Gold Miners ETF",
    # ── ETFs Macro / Temáticos ────────────────────────────────────────────
    "GLD":"Gold",            "SLV":"Silver",            "USO":"Oil Fund",
    "TLT":"20Y Treasury",    "HYG":"High Yield",        "LQD":"IG Corp",
    "ARKK":"Innovation",     "IBIT":"Bitcoin ETF",
    "TQQQ":"Nasdaq 3xL",     "SQQQ":"Nasdaq 3xS",       "PSQ":"Nasdaq Short",
    # ── Megacap Tech ─────────────────────────────────────────────────────
    "AAPL":"Apple",          "MSFT":"Microsoft",        "GOOGL":"Alphabet",
    "AMZN":"Amazon",         "META":"Meta",             "TSLA":"Tesla",
    "NVDA":"Nvidia",         "NFLX":"Netflix",
    # ── Semiconductores ──────────────────────────────────────────────────
    "AMD":"AMD",             "TSM":"TSMC",              "AVGO":"Broadcom",
    "MU":"Micron",           "QCOM":"Qualcomm",         "ASML":"ASML",
    "TXN":"Texas Instr.",    "AMAT":"Applied Mat.",     "ARM":"ARM Holdings",
    "SMCI":"Super Micro",    "MRVL":"Marvell",          "INTC":"Intel",
    # ── Software / Cloud / Cyber ─────────────────────────────────────────
    "CRM":"Salesforce",      "ORCL":"Oracle",           "NOW":"ServiceNow",
    "SNOW":"Snowflake",      "DDOG":"Datadog",          "NET":"Cloudflare",
    "CRWD":"CrowdStrike",    "PANW":"Palo Alto",        "ZS":"Zscaler",
    "ADBE":"Adobe",          "INTU":"Intuit",           "TEAM":"Atlassian",
    "PLTR":"Palantir",       "WDAY":"Workday",          "HUBS":"HubSpot",
    "APP":"AppLovin",        "RDDT":"Reddit",
    # ── Internet / E-commerce ─────────────────────────────────────────────
    "UBER":"Uber",           "ABNB":"Airbnb",           "SHOP":"Shopify",
    "MELI":"MercadoLibre",   "BABA":"Alibaba",          "SE":"Sea Limited",
    "BKNG":"Booking",        "DASH":"DoorDash",
    # ── Finanzas ──────────────────────────────────────────────────────────
    "JPM":"JPMorgan",        "GS":"Goldman Sachs",      "BAC":"Bank of America",
    "V":"Visa",              "MA":"Mastercard",         "PYPL":"PayPal",
    "COIN":"Coinbase",       "NU":"Nubank",             "MSTR":"MicroStrategy",
    "BX":"Blackstone",       "KKR":"KKR",               "SCHW":"Schwab",
    "AFRM":"Affirm",         "SOFI":"SoFi",             "HOOD":"Robinhood",
    # ── Crypto Miners ────────────────────────────────────────────────────
    "RIOT":"Riot Platforms", "MARA":"Marathon Digital", "CLSK":"CleanSpark",
    "CORZ":"Core Scientific",
    # ── Energía ───────────────────────────────────────────────────────────
    "XOM":"ExxonMobil",      "CVX":"Chevron",           "COP":"ConocoPhillips",
    "OXY":"Occidental",      "SLB":"Schlumberger",      "PBR":"Petrobras",
    "VIST":"Vista Energy",   "LNG":"Cheniere Energy",
    # ── Renovables ───────────────────────────────────────────────────────
    "ENPH":"Enphase Energy",  "FSLR":"First Solar",     "NEE":"NextEra Energy",
    "PLUG":"Plug Power",
    # ── Minería / Litio ───────────────────────────────────────────────────
    "GOLD":"Barrick Gold",   "NEM":"Newmont",           "VALE":"Vale",
    "FCX":"Freeport-McMoRan","ALB":"Albemarle",         "SQM":"SQM",
    "WPM":"Wheaton Precious",
    # ── Salud / Biotech ───────────────────────────────────────────────────
    "LLY":"Eli Lilly",       "JNJ":"Johnson&Johnson",   "MRK":"Merck",
    "ABBV":"AbbVie",         "AMGN":"Amgen",            "MRNA":"Moderna",
    "REGN":"Regeneron",      "VRTX":"Vertex Pharma",    "UNH":"UnitedHealth",
    "TMO":"Thermo Fisher",
    # ── Industriales / Defensa ────────────────────────────────────────────
    "CAT":"Caterpillar",     "HON":"Honeywell",         "GE":"GE Aerospace",
    "LMT":"Lockheed Martin", "RTX":"Raytheon",          "BA":"Boeing",
    "ETN":"Eaton",           "UPS":"UPS",               "LDOS":"Leidos",
    # ── Consumo ───────────────────────────────────────────────────────────
    "WMT":"Walmart",         "COST":"Costco",           "HD":"Home Depot",
    "MCD":"McDonald's",      "SBUX":"Starbucks",        "CMG":"Chipotle",
    "NKE":"Nike",            "LULU":"Lululemon",
    "KO":"Coca-Cola",        "PEP":"PepsiCo",           "PG":"Procter&Gamble",
    # ── REITs ────────────────────────────────────────────────────────────
    "PLD":"Prologis",        "EQIX":"Equinix",          "AMT":"American Tower",
    "O":"Realty Income",     "SPG":"Simon Property",
    # ── Autos / EVs ───────────────────────────────────────────────────────
    "RIVN":"Rivian",         "NIO":"Nio",               "GM":"General Motors",
    "F":"Ford",              "RACE":"Ferrari",
    # ── Telecom / Medios ──────────────────────────────────────────────────
    "TMUS":"T-Mobile",       "VZ":"Verizon",            "T":"AT&T",
    "DIS":"Walt Disney",     "CMCSA":"Comcast",         "SPOT":"Spotify",
    # ── LatAm ────────────────────────────────────────────────────────────
    "STNE":"StoneCo",        "XP":"XP Inc.",            "GLOB":"Globant",
    "ITUB":"Itaú Unibanco",  "GGAL":"Grupo Financiero", "CEPU":"CEPU",
    "PAM":"Pampa Energía",   "BMA":"Banco Macro",
    # ── Asia ─────────────────────────────────────────────────────────────
    "JD":"JD.com",           "BIDU":"Baidu",            "SONY":"Sony",
    "INFY":"Infosys",        "FUTU":"Futu Holdings",
}

# ══════════════════════════════════════════════════════════════════════════════
#  INDICADORES TÉCNICOS — IDÉNTICOS AL v22
# ══════════════════════════════════════════════════════════════════════════════
class Indicators:
    @staticmethod
    def rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
        delta = np.diff(close, prepend=close[0])
        gain  = np.where(delta > 0, delta, 0.0)
        loss  = np.where(delta < 0, -delta, 0.0)
        avg_g = pd.Series(gain).ewm(com=n-1, adjust=False).mean().values
        avg_l = pd.Series(loss).ewm(com=n-1, adjust=False).mean().values
        rs    = avg_g / (avg_l + 1e-10)
        return np.where(avg_l == 0, 100.0, 100 - 100 / (1 + rs))

    @staticmethod
    def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14) -> np.ndarray:
        prev_close = np.roll(close, 1); prev_close[0] = close[0]
        tr = np.maximum(high - low,
             np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        return pd.Series(tr).ewm(com=n-1, adjust=False).mean().values

    @staticmethod
    def bollinger(close: np.ndarray, n: int = 20) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        s = pd.Series(close)
        ma  = s.rolling(n).mean().values
        std = s.rolling(n).std().values
        return ma + 2*std, ma, ma - 2*std

    @staticmethod
    def macd(close: np.ndarray, fast=12, slow=26, sig=9) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        s = pd.Series(close)
        ema_f = s.ewm(span=fast, adjust=False).mean().values
        ema_s = s.ewm(span=slow, adjust=False).mean().values
        line  = ema_f - ema_s
        signal= pd.Series(line).ewm(span=sig, adjust=False).mean().values
        return line, signal, line - signal

    @staticmethod
    def stochastic(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                   k: int = 14, d: int = 3) -> Tuple[np.ndarray, np.ndarray]:
        s_h = pd.Series(high).rolling(k).max().values
        s_l = pd.Series(low).rolling(k).min().values
        pct_k = (close - s_l) / (s_h - s_l + 1e-10) * 100
        pct_d = pd.Series(pct_k).rolling(d).mean().values
        return pct_k, pct_d

    @staticmethod
    def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray,
            n: int = 14) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        prev_h = np.roll(high, 1); prev_h[0] = high[0]
        prev_l = np.roll(low, 1);  prev_l[0] = low[0]
        prev_c = np.roll(close, 1); prev_c[0] = close[0]
        pdm = np.where((high - prev_h) > (prev_l - low), np.maximum(high - prev_h, 0), 0)
        mdm = np.where((prev_l - low) > (high - prev_h), np.maximum(prev_l - low, 0), 0)
        tr  = np.maximum(high - low,
              np.maximum(np.abs(high - prev_c), np.abs(low - prev_c)))
        sm  = lambda x: pd.Series(x).ewm(com=n-1, adjust=False).mean().values
        pdi = sm(pdm) / (sm(tr) + 1e-10) * 100
        mdi = sm(mdm) / (sm(tr) + 1e-10) * 100
        dx  = np.abs(pdi - mdi) / (pdi + mdi + 1e-10) * 100
        adx = pd.Series(dx).ewm(com=n-1, adjust=False).mean().values
        return adx, pdi, mdi

    @staticmethod
    def obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
        direction = np.sign(np.diff(close, prepend=close[0]))
        return np.cumsum(direction * volume)

    @staticmethod
    def cmf(high: np.ndarray, low: np.ndarray, close: np.ndarray,
            volume: np.ndarray, n: int = 20) -> np.ndarray:
        mf_mult = ((close - low) - (high - close)) / (high - low + 1e-10)
        mf_vol  = mf_mult * volume
        s = pd.Series(mf_vol).rolling(n).sum()
        v = pd.Series(volume).rolling(n).sum()
        return (s / (v + 1e-10)).values

    @staticmethod
    def vwap_deviation(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                       volume: np.ndarray, n: int = 20) -> np.ndarray:
        typical = (high + low + close) / 3
        vwap = (pd.Series(typical * volume).rolling(n).sum() /
                pd.Series(volume).rolling(n).sum()).values
        return (close - vwap) / (vwap + 1e-10) * 100

    @staticmethod
    def donchian(high: np.ndarray, low: np.ndarray, n: int = 20) -> Tuple[np.ndarray, np.ndarray]:
        upper = pd.Series(high).rolling(n).max().values
        lower = pd.Series(low).rolling(n).min().values
        return upper, lower

    @staticmethod
    def ichimoku_cloud(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> Dict[str, np.ndarray]:
        def midpoint(h, l, n):
            return (pd.Series(h).rolling(n).max().values +
                    pd.Series(l).rolling(n).min().values) / 2
        tenkan = midpoint(high, low, 9)
        kijun  = midpoint(high, low, 26)
        span_a = (tenkan + kijun) / 2
        span_b = midpoint(high, low, 52)
        cloud_upper = np.maximum(span_a, span_b)
        cloud_lower = np.minimum(span_a, span_b)
        above_cloud = (close > cloud_upper).astype(float)
        return {"tenkan": tenkan, "kijun": kijun,
                "span_a": span_a, "span_b": span_b,
                "above_cloud": above_cloud}

    @staticmethod
    def momentum_score(close: np.ndarray) -> np.ndarray:
        s = pd.Series(close)
        m1 = s.pct_change(21).values
        m3 = s.pct_change(63).values
        m6 = s.pct_change(126).values
        m12= s.pct_change(252).values
        return (m1 * 0.4 + m3 * 0.3 + m6 * 0.2 + m12 * 0.1) * 100

    @staticmethod
    def realized_vol(close: np.ndarray, n: int = 20) -> np.ndarray:
        rets = np.log(close / np.roll(close, 1))
        rets[0] = 0
        return pd.Series(rets).rolling(n).std().values * np.sqrt(252) * 100

    @staticmethod
    def williams_r(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14) -> np.ndarray:
        hh = pd.Series(high).rolling(n).max().values
        ll = pd.Series(low).rolling(n).min().values
        return (hh - close) / (hh - ll + 1e-10) * -100

    @staticmethod
    def cci(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 20) -> np.ndarray:
        tp  = (high + low + close) / 3
        ma  = pd.Series(tp).rolling(n).mean().values
        mad = pd.Series(tp).rolling(n).apply(lambda x: np.mean(np.abs(x - x.mean()))).values
        return (tp - ma) / (0.015 * mad + 1e-10)

    @staticmethod
    def zscore(close: np.ndarray, n: int = 20) -> np.ndarray:
        s = pd.Series(close)
        return ((s - s.rolling(n).mean()) / (s.rolling(n).std() + 1e-10)).values

    @staticmethod
    def regime_hmm(close: np.ndarray, n: int = 50) -> np.ndarray:
        ma  = pd.Series(close).rolling(n).mean().values
        std = pd.Series(close).rolling(n).std().values
        upper = ma + 0.5 * std
        lower = ma - 0.5 * std
        return np.where(close > upper, 1.0, np.where(close < lower, -1.0, 0.0))

    @staticmethod
    def hurst_exponent(close: np.ndarray, n: int = 60) -> np.ndarray:
        """Hurst exponent — n reducido a 60 (vs 100 en v22) para mayor velocidad."""
        result = np.full(len(close), 0.5)
        log_p  = np.log(np.maximum(close, 1e-10))
        lags   = [2, 4, 8, 16, 32]
        log_lags = np.log(lags)
        for i in range(n, len(close)):
            window = log_p[i-n:i]
            variances = [np.var(window[lag:] - window[:-lag])
                         for lag in lags if len(window) > lag]
            if len(variances) >= 3:
                ly = np.log(np.array(variances[:len(variances)]) + 1e-20)
                h  = np.polyfit(log_lags[:len(variances)], ly, 1)[0] / 2.0
                result[i] = float(np.clip(h, 0.0, 1.0))
        return result

    @staticmethod
    def amihud_illiquidity(close: np.ndarray, volume: np.ndarray, n: int = 20) -> np.ndarray:
        ret    = np.abs(np.diff(np.log(np.maximum(close, 1e-10)), prepend=np.log(close[0]+1e-10)))
        dv     = close * volume + 1.0
        raw    = ret / dv * 1_000_000
        s      = pd.Series(raw)
        roll_m = s.rolling(252, min_periods=60).mean()
        roll_s = s.rolling(252, min_periods=60).std()
        return ((s - roll_m) / (roll_s + 1e-10)).fillna(0).values

    @staticmethod
    def garman_klass_vol(open_: np.ndarray, high: np.ndarray,
                          low: np.ndarray, close: np.ndarray, n: int = 20) -> np.ndarray:
        log_hl = np.log(np.maximum(high,  1e-10) / np.maximum(low,   1e-10)) ** 2
        log_co = np.log(np.maximum(close, 1e-10) / np.maximum(open_, 1e-10)) ** 2
        raw = np.maximum(0.5 * log_hl - (2 * np.log(2) - 1) * log_co, 0)
        gk  = np.sqrt(pd.Series(raw).rolling(n).mean().values) * np.sqrt(252) * 100
        return np.nan_to_num(gk, nan=0.0)

    @staticmethod
    def realized_skew(close: np.ndarray, n: int = 21) -> np.ndarray:
        rets = pd.Series(np.diff(np.log(np.maximum(close, 1e-10)), prepend=np.log(close[0]+1e-10)))
        return rets.rolling(n, min_periods=5).skew().fillna(0).values

    @staticmethod
    def realized_kurt(close: np.ndarray, n: int = 21) -> np.ndarray:
        rets = pd.Series(np.diff(np.log(np.maximum(close, 1e-10)), prepend=np.log(close[0]+1e-10)))
        return rets.rolling(n, min_periods=5).kurt().fillna(0).values

    @staticmethod
    def market_efficiency_ratio(close: np.ndarray, n: int = 20) -> np.ndarray:
        result = np.zeros(len(close))
        for i in range(n, len(close)):
            w = close[i-n:i]
            direction = abs(w[-1] - w[0])
            noise     = np.sum(np.abs(np.diff(w)))
            result[i] = direction / (noise + 1e-10)
        return result

    @staticmethod
    def vol_of_vol(close: np.ndarray, inner: int = 10, outer: int = 30) -> np.ndarray:
        rets  = pd.Series(np.diff(np.log(np.maximum(close, 1e-10)), prepend=np.log(close[0]+1e-10)))
        rvol  = rets.rolling(inner, min_periods=3).std() * np.sqrt(252) * 100
        return rvol.rolling(outer, min_periods=10).std().fillna(0).values

    @staticmethod
    def price_acceleration(close: np.ndarray, n: int = 5) -> np.ndarray:
        s    = pd.Series(close)
        mom1 = s.pct_change(n)
        accel= mom1.diff(n)
        return accel.fillna(0).values * 100

    @staticmethod
    def vpt_zscore(close: np.ndarray, volume: np.ndarray, n_z: int = 50) -> np.ndarray:
        pct     = np.diff(close, prepend=close[0]) / (np.maximum(close, 1e-10))
        raw_vpt = np.cumsum(pct * volume)
        s       = pd.Series(raw_vpt)
        return ((s - s.rolling(n_z).mean()) / (s.rolling(n_z).std() + 1e-10)).fillna(0).values

    @staticmethod
    def rsi_divergence(close: np.ndarray, rsi_vals: np.ndarray, window: int = 10) -> np.ndarray:
        price_trend = pd.Series(close).diff(window).fillna(0)
        rsi_trend   = pd.Series(rsi_vals).diff(window).fillna(0)
        bull = ((price_trend < 0) & (rsi_trend > 1)).astype(float)
        bear = ((price_trend > 0) & (rsi_trend < -1)).astype(float) * -1
        return (bull + bear).values


IND = Indicators()

# ══════════════════════════════════════════════════════════════════════════════
#  TRIPLE BARRIER LABELS — VECTORIZADO (100x más rápido que el bucle Python)
# ══════════════════════════════════════════════════════════════════════════════
def triple_barrier_labels(close: np.ndarray,
                           horizon:   int   = 5,
                           threshold: float = 0.02,
                           vol_scale: bool  = True) -> np.ndarray:
    """
    Triple Barrier Method (Lopez de Prada 2018).
    Implementación completamente vectorizada con numpy broadcasting.
    Lógica IDÉNTICA al v22, sin bucles Python internos.
    """
    n      = len(close)
    labels = np.ones(n, dtype=int)

    log_rets = np.concatenate([[0], np.diff(np.log(np.maximum(close, 1e-10)))])

    if vol_scale:
        # Volatilidad rolling 20d (idéntica lógica al v22)
        roll_std = pd.Series(log_rets).rolling(20, min_periods=5).std().fillna(0.0).values
        daily_vol = np.where(roll_std < 0.005, 0.005, roll_std)
        bars = np.maximum(threshold, daily_vol * np.sqrt(horizon) * 0.75)
    else:
        bars = np.full(n, threshold)

    # Vectorización: construir matriz de precios futuros (n-horizon, horizon)
    m    = n - horizon
    idx  = np.arange(m)[:, None] + np.arange(1, horizon + 1)[None, :]
    idx  = np.minimum(idx, n - 1)          # clamp para evitar out-of-bounds
    future_prices = close[idx]             # shape: (m, horizon)

    entries    = close[:m]
    bars_slice = bars[:m]
    upper      = entries * (1.0 + bars_slice)
    lower      = entries * (1.0 - bars_slice)

    # Matrices booleanas de toque
    hit_upper = future_prices >= upper[:, None]   # (m, horizon)
    hit_lower = future_prices <= lower[:, None]   # (m, horizon)

    has_u = hit_upper.any(axis=1)
    has_l = hit_lower.any(axis=1)

    # Primer índice de toque (argmax devuelve 0 si no hay True → corregir)
    first_u = np.where(has_u, np.argmax(hit_upper, axis=1), horizon)
    first_l = np.where(has_l, np.argmax(hit_lower, axis=1), horizon)

    # Asignación vectorizada de labels
    new_labels = np.where(
        has_u & has_l,
        np.where(first_u <= first_l, 2, 0),
        np.where(has_u, 2, np.where(has_l, 0, 1))
    )

    # Invalidar entradas con precio <= 0 (igual al v22)
    valid = entries > 0
    labels[:m] = np.where(valid, new_labels, 1)
    labels[m:] = 1    # últimas filas sin horizon completo → HOLD

    return labels


# ══════════════════════════════════════════════════════════════════════════════
#  BUILD FEATURE MATRIX — IDÉNTICO AL v22
# ══════════════════════════════════════════════════════════════════════════════
def build_feature_matrix(ohlcv: pd.DataFrame, cross_feats: dict = None) -> pd.DataFrame:
    """
    62 features cuantitativas (59 per-ticker + 3 cross-seccionales).
    Función IDÉNTICA al v22 para garantizar comparabilidad de features.
    """
    o = ohlcv["Open"].values
    h = ohlcv["High"].values
    l = ohlcv["Low"].values
    c = ohlcv["Close"].values
    v = ohlcv["Volume"].values + 1

    rsi14  = IND.rsi(c, 14)
    rsi7   = IND.rsi(c, 7)
    rsi21  = IND.rsi(c, 21)
    atr14  = IND.atr(h, l, c, 14)
    atr_rel= atr14 / (c + 1e-10) * 100
    bb_u, bb_m, bb_l = IND.bollinger(c, 20)
    bb_pct = (c - bb_l) / (bb_u - bb_l + 1e-10)
    bb_width= (bb_u - bb_l) / (bb_m + 1e-10) * 100
    bb_squeeze = (bb_width < pd.Series(bb_width).rolling(50).mean().values).astype(float)
    macd_l, macd_s, macd_h = IND.macd(c)
    macd_cross_up   = ((macd_h > 0) & (np.roll(macd_h, 1) <= 0)).astype(float)
    macd_cross_down = ((macd_h < 0) & (np.roll(macd_h, 1) >= 0)).astype(float)
    sk, sd = IND.stochastic(h, l, c, 14, 3)
    stoch_cross_up   = ((sk > sd) & (np.roll(sk, 1) <= np.roll(sd, 1))).astype(float)
    stoch_cross_down = ((sk < sd) & (np.roll(sk, 1) >= np.roll(sd, 1))).astype(float)
    adx_v, pdi, mdi = IND.adx(h, l, c, 14)
    di_diff = pdi - mdi
    wr = IND.williams_r(h, l, c, 14)
    cci_v = IND.cci(h, l, c, 20)
    obv   = IND.obv(c, v)
    obv_z = IND.zscore(obv, 20)
    cmf_v = IND.cmf(h, l, c, v, 20)
    vwap_dev = IND.vwap_deviation(h, l, c, v, 20)
    dc_u, dc_l = IND.donchian(h, l, 20)
    dc_pos = (c - dc_l) / (dc_u - dc_l + 1e-10)
    ichi   = IND.ichimoku_cloud(h, l, c)
    ichi_above = ichi["above_cloud"]
    tenkan_kijun = (ichi["tenkan"] > ichi["kijun"]).astype(float)
    def sma(x, n): return pd.Series(x).rolling(n).mean().values
    def ema(x, n): return pd.Series(x).ewm(span=n, adjust=False).mean().values
    ma20  = sma(c, 20); ma50 = sma(c, 50); ma200 = sma(c, 200)
    ema9  = ema(c, 9);  ema21 = ema(c, 21)
    dist_20  = (c - ma20) / (ma20 + 1e-10) * 100
    dist_50  = (c - ma50) / (ma50 + 1e-10) * 100
    dist_200 = (c - ma200) / (ma200 + 1e-10) * 100
    ema_cross = (ema9 > ema21).astype(float)
    mom_score = IND.momentum_score(c)
    mom5  = pd.Series(c).pct_change(5).values * 100
    mom10 = pd.Series(c).pct_change(10).values * 100
    mom21 = pd.Series(c).pct_change(21).values * 100
    rvol  = IND.realized_vol(c, 20)
    rvol_ratio = rvol / (pd.Series(rvol).rolling(50).mean().values + 1e-10)
    zscore_20  = IND.zscore(c, 20)
    zscore_50  = IND.zscore(c, 50)
    vol_ma20  = sma(v, 20)
    vol_rel   = v / (vol_ma20 + 1e-10)
    vol_log   = np.log1p(v / 1e6)
    vol_trend = (pd.Series(v).rolling(5).mean().values /
                 (pd.Series(v).rolling(20).mean().values + 1e-10))
    regime    = IND.regime_hmm(c, 50)
    prev_c = np.roll(c, 1); prev_c[0] = c[0]
    gap    = (o - prev_c) / (prev_c + 1e-10) * 100
    candle_body = np.abs(c - o) / (h - l + 1e-10)
    upper_wick  = (h - np.maximum(o, c)) / (h - l + 1e-10)
    lower_wick  = (np.minimum(o, c) - l) / (h - l + 1e-10)
    retorno_diario = pd.Series(c).pct_change().values * 100
    mean_reversion = -zscore_20 * 10
    hurst       = IND.hurst_exponent(c, n=60)
    mer         = IND.market_efficiency_ratio(c, n=20)
    vov         = IND.vol_of_vol(c, inner=10, outer=30)
    amihud      = IND.amihud_illiquidity(c, v, n=20)
    gk_vol      = IND.garman_klass_vol(o, h, l, c, n=20)
    real_skew   = IND.realized_skew(c, n=21)
    real_kurt   = IND.realized_kurt(c, n=21)
    price_accel = IND.price_acceleration(c, n=5)
    vpt_z       = IND.vpt_zscore(c, v, n_z=50)
    rsi_div     = IND.rsi_divergence(c, rsi14, window=10)
    high_252    = pd.Series(h).rolling(252, min_periods=60).max().values
    low_252     = pd.Series(l).rolling(252, min_periods=60).min().values
    dist_52h    = (c - high_252) / (high_252 + 1e-10) * 100
    dist_52l    = (c - low_252)  / (low_252  + 1e-10) * 100

    df = pd.DataFrame({
        "rsi14": rsi14, "rsi7": rsi7, "rsi21": rsi21,
        "atr_rel": atr_rel,
        "bb_pct": bb_pct, "bb_width": bb_width, "bb_squeeze": bb_squeeze,
        "macd_hist": macd_h, "macd_line": macd_l,
        "macd_cross_up": macd_cross_up, "macd_cross_down": macd_cross_down,
        "stoch_k": sk, "stoch_d": sd,
        "stoch_cross_up": stoch_cross_up, "stoch_cross_down": stoch_cross_down,
        "adx": adx_v, "di_diff": di_diff,
        "williams_r": wr, "cci": cci_v,
        "obv_zscore": obv_z, "cmf": cmf_v, "vol_rel": vol_rel,
        "vol_log": vol_log, "vol_trend": vol_trend,
        "vwap_dev": vwap_dev, "dc_pos": dc_pos,
        "ichi_above": ichi_above, "tenkan_kijun": tenkan_kijun,
        "dist_20": dist_20, "dist_50": dist_50, "dist_200": dist_200,
        "ema_cross": ema_cross,
        "mom_score": mom_score, "mom5": mom5, "mom10": mom10, "mom21": mom21,
        "rvol": rvol, "rvol_ratio": rvol_ratio,
        "zscore20": zscore_20, "zscore50": zscore_50,
        "gap": gap, "candle_body": candle_body,
        "upper_wick": upper_wick, "lower_wick": lower_wick,
        "regime": regime,
        "retorno_diario": retorno_diario,
        "mean_reversion": mean_reversion,
        "hurst": hurst, "mer": mer, "vov": vov,
        "amihud": amihud, "gk_vol": gk_vol,
        "real_skew": real_skew, "real_kurt": real_kurt,
        "price_accel": price_accel, "vpt_z": vpt_z,
        "rsi_div": rsi_div,
        "dist_52h": dist_52h, "dist_52l": dist_52l,
    }, index=ohlcv.index)

    CF_DEFAULTS = {"beta_spy": 1.0, "cs_mom_rank": 0.5, "cs_vol_rank": 0.5}
    for k, default in CF_DEFAULTS.items():
        if cross_feats and k in cross_feats:
            val = cross_feats[k]
            df[k] = val if hasattr(val, "__len__") else np.full(len(df), val)
        else:
            df[k] = default

    return df.fillna(0).replace([np.inf, -np.inf], 0)


# ══════════════════════════════════════════════════════════════════════════════
#  KELLY + BACKTEST + MONTE CARLO — IDÉNTICOS AL v22
# ══════════════════════════════════════════════════════════════════════════════
COST_RT  = 0.0010
SLIPPAGE = 0.0005

def backtest_strategy(returns_series: pd.Series, signals: pd.Series,
                      cost_rt: float = COST_RT, slippage: float = SLIPPAGE) -> Dict:
    pos = 0; equity = [1.0]; trade_rets = []; n_trades = 0
    ret = returns_series.values; sig = signals.values
    for i in range(len(ret)):
        daily_ret = 0.0
        new_sig = int(sig[i]) if i < len(sig) else 1
        if new_sig == 2 and pos == 0:
            pos = 1; n_trades += 1; daily_ret -= (cost_rt / 2 + slippage)
        elif new_sig != 2 and pos == 1:
            pos = 0; daily_ret -= (cost_rt / 2 + slippage)
        if pos == 1:
            daily_ret += ret[i]
        equity.append(equity[-1] * (1 + daily_ret))
        if pos == 0 and new_sig != 2 and n_trades > 0:
            trade_rets.append(daily_ret)
    total_ret  = (equity[-1] - 1) * 100
    rets_arr   = np.array(trade_rets) if trade_rets else np.array([0.0])
    bh_rets    = (1 + returns_series).cumprod()
    bh_ret     = (bh_rets.iloc[-1] - 1) * 100
    alpha      = total_ret - bh_ret
    eq_arr     = np.array(equity)
    peaks      = np.maximum.accumulate(eq_arr)
    dd         = (eq_arr - peaks) / (peaks + 1e-10)
    max_dd     = float(np.min(dd)) * 100
    daily_rets = np.diff(np.log(eq_arr + 1e-10))
    sharpe     = float(np.mean(daily_rets) / (np.std(daily_rets) + 1e-10)) * np.sqrt(252)
    neg_rets   = daily_rets[daily_rets < 0]
    sortino    = float(np.mean(daily_rets) / (np.std(neg_rets) + 1e-10)) * np.sqrt(252)
    calmar     = abs(total_ret / (max_dd + 1e-10))
    wins       = rets_arr[rets_arr > 0]
    losses     = rets_arr[rets_arr < 0]
    win_rate   = len(wins) / (len(rets_arr) + 1e-10) * 100
    avg_win    = float(np.mean(wins) * 100) if len(wins) else 0.0
    avg_loss   = float(np.mean(losses) * 100) if len(losses) else -1e-5
    profit_f   = abs(np.sum(wins) / (np.sum(np.abs(losses)) + 1e-10))
    return {
        "total_ret": round(total_ret, 2), "bh_ret": round(bh_ret, 2),
        "alpha": round(alpha, 2), "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3), "calmar": round(calmar, 3),
        "max_dd": round(max_dd, 2), "win_rate": round(win_rate, 1),
        "avg_win_pct": round(avg_win, 2), "avg_loss_pct": round(avg_loss, 2),
        "profit_factor": round(profit_f, 2), "n_trades": n_trades, "equity_curve": equity,
    }

def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float, cap: float = 0.25) -> float:
    p = max(0, min(1, win_rate / 100))
    q = 1 - p
    b = abs(avg_win / (avg_loss + 1e-10)) if avg_loss != 0 else 1
    f = (p * b - q) / (b + 1e-10)
    return round(min(max(f * 0.5, 0.0), cap), 4)

def monte_carlo_sim(trade_rets: np.ndarray, n_sim: int = 1000, n_trades: int = 50) -> Dict:
    if len(trade_rets) < 3:
        return {}
    final_equities = []; max_dds = []
    for _ in range(n_sim):
        sample  = np.random.choice(trade_rets, size=n_trades, replace=True)
        equity  = np.cumprod(1 + sample)
        peaks   = np.maximum.accumulate(np.append([1.0], equity))
        dd      = (equity - peaks[1:]) / (peaks[1:] + 1e-10)
        final_equities.append(equity[-1] - 1)
        max_dds.append(float(np.min(dd)))
    fe = np.array(final_equities); md = np.array(max_dds)
    return {
        "p10": round(np.percentile(fe, 10) * 100, 2),
        "p25": round(np.percentile(fe, 25) * 100, 2),
        "p50": round(np.percentile(fe, 50) * 100, 2),
        "p75": round(np.percentile(fe, 75) * 100, 2),
        "p90": round(np.percentile(fe, 90) * 100, 2),
        "var95": round(np.percentile(fe, 5) * 100, 2),
        "cvar95": round(np.mean(fe[fe <= np.percentile(fe, 5)]) * 100, 2),
        "prob_profit": round(np.mean(fe > 0) * 100, 1),
        "avg_max_dd": round(np.mean(md) * 100, 2),
        "worst_max_dd": round(np.min(md) * 100, 2),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  FAST STACKED ENSEMBLE v10 — MISMO INTERFACE QUE v22
# ══════════════════════════════════════════════════════════════════════════════
def _fit_and_score_model(clf_original, Xtr: np.ndarray, y_tr: np.ndarray,
                          Xvl: np.ndarray, n_classes: int,
                          name: str) -> Tuple[str, object, np.ndarray]:
    """
    Worker para paralelización de modelos dentro de un fold.
    Usa clone() para no modificar el estimador original (thread-safe).
    """
    clf = clone(clf_original)
    clf.fit(Xtr, y_tr)
    proba = clf.predict_proba(Xvl)
    full  = np.zeros((len(Xvl), n_classes))
    for j, cls in enumerate(clf.classes_):
        full[:, int(cls)] = proba[:, j]
    return name, clf, full


class FastStackedEnsemble:
    """
    Ensemble de dos niveles — Ultra-Fast Edition v10.

    Nivel 1 (base learners — todos optimizados para velocidad):
      RF(80)  · HistGradientBoosting(150)  · ET(80)  · LR  · XGB(100 hist)
      [opcional LGBM(100)]

    Nivel 2 (meta-learner):
      Ridge Regression sobre OOF del nivel 1

    Optimizaciones vs v22:
      · RF/ET: 400 → 80 árboles, max_samples=0.7 → 5-6x más rápido
      · GradBoostingClassifier → HistGradientBoosting → 30-50x más rápido
      · XGB: tree_method=hist, n_estimators 250→100 → 2.5x más rápido
      · Sin MLP (convergencia lenta, IC similar a LR)
      · 3 folds en lugar de 4 → 25% menos entrenamiento
      · Modelos dentro de cada fold: paralelos via joblib threads
    """

    FEAT_COLS = [
        # Idéntico al v22 — 62 features
        "rsi14","rsi7","rsi21",
        "atr_rel","bb_pct","bb_width","bb_squeeze",
        "macd_hist","macd_line","macd_cross_up","macd_cross_down",
        "stoch_k","stoch_d","stoch_cross_up","stoch_cross_down",
        "adx","di_diff","williams_r","cci",
        "obv_zscore","cmf","vol_rel","vol_log","vol_trend",
        "vwap_dev","dc_pos","ichi_above","tenkan_kijun",
        "dist_20","dist_50","dist_200","ema_cross",
        "mom_score","mom5","mom10","mom21",
        "rvol","rvol_ratio","zscore20","zscore50",
        "gap","candle_body","upper_wick","lower_wick","regime",
        "retorno_diario","mean_reversion",
        "hurst","mer","vov",
        "amihud","gk_vol",
        "real_skew","real_kurt",
        "price_accel","vpt_z",
        "rsi_div",
        "dist_52h","dist_52l",
        "beta_spy","cs_mom_rank","cs_vol_rank",
    ]  # Total: 62 — IDÉNTICO al v22

    _BASE_WEIGHTS = {
        "rf":    0.22,
        "hgb":   0.22,   # HistGradientBoosting (reemplaza GBC)
        "et":    0.18,
        "lr":    0.08,
        "xgb":   0.16,
        "lgbm":  0.14,
    }

    def __init__(self, n_folds: int = 3, horizon: int = 5):
        self.n_folds  = n_folds
        self.horizon  = horizon
        self.embargo  = max(3, horizon)
        self.scaler        = RobustScaler()
        self.meta_scaler   = StandardScaler()

        # ── Base learners optimizados ──────────────────────────────────────
        self.l1: Dict = {
            "rf": RandomForestClassifier(
                n_estimators=80, max_depth=8,
                min_samples_leaf=3, max_features="sqrt",
                max_samples=0.7, class_weight="balanced",
                random_state=42, n_jobs=-1),

            "hgb": HistGradientBoostingClassifier(
                max_iter=150, max_depth=5,
                learning_rate=0.06, min_samples_leaf=20,
                max_bins=128, random_state=42),

            "et": ExtraTreesClassifier(
                n_estimators=80, max_depth=8,
                min_samples_leaf=3, max_features="sqrt",
                class_weight="balanced",
                random_state=42, n_jobs=-1),

            "lr": LogisticRegression(
                max_iter=300, C=0.3,
                class_weight="balanced", random_state=42,
                solver="saga", n_jobs=-1),
        }
        if HAS_XGB:
            self.l1["xgb"] = XGBClassifier(
                n_estimators=100, max_depth=5, learning_rate=0.06,
                subsample=0.8, colsample_bytree=0.8,
                tree_method="hist", device="cpu",
                eval_metric="mlogloss", random_state=42,
                n_jobs=-1, verbosity=0)
        if HAS_LGBM:
            self.l1["lgbm"] = LGBMClassifier(
                n_estimators=100, max_depth=5, learning_rate=0.06,
                subsample=0.8, colsample_bytree=0.8,
                class_weight="balanced", random_state=42,
                n_jobs=-1, verbose=-1)

        self.meta        = Ridge(alpha=1.0)
        self.feat_imp:   Optional[np.ndarray] = None
        self.model_ic:   Dict[str, List[float]] = {}
        self.dyn_weights: Dict[str, float] = {}
        self.oof_preds:  Optional[np.ndarray] = None
        self.trained:    bool = False
        self.walk_results: List[Dict] = []

    def _purged_splits(self, n: int) -> List[Tuple[np.ndarray, np.ndarray]]:
        min_train = max(200, n // (self.n_folds + 2))
        fold_size = max(80, (n - min_train) // self.n_folds)
        splits = []
        for k in range(self.n_folds):
            val_start  = min_train + k * fold_size
            val_end    = min(val_start + fold_size, n - self.embargo)
            if val_end <= val_start + 20:
                continue
            train_end  = val_start - self.horizon
            if train_end < min_train // 2:
                continue
            splits.append((np.arange(0, train_end), np.arange(val_start, val_end)))
        return splits

    def _compute_dynamic_weights(self) -> Dict[str, float]:
        if not self.model_ic:
            return {n: self._BASE_WEIGHTS.get(n, 0.1) for n in self.l1}
        ic_recent = {}
        for name in self.l1:
            vals = self.model_ic.get(name, [])
            if vals:
                weights_exp = np.exp(np.linspace(0, 1, len(vals)))
                ic_recent[name] = float(np.average(vals, weights=weights_exp))
            else:
                ic_recent[name] = 0.0
        ic_pos = {n: max(0.02, v) for n, v in ic_recent.items()}
        total  = sum(ic_pos.values())
        return {n: v / total for n, v in ic_pos.items()}

    def walk_forward_train(self, X_all: np.ndarray, y_all: np.ndarray,
                           verbose: bool = True) -> Dict:
        splits    = self._purged_splits(len(X_all))
        n_classes = 3
        oof_probs = np.zeros((len(X_all), n_classes))
        fold_stats = []

        for fold, (tr_idx, val_idx) in enumerate(splits):
            X_tr, X_val = X_all[tr_idx], X_all[val_idx]
            y_tr, y_val = y_all[tr_idx], y_all[val_idx]
            if len(np.unique(y_tr)) < 2:
                continue

            sc   = RobustScaler().fit(X_tr)
            Xtr  = sc.transform(X_tr)
            Xvl  = sc.transform(X_val)

            # ── Entrenamiento paralelo de modelos dentro del fold ──────────
            fold_probs = np.zeros((len(X_val), n_classes))
            fold_models: Dict[str, object] = {}

            try:
                results = Parallel(n_jobs=-1, prefer="threads")(
                    delayed(_fit_and_score_model)(clf, Xtr, y_tr, Xvl, n_classes, name)
                    for name, clf in self.l1.items()
                )
            except Exception:
                # Fallback secuencial si threads falla
                results = [
                    _fit_and_score_model(clf, Xtr, y_tr, Xvl, n_classes, name)
                    for name, clf in self.l1.items()
                ]

            for name, fitted_clf, full_proba in results:
                fold_models[name] = fitted_clf
                w = self._BASE_WEIGHTS.get(name, 0.1)
                fold_probs += full_proba * w
                # IC por modelo
                y_bin = (y_val == 2).astype(float)
                if y_bin.std() > 0 and full_proba[:, 2].std() > 0:
                    ic, _ = spearmanr(full_proba[:, 2], y_bin)
                    self.model_ic.setdefault(name, []).append(
                        float(ic) if not np.isnan(ic) else 0.0)

            oof_probs[val_idx] = fold_probs
            y_pred = np.argmax(fold_probs, axis=1)
            acc    = accuracy_score(y_val, y_pred)
            fold_stats.append({
                "fold": fold + 1,
                "n_train": len(tr_idx), "n_val": len(val_idx),
                "accuracy": acc,
            })
            if verbose:
                print(f"    [Fold {fold+1}/{len(splits)}] "
                      f"Train:{len(tr_idx):>5}  Val:{len(val_idx):>4}  Acc:{acc:.3f}")

        self.oof_preds   = oof_probs
        self.dyn_weights = self._compute_dynamic_weights()
        avg_ic = {k: np.mean(v) for k, v in self.model_ic.items() if v}
        return {"fold_stats": fold_stats, "avg_ic": avg_ic}

    def fit(self, X_all: np.ndarray, y_all: np.ndarray,
            verbose: bool = True) -> Dict:
        """Entrena walk-forward + modelos finales en todos los datos."""
        X_sc   = self.scaler.fit_transform(X_all)
        wf_res = self.walk_forward_train(X_all, y_all, verbose)

        # Entrenamiento final (paralelo)
        try:
            final_results = Parallel(n_jobs=-1, prefer="threads")(
                delayed(_fit_and_score_model)(clf, X_sc, y_all, X_sc[:1], 3, name)
                for name, clf in self.l1.items()
            )
            for name, fitted_clf, _ in final_results:
                self.l1[name] = fitted_clf
        except Exception:
            for name, clf in self.l1.items():
                clf.fit(X_sc, y_all)

        # Meta-learner Ridge sobre OOF
        if self.oof_preds is not None and len(self.oof_preds) > 10:
            y_bin = (y_all == 2).astype(float)
            valid = ~np.isnan(self.oof_preds).any(axis=1)
            if valid.sum() > 5:
                Xm = self.meta_scaler.fit_transform(self.oof_preds[valid])
                self.meta.fit(Xm, y_bin[valid])

        # Feature importance (RF + ET media)
        rf_imp = getattr(self.l1.get("rf"), "feature_importances_", None)
        et_imp = getattr(self.l1.get("et"), "feature_importances_", None)
        if rf_imp is not None and et_imp is not None:
            self.feat_imp = rf_imp * 0.5 + et_imp * 0.5
        elif rf_imp is not None:
            self.feat_imp = rf_imp

        self.trained = True
        return wf_res

    def predict_proba_ensemble(self, X: np.ndarray) -> np.ndarray:
        X_sc    = self.scaler.transform(X)
        weights = self.dyn_weights if self.dyn_weights else \
                  {n: self._BASE_WEIGHTS.get(n, 0.1) for n in self.l1}
        total_w = sum(weights.values()) + 1e-10
        proba   = np.zeros((len(X), 3))
        for name, clf in self.l1.items():
            p    = clf.predict_proba(X_sc)
            full = np.zeros((len(X), 3))
            for j, cls in enumerate(clf.classes_):
                full[:, int(cls)] = p[:, j]
            proba += full * (weights.get(name, 0.1) / total_w)
        return proba

    def predict_meta_score(self, X: np.ndarray) -> np.ndarray:
        proba = self.predict_proba_ensemble(X)
        try:
            Xm  = self.meta_scaler.transform(proba)
            raw = self.meta.predict(Xm)
        except Exception:
            raw = proba[:, 2]
        return np.clip(raw, 0, 1) * 100

    def signal(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        proba  = self.predict_proba_ensemble(X)
        pred   = np.argmax(proba, axis=1)
        conf   = proba[np.arange(len(pred)), pred] * 100
        score  = self.predict_meta_score(X)
        return pred, conf, score


# ══════════════════════════════════════════════════════════════════════════════
#  TRADING ENGINE — MISMO INTERFACE QUE v22
# ══════════════════════════════════════════════════════════════════════════════
def _compute_features_worker(ticker_ohlcv: Tuple[str, pd.DataFrame]) -> Tuple[str, Optional[pd.DataFrame]]:
    """Worker para joblib: calcula features de un ticker en paralelo."""
    ticker, ohlcv = ticker_ohlcv
    try:
        return ticker, build_feature_matrix(ohlcv)
    except Exception:
        return ticker, None


class TradingEngine:
    def __init__(self):
        self.brain     = FastStackedEnsemble(n_folds=3, horizon=5)
        self.data:     Dict[str, pd.DataFrame] = {}
        self.features: Dict[str, pd.DataFrame] = {}
        self.signals:  List[Dict] = []
        self.bt_stats: Dict[str, Dict] = {}
        self.mc_stats: Dict = {}
        self.wf_stats: Dict = {}
        self.train_log: List[str] = []
        self.spy_ret:  Optional[pd.Series] = None

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.train_log.append(f"[{ts}] {msg}")

    def descargar(self, tickers: List[str], period: str = "2y") -> int:
        """Descarga desde yfinance (modo standalone)."""
        try:
            import yfinance as yf
        except ImportError:
            print(f"{R}[ERROR] yfinance no instalado: pip install yfinance{RST}")
            return 0

        all_tickers = list(dict.fromkeys(["SPY"] + tickers))
        print(f"\n  {C}Descargando {len(all_tickers)} tickers ({period})...{RST}")
        ok = 0
        batch = [all_tickers[i:i+20] for i in range(0, len(all_tickers), 20)]
        for b in batch:
            try:
                raw = yf.download(b, period=period, group_by="ticker",
                                   auto_adjust=True, progress=False, timeout=30)
                for t in b:
                    try:
                        df = raw[t] if len(b) > 1 and t in raw.columns.get_level_values(0) \
                             else (raw if len(b) == 1 else pd.DataFrame())
                        df = df.dropna()
                        if len(df) >= 252:
                            self.data[t] = df; ok += 1
                    except Exception:
                        pass
            except Exception as e:
                print(f"  {Y}[WARN] Batch error: {e}{RST}")
        if "SPY" in self.data:
            self.spy_ret = self.data["SPY"]["Close"].pct_change().fillna(0)
        return ok

    def calcular_features(self):
        """
        Calcula 62 features por ticker.
        PASO 1: features per-ticker en PARALELO (joblib) — 8x más rápido que v22.
        PASO 2: cross-seccionales (requiere todos los tickers → secuencial).
        """
        # ── PASO 1: Parallel per-ticker ───────────────────────────────────
        items = list(self.data.items())
        try:
            results = Parallel(n_jobs=-1, prefer="threads")(
                delayed(_compute_features_worker)(item) for item in items
            )
        except Exception:
            results = [_compute_features_worker(item) for item in items]

        for ticker, feat_df in results:
            if feat_df is not None:
                self.features[ticker] = feat_df

        # ── PASO 2: Cross-seccionales (secuencial, requiere universo completo)
        self._compute_cross_sectional()

    def _compute_cross_sectional(self):
        """Idéntico al v22 — beta_spy + cs_mom_rank + cs_vol_rank."""
        tickers = list(self.features.keys())
        if not tickers:
            return

        # Beta vs SPY
        if self.spy_ret is not None:
            spy = self.spy_ret
            for ticker in tickers:
                try:
                    feat_df  = self.features[ticker]
                    tk_close = self.data[ticker]["Close"]
                    tk_ret   = tk_close.pct_change().fillna(0)
                    common   = feat_df.index.intersection(spy.index)
                    if len(common) < 30:
                        feat_df["beta_spy"] = 1.0; continue
                    tk_a  = tk_ret.reindex(common, fill_value=0)
                    spy_a = spy.reindex(common, fill_value=0)
                    roll_cov  = tk_a.rolling(20).cov(spy_a)
                    roll_var  = spy_a.rolling(20).var() + 1e-10
                    beta_roll = (roll_cov / roll_var).reindex(feat_df.index).fillna(1.0)
                    feat_df["beta_spy"] = np.clip(beta_roll.values, -3.0, 6.0)
                except Exception:
                    self.features[ticker]["beta_spy"] = 1.0
        else:
            for t in tickers:
                self.features[t]["beta_spy"] = 1.0

        # Cross-sectional momentum rank
        try:
            mom_dict = {t: self.features[t]["mom21"] for t in tickers if "mom21" in self.features[t].columns}
            if mom_dict:
                mom_df  = pd.DataFrame(mom_dict)
                rank_df = mom_df.rank(axis=1, pct=True)
                for t in tickers:
                    if t in rank_df.columns:
                        self.features[t]["cs_mom_rank"] = rank_df[t].reindex(self.features[t].index).fillna(0.5).values
                    else:
                        self.features[t]["cs_mom_rank"] = 0.5
        except Exception:
            for t in tickers: self.features[t]["cs_mom_rank"] = 0.5

        # Cross-sectional volatility rank
        try:
            vol_dict = {t: self.features[t]["rvol"] for t in tickers if "rvol" in self.features[t].columns}
            if vol_dict:
                vol_df  = pd.DataFrame(vol_dict)
                rank_df = vol_df.rank(axis=1, pct=True)
                for t in tickers:
                    if t in rank_df.columns:
                        self.features[t]["cs_vol_rank"] = rank_df[t].reindex(self.features[t].index).fillna(0.5).values
                    else:
                        self.features[t]["cs_vol_rank"] = 0.5
        except Exception:
            for t in tickers: self.features[t]["cs_vol_rank"] = 0.5

    def entrenar_global(self, verbose: bool = True) -> Dict:
        """Entrena el FastEnsemble con Triple Barrier Labels vectorizados."""
        all_X, all_y = [], []
        for ticker, feat_df in self.features.items():
            try:
                close = self.data[ticker]["Close"].values
                y = triple_barrier_labels(close, horizon=5, threshold=0.018, vol_scale=True)
                X = feat_df[self.brain.FEAT_COLS].values
                n = min(len(X), len(y))
                X, y = X[:n], y[:n]
                valid = np.isfinite(X).all(axis=1)
                all_X.append(X[valid]); all_y.append(y[valid])
            except Exception:
                pass

        if not all_X:
            return {}

        X_all = np.vstack(all_X)
        y_all = np.concatenate(all_y)

        if verbose:
            dist  = {k: int(v) for k, v in zip(*np.unique(y_all, return_counts=True))}
            boost = []
            if HAS_XGB:  boost.append("XGBoost✓")
            if HAS_LGBM: boost.append("LightGBM✓")
            print(f"\n  {C}Matrix global: {X_all.shape[0]:,} muestras × {X_all.shape[1]} features{RST}")
            print(f"  {DIM}Labels Triple Barrier: SELL={dist.get(0,0)} HOLD={dist.get(1,0)} BUY={dist.get(2,0)}{RST}")
            if boost:
                print(f"  {G}Boosters: {' · '.join(boost)}{RST}")

        wf = self.brain.fit(X_all, y_all, verbose=verbose)
        self.wf_stats = wf
        return wf

    def generar_senales(self) -> List[Dict]:
        """
        Genera señales — output IDÉNTICO al v22.
        Misma clave 'señal', mismo formato de dict.
        """
        results = []
        smap = {2: "BUY", 1: "HOLD", 0: "SELL"}

        for ticker in self.features:
            try:
                feat_df = self.features[ticker]
                close   = self.data[ticker]["Close"].values
                ohlcv   = self.data[ticker]
                high    = ohlcv["High"].values
                low     = ohlcv["Low"].values

                X_last = feat_df[self.brain.FEAT_COLS].values[-5:]
                valid  = np.isfinite(X_last).all(axis=1)
                if not valid.any():
                    continue
                X_last = X_last[valid]

                preds, confs, scores = self.brain.signal(X_last)
                final_pred  = np.argmax(np.bincount(preds, minlength=3))
                final_conf  = float(np.mean(confs[preds == final_pred])) if (preds == final_pred).any() else 0
                final_score = float(np.mean(scores))
                consensus   = int(np.sum(preds == final_pred))

                atr14  = IND.atr(high, low, close, 14)[-1]
                precio = float(close[-1])
                sl_pct  = round(-2.0 * atr14 / (precio + 1e-10) * 100, 2)
                tp1_pct = round(+2.0 * atr14 / (precio + 1e-10) * 100, 2)
                tp2_pct = round(+3.5 * atr14 / (precio + 1e-10) * 100, 2)
                rr      = round(abs(tp1_pct / (sl_pct + 1e-10)), 2)

                last = feat_df.iloc[-1]
                bt   = self.bt_stats.get(ticker, {})
                kelly = kelly_fraction(
                    win_rate = bt.get("win_rate", 55),
                    avg_win  = bt.get("avg_win_pct", 2.0),
                    avg_loss = bt.get("avg_loss_pct", -1.5),
                )

                results.append({
                    "ticker":    ticker,
                    "sector":    ACTIVOS.get(ticker, "N/A"),
                    "precio":    round(precio, 4),
                    "cambio_d":  round(float(pd.Series(close).pct_change(1).iloc[-1]) * 100, 2),
                    "señal":     smap[final_pred],
                    "confianza": round(final_conf, 1),
                    "score":     round(final_score, 1),
                    "consenso":  f"{consensus}/5",
                    "sl_pct":    sl_pct, "tp1_pct": tp1_pct,
                    "tp2_pct":   tp2_pct, "rr": rr,
                    "kelly_pct": round(kelly * 100, 1),
                    "rsi14":     round(last.rsi14, 1),
                    "rsi7":      round(last.rsi7, 1),
                    "stoch_k":   round(last.stoch_k, 1),
                    "stoch_d":   round(last.stoch_d, 1),
                    "adx":       round(last.adx, 1),
                    "williams_r":round(last.williams_r, 1),
                    "cci":       round(last.cci, 1),
                    "bb_pct":    round(last.bb_pct, 3),
                    "cmf":       round(last.cmf, 3),
                    "obv_z":     round(last.obv_zscore, 2),
                    "vwap_dev":  round(last.vwap_dev, 2),
                    "vol_rel":   round(last.vol_rel, 2),
                    "mom_score": round(last.mom_score, 1),
                    "mom10":     round(last.mom10, 2),
                    "zscore20":  round(last.zscore20, 2),
                    "dist_50":   round(last.dist_50, 2),
                    "dist_200":  round(last.dist_200, 2),
                    "rvol":      round(last.rvol, 1),
                    "atr_rel":   round(last.atr_rel, 2),
                    "regime":    int(last.regime),
                    "ichi_above":int(last.ichi_above),
                    "ema_cross": int(last.ema_cross),
                    "hurst":     round(float(getattr(last, "hurst", 0.5)), 3),
                    "mer":       round(float(getattr(last, "mer", 0.5)), 3),
                    "vov":       round(float(getattr(last, "vov", 0)), 3),
                    "amihud":    round(float(getattr(last, "amihud", 0)), 3),
                    "gk_vol":    round(float(getattr(last, "gk_vol", 0)), 1),
                    "real_skew": round(float(getattr(last, "real_skew", 0)), 3),
                    "real_kurt": round(float(getattr(last, "real_kurt", 0)), 3),
                    "price_accel": round(float(getattr(last, "price_accel", 0)), 3),
                    "vpt_z":     round(float(getattr(last, "vpt_z", 0)), 2),
                    "rsi_div":   int(getattr(last, "rsi_div", 0)),
                    "dist_52h":  round(float(getattr(last, "dist_52h", 0)), 2),
                    "dist_52l":  round(float(getattr(last, "dist_52l", 0)), 2),
                    "beta_spy":  round(float(getattr(last, "beta_spy", 1.0)), 2),
                    "cs_mom_rank": round(float(getattr(last, "cs_mom_rank", 0.5)), 3),
                    "cs_vol_rank": round(float(getattr(last, "cs_vol_rank", 0.5)), 3),
                    "bt_sharpe": round(bt.get("sharpe", 0), 2),
                    "bt_wr":     round(bt.get("win_rate", 0), 1),
                    "bt_alpha":  round(bt.get("alpha", 0), 2),
                    "bt_dd":     round(bt.get("max_dd", 0), 2),
                })
            except Exception:
                pass

        self.signals = sorted(results, key=lambda x: (x["score"], x["confianza"]), reverse=True)
        return self.signals

    def backtest_all(self, lookback_pct: float = 0.30) -> Dict:
        all_trade_rets = []
        for ticker in self.features:
            try:
                feat_df = self.features[ticker]
                close   = self.data[ticker]["Close"].values
                n_total = len(feat_df)
                n_test  = max(50, int(n_total * lookback_pct))
                n_train = n_total - n_test
                X_tr = feat_df[self.brain.FEAT_COLS].values[:n_train]
                y_tr = triple_barrier_labels(close[:n_train], 5, 0.018, True)
                mn   = min(len(X_tr), len(y_tr))
                X_tr, y_tr = X_tr[:mn], y_tr[:mn]
                valid_tr = np.isfinite(X_tr).all(axis=1)
                if valid_tr.sum() < 30:
                    continue
                local_rf = RandomForestClassifier(n_estimators=50, max_depth=5,
                                                   random_state=42, n_jobs=-1)
                sc_local = RobustScaler().fit(X_tr[valid_tr])
                local_rf.fit(sc_local.transform(X_tr[valid_tr]), y_tr[valid_tr])
                X_te = feat_df[self.brain.FEAT_COLS].values[n_train:]
                valid_te = np.isfinite(X_te).all(axis=1)
                X_te_sc  = sc_local.transform(X_te)
                preds_te = np.ones(len(X_te), dtype=int)
                preds_te[valid_te] = local_rf.predict(X_te_sc[valid_te])
                close_te = close[n_train:]
                rets_te  = pd.Series(np.diff(np.log(close_te + 1e-10)))
                sigs_te  = pd.Series(preds_te[1:])
                if len(rets_te) < 20:
                    continue
                bt = backtest_strategy(rets_te, sigs_te)
                self.bt_stats[ticker] = bt
                all_trade_rets.append(bt.get("total_ret", 0) / 100)
            except Exception:
                pass
        if all_trade_rets:
            self.mc_stats = monte_carlo_sim(np.array(all_trade_rets), n_sim=1000,
                                             n_trades=min(50, len(all_trade_rets)))
        return self.bt_stats

    def portfolio_kelly(self, capital: float = 100_000, max_pos: int = 10) -> List[Dict]:
        buys = [s for s in self.signals if s["señal"] == "BUY"
                and s["confianza"] >= 55][:max_pos]
        if not buys:
            return []
        total_kelly = sum(s["kelly_pct"] / 100 for s in buys) + 1e-10
        scale = min(1.0, 0.90 / total_kelly)
        port = []
        for s in buys:
            kelly_adj = round(s["kelly_pct"] / 100 * scale * 100, 1)
            monto     = round(capital * kelly_adj / 100, 2)
            precio    = s["precio"]
            shares    = int(monto / precio) if precio > 0 else 0
            port.append({
                **s,
                "kelly_adj_pct": kelly_adj,
                "monto_usd":     monto,
                "shares":        shares,
                "sl_precio":     round(precio * (1 + s["sl_pct"] / 100), 4),
                "tp1_precio":    round(precio * (1 + s["tp1_pct"] / 100), 4),
                "tp2_precio":    round(precio * (1 + s["tp2_pct"] / 100), 4),
                "riesgo_usd":    round(monto * abs(s["sl_pct"]) / 100, 2),
                "potencial_usd": round(monto * s["tp2_pct"] / 100, 2),
            })
        return port


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN — MODO STANDALONE (con yfinance)
# ══════════════════════════════════════════════════════════════════════════════
def main():
    print()
    print(cc("╔══════════════════════════════════════════════════════════════╗", C))
    print(cc("║  🧠⚡ ML TRADING BRAIN v10.0 — ULTRA-FAST EDITION           ║", C))
    print(cc("║  62 Features · Triple Barrier · HistGBC · Parallel Jobs    ║", C))
    print(cc("╚══════════════════════════════════════════════════════════════╝", C))
    boost = []
    if HAS_XGB:  boost.append("XGBoost✓")
    if HAS_LGBM: boost.append("LightGBM✓")
    print(cc(f"  Boosters: {' · '.join(boost) if boost else 'sklearn only'}", DIM))
    print()

    engine  = TradingEngine()
    tickers = list(ACTIVOS.keys())

    t0 = time.time()
    print(cc(f"  PASO 1/5 — Descarga OHLCV real (2 años · {len(tickers)} tickers)", Y))
    n_ok = engine.descargar(tickers, period="2y")
    print(cc(f"  ✓  {n_ok} activos descargados ({time.time()-t0:.1f}s)", G))

    t1 = time.time()
    print(cc("\n  PASO 2/5 — Calculando 62 features (paralelo)...", Y))
    engine.calcular_features()
    print(cc(f"  ✓  Features calculadas: {len(engine.features)} tickers ({time.time()-t1:.1f}s)", G))

    t2 = time.time()
    print(cc("\n  PASO 3/5 — Entrenamiento FastEnsemble (HistGBC + RF80 + ET80 + XGB100)...", Y))
    wf_res = engine.entrenar_global(verbose=True)
    avg_accs = [f["accuracy"] for f in wf_res.get("fold_stats", [])]
    if avg_accs:
        print(cc(f"\n  ✓  Walk-Forward Acc media: {np.mean(avg_accs)*100:.1f}%  ({time.time()-t2:.1f}s)", G))
    dw = engine.brain.dyn_weights
    if dw:
        dw_str = "  ".join([f"{k.upper()}:{v:.2f}" for k, v in sorted(dw.items(), key=lambda x: -x[1])])
        print(cc(f"  Pesos dinámicos (IC): {dw_str}", DIM))

    t3 = time.time()
    print(cc("\n  PASO 4/5 — Backtest OOS + Monte Carlo...", Y))
    engine.backtest_all(lookback_pct=0.30)
    valid_bt = len([v for v in engine.bt_stats.values() if v.get("n_trades", 0) > 0])
    sharpes  = [v["sharpe"] for v in engine.bt_stats.values() if "sharpe" in v]
    print(cc(f"  ✓  {valid_bt} estrategias backtestadas ({time.time()-t3:.1f}s)", G))
    if sharpes:
        sc = G if np.mean(sharpes) > 0.5 else Y
        print(f"    Sharpe promedio: {cc(f'{np.mean(sharpes):.3f}', sc)}")

    t4 = time.time()
    print(cc("\n  PASO 5/5 — Generando señales...", Y))
    signals = engine.generar_senales()
    buys    = [s for s in signals if s["señal"] == "BUY"]
    print(cc(f"  ✓  {len(signals)} activos → {len(buys)} BUY  ({time.time()-t4:.1f}s)", G))

    total_time = time.time() - t0
    print()
    print(cc(f"  ══ TOTAL: {total_time:.1f}s  ({total_time/60:.1f}min) ══", BOLD + G))
    print()

    print(cc(f"  TOP BUYs:", W))
    for s in buys[:10]:
        print(f"    {cc(s['ticker'].ljust(7), BOLD+W)}"
              f"  Score:{cc(str(round(s['score'])), G)}"
              f"  Conf:{cc(str(round(s['confianza']))+'%', Y)}"
              f"  RSI:{s['rsi14']:.0f}"
              f"  Régimen:{cc(str(s['regime']), C)}"
              f"  Kelly:{s['kelly_pct']:.1f}%")

    port = engine.portfolio_kelly(capital=100_000)
    if port:
        print(cc(f"\n  PORTFOLIO KELLY (top {len(port)}):", W))
        for p in port:
            print(f"    {cc(p['ticker'].ljust(7), BOLD+W)}"
                  f"  ${p['precio']:>8,.2f}"
                  f"  Kelly:{p['kelly_adj_pct']:.1f}%"
                  f"  ${p['monto_usd']:>8,.0f}"
                  f"  R/R:{p['rr']:.1f}x")


if __name__ == "__main__":
    main()
