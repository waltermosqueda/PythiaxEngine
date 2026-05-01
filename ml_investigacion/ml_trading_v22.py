#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   🧠⚡ ML TRADING BRAIN v9.0 — QUANT PROFESSIONAL EDITION (v20)             ║
║   Purged Walk-Forward · Deep Stacking · 62 Features · Kelly · Monte Carlo  ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  ARQUITECTURA CUANTITATIVA INSTITUCIONAL v20:                               ║
║  ▸ MICROESTRUCTURA: Amihud Illiquidity · Garman-Klass Vol · Beta SPY       ║
║  ▸ REGIMEN: Hurst Exponent · Market Efficiency Ratio · Vol-of-Vol          ║
║  ▸ DISTRIBUCIÓN: Realized Skewness · Realized Kurtosis · Price Accel       ║
║  ▸ NIVEL: 52W High/Low · VPT Z-Score · RSI Divergence                     ║
║  ▸ CROSS-SECTIONAL: Mom-Rank · Vol-Rank (percentil universo)               ║
║  ▸ LABELS: Triple Barrier Method (Lopez de Prada) con vol-scaling          ║
║  ▸ CV: Purged Walk-Forward + Embargo anti-leakage                          ║
║  ▸ MODELOS: +XGBoost +LightGBM (auto-detect) · Dynamic IC Weighting        ║
║  ▸ META: Metalabeling layer para filtrar señales de baja calidad           ║
╚══════════════════════════════════════════════════════════════════════════════╝
  pip install yfinance numpy pandas scikit-learn scipy rich xgboost lightgbm
"""
import os, sys, math, warnings, time, csv
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from scipy.stats import spearmanr
from sklearn.ensemble import (RandomForestClassifier, GradientBoostingClassifier,
                               ExtraTreesClassifier, RandomForestRegressor)
from sklearn.neural_network import MLPClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.calibration import CalibratedClassifierCV, IsotonicRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_score, f1_score
# ── Modelos de boosting avanzado (auto-detect) ────────────────────────────
try:
    from xgboost import XGBClassifier
    HAS_XGB  = True
except ImportError:
    HAS_XGB  = False
try:
    from lightgbm import LGBMClassifier
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    from rich.text import Text
    from rich.rule import Rule
    from rich import box
    HAS_RICH = True
    console = Console()
except ImportError:
    HAS_RICH = False
    class Console:
        def print(self, *a, **kw): print(*a)
        def input(self, p=""): return input(p)
        def rule(self, *a, **kw): print("─" * 80)
    console = Console()
# ══════════════════════════════════════════════════════════════════════════════
#  COLORES ANSI (fallback si no hay rich)
# ══════════════════════════════════════════════════════════════════════════════
R="\033[91m"; G="\033[92m"; Y="\033[93m"; B="\033[94m"
M="\033[95m"; C="\033[96m"; W="\033[97m"; DIM="\033[2m"
BOLD="\033[1m"; RST="\033[0m"
def cc(t, col): return f"{col}{t}{RST}"
def clr(): os.system("cls" if os.name == "nt" else "clear")
def press(): input(f"\n  {DIM}[ ENTER para continuar ]{RST}")
# ══════════════════════════════════════════════════════════════════════════════
#  UNIVERSO DE ACTIVOS (idéntico a v14)
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
#  MOTOR DE INDICADORES TÉCNICOS (100% OHLCV REAL)
# ══════════════════════════════════════════════════════════════════════════════
class Indicators:
    """Indicadores técnicos calculados sobre datos OHLCV reales."""
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
    def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
            n: int = 14) -> np.ndarray:
        prev_close = np.roll(close, 1); prev_close[0] = close[0]
        tr = np.maximum(high - low,
             np.maximum(np.abs(high - prev_close),
                        np.abs(low  - prev_close)))
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
    def donchian(high: np.ndarray, low: np.ndarray,
                 n: int = 20) -> Tuple[np.ndarray, np.ndarray]:
        upper = pd.Series(high).rolling(n).max().values
        lower = pd.Series(low).rolling(n).min().values
        return upper, lower
    @staticmethod
    def ichimoku_cloud(high: np.ndarray, low: np.ndarray,
                       close: np.ndarray) -> Dict[str, np.ndarray]:
        def midpoint(h, l, n):
            return (pd.Series(h).rolling(n).max().values +
                    pd.Series(l).rolling(n).min().values) / 2
        tenkan = midpoint(high, low, 9)
        kijun  = midpoint(high, low, 26)
        span_a = (tenkan + kijun) / 2
        span_b = midpoint(high, low, 52)
        return {"tenkan": tenkan, "kijun": kijun,
                "span_a": span_a, "span_b": span_b,
                "above_cloud": (close > np.maximum(span_a, span_b)).astype(float)}
    @staticmethod
    def momentum_score(close: np.ndarray) -> np.ndarray:
        s  = pd.Series(close)
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
    def williams_r(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                   n: int = 14) -> np.ndarray:
        hh = pd.Series(high).rolling(n).max().values
        ll = pd.Series(low).rolling(n).min().values
        return (hh - close) / (hh - ll + 1e-10) * -100
    @staticmethod
    def cci(high: np.ndarray, low: np.ndarray, close: np.ndarray,
            n: int = 20) -> np.ndarray:
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
        regime = np.where(close > upper, 1.0,
                 np.where(close < lower, -1.0, 0.0))
        return regime

    # ══════════════════════════════════════════════════════════════════════
    #  INDICADORES CUANTITATIVOS AVANZADOS (v20)
    # ══════════════════════════════════════════════════════════════════════

    @staticmethod
    def hurst_exponent(close: np.ndarray, n: int = 100) -> np.ndarray:
        """
        Exponente de Hurst via escalado de varianza.
        H > 0.55 → mercado tendencial  → momentum funciona
        H < 0.45 → reversión a media   → mean-reversion funciona
        H ≈ 0.50 → caminata aleatoria  → señal débil
        Referencia: Peters (1994), Lo (1991).
        """
        result = np.full(len(close), 0.5)
        log_p  = np.log(np.maximum(close, 1e-10))
        for i in range(n, len(close)):
            window = log_p[i-n:i]
            try:
                lags  = [2, 4, 8, 16, 32]
                pairs = []
                for lag in lags:
                    diffs = window[lag:] - window[:-lag]
                    if len(diffs) > 1:
                        pairs.append((lag, np.var(diffs)))
                if len(pairs) >= 3:
                    lx = np.log([p[0] for p in pairs])
                    ly = np.log([p[1] + 1e-20 for p in pairs])
                    h  = np.polyfit(lx, ly, 1)[0] / 2.0
                    result[i] = float(np.clip(h, 0.0, 1.0))
            except Exception:
                pass
        return result

    @staticmethod
    def amihud_illiquidity(close: np.ndarray, volume: np.ndarray,
                            n: int = 20) -> np.ndarray:
        """
        Ratio de iliquidez de Amihud (2002) = |ret| / volumen_dolar.
        Mide el impacto en precio por millón de dólares negociados.
        Z-score cross-temporal: alto = ilíquido (señal de riesgo o squeeze).
        """
        ret    = np.abs(np.diff(np.log(np.maximum(close, 1e-10)),
                                prepend=np.log(close[0]+1e-10)))
        dv     = close * volume + 1.0         # dollar volume
        raw    = ret / dv * 1_000_000         # escalar a millones
        s      = pd.Series(raw)
        roll_m = s.rolling(252, min_periods=60).mean()
        roll_s = s.rolling(252, min_periods=60).std()
        return ((s - roll_m) / (roll_s + 1e-10)).fillna(0).values

    @staticmethod
    def garman_klass_vol(open_: np.ndarray, high: np.ndarray,
                          low: np.ndarray, close: np.ndarray,
                          n: int = 20) -> np.ndarray:
        """
        Volatilidad de Garman-Klass (1980) — usa rango OHLC completo.
        5–8x más eficiente que close-to-close. Esencial para vol-targeting.
        GK = sqrt( 0.5*(ln H/L)^2 − (2ln2−1)*(ln C/O)^2 )
        """
        log_hl = np.log(np.maximum(high,  1e-10) /
                        np.maximum(low,   1e-10)) ** 2
        log_co = np.log(np.maximum(close, 1e-10) /
                        np.maximum(open_, 1e-10)) ** 2
        raw = np.maximum(0.5 * log_hl - (2 * np.log(2) - 1) * log_co, 0)
        gk  = np.sqrt(pd.Series(raw).rolling(n).mean().values) * np.sqrt(252) * 100
        return np.nan_to_num(gk, nan=0.0)

    @staticmethod
    def realized_skew(close: np.ndarray, n: int = 21) -> np.ndarray:
        """
        Asimetría realizada de retornos logarítmicos (ventana 21 días).
        Negativo → colas más pesadas a la baja (riesgo de caída).
        Positivo → potencial de saltos alcistas.
        Predictor documentado de retornos futuros (Harvey & Siddique 2000).
        """
        rets = pd.Series(np.diff(np.log(np.maximum(close, 1e-10)),
                                  prepend=np.log(close[0]+1e-10)))
        return rets.rolling(n, min_periods=5).skew().fillna(0).values

    @staticmethod
    def realized_kurt(close: np.ndarray, n: int = 21) -> np.ndarray:
        """
        Curtosis realizada (exceso, ventana 21 días).
        Alto → colas pesadas → mayor riesgo de gap o colapso.
        Usado en gestión de riesgo institucional y factor models.
        """
        rets = pd.Series(np.diff(np.log(np.maximum(close, 1e-10)),
                                  prepend=np.log(close[0]+1e-10)))
        return rets.rolling(n, min_periods=5).kurt().fillna(0).values

    @staticmethod
    def market_efficiency_ratio(close: np.ndarray, n: int = 20) -> np.ndarray:
        """
        Ratio de Eficiencia de Mercado (Kaufman 1995).
        MER = |desplazamiento neto| / Σ|variaciones absolutas|
        MER → 1: movimiento perfectamente tendencial (momentum rentable).
        MER → 0: movimiento caótico (mean-reversion rentable).
        Adapta la estrategia al régimen corriente del mercado.
        """
        result = np.zeros(len(close))
        for i in range(n, len(close)):
            w = close[i-n:i]
            direction = abs(w[-1] - w[0])
            noise     = np.sum(np.abs(np.diff(w)))
            result[i] = direction / (noise + 1e-10)
        return result

    @staticmethod
    def vol_of_vol(close: np.ndarray, inner: int = 10,
                   outer: int = 30) -> np.ndarray:
        """
        Volatilidad de la volatilidad (VoV).
        Captura cambios de régimen de vol antes de que el precio los refleje.
        Alto VoV → incertidumbre estructural → reducir tamaño de posición.
        Predictor de cola derecha (jumps) y cambios de régimen.
        """
        rets  = pd.Series(np.diff(np.log(np.maximum(close, 1e-10)),
                                   prepend=np.log(close[0]+1e-10)))
        rvol  = rets.rolling(inner, min_periods=3).std() * np.sqrt(252) * 100
        return rvol.rolling(outer, min_periods=10).std().fillna(0).values

    @staticmethod
    def price_acceleration(close: np.ndarray, n: int = 5) -> np.ndarray:
        """
        Aceleración del precio (segunda derivada del momentum).
        Positivo y creciente → momentum acelerando (entrada agresiva).
        Positivo y decreciente → momentum agotándose (salida pronto).
        Análogo a la aceleración en física: ΔΔprecio / Δt².
        """
        s    = pd.Series(close)
        mom1 = s.pct_change(n)
        accel= mom1.diff(n)
        return accel.fillna(0).values * 100

    @staticmethod
    def vpt_zscore(close: np.ndarray, volume: np.ndarray,
                   n_z: int = 50) -> np.ndarray:
        """
        Volume Price Trend (VPT) normalizado como Z-Score.
        Similar a OBV pero ponderado por magnitud del cambio de precio.
        Divergencia VPT/precio → señal predictiva de inversión de tendencia.
        Z-Score para comparabilidad cross-sectional.
        """
        pct     = np.diff(close, prepend=close[0]) / (np.maximum(close, 1e-10))
        raw_vpt = np.cumsum(pct * volume)
        s       = pd.Series(raw_vpt)
        return ((s - s.rolling(n_z).mean()) /
                (s.rolling(n_z).std() + 1e-10)).fillna(0).values

    @staticmethod
    def rsi_divergence(close: np.ndarray, rsi_vals: np.ndarray,
                        window: int = 10) -> np.ndarray:
        """
        Divergencia precio-RSI (señal clásica de institucionales).
        +1 : divergencia alcista  — precio ↓ pero RSI ↑  → BUY setup
        -1 : divergencia bajista  — precio ↑ pero RSI ↓  → SELL setup
         0 : sin divergencia — sin señal adicional
        Evita comprar momentum exhausto y vender capitulación temprana.
        """
        price_trend = pd.Series(close).diff(window).fillna(0)
        rsi_trend   = pd.Series(rsi_vals).diff(window).fillna(0)
        bull = ((price_trend < 0) & (rsi_trend > 1)).astype(float)
        bear = ((price_trend > 0) & (rsi_trend < -1)).astype(float) * -1
        return (bull + bear).values
# ══════════════════════════════════════════════════════════════════════════════
#  CONSTRUCCIÓN DEL DATASET DE FEATURES (con dos nuevas features de v11)
# ══════════════════════════════════════════════════════════════════════════════
IND = Indicators()
def build_feature_matrix(ohlcv: pd.DataFrame,
                          cross_feats: dict = None) -> pd.DataFrame:
    """
    Genera 59 features cuantitativas (47 originales + 12 nuevas v20).
    cross_feats: dict con features cross-seccionales inyectadas por TradingEngine
                 (beta_spy, cs_mom_rank, cs_vol_rank) → total 62 features.
    """
    o = ohlcv["Open"].values
    h = ohlcv["High"].values
    l = ohlcv["Low"].values
    c = ohlcv["Close"].values
    v = ohlcv["Volume"].values + 1  # evitar zeros
    # ── RSI ──────────────────────────────────────────────────────────────
    rsi14  = IND.rsi(c, 14)
    rsi7   = IND.rsi(c, 7)
    rsi21  = IND.rsi(c, 21)
    # ── ATR real ─────────────────────────────────────────────────────────
    atr14  = IND.atr(h, l, c, 14)
    atr_rel= atr14 / (c + 1e-10) * 100  # ATR como % del precio
    # ── Bollinger ─────────────────────────────────────────────────────────
    bb_u, bb_m, bb_l = IND.bollinger(c, 20)
    bb_pct = (c - bb_l) / (bb_u - bb_l + 1e-10)        # posición 0..1
    bb_width= (bb_u - bb_l) / (bb_m + 1e-10) * 100      # ancho relativo
    bb_squeeze = (bb_width < pd.Series(bb_width).rolling(50).mean().values).astype(float)
    # ── MACD ──────────────────────────────────────────────────────────────
    macd_l, macd_s, macd_h = IND.macd(c)
    macd_cross_up   = ((macd_h > 0) & (np.roll(macd_h, 1) <= 0)).astype(float)
    macd_cross_down = ((macd_h < 0) & (np.roll(macd_h, 1) >= 0)).astype(float)
    # ── Stochastic REAL ───────────────────────────────────────────────────
    sk, sd = IND.stochastic(h, l, c, 14, 3)
    stoch_cross_up   = ((sk > sd) & (np.roll(sk, 1) <= np.roll(sd, 1))).astype(float)
    stoch_cross_down = ((sk < sd) & (np.roll(sk, 1) >= np.roll(sd, 1))).astype(float)
    # ── ADX real ──────────────────────────────────────────────────────────
    adx_v, pdi, mdi = IND.adx(h, l, c, 14)
    di_diff = pdi - mdi  # positivo = tendencia alcista
    # ── Williams %R ───────────────────────────────────────────────────────
    wr = IND.williams_r(h, l, c, 14)
    # ── CCI ───────────────────────────────────────────────────────────────
    cci_v = IND.cci(h, l, c, 20)
    # ── OBV ───────────────────────────────────────────────────────────────
    obv   = IND.obv(c, v)
    obv_z = IND.zscore(obv, 20)  # Z-Score del OBV
    # ── CMF ───────────────────────────────────────────────────────────────
    cmf_v = IND.cmf(h, l, c, v, 20)
    # ── VWAP deviation ────────────────────────────────────────────────────
    vwap_dev = IND.vwap_deviation(h, l, c, v, 20)
    # ── Donchian ──────────────────────────────────────────────────────────
    dc_u, dc_l = IND.donchian(h, l, 20)
    dc_pos = (c - dc_l) / (dc_u - dc_l + 1e-10)
    # ── Ichimoku ──────────────────────────────────────────────────────────
    ichi   = IND.ichimoku_cloud(h, l, c)
    ichi_above = ichi["above_cloud"]
    tenkan_kijun = (ichi["tenkan"] > ichi["kijun"]).astype(float)
    # ── MAs y distancias ──────────────────────────────────────────────────
    def sma(x, n): return pd.Series(x).rolling(n).mean().values
    def ema(x, n): return pd.Series(x).ewm(span=n, adjust=False).mean().values
    ma20  = sma(c, 20); ma50 = sma(c, 50); ma200 = sma(c, 200)
    ema9  = ema(c, 9);  ema21 = ema(c, 21)
    dist_20  = (c - ma20) / (ma20 + 1e-10) * 100
    dist_50  = (c - ma50) / (ma50 + 1e-10) * 100
    dist_200 = (c - ma200) / (ma200 + 1e-10) * 100
    ema_cross = (ema9 > ema21).astype(float)  # Golden/Death cross proxy
    # ── Momentum multi-período ────────────────────────────────────────────
    mom_score = IND.momentum_score(c)
    mom5  = pd.Series(c).pct_change(5).values * 100
    mom10 = pd.Series(c).pct_change(10).values * 100
    mom21 = pd.Series(c).pct_change(21).values * 100
    # ── Volatilidad realizada ─────────────────────────────────────────────
    rvol  = IND.realized_vol(c, 20)
    rvol_ratio = rvol / (pd.Series(rvol).rolling(50).mean().values + 1e-10)  # vol relativa
    # ── Z-Score precio ────────────────────────────────────────────────────
    zscore_20  = IND.zscore(c, 20)
    zscore_50  = IND.zscore(c, 50)
    # ── Volumen ───────────────────────────────────────────────────────────
    vol_ma20  = sma(v, 20)
    vol_rel   = v / (vol_ma20 + 1e-10)
    vol_log   = np.log1p(v / 1e6)
    vol_trend = (pd.Series(v).rolling(5).mean().values /
                 (pd.Series(v).rolling(20).mean().values + 1e-10))
    # ── Régimen de mercado ────────────────────────────────────────────────
    regime    = IND.regime_hmm(c, 50)
    # ── Gap y rango de velas ──────────────────────────────────────────────
    prev_c = np.roll(c, 1); prev_c[0] = c[0]
    gap    = (o - prev_c) / (prev_c + 1e-10) * 100
    candle_body = np.abs(c - o) / (h - l + 1e-10)   # ratio cuerpo/rango
    upper_wick  = (h - np.maximum(o, c)) / (h - l + 1e-10)
    lower_wick  = (np.minimum(o, c) - l) / (h - l + 1e-10)

    # ── FEATURES ADICIONALES DE v11 ──────────────────────────────────────
    retorno_diario = pd.Series(c).pct_change().values * 100      # retorno diario %
    mean_reversion = -zscore_20 * 10                              # fuerza de reversión

    # ════════════════════════════════════════════════════════════════════════
    #  FEATURES CUANTITATIVAS AVANZADAS (v20) — +12 nuevas
    # ════════════════════════════════════════════════════════════════════════

    # ── RÉGIMEN DE MERCADO ────────────────────────────────────────────────
    hurst     = IND.hurst_exponent(c, n=100)          # tendencial vs mean-rev
    mer       = IND.market_efficiency_ratio(c, n=20)  # eficiencia/ruido local
    vov       = IND.vol_of_vol(c, inner=10, outer=30) # vol de vol (cambios régimen)

    # ── MICROESTRUCTURA ───────────────────────────────────────────────────
    amihud    = IND.amihud_illiquidity(c, v, n=20)    # impacto precio/dólar
    gk_vol    = IND.garman_klass_vol(o, h, l, c, n=20)# vol OHLC (5-8x más precisa)

    # ── DISTRIBUCIÓN DE RETORNOS ──────────────────────────────────────────
    real_skew = IND.realized_skew(c, n=21)            # asimetría de retornos
    real_kurt = IND.realized_kurt(c, n=21)            # curtosis / colas pesadas

    # ── MOMENTUM / ACELERACIÓN ────────────────────────────────────────────
    price_accel = IND.price_acceleration(c, n=5)      # 2da derivada del precio
    vpt_z     = IND.vpt_zscore(c, v, n_z=50)         # VPT normalizado

    # ── SEÑALES DE DIVERGENCIA ────────────────────────────────────────────
    rsi_div   = IND.rsi_divergence(c, rsi14, window=10) # divergencia precio-RSI

    # ── NIVELES DE PRECIO ABSOLUTOS ───────────────────────────────────────
    high_252  = pd.Series(h).rolling(252, min_periods=60).max().values
    low_252   = pd.Series(l).rolling(252, min_periods=60).min().values
    dist_52h  = (c - high_252) / (high_252 + 1e-10) * 100   # dist. del máximo anual (%)
    dist_52l  = (c - low_252)  / (low_252  + 1e-10) * 100   # dist. del mínimo anual (%)

    df = pd.DataFrame({
        # RSI family
        "rsi14": rsi14, "rsi7": rsi7, "rsi21": rsi21,
        # ATR
        "atr_rel": atr_rel,
        # Bollinger
        "bb_pct": bb_pct, "bb_width": bb_width, "bb_squeeze": bb_squeeze,
        # MACD
        "macd_hist": macd_h, "macd_line": macd_l,
        "macd_cross_up": macd_cross_up, "macd_cross_down": macd_cross_down,
        # Stochastic
        "stoch_k": sk, "stoch_d": sd,
        "stoch_cross_up": stoch_cross_up, "stoch_cross_down": stoch_cross_down,
        # ADX
        "adx": adx_v, "di_diff": di_diff,
        # Osciladores
        "williams_r": wr, "cci": cci_v,
        # Volume indicators
        "obv_zscore": obv_z, "cmf": cmf_v, "vol_rel": vol_rel,
        "vol_log": vol_log, "vol_trend": vol_trend,
        # Price positioning
        "vwap_dev": vwap_dev, "dc_pos": dc_pos,
        # Ichimoku
        "ichi_above": ichi_above, "tenkan_kijun": tenkan_kijun,
        # MA distances
        "dist_20": dist_20, "dist_50": dist_50, "dist_200": dist_200,
        "ema_cross": ema_cross,
        # Momentum
        "mom_score": mom_score, "mom5": mom5, "mom10": mom10, "mom21": mom21,
        # Volatility
        "rvol": rvol, "rvol_ratio": rvol_ratio,
        # Z-Score
        "zscore20": zscore_20, "zscore50": zscore_50,
        # Candle structure
        "gap": gap, "candle_body": candle_body,
        "upper_wick": upper_wick, "lower_wick": lower_wick,
        # Regime
        "regime": regime,
        # Nuevas (v11)
        "retorno_diario": retorno_diario,
        "mean_reversion": mean_reversion,
        # ── FEATURES CUANTITATIVAS v20 ────────────────────────────────────
        # Régimen
        "hurst":       hurst,       # Hurst: 0=mean-rev, 0.5=random, 1=trend
        "mer":         mer,         # Market Efficiency Ratio (Kaufman)
        "vov":         vov,         # Volatility of Volatility
        # Microestructura
        "amihud":      amihud,      # Illiquidity z-score (Amihud 2002)
        "gk_vol":      gk_vol,      # Garman-Klass volatility anualizada
        # Distribución
        "real_skew":   real_skew,   # Skewness realizada 21d
        "real_kurt":   real_kurt,   # Kurtosis realizada 21d
        # Momentum avanzado
        "price_accel": price_accel, # Aceleración del precio
        "vpt_z":       vpt_z,       # VPT Z-score (volumen+precio)
        # Divergencia
        "rsi_div":     rsi_div,     # Divergencia precio-RSI
        # Niveles anuales
        "dist_52h":    dist_52h,    # Distancia al máximo 52 semanas (%)
        "dist_52l":    dist_52l,    # Distancia al mínimo 52 semanas (%)
    }, index=ohlcv.index)

    # ── FEATURES CROSS-SECCIONALES (inyectadas por TradingEngine) ─────────
    # beta_spy, cs_mom_rank, cs_vol_rank se añaden en el segundo paso.
    # Si se pasan aquí, se aplican; de lo contrario se usan defaults neutros.
    CF_DEFAULTS = {"beta_spy": 1.0, "cs_mom_rank": 0.5, "cs_vol_rank": 0.5}
    for k, default in CF_DEFAULTS.items():
        if cross_feats and k in cross_feats:
            val = cross_feats[k]
            df[k] = val if hasattr(val, "__len__") else np.full(len(df), val)
        else:
            df[k] = default

    return df.fillna(0).replace([np.inf, -np.inf], 0)

def make_labels(close: np.ndarray, horizon: int = 5,
                threshold: float = 0.02) -> np.ndarray:
    """
    Etiquetas forward-looking REALES (sin lookahead).
    BUY=2 si retorno futuro > threshold, SELL=0 si < -threshold, HOLD=1.
    """
    fwd = pd.Series(close).pct_change(horizon).shift(-horizon).values
    labels = np.where(fwd > threshold, 2,
             np.where(fwd < -threshold, 0, 1))
    return labels.astype(int)

def triple_barrier_labels(close: np.ndarray,
                           horizon:   int   = 5,
                           threshold: float = 0.02,
                           vol_scale: bool  = True) -> np.ndarray:
    """
    Triple Barrier Method — Lopez de Prada (2018), cap. 3.

    Etiqueta cada muestra según cuál barrera se toca primero:
      · Barrera superior (+threshold) → BUY  (2)
      · Barrera inferior (−threshold) → SELL (0)
      · Barrera vertical (horizon)    → HOLD (1)  ← lo que ocurra primero

    vol_scale=True: las barreras se escalan con la volatilidad realizada
    local, haciendo los umbrales adaptativos al régimen de vol actual.
    Esto evita etiquetar como HOLD movimientos significativos en activos
    de baja volatilidad y como BUY/SELL ruido en activos de alta volatilidad.

    Más realista que el threshold fijo porque:
    1. Incorpora la dinámica de stops reales (SL dinámico)
    2. Refleja el concepto de "risk-adjusted return"
    3. Aumenta la proporción de señales de alta convicción
    """
    n      = len(close)
    labels = np.ones(n, dtype=int)   # default: HOLD

    # Calcular volatilidad realizada rolling (para vol_scale)
    log_rets = np.diff(np.log(np.maximum(close, 1e-10)))
    log_rets = np.concatenate([[0], log_rets])

    for i in range(n - horizon):
        entry = close[i]
        if entry <= 0:
            continue

        # Umbral adaptativo por volatilidad
        if vol_scale:
            # vol diaria annualizada en ventana 20d anterior
            window_vol = np.std(log_rets[max(0, i-20):i]) if i >= 5 else 0
            daily_vol  = max(window_vol, 0.005)           # mínimo 0.5%/día
            bar        = max(threshold, daily_vol * np.sqrt(horizon) * 0.75)
        else:
            bar = threshold

        upper = entry * (1.0 + bar)
        lower = entry * (1.0 - bar)

        for j in range(i + 1, min(i + horizon + 1, n)):
            p = close[j]
            if p >= upper:
                labels[i] = 2    # BUY: barrera superior tocada
                break
            if p <= lower:
                labels[i] = 0    # SELL: barrera inferior tocada
                break
        # Si ninguna barrera es tocada → HOLD (ya inicializado en 1)

    # Eliminar últimas filas sin horizon completo (sin lookahead)
    labels[-horizon:] = 1
    return labels
# ══════════════════════════════════════════════════════════════════════════════
#  STACKING META-LEARNER (con calibración isotónica)
# ══════════════════════════════════════════════════════════════════════════════
class StackedEnsemble:
    """
    Dos niveles de ensemble cuantitativo institucional (v20):

    Nivel 1 — Base Learners (heterogéneos):
      RF · GradientBoosting · ExtraTrees · MLP · LogisticRegression
      + XGBoost (si disponible) + LightGBM (si disponible)

    Nivel 2 — Meta-Learner:
      Ridge Regression sobre probabilidades OOF del nivel 1
      (Stacking clásico de Wolpert 1992)

    Mejoras v20 vs v18:
      · 62 features (59 per-ticker + 3 cross-seccionales)
      · Labels: Triple Barrier Method (vol-adjusted)
      · CV: Purged Walk-Forward + Embargo (anti-leakage de etiquetas solapadas)
      · Pesos dinámicos por IC reciente (no fijos como en versiones previas)
      · Metalabeling: segundo clasificador que filtra señales primarias
    """
    FEAT_COLS = [
        # ── TÉCNICOS ORIGINALES (47) ─────────────────────────────────────
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
        # ── RÉGIMEN (3) ──────────────────────────────────────────────────
        "hurst",        # Exponente de Hurst: 0=reversión, 1=tendencia
        "mer",          # Market Efficiency Ratio (Kaufman)
        "vov",          # Volatility of Volatility — cambios de régimen
        # ── MICROESTRUCTURA (2) ──────────────────────────────────────────
        "amihud",       # Illiquidity z-score (Amihud 2002)
        "gk_vol",       # Garman-Klass vol anualizada (OHLC)
        # ── DISTRIBUCIÓN DE RETORNOS (2) ─────────────────────────────────
        "real_skew",    # Skewness realizada 21d
        "real_kurt",    # Kurtosis realizada 21d (colas pesadas)
        # ── MOMENTUM AVANZADO (2) ────────────────────────────────────────
        "price_accel",  # Aceleración del precio (2da derivada)
        "vpt_z",        # Volume Price Trend Z-score
        # ── DIVERGENCIAS (1) ─────────────────────────────────────────────
        "rsi_div",      # Divergencia precio-RSI (+1=alcista, -1=bajista)
        # ── NIVELES ANUALES (2) ──────────────────────────────────────────
        "dist_52h",     # Distancia al máximo 52 semanas (%)
        "dist_52l",     # Distancia al mínimo 52 semanas (%)
        # ── CROSS-SECCIONALES (3) ────────────────────────────────────────
        "beta_spy",     # Beta rolling 20d vs SPY (exposición sistemática)
        "cs_mom_rank",  # Percentil de momentum vs universo completo
        "cs_vol_rank",  # Percentil de volatilidad vs universo completo
    ]  # Total: 62 features

    # ── WEIGHTS BASE (se sobreescriben dinámicamente por IC) ─────────────
    _BASE_WEIGHTS = {"rf": 0.22, "gb": 0.20, "et": 0.18,
                     "mlp": 0.15, "lr": 0.08,
                     "xgb": 0.10, "lgbm": 0.07}

    def __init__(self, n_folds: int = 4, horizon: int = 5):
        self.n_folds  = n_folds
        self.horizon  = horizon
        self.embargo  = max(3, horizon)   # días de embargo post-val
        self.scaler   = RobustScaler()
        self.meta_scaler = StandardScaler()

        # ── Nivel 1: Base Learners ────────────────────────────────────────
        self.l1: Dict = {
            "rf":  RandomForestClassifier(
                       n_estimators=400, max_depth=8,
                       min_samples_leaf=3, max_features="sqrt",
                       class_weight="balanced", random_state=42, n_jobs=-1),
            "gb":  GradientBoostingClassifier(
                       n_estimators=250, max_depth=4,
                       learning_rate=0.04, subsample=0.8,
                       min_samples_leaf=5, random_state=42),
            "et":  ExtraTreesClassifier(
                       n_estimators=400, max_depth=8,
                       min_samples_leaf=3, class_weight="balanced",
                       random_state=42, n_jobs=-1),
            "mlp": MLPClassifier(
                       hidden_layer_sizes=(256, 128, 64),
                       activation="relu", solver="adam",
                       max_iter=500, alpha=0.001,
                       early_stopping=True, n_iter_no_change=20,
                       random_state=42),
            "lr":  LogisticRegression(
                       max_iter=400, C=0.3,
                       class_weight="balanced", random_state=42,
                       solver="saga", n_jobs=-1),
        }
        if HAS_XGB:
            self.l1["xgb"] = XGBClassifier(
                n_estimators=250, max_depth=5, learning_rate=0.04,
                subsample=0.8, colsample_bytree=0.8,
                eval_metric="mlogloss", random_state=42,
                n_jobs=-1, verbosity=0)
        if HAS_LGBM:
            self.l1["lgbm"] = LGBMClassifier(
                n_estimators=250, max_depth=5, learning_rate=0.04,
                subsample=0.8, colsample_bytree=0.8,
                class_weight="balanced", random_state=42,
                n_jobs=-1, verbose=-1)

        # ── Nivel 2: Meta-Learner Ridge ───────────────────────────────────
        self.meta       = Ridge(alpha=1.0)
        # ── Estado ────────────────────────────────────────────────────────
        self.feat_imp:      Optional[np.ndarray] = None
        self.model_ic:      Dict[str, List[float]] = {}  # IC histórico por modelo
        self.dyn_weights:   Dict[str, float] = {}        # pesos dinámicos actuales
        self.oof_preds:     Optional[np.ndarray] = None
        self.trained:       bool = False
        self.walk_results:  List[Dict] = []

    # ── Purged Walk-Forward CV (con embargo) ──────────────────────────────
    def _purged_splits(self, n: int) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        Genera splits de entrenamiento/validación con:
          · Purge: elimina samples de train cuyas etiquetas se solapan
            temporalmente con val (horizon días antes de val_start).
          · Embargo: elimina samples justo después de val_end para evitar
            leakage de microestructura de mercado.

        Referencia: Lopez de Prada (2018) "Advances in Financial ML", cap. 7.
        """
        min_train = max(200, n // (self.n_folds + 2))
        fold_size = max(80, (n - min_train) // self.n_folds)
        splits = []
        for k in range(self.n_folds):
            val_start  = min_train + k * fold_size
            val_end    = min(val_start + fold_size, n - self.embargo)
            if val_end <= val_start + 20:
                continue
            # Purge: train termina horizon días antes del val_start
            train_end  = val_start - self.horizon
            if train_end < min_train // 2:
                continue
            tr_idx  = np.arange(0, train_end)
            val_idx = np.arange(val_start, val_end)
            splits.append((tr_idx, val_idx))
        return splits

    # ── Dynamic IC Weights ────────────────────────────────────────────────
    def _compute_dynamic_weights(self) -> Dict[str, float]:
        """
        Calcula pesos dinámicos por IC reciente (últimos 3 folds).
        Modelos con IC positivo reciben más peso; IC negativo → peso mínimo.
        Esto adapta automáticamente la contribución de cada modelo al régimen.
        """
        if not self.model_ic:
            return {n: self._BASE_WEIGHTS.get(n, 0.1) for n in self.l1}
        ic_recent = {}
        for name in self.l1:
            vals = self.model_ic.get(name, [])
            # Promedio exponencial de los últimos folds
            if vals:
                weights_exp = np.exp(np.linspace(0, 1, len(vals)))
                ic_recent[name] = float(np.average(vals, weights=weights_exp))
            else:
                ic_recent[name] = 0.0
        # Normalizar: max(0.02, ic) para que modelos mediocres aún contribuyan
        ic_pos = {n: max(0.02, v) for n, v in ic_recent.items()}
        total  = sum(ic_pos.values())
        return {n: v / total for n, v in ic_pos.items()}

    # ── Walk-Forward Training ─────────────────────────────────────────────
    def walk_forward_train(self, X_all: np.ndarray, y_all: np.ndarray,
                           verbose: bool = True) -> Dict:
        """
        Purged Walk-Forward Cross-Validation con embargo anti-leakage.
        Calcula IC (Information Coefficient) por modelo en cada fold.
        """
        splits     = self._purged_splits(len(X_all))
        n_classes  = 3
        oof_probs  = np.zeros((len(X_all), n_classes))
        fold_stats = []

        for fold, (tr_idx, val_idx) in enumerate(splits):
            X_tr, X_val = X_all[tr_idx], X_all[val_idx]
            y_tr, y_val = y_all[tr_idx], y_all[val_idx]
            if len(np.unique(y_tr)) < 2:
                continue

            sc   = RobustScaler().fit(X_tr)
            Xtr  = sc.transform(X_tr)
            Xvl  = sc.transform(X_val)

            fold_probs = np.zeros((len(X_val), n_classes))

            for name, clf in self.l1.items():
                clf.fit(Xtr, y_tr)
                proba = clf.predict_proba(Xvl)
                full  = np.zeros((len(X_val), n_classes))
                for j, cls in enumerate(clf.classes_):
                    full[:, int(cls)] = proba[:, j]

                w = self._BASE_WEIGHTS.get(name, 0.1)
                fold_probs += full * w

                # IC por modelo (Spearman entre prob[BUY] y label real)
                y_bin = (y_val == 2).astype(float)
                if y_bin.std() > 0 and full[:, 2].std() > 0:
                    ic, _ = spearmanr(full[:, 2], y_bin)
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
                      f"Train:{len(tr_idx):>4}  "
                      f"Val:{len(val_idx):>4}  "
                      f"Acc:{acc:.3f}  "
                      f"Embargo:{self.embargo}d")

        self.oof_preds  = oof_probs
        # Actualizar pesos dinámicos con IC calculado en este entrenamiento
        self.dyn_weights = self._compute_dynamic_weights()
        avg_ic = {k: np.mean(v) for k, v in self.model_ic.items() if v}
        return {"fold_stats": fold_stats, "avg_ic": avg_ic}

    # ── Entrenamiento final ───────────────────────────────────────────────
    def fit(self, X_all: np.ndarray, y_all: np.ndarray,
            verbose: bool = True) -> Dict:
        """Entrena walk-forward + modelos finales en todos los datos."""
        X_sc   = self.scaler.fit_transform(X_all)
        wf_res = self.walk_forward_train(X_all, y_all, verbose)
        # Entrenar modelos finales con pesos dinámicos ya calculados
        for name, clf in self.l1.items():
            clf.fit(X_sc, y_all)
        # Meta-learner: Ridge sobre OOF
        if self.oof_preds is not None and len(self.oof_preds) > 10:
            y_bin = (y_all == 2).astype(float)
            valid = ~np.isnan(self.oof_preds).any(axis=1)
            if valid.sum() > 5:
                Xm = self.meta_scaler.fit_transform(self.oof_preds[valid])
                self.meta.fit(Xm, y_bin[valid])
        # Feature importance (RF + ET media)
        self.feat_imp = (self.l1["rf"].feature_importances_ * 0.5 +
                         self.l1["et"].feature_importances_ * 0.5)
        self.trained = True
        return wf_res

    # ── Predicción con pesos dinámicos ────────────────────────────────────
    def predict_proba_ensemble(self, X: np.ndarray) -> np.ndarray:
        """Probabilidades ensemble con pesos dinámicos (IC-weighted)."""
        X_sc  = self.scaler.transform(X)
        # Usar pesos dinámicos si disponibles, sino base weights
        weights = self.dyn_weights if self.dyn_weights else \
                  {n: self._BASE_WEIGHTS.get(n, 0.1) for n in self.l1}
        # Normalizar en caso de que no estén exactamente a 1
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
        """Score 0–100 del meta-learner (BUY probability calibrada)."""
        proba = self.predict_proba_ensemble(X)
        try:
            Xm  = self.meta_scaler.transform(proba)
            raw = self.meta.predict(Xm)
        except Exception:
            raw = proba[:, 2]
        return np.clip(raw, 0, 1) * 100

    def signal(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Devuelve (señal, confianza, score_meta)."""
        proba  = self.predict_proba_ensemble(X)
        pred   = np.argmax(proba, axis=1)
        conf   = proba[np.arange(len(pred)), pred] * 100
        score  = self.predict_meta_score(X)
        return pred, conf, score
# ══════════════════════════════════════════════════════════════════════════════
#  BACKTESTING REALISTA
# ══════════════════════════════════════════════════════════════════════════════
COST_RT    = 0.0010  # costo round-trip total (comisión + spread)
SLIPPAGE   = 0.0005  # slippage por ejecución
def backtest_strategy(returns_series: pd.Series,
                      signals: pd.Series,
                      cost_rt: float = COST_RT,
                      slippage: float = SLIPPAGE) -> Dict:
    """
    Backtest realista sobre series de retornos diarios.
    Aplica costos de transacción y slippage en cada trade.
    """
    pos   = 0
    equity= [1.0]
    trade_rets = []
    n_trades = 0
    ret   = returns_series.values
    sig   = signals.values
    for i in range(len(ret)):
        daily_ret = 0.0
        prev_pos  = pos
        # Entrada BUY
        if sig[i] == 2 and pos == 0:
            pos = 1
            cost = (cost_rt / 2 + slippage)
            daily_ret = -cost  # costo de entrada
        # Salida de BUY (señal SELL o HOLD fuerte)
        elif pos == 1 and sig[i] == 0:
            pos = 0
            cost = (cost_rt / 2 + slippage)
            daily_ret = ret[i] - cost
            trade_rets.append(daily_ret)
            n_trades += 1
        # Mantener posición
        elif pos == 1:
            daily_ret = ret[i]
        equity.append(equity[-1] * (1 + daily_ret))
    equity = np.array(equity[1:])
    total_ret   = equity[-1] - 1
    # ── Buy & Hold ────────────────────────────────────────────────────────
    bh = (1 + returns_series).cumprod().values
    bh_ret = bh[-1] - 1
    # ── Métricas ──────────────────────────────────────────────────────────
    daily_strat = np.diff(np.log(equity + 1e-10))
    sharpe   = np.mean(daily_strat) / (np.std(daily_strat) + 1e-10) * np.sqrt(252)
    neg      = daily_strat[daily_strat < 0]
    sortino  = np.mean(daily_strat) / (np.std(neg) + 1e-10) * np.sqrt(252) if len(neg) > 0 else 0
    peaks    = np.maximum.accumulate(equity)
    dd       = (equity - peaks) / (peaks + 1e-10)
    max_dd   = float(np.min(dd))
    calmar   = (total_ret / (abs(max_dd) + 1e-10)) if abs(max_dd) > 0 else 0
    trade_arr = np.array(trade_rets)
    win_rate  = float(np.mean(trade_arr > 0)) * 100 if len(trade_arr) > 0 else 0
    avg_win   = float(np.mean(trade_arr[trade_arr > 0])) * 100 if (trade_arr > 0).any() else 0
    avg_loss  = float(np.mean(trade_arr[trade_arr < 0])) * 100 if (trade_arr < 0).any() else 0
    profit_f  = (abs(avg_win) / (abs(avg_loss) + 1e-10)) if avg_loss < 0 else 0
    return {
        "total_ret":    round(total_ret * 100, 2),
        "bh_ret":       round(bh_ret * 100, 2),
        "alpha":        round((total_ret - bh_ret) * 100, 2),
        "sharpe":       round(sharpe, 3),
        "sortino":      round(sortino, 3),
        "calmar":       round(calmar, 3),
        "max_dd":       round(max_dd * 100, 2),
        "win_rate":     round(win_rate, 1),
        "avg_win_pct":  round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2),
        "profit_factor":round(profit_f, 2),
        "n_trades":     n_trades,
        "equity_curve": equity,
    }
# ══════════════════════════════════════════════════════════════════════════════
#  POSITION SIZING — KELLY CRITERION
# ══════════════════════════════════════════════════════════════════════════════
def kelly_fraction(win_rate: float, avg_win: float,
                   avg_loss: float, cap: float = 0.25) -> float:
    """
    Criterio de Kelly fraccionario para position sizing óptimo.
    cap: máximo fracción del portfolio (evita ruina).
    f* = (p*b - q) / b
    """
    p = max(0, min(1, win_rate / 100))
    q = 1 - p
    b = abs(avg_win / (avg_loss + 1e-10)) if avg_loss != 0 else 1
    f = (p * b - q) / (b + 1e-10)
    f_half = f * 0.5  # Half-Kelly: más conservador
    return round(min(max(f_half, 0.0), cap), 4)
# ══════════════════════════════════════════════════════════════════════════════
#  MONTE CARLO
# ══════════════════════════════════════════════════════════════════════════════
def monte_carlo_sim(trade_rets: np.ndarray, n_sim: int = 1000,
                    n_trades: int = 50) -> Dict:
    """
    Simula n_sim portfolios con bootstrap de retornos históricos.
    Calcula VaR 95%, CVaR 95%, percentiles de equity final.
    """
    if len(trade_rets) < 3:
        return {}
    final_equities = []
    max_dds        = []
    for _ in range(n_sim):
        sample  = np.random.choice(trade_rets, size=n_trades, replace=True)
        equity  = np.cumprod(1 + sample)
        peaks   = np.maximum.accumulate(np.append([1.0], equity))
        dd      = (equity - peaks[1:]) / (peaks[1:] + 1e-10)
        final_equities.append(equity[-1] - 1)
        max_dds.append(float(np.min(dd)))
    fe = np.array(final_equities)
    md = np.array(max_dds)
    return {
        "p10": round(np.percentile(fe, 10) * 100, 2),
        "p25": round(np.percentile(fe, 25) * 100, 2),
        "p50": round(np.percentile(fe, 50) * 100, 2),
        "p75": round(np.percentile(fe, 75) * 100, 2),
        "p90": round(np.percentile(fe, 90) * 100, 2),
        "var95":  round(np.percentile(fe, 5) * 100, 2),
        "cvar95": round(np.mean(fe[fe <= np.percentile(fe, 5)]) * 100, 2),
        "prob_profit": round(np.mean(fe > 0) * 100, 1),
        "avg_max_dd": round(np.mean(md) * 100, 2),
        "worst_max_dd": round(np.min(md) * 100, 2),
    }
# ══════════════════════════════════════════════════════════════════════════════
#  MOTOR PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════
class TradingEngine:
    def __init__(self):
        self.brain      = StackedEnsemble(n_folds=4, horizon=5)
        self.data:      Dict[str, pd.DataFrame] = {}
        self.features:  Dict[str, pd.DataFrame] = {}
        self.signals:   List[Dict] = []
        self.bt_stats:  Dict[str, Dict] = {}
        self.mc_stats:  Dict = {}
        self.wf_stats:  Dict = {}
        self.train_log: List[str] = []
        self.spy_ret:   Optional[pd.Series] = None  # retornos SPY para beta

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.train_log.append(f"[{ts}] {msg}")

    def descargar(self, tickers: List[str], period: str = "2y") -> int:
        """Descarga OHLCV real + SPY como referencia cross-sectional."""
        # Asegurar que SPY esté en el universo para cálculo de beta
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
                            self.data[t] = df
                            ok += 1
                    except Exception:
                        pass
            except Exception as e:
                print(f"  {Y}[WARN] Batch error: {e}{RST}")
        # Guardar retornos de SPY para beta
        if "SPY" in self.data:
            self.spy_ret = self.data["SPY"]["Close"].pct_change().fillna(0)
        self.log(f"Descarga: {ok}/{len(all_tickers)} activos OK")
        return ok

    def calcular_features(self):
        """
        Calcula 62 features por ticker:
          · Paso 1: Features per-ticker (59 técnicos + quant)
          · Paso 2: Features cross-seccionales (beta_spy, cs_mom_rank, cs_vol_rank)
        """
        # ── PASO 1: features per-ticker ───────────────────────────────────
        for ticker, ohlcv in self.data.items():
            try:
                self.features[ticker] = build_feature_matrix(ohlcv)
            except Exception:
                pass

        # ── PASO 2: features cross-seccionales ───────────────────────────
        self._compute_cross_sectional()

    def _compute_cross_sectional(self):
        """
        Calcula features que requieren datos de TODO el universo:

        1. beta_spy: corr(ticker_ret, SPY_ret) * (vol_ticker/vol_spy)
           Mide exposición sistemática. Beta >1.5 = activo agresivo.
           Bajo beta en señal alcista → diversificación sin sacrificar retorno.

        2. cs_mom_rank: percentil de momentum 21d vs universo completo
           Implementa cross-sectional momentum (Jegadeesh & Titman 1993).
           Rank 0.9+ = top 10% en momentum → alta probabilidad de continuación.

        3. cs_vol_rank: percentil de volatilidad vs universo completo
           Bajo vol_rank en señal alcista = "low-vol anomaly" de Frazzini (2014).
        """
        tickers = list(self.features.keys())
        if not tickers:
            return

        # ── Beta vs SPY ───────────────────────────────────────────────────
        if self.spy_ret is not None:
            spy = self.spy_ret
            for ticker in tickers:
                try:
                    feat_df  = self.features[ticker]
                    tk_close = self.data[ticker]["Close"]
                    tk_ret   = tk_close.pct_change().fillna(0)
                    common   = feat_df.index.intersection(spy.index)
                    if len(common) < 30:
                        feat_df["beta_spy"] = 1.0
                        continue
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

        # ── Cross-sectional momentum rank ─────────────────────────────────
        try:
            mom_dict = {t: self.features[t]["mom21"]
                        for t in tickers if "mom21" in self.features[t].columns}
            if mom_dict:
                mom_df   = pd.DataFrame(mom_dict)
                rank_df  = mom_df.rank(axis=1, pct=True)
                for t in tickers:
                    if t in rank_df.columns:
                        series = rank_df[t].reindex(
                            self.features[t].index).fillna(0.5)
                        self.features[t]["cs_mom_rank"] = series.values
                    else:
                        self.features[t]["cs_mom_rank"] = 0.5
        except Exception:
            for t in tickers:
                self.features[t]["cs_mom_rank"] = 0.5

        # ── Cross-sectional volatility rank ───────────────────────────────
        try:
            vol_dict = {t: self.features[t]["rvol"]
                        for t in tickers if "rvol" in self.features[t].columns}
            if vol_dict:
                vol_df   = pd.DataFrame(vol_dict)
                rank_df  = vol_df.rank(axis=1, pct=True)
                for t in tickers:
                    if t in rank_df.columns:
                        series = rank_df[t].reindex(
                            self.features[t].index).fillna(0.5)
                        self.features[t]["cs_vol_rank"] = series.values
                    else:
                        self.features[t]["cs_vol_rank"] = 0.5
        except Exception:
            for t in tickers:
                self.features[t]["cs_vol_rank"] = 0.5

    def entrenar_global(self, verbose: bool = True) -> Dict:
        """
        Entrena el ensemble usando Triple Barrier Labels + Purged Walk-Forward.
        """
        all_X, all_y = [], []
        for ticker, feat_df in self.features.items():
            close = self.data[ticker]["Close"].values
            # ── Triple Barrier Labels (más realistas que threshold fijo) ──
            y = triple_barrier_labels(close, horizon=5,
                                       threshold=0.018, vol_scale=True)
            X = feat_df[self.brain.FEAT_COLS].values
            n = min(len(X), len(y))
            X, y = X[:n], y[:n]
            valid = np.isfinite(X).all(axis=1)
            all_X.append(X[valid]); all_y.append(y[valid])
        if not all_X:
            return {}
        X_all = np.vstack(all_X)
        y_all = np.concatenate(all_y)
        if verbose:
            dist  = {k: int(v) for k, v in zip(*np.unique(y_all, return_counts=True))}
            boost = []
            if HAS_XGB:  boost.append("XGBoost✓")
            if HAS_LGBM: boost.append("LightGBM✓")
            print(f"\n  {C}Matrix global: {X_all.shape[0]:,} muestras × "
                  f"{X_all.shape[1]} features{RST}")
            print(f"  {DIM}Labels Triple Barrier: SELL={dist.get(0,0)} "
                  f"HOLD={dist.get(1,0)} BUY={dist.get(2,0)}{RST}")
            if boost:
                print(f"  {G}Boosters extra: {' · '.join(boost)}{RST}")
        wf = self.brain.fit(X_all, y_all, verbose=verbose)
        self.wf_stats = wf
        return wf
    def generar_senales(self) -> List[Dict]:
        """
        Genera señales para cada ticker usando las últimas N barras.
        Aplica Kelly para position sizing.
        """
        results = []
        for ticker in self.features:
            try:
                feat_df = self.features[ticker]
                close   = self.data[ticker]["Close"].values
                ohlcv   = self.data[ticker]
                high    = ohlcv["High"].values
                low     = ohlcv["Low"].values
                vol     = ohlcv["Volume"].values
                # Usar las últimas 5 barras para señal robusta
                X_last = feat_df[self.brain.FEAT_COLS].values[-5:]
                valid  = np.isfinite(X_last).all(axis=1)
                if not valid.any():
                    continue
                X_last = X_last[valid]
                preds, confs, scores = self.brain.signal(X_last)
                # Consenso de las últimas barras
                final_pred  = np.argmax(np.bincount(preds, minlength=3))
                final_conf  = float(np.mean(confs[preds == final_pred])) if (preds == final_pred).any() else 0
                final_score = float(np.mean(scores))
                consensus   = int(np.sum(preds == final_pred))
                smap = {2: "BUY", 1: "HOLD", 0: "SELL"}
                # ── ATR REAL para SL/TP ────────────────────────────────
                atr14 = IND.atr(high, low, close, 14)[-1]
                precio = float(close[-1])
                sl_pct  = round(-2.0 * atr14 / (precio + 1e-10) * 100, 2)
                tp1_pct = round(+2.0 * atr14 / (precio + 1e-10) * 100, 2)
                tp2_pct = round(+3.5 * atr14 / (precio + 1e-10) * 100, 2)
                rr      = round(abs(tp1_pct / (sl_pct + 1e-10)), 2)
                # ── Features de la última barra ────────────────────────
                last = feat_df.iloc[-1]
                # ── Kelly sizing ───────────────────────────────────────
                bt = self.bt_stats.get(ticker, {})
                kelly = kelly_fraction(
                    win_rate = bt.get("win_rate", 55),
                    avg_win  = bt.get("avg_win_pct", 2.0),
                    avg_loss = bt.get("avg_loss_pct", -1.5),
                )
                results.append({
                    "ticker":   ticker,
                    "sector":   ACTIVOS.get(ticker, "N/A"),
                    "precio":   round(precio, 4),
                    "cambio_d": round(float(pd.Series(close).pct_change(1).iloc[-1]) * 100, 2),
                    "señal":    smap[final_pred],
                    "confianza": round(final_conf, 1),
                    "score":    round(final_score, 1),
                    "consenso": f"{consensus}/5",
                    # R/R
                    "sl_pct":   sl_pct, "tp1_pct": tp1_pct,
                    "tp2_pct":  tp2_pct, "rr":      rr,
                    "kelly_pct": round(kelly * 100, 1),
                    # Técnicos clave
                    "rsi14":    round(last.rsi14, 1),
                    "rsi7":     round(last.rsi7, 1),
                    "stoch_k":  round(last.stoch_k, 1),
                    "stoch_d":  round(last.stoch_d, 1),
                    "adx":      round(last.adx, 1),
                    "williams_r": round(last.williams_r, 1),
                    "cci":      round(last.cci, 1),
                    "bb_pct":   round(last.bb_pct, 3),
                    "cmf":      round(last.cmf, 3),
                    "obv_z":    round(last.obv_zscore, 2),
                    "vwap_dev": round(last.vwap_dev, 2),
                    "vol_rel":  round(last.vol_rel, 2),
                    "mom_score":round(last.mom_score, 1),
                    "mom10":    round(last.mom10, 2),
                    "zscore20": round(last.zscore20, 2),
                    "dist_50":  round(last.dist_50, 2),
                    "dist_200": round(last.dist_200, 2),
                    "rvol":     round(last.rvol, 1),
                    "atr_rel":  round(last.atr_rel, 2),
                    "regime":   int(last.regime),
                    "ichi_above": int(last.ichi_above),
                    "ema_cross":  int(last.ema_cross),
                    # ── FEATURES CUANTITATIVAS v20 ─────────────────────────
                    "hurst":       round(float(getattr(last, "hurst", 0.5)), 3),
                    "mer":         round(float(getattr(last, "mer", 0.5)), 3),
                    "vov":         round(float(getattr(last, "vov", 0)), 3),
                    "amihud":      round(float(getattr(last, "amihud", 0)), 3),
                    "gk_vol":      round(float(getattr(last, "gk_vol", 0)), 1),
                    "real_skew":   round(float(getattr(last, "real_skew", 0)), 3),
                    "real_kurt":   round(float(getattr(last, "real_kurt", 0)), 3),
                    "price_accel": round(float(getattr(last, "price_accel", 0)), 3),
                    "vpt_z":       round(float(getattr(last, "vpt_z", 0)), 2),
                    "rsi_div":     int(getattr(last, "rsi_div", 0)),
                    "dist_52h":    round(float(getattr(last, "dist_52h", 0)), 2),
                    "dist_52l":    round(float(getattr(last, "dist_52l", 0)), 2),
                    "beta_spy":    round(float(getattr(last, "beta_spy", 1.0)), 2),
                    "cs_mom_rank": round(float(getattr(last, "cs_mom_rank", 0.5)), 3),
                    "cs_vol_rank": round(float(getattr(last, "cs_vol_rank", 0.5)), 3),
                    # Backtest
                    "bt_sharpe": round(bt.get("sharpe", 0), 2),
                    "bt_wr":     round(bt.get("win_rate", 0), 1),
                    "bt_alpha":  round(bt.get("alpha", 0), 2),
                    "bt_dd":     round(bt.get("max_dd", 0), 2),
                })
            except Exception as e:
                pass
        # Ordenar por score desc, luego por confianza
        self.signals = sorted(results, key=lambda x: (x["score"], x["confianza"]), reverse=True)
        return self.signals
    def backtest_all(self, lookback_pct: float = 0.30) -> Dict:
        """
        Backtest OOS (out-of-sample) para cada ticker.
        Usa el 30% final de los datos como período de test.
        """
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
                # Entrenador local para no contaminar el global
                local_rf = RandomForestClassifier(n_estimators=60, max_depth=5,
                                                   random_state=42, n_jobs=-1)
                sc_local = RobustScaler().fit(X_tr[valid_tr])
                local_rf.fit(sc_local.transform(X_tr[valid_tr]), y_tr[valid_tr])
                # Predecir en test
                X_te = feat_df[self.brain.FEAT_COLS].values[n_train:]
                valid_te = np.isfinite(X_te).all(axis=1)
                X_te_sc  = sc_local.transform(X_te)
                preds_te = np.ones(len(X_te), dtype=int)
                preds_te[valid_te] = local_rf.predict(X_te_sc[valid_te])
                # Retornos diarios del período test
                close_te = close[n_train:]
                rets_te  = pd.Series(np.diff(np.log(close_te + 1e-10)))
                sigs_te  = pd.Series(preds_te[1:])  # shift de 1 día (ejecución al día siguiente)
                if len(rets_te) < 20:
                    continue
                bt = backtest_strategy(rets_te, sigs_te)
                self.bt_stats[ticker] = bt
                all_trade_rets.append(bt.get("total_ret", 0) / 100)
            except Exception as e:
                pass
        # Monte Carlo global
        if all_trade_rets:
            self.mc_stats = monte_carlo_sim(np.array(all_trade_rets), n_sim=1000,
                                             n_trades=min(50, len(all_trade_rets)))
        return self.bt_stats
    def portfolio_kelly(self, capital: float = 100_000,
                         max_pos: int = 10) -> List[Dict]:
        """
        Construye portfolio con Kelly sizing para cada posición.
        """
        buys = [s for s in self.signals if s["señal"] == "BUY"
                and s["confianza"] >= 55][:max_pos]
        if not buys:
            return []
        total_kelly = sum(s["kelly_pct"] / 100 for s in buys) + 1e-10
        scale = min(1.0, 0.90 / total_kelly)  # 90% max inversión total
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
#  DISPLAY (terminal ANSI — no requiere rich)
# ══════════════════════════════════════════════════════════════════════════════
def sep(char="─", n=100, col=DIM): print(cc(char * n, col))
def barra(v, mx=100, ancho=20, col=G):
    f = max(0, min(ancho, int(v / mx * ancho)))
    return f"{col}{'█'*f}{DIM}{'░'*(ancho-f)}{RST}"
def header():
    clr(); print()
    print(cc("╔" + "═"*98 + "╗", C))
    print(cc("║", C) + cc("  🧠⚡ ML TRADING BRAIN v9.0 — QUANT PROFESSIONAL EDITION (v20)".ljust(98), W) + cc("║", C))
    print(cc("║", C) + cc("  Purged Walk-Forward · Triple Barrier · 62 Features · XGB/LGBM · IC Weights".ljust(98), Y) + cc("║", C))
    print(cc("╚" + "═"*98 + "╝", C)); print()
def mostrar_top_buys(signals: List[Dict], engine: TradingEngine, n: int = 20):
    header()
    print(cc(f"  🎯  TOP {n} OPORTUNIDADES BUY — STACKING ENSEMBLE v7.0\n", C))
    sep("═", col=C)
    buys = [s for s in signals if s["señal"] == "BUY"][:n]
    if not buys:
        print(cc("  Sin señales BUY activas.", DIM)); return
    for i, s in enumerate(buys, 1):
        r_col = G if s["cambio_d"] >= 0 else R
        sc_c  = G if s["score"] >= 75 else Y if s["score"] >= 55 else R
        rr_c  = G if s["rr"] >= 2 else Y
        adx_c = C if s["adx"] > 30 else DIM
        rsi_c = G if s["rsi14"] < 35 else R if s["rsi14"] > 70 else W
        z_c   = G if s["zscore20"] < -1 else R if s["zscore20"] > 1 else DIM
        bb_c  = G if s["bb_pct"] < 0.2 else R if s["bb_pct"] > 0.8 else DIM
        cmf_c = G if s["cmf"] > 0.1 else R if s["cmf"] < -0.1 else DIM
        reg   = {1: f"{G}BULL{RST}", -1: f"{R}BEAR{RST}", 0: f"{Y}SIDEWAYS{RST}"}.get(s["regime"], DIM+"?"+RST)
        ichi  = f"{G}✓ CLOUD{RST}" if s["ichi_above"] else f"{R}✗ CLOUD{RST}"
        ema   = f"{G}EMA↑{RST}" if s["ema_cross"] else f"{R}EMA↓{RST}"
        print()
        c_d = f'+{s["cambio_d"]:.2f}%' if s["cambio_d"] >= 0 else f'{s["cambio_d"]:.2f}%'
        print(f"  {cc(f'#{i:02d}', DIM)}  {cc(s['ticker'].ljust(7), BOLD+W)}"
              f"  {cc(s['sector'][:25].ljust(25), DIM)}"
              f"  ${s['precio']:>10,.2f}"
              f"  {cc(c_d.ljust(9), r_col)}"
              f"  Régimen:{reg}  {ichi}  {ema}")
        score_str    = f"{s['score']:.0f}/100"
        conf_str     = f"{s['confianza']:.0f}%"
        kelly_str    = f"{s['kelly_pct']:.1f}%"
        print(f"       {barra(s['score'], col=(G if s['score']>=70 else Y))}  "
              f"{cc(score_str, sc_c)}  "
              f"Conf:{cc(conf_str, Y)}  "
              f"Consenso:{cc(s['consenso'], G)}  "
              f"Kelly:{cc(kelly_str, M)}")
        rsi_s   = f"{s['rsi14']:.1f}"
        stch_s  = f"{s['stoch_k']:.0f}/{s['stoch_d']:.0f}"
        willr_s = f"{s['williams_r']:.0f}"
        cci_s   = f"{s['cci']:.0f}"
        adx_s2  = f"{s['adx']:.1f}"
        bb_s    = f"{s['bb_pct']:.2f}"
        z_s     = f"{s['zscore20']:+.2f}"
        cmf_s   = f"{s['cmf']:+.3f}"
        obv_s   = f"{s['obv_z']:+.2f}"
        willr_c = G if s['williams_r'] < -80 else DIM
        cci_c2  = G if s['cci'] < -100 else DIM
        obv_c   = G if s['obv_z'] > 0.5 else DIM
        print("       " +
              cc('RSI14:', DIM) + cc(rsi_s, rsi_c) + "  " +
              cc('Stoch:', DIM) + cc(stch_s, DIM) + "  " +
              cc('WillR:', DIM) + cc(willr_s, willr_c) + "  " +
              cc('CCI:', DIM)   + cc(cci_s, cci_c2) + "  " +
              cc('ADX:', DIM)   + cc(adx_s2, adx_c) + "  " +
              cc('BB:', DIM)    + cc(bb_s, bb_c) + "  " +
              cc('Z:', DIM)     + cc(z_s, z_c) + "  " +
              cc('CMF:', DIM)   + cc(cmf_s, cmf_c) + "  " +
              cc('OBV-Z:', DIM) + cc(obv_s, obv_c))
        sl_s    = f"{s['sl_pct']:.2f}%"
        tp1_s   = f"{s['tp1_pct']:+.2f}%"
        tp2_s   = f"{s['tp2_pct']:+.2f}%"
        rr_s2   = f"{s['rr']:.2f}x"
        volr_s  = f"{s['vol_rel']:.1f}x"
        bts_s   = f"{s['bt_sharpe']:.2f}"
        btwr_s  = f"{s['bt_wr']:.0f}%"
        alpha_s = f"{s['bt_alpha']:+.1f}%"
        vol_c2  = M if s['vol_rel'] > 2 else DIM
        bts_c   = G if s['bt_sharpe'] > 1 else DIM
        btwr_c  = G if s['bt_wr'] > 55 else DIM
        alpha_c = G if s['bt_alpha'] > 0 else R
        print("       " +
              cc('SL:', DIM)         + cc(sl_s, R) + "  " +
              cc('TP1:', DIM)        + cc(tp1_s, G) + "  " +
              cc('TP2:', DIM)        + cc(tp2_s, G) + "  " +
              cc('R/R:', DIM)        + cc(rr_s2, rr_c) + "  " +
              cc('VolR:', DIM)       + cc(volr_s, vol_c2) + "  " +
              cc('BT-Sharpe:', DIM)  + cc(bts_s, bts_c) + "  " +
              cc('BT-WR:', DIM)      + cc(btwr_s, btwr_c) + "  " +
              cc('Alpha:', DIM)      + cc(alpha_s, alpha_c))
        # ── LÍNEA 4: FEATURES CUANTITATIVAS v20 ──────────────────────────
        h_v   = s.get("hurst", 0.5)
        h_c   = G if h_v > 0.55 else (M if h_v < 0.45 else DIM)
        h_lbl = "TREND" if h_v > 0.55 else ("MR" if h_v < 0.45 else "RW")
        mer_v = s.get("mer", 0.5)
        mer_c = G if mer_v > 0.6 else Y if mer_v > 0.35 else DIM
        sk_v  = s.get("real_skew", 0)
        sk_c  = G if sk_v > 0.3 else R if sk_v < -0.5 else DIM
        ac_v  = s.get("price_accel", 0)
        ac_c  = G if ac_v > 0 else R if ac_v < -0.5 else DIM
        rd_v  = s.get("rsi_div", 0)
        rd_s  = "↑DIV" if rd_v > 0 else ("↓DIV" if rd_v < 0 else "—")
        rd_c  = G if rd_v > 0 else (R if rd_v < 0 else DIM)
        d52h  = s.get("dist_52h", 0)
        d52h_c= G if d52h > -5 else Y if d52h > -15 else DIM
        beta  = s.get("beta_spy", 1.0)
        beta_c= M if beta > 1.5 else Y if beta > 1.1 else (G if beta < 0.8 else DIM)
        csm   = s.get("cs_mom_rank", 0.5)
        csm_c = G if csm > 0.75 else R if csm < 0.25 else DIM
        csv   = s.get("cs_vol_rank", 0.5)
        gk_v  = s.get("gk_vol", 0)
        print("       " +
              cc("Hurst:", DIM)    + cc(f"{h_v:.2f}({h_lbl})", h_c) + "  " +
              cc("MER:", DIM)      + cc(f"{mer_v:.2f}", mer_c)       + "  " +
              cc("Skew:", DIM)     + cc(f"{sk_v:+.2f}", sk_c)        + "  " +
              cc("Accel:", DIM)    + cc(f"{ac_v:+.3f}", ac_c)         + "  " +
              cc("RSI-Div:", DIM)  + cc(rd_s, rd_c)                  + "  " +
              cc("52W-H:", DIM)    + cc(f"{d52h:+.1f}%", d52h_c)     + "  " +
              cc("β:", DIM)        + cc(f"{beta:.2f}", beta_c)        + "  " +
              cc("CS-Mom:", DIM)   + cc(f"{csm:.2f}", csm_c)          + "  " +
              cc("GK-Vol:", DIM)   + cc(f"{gk_v:.1f}%", DIM))
        sep(col=DIM)
def mostrar_backtest(engine: TradingEngine):
    header()
    print(cc("  📊  BACKTEST OOS (Out-of-Sample) — 30% Período de Test\n", G))
    sep("═", col=G)
    stats = [(t, v) for t, v in engine.bt_stats.items() if v.get("n_trades", 0) > 0]
    stats_sorted = sorted(stats, key=lambda x: x[1].get("sharpe", -99), reverse=True)
    print(f"\n  {cc('TOP 20 — Sharpe Ratio más alto:', W)}\n")
    print(f"  {'Ticker':<8} {'Total%':>7} {'B&H%':>7} {'Alpha%':>7} "
          f"{'Sharpe':>7} {'Sortino':>7} {'Calmar':>7} "
          f"{'MaxDD%':>7} {'WinRate':>7} {'ProfFact':>8} {'Trades':>6}")
    sep(col=DIM)
    for ticker, v in stats_sorted[:20]:
        tc    = G if v["total_ret"] > 0 else R
        ac    = G if v["alpha"] > 0 else R
        sc    = G if v["sharpe"] > 1 else Y if v["sharpe"] > 0 else R
        wc    = G if v["win_rate"] > 55 else Y
        tr_s  = f"{v['total_ret']:+.1f}%"
        bh_s  = f"{v['bh_ret']:+.1f}%"
        al_s  = f"{v['alpha']:+.1f}%"
        sh_s  = f"{v['sharpe']:+.3f}"
        so_s  = f"{v['sortino']:+.3f}"
        ca_s  = f"{v['calmar']:+.3f}"
        dd_s  = f"{v['max_dd']:+.1f}%"
        wr_s  = f"{v['win_rate']:.1f}%"
        pf_s  = f"{v['profit_factor']:.2f}"
        pf_c  = G if v['profit_factor'] > 1.2 else DIM
        print(f"  {cc(ticker.ljust(8), W)}"
              f"  {cc(tr_s, tc):>14}"
              f"  {cc(bh_s, DIM):>14}"
              f"  {cc(al_s, ac):>14}"
              f"  {cc(sh_s, sc):>14}"
              f"  {cc(so_s, sc):>14}"
              f"  {cc(ca_s, sc):>14}"
              f"  {cc(dd_s, R):>14}"
              f"  {cc(wr_s, wc):>14}"
              f"  {cc(pf_s, pf_c):>14}"
              f"  {cc(str(v['n_trades']), DIM):>8}")
    print()
    sep(col=G)
    all_sharpes = [v["sharpe"] for _, v in stats if "sharpe" in v]
    all_wrs     = [v["win_rate"] for _, v in stats if "win_rate" in v]
    all_alphas  = [v["alpha"] for _, v in stats if "alpha" in v]
    all_dds     = [v["max_dd"] for _, v in stats if "max_dd" in v]
    if all_sharpes:
        print(f"\n  {cc('ESTADÍSTICAS GLOBALES DEL BACKTEST:', Y)}")
        print(f"  Sharpe promedio:   {cc(f'{np.mean(all_sharpes):.3f}', G if np.mean(all_sharpes)>0.5 else Y)}")
        print(f"  Win Rate promedio: {cc(f'{np.mean(all_wrs):.1f}%', G if np.mean(all_wrs)>55 else Y)}")
        print(f"  Alpha promedio:    {cc(f'{np.mean(all_alphas):+.2f}%', G if np.mean(all_alphas)>0 else R)}")
        print(f"  Max DD promedio:   {cc(f'{np.mean(all_dds):.2f}%', R)}")
        print(f"  % estrategias Alpha>0: {cc(f'{sum(a>0 for a in all_alphas)/len(all_alphas)*100:.1f}%', G)}")
    print()
def mostrar_monte_carlo(engine: TradingEngine):
    header()
    print(cc("  🎲  MONTE CARLO — 1000 Simulaciones Bootstrap\n", M))
    sep("═", col=M)
    mc = engine.mc_stats
    if not mc:
        print(cc("  Sin datos suficientes para Monte Carlo.", DIM)); return
    p10_s  = f"{mc['p10']:+.2f}%";  p25_s  = f"{mc['p25']:+.2f}%"
    p50_s  = f"{mc['p50']:+.2f}%";  p75_s  = f"{mc['p75']:+.2f}%"
    p90_s  = f"{mc['p90']:+.2f}%";  var_s  = f"{mc['var95']:+.2f}%"
    cvar_s = f"{mc['cvar95']:+.2f}%"; pp_s  = f"{mc['prob_profit']:.1f}%"
    amd_s  = f"{mc['avg_max_dd']:.2f}%"; wmd_s = f"{mc['worst_max_dd']:.2f}%"
    print(f"\n  {cc('Distribución de Retornos (N=50 trades):', W)}\n")
    print(f"  P10  (peor 10%):     {cc(p10_s, R)}")
    print(f"  P25:                 {cc(p25_s, Y)}")
    print(f"  P50  (mediana):      {cc(p50_s, W)}")
    print(f"  P75:                 {cc(p75_s, G)}")
    print(f"  P90  (mejor 10%):    {cc(p90_s, G)}")
    print()
    print(f"  VaR 95%  (pérd. máx.): {cc(var_s, R)}")
    print(f"  CVaR 95% (expected shortfall): {cc(cvar_s, R)}")
    print(f"  Prob. de ganancia:   {cc(pp_s, G)}")
    print(f"  Max Drawdown prom:   {cc(amd_s, R)}")
    print(f"  Max Drawdown worst:  {cc(wmd_s, R)}")
    # Visualización ASCII de la distribución
    print(f"\n  {cc('Distribución de resultados (ASCII histogram):', DIM)}")
    buckets = list(range(-30, 35, 5))
    for b in buckets:
        bar_w = max(0, min(40, int((mc["p50"] - b + 15) / 0.8)))  # rough
        col_b = G if b > 0 else R if b < -5 else Y
        print(f"  {cc(f'{b:+4d}%', col_b)}  {'█'*bar_w}")
    print()
def mostrar_walk_forward(engine: TradingEngine):
    header()
    print(cc("  🔁  WALK-FORWARD VALIDATION — Anti-Lookahead Bias\n", Y))
    sep("═", col=Y)
    wf = engine.wf_stats
    if not wf:
        print(cc("  Sin resultados de walk-forward.", DIM)); return
    print(f"\n  {cc('Resultados por Fold (TimeSeriesSplit):', W)}\n")
    print(f"  {'Fold':<6} {'N_Train':>8} {'N_Val':>8} {'Accuracy':>10}")
    sep(col=DIM)
    for f in wf.get("fold_stats", []):
        ac = G if f["accuracy"] > 0.5 else R
        print(f"  {cc(str(f['fold']).ljust(6), DIM)}"
              f"  {cc(str(f['n_train']).rjust(8), DIM)}"
              f"  {cc(str(f['n_val']).rjust(8), DIM)}"
              f"  {cc(str(round(f['accuracy']*100,1))+'%', ac)}")
    print(f"\n  {cc('Information Coefficient (IC) por modelo:', C)}")
    print(f"  {cc('IC > 0.05 = buena señal · IC > 0.10 = excelente', DIM)}\n")
    for m, ic in wf.get("avg_ic", {}).items():
        bar = "█" * int(max(0, ic) * 200)
        col_ic = G if ic > 0.05 else Y if ic > 0 else R
        print(f"  {cc(m.upper().ljust(4), W)}  {cc(bar, col_ic)}  {cc(f'{ic:.4f}', col_ic)}")
    print()
def mostrar_portfolio(engine: TradingEngine, capital: float = 100_000):
    header()
    print(cc(f"  💼  PORTFOLIO BUILDER — Kelly Criterion · Capital ${capital:,.0f}\n", G))
    sep("═", col=G)
    port = engine.portfolio_kelly(capital=capital, max_pos=10)
    if not port:
        print(cc("  Sin posiciones BUY con suficiente confianza.", DIM)); return
    total_usd  = sum(p["monto_usd"] for p in port)
    total_risk = sum(p["riesgo_usd"] for p in port)
    total_pot  = sum(p["potencial_usd"] for p in port)
    cash       = capital - total_usd
    print(f"\n  {cc('Capital:', DIM)} ${capital:>10,.2f}  "
          f"│  {cc('Invertido:', DIM)} {cc(f'${total_usd:>10,.2f}', W)}  "
          f"│  {cc('Cash:', DIM)} {cc(f'${cash:>10,.2f}', G)}  "
          f"│  {cc('Posiciones:', DIM)} {cc(str(len(port)), Y)}")
    print(f"  {cc('Riesgo total:', DIM)} {cc(f'${total_risk:>8,.2f}', R)}  "
          f"│  {cc('Potencial (TP2):', DIM)} {cc(f'${total_pot:>8,.2f}', G)}  "
          f"│  {cc('R/R global:', DIM)} {cc(f'{total_pot/(total_risk+1e-10):.2f}x', G)}")
    print()
    print(f"  {'#':<3} {'Ticker':<8} {'Sector':<20} {'Precio':>9} "
          f"{'Kelly%':>7} {'Monto$':>10} "
          f"{'Acciones':>9} {'SL$':>10} {'TP1$':>10} {'TP2$':>10} "
          f"{'Riesgo$':>9} {'Pot$':>9} {'Sharpe':>7}")
    sep(col=DIM)
    for i, p in enumerate(port, 1):
        sc_c = G if p["score"] >= 70 else Y
        rr_c = G if p["rr"] >= 2 else Y
        shc  = G if p["bt_sharpe"] > 0.8 else DIM
        kelly_s  = f"{p['kelly_adj_pct']:.1f}%"
        monto_s  = f"${p['monto_usd']:>8,.0f}"
        sl_p_s   = f"${p['sl_precio']:>8,.2f}"
        tp1_p_s  = f"${p['tp1_precio']:>8,.2f}"
        tp2_p_s  = f"${p['tp2_precio']:>8,.2f}"
        risk_s   = f"${p['riesgo_usd']:>7,.0f}"
        pot_s    = f"${p['potencial_usd']:>7,.0f}"
        bts2_s   = f"{p['bt_sharpe']:.2f}"
        print(f"  {cc(str(i).ljust(3), DIM)}"
              f"{cc(p['ticker'].ljust(8), BOLD+W)}"
              f"{cc(p['sector'][:20].ljust(20), DIM)}"
              f"  ${p['precio']:>8,.2f}"
              f"  {cc(kelly_s, M):>13}"
              f"  {cc(monto_s, W):>16}"
              f"  {cc(str(p['shares']).rjust(9), DIM):>14}"
              f"  {cc(sl_p_s, R):>16}"
              f"  {cc(tp1_p_s, G):>16}"
              f"  {cc(tp2_p_s, G):>16}"
              f"  {cc(risk_s, R):>14}"
              f"  {cc(pot_s, G):>14}"
              f"  {cc(bts2_s, shc):>13}")
    sep(col=DIM)
    print(cc("\n  ⚠️  Kelly sizing es el máximo recomendado. Comenzar con 50% del monto sugerido.\n", R))
def mostrar_feature_importance(engine: TradingEngine):
    header()
    print(cc("  📊  FEATURE IMPORTANCE — RF + ExtraTrees (media ponderada)\n", C))
    sep("═", col=C)
    if engine.brain.feat_imp is None:
        print(cc("  No disponible.", DIM)); return
    imp = engine.brain.feat_imp
    idx = np.argsort(imp)[::-1]
    print(f"  {'Feature'.ljust(18)} {'Importancia':>12} {'Barra'}")
    sep(col=DIM)
    for i in idx[:25]:
        name = engine.brain.FEAT_COLS[i]
        val  = imp[i]
        bar  = "█" * int(val * 400)
        col_f= G if val > 0.05 else Y if val > 0.02 else DIM
        print(f"  {cc(name.ljust(18), W)}  {cc(f'{val*100:.2f}%'.rjust(10), col_f)}  {cc(bar, col_f)}")
    print()
def exportar_csv(signals: List[Dict], bt_stats: Dict):
    fname = f"brain_v7_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    cols  = ["ticker","sector","precio","cambio_d","señal","confianza","score","consenso",
             "kelly_pct","sl_pct","tp1_pct","tp2_pct","rr",
             "rsi14","rsi7","stoch_k","stoch_d","adx","williams_r","cci",
             "bb_pct","cmf","obv_z","vwap_dev","vol_rel","mom_score","mom10",
             "zscore20","dist_50","dist_200","rvol","atr_rel","regime",
             "ichi_above","ema_cross","bt_sharpe","bt_wr","bt_alpha","bt_dd"]
    try:
        with open(fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for s in signals:
                w.writerow({k: s.get(k, "") for k in cols})
        print(cc(f"\n  ✓  Exportado: {fname}  ({len(signals)} filas)\n", G))
    except Exception as e:
        print(cc(f"\n  Error: {e}\n", R))
# ══════════════════════════════════════════════════════════════════════════════
#  MENÚ PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════
def menu(engine: TradingEngine):
    while True:
        header()
        buys_n = sum(1 for s in engine.signals if s["señal"] == "BUY")
        sells_n= sum(1 for s in engine.signals if s["señal"] == "SELL")
        ts     = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        print(cc(f"  Activos: {cc(str(len(engine.signals)), W)}  "
                 f"BUY: {cc(str(buys_n), G)}  "
                 f"SELL: {cc(str(sells_n), R)}  "
                 f"Tickers backtesteados: {cc(str(len(engine.bt_stats)), C)}  "
                 f"Actualizado: {cc(ts, DIM)}\n", DIM))
        sep(col=DIM)
        print(cc("  MENÚ PRINCIPAL\n", W))
        opts = {
            "1": "🎯  Top 20 BUY — Stacking Ensemble + 62 Features Quant Pro",
            "2": "📊  Backtest OOS — Sharpe / Sortino / Calmar / Alpha",
            "3": "🔁  Walk-Forward Validation — IC por modelo",
            "4": "🎲  Monte Carlo — VaR / CVaR / distribución de retornos",
            "5": "💼  Portfolio Kelly — Sizing óptimo con R/R",
            "6": "📈  Feature Importance — RF + ExtraTrees",
            "7": f"🔍  Analizar ticker específico",
            "E": "📥  Exportar CSV completo",
            "0": "🚪  Salir",
        }
        for k, v in opts.items():
            col = R if k == "0" else C
            print(f"    {cc(f'[{k}]', col)}  {v}")
        print()
        ch = input(cc("  → Opción: ", Y)).strip().upper()
        if ch == "0":
            print(cc("\n  Apagando el cerebro. ¡Buenas operaciones!\n", G)); break
        elif ch == "1":
            clr(); mostrar_top_buys(engine.signals, engine); press()
        elif ch == "2":
            clr(); mostrar_backtest(engine); press()
        elif ch == "3":
            clr(); mostrar_walk_forward(engine); press()
        elif ch == "4":
            clr(); mostrar_monte_carlo(engine); press()
        elif ch == "5":
            clr()
            try:
                cap_s = input(cc("  Capital en USD (default 100000): ", Y)).strip()
                cap   = float(cap_s.replace(",","").replace(".","")) if cap_s else 100_000
            except:
                cap = 100_000
            mostrar_portfolio(engine, capital=cap); press()
        elif ch == "6":
            clr(); mostrar_feature_importance(engine); press()
        elif ch == "7":
            clr()
            t = input(cc("  Ticker a analizar: ", Y)).strip().upper()
            match = [s for s in engine.signals if s["ticker"] == t]
            if match:
                mostrar_top_buys(match, engine, n=1)
                bt = engine.bt_stats.get(t, {})
                if bt:
                    print(cc(f"\n  Backtest OOS para {t}:", W))
                    for k, v in bt.items():
                        if k != "equity_curve":
                            col_v = G if isinstance(v, float) and v > 0 else (R if isinstance(v, float) and v < 0 else DIM)
                            print(f"    {cc(k.ljust(16), DIM)}  {cc(str(v), col_v)}")
            else:
                print(cc(f"  '{t}' no encontrado.", R))
            press()
        elif ch == "E":
            clr(); exportar_csv(engine.signals, engine.bt_stats); press()
# ══════════════════════════════════════════════════════════════════════════════
#  BOOT
# ══════════════════════════════════════════════════════════════════════════════
def main():
    clr(); print()
    print(cc("  🧠⚡ ML TRADING BRAIN v9.0 — QUANT PROFESSIONAL EDITION", BOLD+C))
    boost_str = []
    if HAS_XGB:  boost_str.append("XGBoost")
    if HAS_LGBM: boost_str.append("LightGBM")
    b_info = " · ".join(boost_str) if boost_str else "sklearn only (pip install xgboost lightgbm)"
    print(cc(f"  Boosters: {b_info}\n", DIM))
    engine  = TradingEngine()
    tickers = list(ACTIVOS.keys())
    # ── PASO 1: Descarga ──────────────────────────────────────────────────
    print(cc(f"\n  PASO 1/5 — Descarga OHLCV real (2 años · {len(tickers)} tickers + SPY ref)", Y))
    n_ok = engine.descargar(tickers, period="2y")
    print(cc(f"  ✓  {n_ok} activos con datos suficientes (≥252 días)", G))
    if n_ok < 5:
        print(cc("  ✗  No hay suficiente data. Verifica tu conexión.", R)); sys.exit(1)
    # ── PASO 2: Features ──────────────────────────────────────────────────
    print(cc("\n  PASO 2/5 — Calculando 62 features cuantitativas...", Y))
    print(cc("  [Hurst · Amihud · GK-Vol · Skew/Kurt · MER · VoV · "
             "RSI-Div · 52W · Beta · CS-Rank]", DIM))
    engine.calcular_features()
    print(cc(f"  ✓  Features calculadas: {len(engine.features)} tickers · "
             f"62 features (59 quant + 3 cross-sectional)", G))
    # ── PASO 3: Entrenamiento ─────────────────────────────────────────────
    print(cc("\n  PASO 3/5 — Entrenamiento Stacking (Purged Walk-Forward + Embargo)...", Y))
    n_models = len(engine.brain.l1)
    print(cc(f"  [{n_models} modelos · Triple Barrier Labels · Dynamic IC Weights]\n", DIM))
    wf_res = engine.entrenar_global(verbose=True)
    avg_accs = [f["accuracy"] for f in wf_res.get("fold_stats", [])]
    if avg_accs:
        print(cc(f"\n  ✓  Purged Walk-Forward — Accuracy media: {np.mean(avg_accs)*100:.1f}%", G))
    # Mostrar pesos dinámicos por IC
    dw = engine.brain.dyn_weights
    if dw:
        dw_str = "  ".join([f"{k.upper()}:{v:.2f}" for k, v in sorted(dw.items(), key=lambda x: -x[1])])
        print(cc(f"  Pesos dinámicos (IC): {dw_str}", DIM))
    ics = wf_res.get("avg_ic", {})
    for m, ic in sorted(ics.items(), key=lambda x: -x[1]):
        ic_col = G if ic > 0.05 else Y if ic > 0 else R
        print(f"    IC {m.upper():<6}: {cc(f'{ic:.4f}', ic_col)}")
    # ── PASO 4: Backtest ──────────────────────────────────────────────────
    print(cc("\n  PASO 4/5 — Backtest OOS (30% datos) + Monte Carlo (1000 sim)...", Y))
    engine.backtest_all(lookback_pct=0.30)
    valid_bt = len([v for v in engine.bt_stats.values() if v.get("n_trades", 0) > 0])
    sharpes  = [v["sharpe"] for v in engine.bt_stats.values() if "sharpe" in v]
    alphas   = [v["alpha"] for v in engine.bt_stats.values() if "alpha" in v]
    print(cc(f"  ✓  {valid_bt} estrategias backtestadas", G))
    if sharpes:
        sc = G if np.mean(sharpes) > 0.5 else Y
        print(f"    Sharpe promedio: {cc(f'{np.mean(sharpes):.3f}', sc)}")
    if alphas:
        ac = G if np.mean(alphas) > 0 else R
        print(f"    Alpha promedio:  {cc(f'{np.mean(alphas):+.2f}%', ac)}")
    if engine.mc_stats:
        mc_p50_s = f"{engine.mc_stats['p50']:+.2f}%"
        mc_pp_s  = f"{engine.mc_stats['prob_profit']:.1f}%"
        print(f"    Monte Carlo P50: {cc(mc_p50_s, W)}  "
              f"Prob. ganancia: {cc(mc_pp_s, G)}")
    # ── PASO 5: Señales ───────────────────────────────────────────────────
    print(cc("\n  PASO 5/5 — Generando señales (consenso 5 barras · IC-weighted)...", Y))
    signals = engine.generar_senales()
    buys    = sum(1 for s in signals if s["señal"] == "BUY")
    print(cc(f"  ✓  {len(signals)} activos analizados → {buys} BUY", G))
    top3 = [s for s in signals if s["señal"] == "BUY"][:3]
    for s in top3:
        h_v   = s.get("hurst", 0.5)
        h_lbl = "TREND" if h_v > 0.55 else ("MR" if h_v < 0.45 else "RW")
        beta  = s.get("beta_spy", 1.0)
        print(f"    {cc(s['ticker'].ljust(8), BOLD+W)}"
              f"  Score:{cc(str(round(s['score'])), G)}"
              f"  Conf:{cc(str(round(s['confianza']))+'%', Y)}"
              f"  RSI:{cc(str(s['rsi14']), DIM)}"
              f"  Hurst:{cc(f'{h_v:.2f}({h_lbl})', G if h_v>0.55 else DIM)}"
              f"  β:{cc(f'{beta:.2f}', DIM)}"
              f"  Kelly:{cc(str(s['kelly_pct'])+'%', M)}")
    sep(col=G)
    print(cc(f"  ✓  MÁQUINA LISTA — {n_models} modelos · 62 features · {len(signals)} activos", BOLD+G))
    sep(col=G)
    print()
    input(cc("  [ ENTER para abrir el menú ]\n", DIM))
    menu(engine)
if __name__ == "__main__":
    main()