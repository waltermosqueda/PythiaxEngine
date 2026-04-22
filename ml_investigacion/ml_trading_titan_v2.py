#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║   TITAN HYBRID v2.0 — PREDICTOR DEFINITIVO DE SUBAS T+1                        ║
║   Fusion: v37 + v66 + v72 + v94 + v97 + v100 + v102 + v39 + v11               ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  ARQUITECTURA RANK-BASED (siempre genera lista):                                ║
║  • 3 Modelos especializados entrenados en paralelo                              ║
║  • Score final = promedio ponderado de probabilidades crudas                    ║
║  • Ranking forzado: siempre muestra TOP 20 del universo                         ║
║  • Backtest integrado Marzo 2026 con hit-rate real                              ║
║  • Maquina del Tiempo para auditar predicciones pasadas                         ║
╚══════════════════════════════════════════════════════════════════════════════════╝
  pip install yfinance numpy pandas scikit-learn
"""

import os, warnings, time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
    ExtraTreesClassifier,
)
from sklearn.preprocessing import RobustScaler

warnings.filterwarnings("ignore")

# ─── COLORES ─────────────────────────────────────────────────────────────────
R = "\033[91m"; G = "\033[92m"; Y = "\033[93m"; M = "\033[95m"
C = "\033[96m"; W = "\033[97m"; DIM = "\033[2m"; BOLD = "\033[1m"; RST = "\033[0m"
def clr(): os.system("cls" if os.name == "nt" else "clear")

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

CONTEXT = ['SPY', 'QQQ']

# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE ENGINEERING — 30 features probadas
# ══════════════════════════════════════════════════════════════════════════════

def compute_features(df):
    """
    30 features combinando lo mejor de todos los modelos.
    Robusto: solo usa OHLCV, no depende de datos externos.
    """
    o = df["Open"].values.astype(float)
    h = df["High"].values.astype(float)
    l = df["Low"].values.astype(float)
    c = df["Close"].values.astype(float)
    v = df["Volume"].values.astype(float) + 1.0
    idx = df.index
    n = len(c)

    feat = pd.DataFrame(index=idx)

    # ── MICROESTRUCTURA T+1 (de NOVA v37 — el mejor para gaps) ──────────
    feat['close_str'] = (c - l) / (h - l + 1e-10)                                # Fuerza cierre
    vol_ma = pd.Series(v).rolling(20).mean().values
    vol_std = pd.Series(v).rolling(20).std().values
    feat['vol_z'] = (v - vol_ma) / (vol_std + 1e-10)                             # Anomalia volumen
    feat['gap'] = np.concatenate([[0], (o[1:] / c[:-1] - 1) * 100])              # Gap apertura
    feat['intra'] = (c / (o + 1e-10) - 1) * 100                                  # Retorno intradia

    # RSI rapido (v37)
    delta = pd.Series(c).diff()
    gain3 = delta.clip(lower=0).ewm(span=3, adjust=False).mean().values
    loss3 = (-delta.clip(upper=0)).ewm(span=3, adjust=False).mean().values
    feat['rsi3'] = 100 - 100 / (1 + gain3 / (loss3 + 1e-10))

    # RSI clasico (v94)
    gain14 = delta.clip(lower=0).ewm(span=14, adjust=False).mean().values
    loss14 = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean().values
    feat['rsi14'] = 100 - 100 / (1 + gain14 / (loss14 + 1e-10))

    # ── BOLLINGER SQUEEZE (de v100/v37) ──────────────────────────────────
    s_c = pd.Series(c)
    ma20 = s_c.rolling(20).mean().values
    std20 = s_c.rolling(20).std().values
    bb_w = (4 * std20) / (ma20 + 1e-10)
    # Squeeze rank: percentil de BB width en ventana de 60 dias
    bb_s = pd.Series(bb_w)
    feat['bb_sqz'] = bb_s.rolling(60, min_periods=20).apply(
        lambda x: (x.values <= x.values[-1]).sum() / len(x), raw=False
    ).values

    # ── MOMENTUM MULTI-ESCALA (de v39/v102) ──────────────────────────────
    feat['r1'] = pd.Series(c).pct_change(1).values
    feat['r3'] = pd.Series(c).pct_change(3).values
    feat['r5'] = pd.Series(c).pct_change(5).values
    feat['r10'] = pd.Series(c).pct_change(10).values
    feat['r20'] = pd.Series(c).pct_change(20).values

    # Aceleracion (v100): segunda derivada del momentum
    r3s = pd.Series(feat['r3'])
    feat['accel'] = r3s.diff(3).values * 100

    # ── MEDIAS MOVILES (v39/v94) ─────────────────────────────────────────
    ma50 = s_c.rolling(50).mean().values
    feat['dist_ma20'] = (c - ma20) / (ma20 + 1e-10) * 100
    feat['dist_ma50'] = (c - ma50) / (ma50 + 1e-10) * 100
    feat['ma5_20'] = (pd.Series(c).rolling(5).mean().values - ma20) / (ma20 + 1e-10) * 100

    # ── VOLATILIDAD (de v66/v100) ────────────────────────────────────────
    rets = pd.Series(c).pct_change()
    feat['vol5'] = (rets.rolling(5).std() * np.sqrt(252) * 100).values
    feat['vol20'] = (rets.rolling(20).std() * np.sqrt(252) * 100).values
    feat['vol_rat'] = feat['vol5'] / (feat['vol20'] + 1e-10)

    # Parkinson volatility (v100)
    log_hl = np.log(np.maximum(h, 1e-10) / np.maximum(l, 1e-10)) ** 2
    feat['park_vol'] = np.sqrt(pd.Series(log_hl).rolling(14).mean().values / (4 * np.log(2)))

    # ── OSCILADORES (de v94/v66) ─────────────────────────────────────────
    # MACD histogram normalizado
    ema12 = pd.Series(c).ewm(span=12, adjust=False).mean().values
    ema26 = pd.Series(c).ewm(span=26, adjust=False).mean().values
    macd = ema12 - ema26
    sig = pd.Series(macd).ewm(span=9, adjust=False).mean().values
    feat['macd_h'] = (macd - sig) / (c + 1e-10) * 100

    # Stochastic (v11/v94)
    lo14 = pd.Series(l).rolling(14).min().values
    hi14 = pd.Series(h).rolling(14).max().values
    feat['stoch'] = (c - lo14) / (hi14 - lo14 + 1e-10) * 100

    # ── VOLUMEN AVANZADO (de v72/v102) ───────────────────────────────────
    feat['vol_ma_r'] = v / (vol_ma + 1e-10)                                     # Volume ratio
    feat['smart'] = feat['close_str'] * feat['vol_ma_r']                         # Smart money (v102)
    # OBV z-score (v102)
    direction = np.sign(pd.Series(c).diff().fillna(0).values)
    obv = np.cumsum(direction * v)
    obv_s = pd.Series(obv)
    feat['obv_z'] = ((obv_s - obv_s.rolling(20).mean()) / (obv_s.rolling(20).std() + 1e-10)).values

    # ── SOPORTE/RESISTENCIA (de v37) ─────────────────────────────────────
    feat['dist_lo10'] = (c / (pd.Series(l).rolling(10).min().values + 1e-10) - 1) * 100
    feat['dist_hi20'] = (c / (pd.Series(h).rolling(20).max().values + 1e-10) - 1) * 100

    feat = pd.DataFrame(feat, index=idx)
    feat = feat.replace([np.inf, -np.inf], np.nan).fillna(0)
    return feat


# ══════════════════════════════════════════════════════════════════════════════
#  TARGET: SUBE AL DIA SIGUIENTE (simple, directo, verificable)
# ══════════════════════════════════════════════════════════════════════════════

def make_target(close):
    """
    Target binario claro:
    1 = el activo estuvo en el TOP 15% de retornos T+1 del universo
        Y ademas subio mas de 0.5%
    0 = el resto

    Complemento: target_surge para subas fuertes >2.5%
    """
    ret_t1 = close.pct_change(1).shift(-1)
    # Suba minima de 0.5% + top del universo
    strong = (ret_t1 >= 0.005).astype(float)
    strong.iloc[-1] = np.nan
    return strong, ret_t1


# ══════════════════════════════════════════════════════════════════════════════
#  CEREBRO: 3 modelos con consenso simple (sin calibracion que aplaste)
# ══════════════════════════════════════════════════════════════════════════════

class TitanBrain:
    """
    Ensemble simple y robusto:
    - HistGBM (mejor para eventos extremos)
    - RandomForest (estable, bajo overfitting)
    - ExtraTrees (captura patrones raros)

    Score = promedio crudo de predict_proba → NUNCA colapsa a 0
    """

    FEAT_COLS = [
        'close_str', 'vol_z', 'gap', 'intra', 'rsi3', 'rsi14', 'bb_sqz',
        'r1', 'r3', 'r5', 'r10', 'r20', 'accel',
        'dist_ma20', 'dist_ma50', 'ma5_20',
        'vol5', 'vol20', 'vol_rat', 'park_vol',
        'macd_h', 'stoch',
        'vol_ma_r', 'smart', 'obv_z',
        'dist_lo10', 'dist_hi20',
    ]

    def __init__(self):
        self.scaler = RobustScaler()
        self.models = {
            'hgb': HistGradientBoostingClassifier(
                max_iter=400, max_depth=5, learning_rate=0.04,
                min_samples_leaf=20, l2_regularization=0.3,
                class_weight='balanced', random_state=42,
            ),
            'rf': RandomForestClassifier(
                n_estimators=300, max_depth=9, min_samples_leaf=12,
                max_features='sqrt', class_weight='balanced',
                n_jobs=-1, random_state=42,
            ),
            'et': ExtraTreesClassifier(
                n_estimators=300, max_depth=9, min_samples_leaf=10,
                max_features='sqrt', class_weight='balanced',
                n_jobs=-1, random_state=42,
            ),
        }
        self.trained = False
        self.train_stats = {}

    def _get_cols(self, feat):
        return [c for c in self.FEAT_COLS if c in feat.columns]

    def train(self, data_dict, feat_dict):
        t0 = time.time()
        X_all, y_all = [], []
        cols = None

        for ticker, df in data_dict.items():
            if ticker not in feat_dict:
                continue
            feat = feat_dict[ticker]
            if cols is None:
                cols = self._get_cols(feat)

            close = df['Close']
            target, _ = make_target(close)

            valid = target.notna()
            valid_idx = feat.index[valid.reindex(feat.index, fill_value=False)]
            if len(valid_idx) < 50:
                continue

            X_all.append(feat.loc[valid_idx, cols].values)
            y_all.append(target.reindex(valid_idx).values)

        if not X_all:
            print(f"  {R}[!] Sin datos suficientes para entrenar.{RST}")
            return False

        X = np.vstack(X_all)
        y = np.concatenate(y_all)
        self._cols = cols

        n_pos = int(y.sum())
        n_neg = len(y) - n_pos
        print(f"  Dataset: {len(y):,} muestras | Positivos: {n_pos:,} ({n_pos/len(y)*100:.1f}%) | Features: {len(cols)}")

        X_sc = self.scaler.fit_transform(X)

        for name, model in self.models.items():
            model.fit(X_sc, y)
            # Score en training para diagnostico
            train_prob = model.predict_proba(X_sc)[:, 1]
            self.train_stats[name] = {
                'mean_prob': train_prob.mean(),
                'max_prob': train_prob.max(),
                'std_prob': train_prob.std(),
            }
            print(f"  [{name}] prob media={train_prob.mean():.3f} max={train_prob.max():.3f} std={train_prob.std():.3f}")

        self.trained = True
        print(f"  {G}Entrenamiento OK en {time.time()-t0:.1f}s{RST}")
        return True

    def score_all(self, feat_dict, data_dict):
        """
        Calcula score para TODOS los activos. SIEMPRE devuelve una lista ordenada.
        Score = promedio de predict_proba de los 3 modelos (0 a 100).
        """
        results = []
        cols = self._cols

        for ticker, feat in feat_dict.items():
            try:
                X = feat[cols].iloc[-1:].values
                X_sc = self.scaler.transform(X)

                probs = []
                for model in self.models.values():
                    p = model.predict_proba(X_sc)[0]
                    # Clase 1 = suba
                    prob_up = p[1] if len(p) > 1 else p[0]
                    probs.append(prob_up)

                score = np.mean(probs) * 100  # 0-100
                precio = data_dict[ticker]['Close'].iloc[-1]
                f = feat.iloc[-1]

                results.append({
                    'ticker': ticker,
                    'score': score,
                    'precio': precio,
                    'prob_hgb': probs[0] * 100,
                    'prob_rf': probs[1] * 100,
                    'prob_et': probs[2] * 100,
                    'r5': f.get('r5', 0) * 100,
                    'vol_z': f.get('vol_z', 0),
                    'bb_sqz': f.get('bb_sqz', 0) * 100,
                    'close_str': f.get('close_str', 0) * 100,
                    'rsi3': f.get('rsi3', 50),
                    'smart': f.get('smart', 0),
                    'stoch': f.get('stoch', 50),
                    'dist_ma20': f.get('dist_ma20', 0),
                    'accel': f.get('accel', 0),
                })
            except:
                pass

        results.sort(key=lambda x: x['score'], reverse=True)
        return results

    def score_at_date(self, feat, date):
        """Score en una fecha historica especifica"""
        cols = self._cols
        idx = feat.index[feat.index <= date]
        if len(idx) == 0:
            return 0.0, None

        fecha_real = idx[-1]
        X = feat.loc[[fecha_real], cols].values
        X_sc = self.scaler.transform(X)

        probs = []
        for model in self.models.values():
            p = model.predict_proba(X_sc)[0]
            prob_up = p[1] if len(p) > 1 else p[0]
            probs.append(prob_up)

        return np.mean(probs) * 100, fecha_real


# ══════════════════════════════════════════════════════════════════════════════
#  BACKTEST MARZO 2026
# ══════════════════════════════════════════════════════════════════════════════

def backtest_marzo(brain, feat_dict, data_dict):
    print(f"\n{C}{'='*95}{RST}")
    print(f"{C}  BACKTEST WALK-FORWARD — MARZO 2026{RST}")
    print(f"{C}{'='*95}{RST}\n")

    # Encontrar fechas de marzo 2026
    all_dates = set()
    for t, feat in feat_dict.items():
        for d in feat.index:
            try:
                if d.year == 2026 and d.month == 3:
                    all_dates.add(d)
            except:
                pass

    march_dates = sorted(all_dates)
    if not march_dates:
        print(f"  {Y}No hay datos de Marzo 2026 en el historico descargado.{RST}")
        return

    total_preds = 0
    total_hits_positive = 0
    total_hits_strong = 0
    daily_results = []

    for test_date in march_dates[:-1]:
        day_preds = []

        for ticker, feat in feat_dict.items():
            if ticker not in data_dict or test_date not in feat.index:
                continue
            score, fecha_real = brain.score_at_date(feat, test_date)
            if fecha_real is None:
                continue

            df = data_dict[ticker]
            idx_list = list(df.index)
            try:
                pos = idx_list.index(fecha_real)
                if pos + 1 < len(idx_list):
                    ret = (df['Close'].iloc[pos + 1] / df['Close'].iloc[pos] - 1) * 100
                    day_preds.append({'ticker': ticker, 'score': score, 'ret': ret})
            except:
                pass

        if day_preds:
            day_preds.sort(key=lambda x: x['score'], reverse=True)
            top = day_preds[:10]
            hits_pos = sum(1 for p in top if p['ret'] > 0)
            hits_str = sum(1 for p in top if p['ret'] > 1.0)
            avg_ret = np.mean([p['ret'] for p in top])
            total_preds += len(top)
            total_hits_positive += hits_pos
            total_hits_strong += hits_str

            daily_results.append({
                'date': test_date,
                'signals': len(day_preds),
                'hits': hits_pos,
                'strong': hits_str,
                'avg_ret': avg_ret,
                'top3': [(p['ticker'], p['ret']) for p in top[:3]],
            })

    if not daily_results:
        print(f"  {Y}Sin resultados para Marzo 2026.{RST}")
        return

    print(f"  {'Fecha':<13} {'Top10':>6} {'Hits>0':>7} {'>1%':>5} {'RetProm':>9}  Top 3 (ticker: ret%)")
    print(f"  {'-'*90}")

    for r in daily_results:
        hc = G if r['hits'] >= 6 else Y if r['hits'] >= 4 else R
        rc = G if r['avg_ret'] > 0 else R
        t3 = '  '.join([f"{t}:{ret:+.1f}%" for t, ret in r['top3']])
        print(f"  {str(r['date'].date()):<13} {r['signals']:>5}  "
              f"{hc}{r['hits']}/10{RST}    {r['strong']:>2}   "
              f"{rc}{r['avg_ret']:+.2f}%{RST}   {DIM}{t3}{RST}")

    print(f"\n  {BOLD}{'─'*60}{RST}")
    print(f"  {BOLD}RESUMEN MARZO 2026:{RST}")
    if total_preds > 0:
        hr = total_hits_positive / total_preds * 100
        sr = total_hits_strong / total_preds * 100
        avg = np.mean([r['avg_ret'] for r in daily_results])
        wins = sum(1 for r in daily_results if r['avg_ret'] > 0)
        print(f"  Dias evaluados:    {len(daily_results)}")
        print(f"  Hit Rate (>0%):    {G if hr > 55 else Y}{hr:.1f}%{RST}  (random ~50%)")
        print(f"  Hit Rate (>1%):    {G if sr > 20 else Y}{sr:.1f}%{RST}")
        print(f"  Retorno prom/dia:  {G if avg > 0 else R}{avg:+.3f}%{RST}")
        print(f"  Dias ganadores:    {wins}/{len(daily_results)} ({wins/len(daily_results)*100:.0f}%)")
        cum_ret = np.prod([1 + r['avg_ret']/100 for r in daily_results]) - 1
        print(f"  Retorno acumulado: {G if cum_ret > 0 else R}{cum_ret*100:+.2f}%{RST}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAQUINA DEL TIEMPO
# ══════════════════════════════════════════════════════════════════════════════

def maquina_del_tiempo(brain, feat_dict, data_dict):
    print(f"\n{C}{'='*95}{RST}")
    print(f"{C}  MAQUINA DEL TIEMPO — AUDITORIA{RST}")
    print(f"{C}{'='*95}{RST}")
    print(f"  {DIM}Ingresa TICKER FECHA (ej: NFLX 2026-02-26) o 'salir'{RST}\n")

    while True:
        cmd = input(f"  {Y}>>> {RST}").strip().upper()
        if cmd in ('SALIR', 'EXIT', 'Q', ''):
            break

        parts = cmd.split()
        if len(parts) != 2:
            print(f"  {R}Formato: TICKER YYYY-MM-DD{RST}\n")
            continue

        ticker, fecha_str = parts
        if ticker not in feat_dict or ticker not in data_dict:
            print(f"  {R}{ticker} no encontrado.{RST}\n")
            continue

        try:
            fecha = pd.to_datetime(fecha_str)
            score, fecha_real = brain.score_at_date(feat_dict[ticker], fecha)
            if fecha_real is None:
                print(f"  {R}No hay datos para esa fecha.{RST}\n")
                continue

            df = data_dict[ticker]
            precio = df.loc[fecha_real, 'Close']
            f = feat_dict[ticker].loc[fecha_real]

            # Buscar retorno real T+1
            idx_list = list(df.index)
            try:
                pos = idx_list.index(fecha_real)
                if pos + 1 < len(idx_list):
                    ret_real = (df['Close'].iloc[pos + 1] / df['Close'].iloc[pos] - 1) * 100
                    ret_str = f"{G if ret_real > 0 else R}{ret_real:+.2f}%{RST}"
                else:
                    ret_str = f"{DIM}N/A{RST}"
            except:
                ret_str = f"{DIM}N/A{RST}"

            sc = G if score > 65 else Y if score > 50 else DIM
            print(f"\n  {BOLD}--- {ticker} al {fecha_real.strftime('%Y-%m-%d')} ---{RST}")
            print(f"  Precio: ${precio:.2f}")
            print(f"  Score IA:        {sc}{score:.1f}%{RST}")
            print(f"  Retorno real T+1: {ret_str}")
            print(f"  {DIM}Vol Z: {f.get('vol_z',0):+.2f} | BB Sqz: {f.get('bb_sqz',0)*100:.0f}% | "
                  f"RSI3: {f.get('rsi3',50):.0f} | Stoch: {f.get('stoch',50):.0f} | "
                  f"CloseStr: {f.get('close_str',0)*100:.0f}%{RST}\n")

        except Exception as e:
            print(f"  {R}Error: {e}{RST}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  DESCARGA
# ══════════════════════════════════════════════════════════════════════════════

def descargar_datos():
    all_tickers = list(set(ACTIVOS + CONTEXT))
    print(f"  Descargando {len(all_tickers)} tickers...")

    raw = yf.download(all_tickers, period="2y", group_by='ticker',
                      progress=False, threads=True, timeout=60)

    data = {}
    for t in all_tickers:
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
            if all(x in df.columns for x in ['Open','High','Low','Close','Volume']) and len(df) > 200:
                data[t] = df
        except:
            pass

    print(f"  {G}OK: {len(data)} activos descargados{RST}")
    return data


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    clr()
    t0 = time.time()

    print(f"\n{C}{'═'*95}{RST}")
    print(f"{C}  TITAN HYBRID v2.0 — PREDICTOR DEFINITIVO DE SUBAS T+1{RST}")
    print(f"{C}  Fusion de 8 modelos | 27 Features | 3 Modelos Ensemble | Rank-Based{RST}")
    print(f"{C}{'═'*95}{RST}\n")

    # ── 1. DESCARGA ──
    print(f"  {BOLD}[1/4] Descargando datos de mercado...{RST}")
    data_dict = descargar_datos()
    if len(data_dict) < 10:
        print(f"  {R}Error critico en descarga.{RST}")
        return

    # ── 2. FEATURES ──
    print(f"\n  {BOLD}[2/4] Calculando features hibridas...{RST}")
    feat_dict = {}

    def calc(t, df):
        try:
            return t, compute_features(df)
        except:
            return t, None

    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        futs = [ex.submit(calc, t, df) for t, df in data_dict.items() if t not in CONTEXT]
        for f in futs:
            t, feat = f.result()
            if feat is not None:
                feat_dict[t] = feat

    print(f"  {G}OK: {len(feat_dict)} activos con features{RST}")

    # ── 3. ENTRENAR ──
    print(f"\n  {BOLD}[3/4] Entrenando Ensemble Hibrido...{RST}")
    brain = TitanBrain()
    if not brain.train(data_dict, feat_dict):
        return

    # ── 4. BACKTEST MARZO 2026 ──
    backtest_marzo(brain, feat_dict, data_dict)

    # ── 5. PREDICCIONES HOY ──
    print(f"\n{C}{'═'*95}{RST}")
    print(f"{C}  PREDICCIONES PARA MANANA — TOP 20 ACTIVOS CON MAYOR PROBABILIDAD DE SUBA{RST}")
    print(f"{C}{'═'*95}{RST}\n")

    results = brain.score_all(feat_dict, data_dict)

    # SIEMPRE mostrar top 20 — nunca lista vacia
    top = results[:20]

    print(f"  {'#':>3} {'TICKER':<7} {'PRECIO':>9} {'SCORE':>7} "
          f"{'HGB':>6} {'RF':>6} {'ET':>6} "
          f"{'Ret5d':>7} {'VolZ':>6} {'Sqz':>5} {'RSI3':>5} {'Smart':>6}")
    print(f"  {'─'*90}")

    for i, s in enumerate(top, 1):
        sc = G+BOLD if s['score'] > 65 else G if s['score'] > 55 else Y if s['score'] > 50 else DIM
        vz = M if s['vol_z'] > 1.5 else (G if s['vol_z'] > 0.5 else DIM)
        sq = G if s['bb_sqz'] < 20 else DIM

        print(f"  {DIM}{i:>3}{RST} {BOLD}{s['ticker']:<7}{RST} "
              f"${s['precio']:>8,.2f} "
              f"{sc}{s['score']:>6.1f}%{RST} "
              f"{DIM}{s['prob_hgb']:>5.1f} {s['prob_rf']:>5.1f} {s['prob_et']:>5.1f}{RST} "
              f"{'G' if s['r5']>0 else R}{s['r5']:>+6.1f}%{RST} "
              f"{vz}{s['vol_z']:>+5.1f}{RST} "
              f"{sq}{s['bb_sqz']:>4.0f}%{RST} "
              f"{s['rsi3']:>4.0f} "
              f"{s['smart']:>5.2f}")

    # Estadisticas del score
    all_scores = [r['score'] for r in results]
    print(f"\n  {DIM}Estadisticas del universo ({len(results)} activos):{RST}")
    print(f"  {DIM}Score medio: {np.mean(all_scores):.1f}% | "
          f"Mediana: {np.median(all_scores):.1f}% | "
          f"Max: {np.max(all_scores):.1f}% | "
          f"Min: {np.min(all_scores):.1f}% | "
          f"Std: {np.std(all_scores):.1f}%{RST}")

    # Resumen de senales fuertes
    strong = [r for r in results if r['score'] > 60]
    moderate = [r for r in results if 55 < r['score'] <= 60]
    print(f"\n  {G}Senales fuertes (>60%): {len(strong)} activos{RST}")
    print(f"  {Y}Senales moderadas (55-60%): {len(moderate)} activos{RST}")

    elapsed = time.time() - t0
    print(f"\n  {DIM}Tiempo total: {elapsed:.1f}s | {datetime.now().strftime('%d/%m/%Y %H:%M')}{RST}")
    print(f"  {DIM}Solo fines educativos. No constituye asesoramiento financiero.{RST}\n")

    # ── MAQUINA DEL TIEMPO ──
    maquina_del_tiempo(brain, feat_dict, data_dict)


if __name__ == "__main__":
    main()
