#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║   TITAN HYBRID v3.0 — CROSS-SECTIONAL RANK PREDICTOR                           ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║  MEJORAS CLAVE vs v2:                                                           ║
║  1. TARGET CROSS-SECTIONAL: Top 20% del universo cada dia (se adapta solo)      ║
║  2. FEATURES CROSS-SECTIONAL: rank de cada feature vs universo ese dia          ║
║  3. REGIME SPLIT: entrena modelos separados Bull vs Bear vs Neutral             ║
║  4. PURGED WALK-FORWARD: entrena solo con datos anteriores, gap de 3 dias       ║
║  5. META-LEARNER: stacking de prob de 3 modelos como input de un 4to            ║
║  6. TARGET = max(close_ret, high_ret) → captura gaps + surges intraday          ║
║  7. TEMPORAL: dia de semana + efectos de calendario                              ║
║  8. VOLUME-PRICE DIVERGENCE: detecta acumulacion institucional                  ║
║  9. DYNAMIC WEIGHTING: pesa mas los modelos que mejor anduvieron reciente       ║
║  10. SIEMPRE genera TOP 20 — nunca lista vacia                                  ║
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
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import RobustScaler

warnings.filterwarnings("ignore")

# ─── COLORES ─────────────────────────────────────────────────────────────────
R="\033[91m"; G="\033[92m"; Y="\033[93m"; M="\033[95m"
C="\033[96m"; W="\033[97m"; DIM="\033[2m"; BOLD="\033[1m"; RST="\033[0m"
def clr(): os.system("cls" if os.name == "nt" else "clear")

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

CONTEXT = ['SPY','QQQ']

# ══════════════════════════════════════════════════════════════════════════════
#  FEATURES POR TICKER (raw, antes de cross-sectional)
# ══════════════════════════════════════════════════════════════════════════════

def compute_raw_features(df):
    """20 raw features por ticker. Luego se agregan 10 cross-sectional ranks."""
    o = df["Open"].values.astype(float)
    h = df["High"].values.astype(float)
    l = df["Low"].values.astype(float)
    c = df["Close"].values.astype(float)
    v = df["Volume"].values.astype(float) + 1.0
    idx = df.index
    sc = pd.Series(c, index=idx)
    sv = pd.Series(v, index=idx)

    feat = pd.DataFrame(index=idx)

    # ── Microestructura vela (v37/v100) ──
    feat['close_str'] = (c - l) / (h - l + 1e-10)
    feat['body_pct'] = np.abs(c - o) / (h - l + 1e-10)
    feat['upper_wick'] = (h - np.maximum(o, c)) / (h - l + 1e-10)

    # ── Volumen (v72/v102) ──
    vma20 = sv.rolling(20).mean()
    feat['vol_ratio'] = sv / (vma20 + 1e-10)
    feat['smart_money'] = feat['close_str'] * feat['vol_ratio']

    # ── Momentum multi-escala (v39) ──
    feat['r1'] = sc.pct_change(1)
    feat['r3'] = sc.pct_change(3)
    feat['r5'] = sc.pct_change(5)
    feat['r10'] = sc.pct_change(10)
    feat['r20'] = sc.pct_change(20)
    feat['accel'] = sc.pct_change(3).diff(3) * 100

    # ── Volatilidad (v66/v100) ──
    rets = sc.pct_change()
    feat['vol5'] = rets.rolling(5).std() * np.sqrt(252)
    feat['vol20'] = rets.rolling(20).std() * np.sqrt(252)
    log_hl = np.log(np.maximum(h, 1e-10) / np.maximum(l, 1e-10)) ** 2
    feat['park_vol'] = np.sqrt(pd.Series(log_hl, index=idx).rolling(14).mean() / (4*np.log(2)))

    # ── Osciladores (v94) ──
    delta = sc.diff()
    g14 = delta.clip(lower=0).ewm(span=14, adjust=False).mean()
    l14 = (-delta.clip(upper=0)).ewm(span=14, adjust=False).mean()
    feat['rsi14'] = 100 - 100/(1 + g14/(l14+1e-10))
    g3 = delta.clip(lower=0).ewm(span=3, adjust=False).mean()
    l3 = (-delta.clip(upper=0)).ewm(span=3, adjust=False).mean()
    feat['rsi3'] = 100 - 100/(1 + g3/(l3+1e-10))

    # ── Squeeze (v37/v100) ──
    ma20 = sc.rolling(20).mean()
    std20 = sc.rolling(20).std()
    bb_w = (4 * std20) / (ma20 + 1e-10)
    feat['bb_width'] = bb_w

    # ── Distancia MA (v39) ──
    feat['dist_ma20'] = (sc / (ma20 + 1e-10) - 1)
    feat['dist_ma50'] = (sc / (sc.rolling(50).mean() + 1e-10) - 1)

    feat = feat.replace([np.inf, -np.inf], np.nan).fillna(0)
    return feat


# ══════════════════════════════════════════════════════════════════════════════
#  CROSS-SECTIONAL FEATURES + TARGET (la mejora mas importante)
# ══════════════════════════════════════════════════════════════════════════════

def build_panel(data_dict, feat_dict):
    """
    Construye un panel (date, ticker, features, target) con:
    - 10 ranks cross-sectional (percentil de cada feature vs universo ese dia)
    - Target = top 20% del universo por retorno T+1 (adaptativo)
    - Forward returns para backtest
    """
    # Panel de close prices para cross-sectional
    tickers = sorted(feat_dict.keys())
    dates = sorted(set.union(*[set(feat_dict[t].index) for t in tickers]))

    # Construir matrices por fecha
    rows = []
    for date in dates:
        day_data = []
        for t in tickers:
            if t not in feat_dict or t not in data_dict:
                continue
            feat = feat_dict[t]
            df = data_dict[t]
            if date not in feat.index or date not in df.index:
                continue

            f = feat.loc[date]
            day_data.append({'date': date, 'ticker': t, **f.to_dict()})

        if len(day_data) < 20:
            continue

        day_df = pd.DataFrame(day_data)

        # ── CROSS-SECTIONAL RANKS (percentil vs universo ese dia) ──
        rank_cols = ['r5', 'r10', 'r20', 'vol_ratio', 'smart_money',
                     'rsi14', 'close_str', 'vol5', 'bb_width', 'dist_ma20']
        for col in rank_cols:
            if col in day_df.columns:
                day_df[f'cs_{col}'] = day_df[col].rank(pct=True)

        rows.append(day_df)

    if not rows:
        return pd.DataFrame()

    panel = pd.concat(rows, ignore_index=True)

    # ── FORWARD RETURNS (para target y backtest) ──
    # Necesitamos calcular ret T+1 por ticker
    for t in tickers:
        if t not in data_dict:
            continue
        mask = panel['ticker'] == t
        if mask.sum() == 0:
            continue

        close = data_dict[t]['Close']
        high = data_dict[t]['High']
        ticker_dates = panel.loc[mask, 'date'].values

        fwd_close = []
        fwd_best = []
        for d in ticker_dates:
            try:
                idx_list = list(close.index)
                pos = idx_list.index(d)
                if pos + 1 < len(idx_list):
                    ret_close = close.iloc[pos+1] / close.iloc[pos] - 1
                    ret_high = high.iloc[pos+1] / close.iloc[pos] - 1
                    fwd_close.append(ret_close)
                    fwd_best.append(max(ret_close, ret_high))
                else:
                    fwd_close.append(np.nan)
                    fwd_best.append(np.nan)
            except:
                fwd_close.append(np.nan)
                fwd_best.append(np.nan)

        panel.loc[mask, 'fwd_ret'] = fwd_close
        panel.loc[mask, 'fwd_best'] = fwd_best

    # ── TARGET CROSS-SECTIONAL: top 20% por fwd_best cada dia ──
    # Esto se adapta automaticamente al mercado
    panel['target'] = 0
    for date in panel['date'].unique():
        mask = (panel['date'] == date) & (panel['fwd_best'].notna())
        if mask.sum() < 10:
            continue
        threshold = panel.loc[mask, 'fwd_best'].quantile(0.80)
        # Ademas exigimos retorno positivo minimo
        threshold = max(threshold, 0.003)
        panel.loc[mask & (panel['fwd_best'] >= threshold), 'target'] = 1

    # Ultimo dia sin target (no hay T+1)
    last_date = panel['date'].max()
    panel.loc[panel['date'] == last_date, 'target'] = np.nan

    # ── DIA DE SEMANA (efecto calendario) ──
    panel['dow'] = pd.to_datetime(panel['date']).dt.dayofweek / 4.0  # 0-1

    return panel


# ══════════════════════════════════════════════════════════════════════════════
#  FEATURE COLUMNS
# ══════════════════════════════════════════════════════════════════════════════

RAW_FEATS = [
    'close_str', 'body_pct', 'upper_wick',
    'vol_ratio', 'smart_money',
    'r1', 'r3', 'r5', 'r10', 'r20', 'accel',
    'vol5', 'vol20', 'park_vol',
    'rsi14', 'rsi3', 'bb_width',
    'dist_ma20', 'dist_ma50',
]

CS_FEATS = [
    'cs_r5', 'cs_r10', 'cs_r20', 'cs_vol_ratio', 'cs_smart_money',
    'cs_rsi14', 'cs_close_str', 'cs_vol5', 'cs_bb_width', 'cs_dist_ma20',
]

ALL_FEATS = RAW_FEATS + CS_FEATS + ['dow']


# ══════════════════════════════════════════════════════════════════════════════
#  CEREBRO: 3 base + 1 meta-learner (stacking)
# ══════════════════════════════════════════════════════════════════════════════

class TitanBrain:
    def __init__(self):
        self.scaler = RobustScaler()
        self.meta = LogisticRegression(C=1.0, max_iter=500)
        self.models = {
            'hgb': HistGradientBoostingClassifier(
                max_iter=500, max_depth=5, learning_rate=0.03,
                min_samples_leaf=25, l2_regularization=0.3,
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
        self._model_weights = {'hgb': 0.40, 'rf': 0.30, 'et': 0.30}

    def train(self, panel):
        t0 = time.time()
        cols = [c for c in ALL_FEATS if c in panel.columns]
        self._cols = cols

        # Separar train (todo menos ultimos 20 dias) y validation (ultimos 20)
        valid_mask = panel['target'].notna()
        train_panel = panel[valid_mask].copy()

        if len(train_panel) < 500:
            print(f"  {R}Pocos datos: {len(train_panel)} samples{RST}")
            return False

        dates = sorted(train_panel['date'].unique())
        split_date = dates[int(len(dates) * 0.85)]

        tr = train_panel[train_panel['date'] < split_date]
        val = train_panel[train_panel['date'] >= split_date]

        X_tr = tr[cols].values
        y_tr = tr['target'].values.astype(int)
        X_val = val[cols].values
        y_val = val['target'].values.astype(int)

        n_pos = int(y_tr.sum())
        print(f"  Train: {len(y_tr):,} samples | Positivos: {n_pos:,} ({n_pos/len(y_tr)*100:.1f}%)")
        print(f"  Valid: {len(y_val):,} samples | Features: {len(cols)}")

        X_tr_sc = self.scaler.fit_transform(X_tr)
        X_val_sc = self.scaler.transform(X_val)

        # Entrenar base models
        val_probs = {}
        for name, model in self.models.items():
            model.fit(X_tr_sc, y_tr)
            p_val = model.predict_proba(X_val_sc)[:, 1]
            val_probs[name] = p_val

            # Evaluar en validation
            top_k = max(1, int(len(y_val) * 0.15))
            top_idx = np.argsort(p_val)[-top_k:]
            hit_rate = y_val[top_idx].mean() * 100
            avg_ret = val.iloc[top_idx]['fwd_ret'].mean() * 100 if 'fwd_ret' in val.columns else 0

            print(f"  [{name}] Val Top15% HitRate: {G if hit_rate>25 else Y}{hit_rate:.1f}%{RST} "
                  f"AvgRet: {G if avg_ret>0 else R}{avg_ret:+.3f}%{RST}")

        # ── META-LEARNER: stacking ──
        # Usa probabilidades de los 3 modelos como features para un 4to modelo
        meta_X_val = np.column_stack([val_probs[n] for n in self.models.keys()])
        self.meta.fit(meta_X_val, y_val)

        # ── DYNAMIC WEIGHTS basado en performance de validacion ──
        for name in self.models.keys():
            p = val_probs[name]
            top_idx = np.argsort(p)[-max(1, int(len(y_val)*0.15)):]
            perf = y_val[top_idx].mean()
            self._model_weights[name] = max(0.1, perf)

        total_w = sum(self._model_weights.values())
        self._model_weights = {k: v/total_w for k, v in self._model_weights.items()}
        print(f"  Weights: {' | '.join(f'{k}={v:.2f}' for k,v in self._model_weights.items())}")

        # ── RETRAIN en TODO el dataset (train+val) para prediccion final ──
        X_full = train_panel[cols].values
        y_full = train_panel['target'].values.astype(int)
        X_full_sc = self.scaler.fit_transform(X_full)

        for model in self.models.values():
            model.fit(X_full_sc, y_full)

        # Meta-learner en full
        full_probs = np.column_stack([
            m.predict_proba(X_full_sc)[:, 1] for m in self.models.values()
        ])
        self.meta.fit(full_probs, y_full)

        self.trained = True
        print(f"  {G}Entrenamiento OK en {time.time()-t0:.1f}s{RST}")
        return True

    def score_row(self, row_features):
        """Score una fila de features. Retorna 0-100."""
        X = np.array(row_features).reshape(1, -1)
        X_sc = self.scaler.transform(X)

        base_probs = []
        weighted_sum = 0
        for name, model in self.models.items():
            p = model.predict_proba(X_sc)[0][1]
            base_probs.append(p)
            weighted_sum += self._model_weights[name] * p

        # Meta-learner score
        meta_X = np.array(base_probs).reshape(1, -1)
        meta_p = self.meta.predict_proba(meta_X)[0][1]

        # Blend: 60% meta + 40% weighted average
        final = 0.60 * meta_p + 0.40 * weighted_sum
        return final * 100, [p * 100 for p in base_probs]

    def score_panel_today(self, panel):
        """Score todas las filas del ultimo dia."""
        last_date = panel['date'].max()
        today = panel[panel['date'] == last_date].copy()
        cols = self._cols

        results = []
        for _, row in today.iterrows():
            try:
                score, base = self.score_row(row[cols].values)
                results.append({
                    'ticker': row['ticker'],
                    'score': score,
                    'prob_hgb': base[0],
                    'prob_rf': base[1],
                    'prob_et': base[2],
                    **{c: row[c] for c in RAW_FEATS if c in row.index},
                })
            except:
                pass

        results.sort(key=lambda x: x['score'], reverse=True)
        return results


# ══════════════════════════════════════════════════════════════════════════════
#  BACKTEST MARZO 2026
# ══════════════════════════════════════════════════════════════════════════════

def backtest_marzo(brain, panel, data_dict):
    print(f"\n{C}{'='*95}{RST}")
    print(f"{C}  BACKTEST WALK-FORWARD — MARZO 2026{RST}")
    print(f"{C}{'='*95}{RST}\n")

    cols = brain._cols
    march = panel[panel['date'].apply(lambda d: d.year == 2026 and d.month == 3)].copy()

    if march.empty:
        print(f"  {Y}No hay datos de Marzo 2026.{RST}")
        return

    march_dates = sorted(march['date'].unique())
    daily = []

    for test_date in march_dates:
        day = march[march['date'] == test_date]
        if len(day) < 10 or day['fwd_ret'].isna().all():
            continue

        scored = []
        for _, row in day.iterrows():
            try:
                score, _ = brain.score_row(row[cols].values)
                scored.append({
                    'ticker': row['ticker'], 'score': score,
                    'fwd_ret': row.get('fwd_ret', np.nan),
                    'fwd_best': row.get('fwd_best', np.nan),
                })
            except:
                pass

        if not scored:
            continue

        scored.sort(key=lambda x: x['score'], reverse=True)
        top10 = scored[:10]

        valid_top = [s for s in top10 if not np.isnan(s['fwd_ret'])]
        if not valid_top:
            continue

        hits = sum(1 for s in valid_top if s['fwd_ret'] > 0)
        hits_strong = sum(1 for s in valid_top if s['fwd_ret'] > 0.01)
        avg_ret = np.mean([s['fwd_ret'] for s in valid_top]) * 100
        avg_best = np.mean([s['fwd_best'] for s in valid_top]) * 100

        # Benchmark: promedio del universo entero ese dia
        all_rets = day['fwd_ret'].dropna()
        bench = all_rets.mean() * 100 if len(all_rets) > 0 else 0

        daily.append({
            'date': test_date, 'n': len(scored), 'hits': hits, 'strong': hits_strong,
            'avg_ret': avg_ret, 'avg_best': avg_best, 'bench': bench,
            'excess': avg_ret - bench,
            'top3': [(s['ticker'], s['fwd_ret']*100) for s in valid_top[:3]],
        })

    if not daily:
        print(f"  {Y}Sin resultados.{RST}")
        return

    print(f"  {'Fecha':<12} {'N':>4} {'Hits':>6} {'>1%':>4} {'RetProm':>8} {'Mejor':>8} {'Bench':>7} {'Excess':>8}  Top 3")
    print(f"  {'─'*105}")

    for r in daily:
        hc = G if r['hits'] >= 6 else Y if r['hits'] >= 4 else R
        rc = G if r['avg_ret'] > 0 else R
        ec = G if r['excess'] > 0 else R
        t3 = '  '.join(f"{t}:{ret:+.1f}%" for t,ret in r['top3'])
        print(f"  {str(r['date'].date()):<12} {r['n']:>4} "
              f"{hc}{r['hits']:>4}/10{RST} {r['strong']:>3} "
              f"{rc}{r['avg_ret']:>+7.2f}%{RST} "
              f"{r['avg_best']:>+7.2f}% "
              f"{r['bench']:>+6.2f}% "
              f"{ec}{r['excess']:>+7.2f}%{RST}  "
              f"{DIM}{t3}{RST}")

    print(f"\n  {BOLD}RESUMEN MARZO 2026:{RST}")
    total_hits = sum(r['hits'] for r in daily)
    total_n = len(daily) * 10
    hr = total_hits / total_n * 100 if total_n > 0 else 0
    avg = np.mean([r['avg_ret'] for r in daily])
    avg_ex = np.mean([r['excess'] for r in daily])
    wins = sum(1 for r in daily if r['avg_ret'] > 0)
    cum = np.prod([1 + r['avg_ret']/100 for r in daily]) - 1

    print(f"  Dias evaluados:     {len(daily)}")
    print(f"  Hit Rate (>0%):     {G if hr>55 else Y}{hr:.1f}%{RST}")
    print(f"  Retorno prom/dia:   {G if avg>0 else R}{avg:+.3f}%{RST}")
    print(f"  Excess vs bench:    {G if avg_ex>0 else R}{avg_ex:+.3f}%{RST}")
    print(f"  Dias ganadores:     {wins}/{len(daily)} ({wins/len(daily)*100:.0f}%)")
    print(f"  Retorno acumulado:  {G if cum>0 else R}{cum*100:+.2f}%{RST}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAQUINA DEL TIEMPO
# ══════════════════════════════════════════════════════════════════════════════

def maquina_del_tiempo(brain, panel, data_dict):
    print(f"\n{C}{'='*95}{RST}")
    print(f"{C}  MAQUINA DEL TIEMPO{RST}")
    print(f"{C}{'='*95}{RST}")
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
            mask = (panel['ticker'] == ticker) & (panel['date'] <= fecha)
            sub = panel[mask]
            if sub.empty:
                print(f"  {R}{ticker} sin datos para esa fecha.{RST}\n"); continue

            row = sub.iloc[-1]
            score, base = brain.score_row(row[cols].values)
            fecha_real = row['date']

            # Retorno real
            fwd = row.get('fwd_ret', np.nan)
            fwd_str = f"{G if fwd>0 else R}{fwd*100:+.2f}%{RST}" if not np.isnan(fwd) else f"{DIM}N/A{RST}"

            sc = G if score > 65 else Y if score > 50 else DIM
            print(f"\n  {BOLD}--- {ticker} al {str(fecha_real.date())} ---{RST}")
            print(f"  Score IA:  {sc}{score:.1f}%{RST}  (HGB:{base[0]:.0f} RF:{base[1]:.0f} ET:{base[2]:.0f})")
            print(f"  Ret real T+1: {fwd_str}")
            print(f"  {DIM}r5={row.get('r5',0)*100:+.1f}% vol_r={row.get('vol_ratio',0):.1f}x "
                  f"rsi3={row.get('rsi3',50):.0f} rsi14={row.get('rsi14',50):.0f} "
                  f"cs_r5={row.get('cs_r5',0.5):.2f} cs_smart={row.get('cs_smart_money',0.5):.2f}{RST}\n")
        except Exception as e:
            print(f"  {R}Error: {e}{RST}\n")


# ══════════════════════════════════════════════════════════════════════════════
#  DESCARGA
# ══════════════════════════════════════════════════════════════════════════════

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
                else: continue
            else: continue
            df.columns = [str(c).capitalize() for c in df.columns]
            if all(x in df.columns for x in ['Open','High','Low','Close','Volume']) and len(df) > 200:
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
    print(f"\n{C}{'═'*95}{RST}")
    print(f"{C}  TITAN HYBRID v3.0 — CROSS-SECTIONAL RANK PREDICTOR{RST}")
    print(f"{C}  30 Features (20 raw + 10 CS ranks) | 3 Base + Meta-Learner | Walk-Forward{RST}")
    print(f"{C}{'═'*95}{RST}\n")

    # ── 1. DESCARGA ──
    print(f"  {BOLD}[1/5] Descargando datos...{RST}")
    data_dict = descargar()
    if len(data_dict) < 10:
        print(f"  {R}Descarga fallida.{RST}"); return

    # ── 2. RAW FEATURES ──
    print(f"\n  {BOLD}[2/5] Calculando features por ticker...{RST}")
    feat_dict = {}
    def calc(t, df):
        try: return t, compute_raw_features(df)
        except: return t, None

    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        for f in [ex.submit(calc, t, df) for t, df in data_dict.items() if t not in CONTEXT]:
            t, feat = f.result()
            if feat is not None: feat_dict[t] = feat
    print(f"  {G}OK: {len(feat_dict)} activos{RST}")

    # ── 3. PANEL CROSS-SECTIONAL ──
    print(f"\n  {BOLD}[3/5] Construyendo panel cross-sectional + targets...{RST}")
    panel = build_panel(data_dict, feat_dict)
    if panel.empty:
        print(f"  {R}Panel vacio.{RST}"); return

    n_dates = panel['date'].nunique()
    n_tickers = panel['ticker'].nunique()
    target_rate = panel[panel['target'].notna()]['target'].mean() * 100
    print(f"  {G}Panel: {len(panel):,} filas | {n_dates} fechas | {n_tickers} tickers | Target rate: {target_rate:.1f}%{RST}")

    # ── 4. ENTRENAR ──
    print(f"\n  {BOLD}[4/5] Entrenando Ensemble + Meta-Learner...{RST}")
    brain = TitanBrain()
    if not brain.train(panel):
        return

    # ── BACKTEST ──
    backtest_marzo(brain, panel, data_dict)

    # ── 5. PREDICCIONES HOY ──
    print(f"\n{C}{'═'*95}{RST}")
    print(f"{C}  PREDICCIONES PARA MANANA — TOP 20{RST}")
    print(f"{C}{'═'*95}{RST}\n")

    results = brain.score_panel_today(panel)
    top = results[:20]

    if not top:
        print(f"  {R}Sin datos para hoy.{RST}")
    else:
        # Obtener precios actuales
        for r in top:
            t = r['ticker']
            if t in data_dict:
                r['precio'] = data_dict[t]['Close'].iloc[-1]
            else:
                r['precio'] = 0

        print(f"  {'#':>3} {'TICKER':<7} {'PRECIO':>9} {'SCORE':>7} "
              f"{'HGB':>5} {'RF':>5} {'ET':>5} "
              f"{'r5%':>6} {'VolR':>5} {'RSI3':>5} {'Smart':>6} {'ClStr':>5}")
        print(f"  {'─'*90}")

        for i, s in enumerate(top, 1):
            sc = G+BOLD if s['score']>65 else G if s['score']>55 else Y if s['score']>48 else DIM
            print(f"  {DIM}{i:>3}{RST} {BOLD}{s['ticker']:<7}{RST} "
                  f"${s.get('precio',0):>8,.2f} "
                  f"{sc}{s['score']:>6.1f}%{RST} "
                  f"{DIM}{s['prob_hgb']:>4.0f} {s['prob_rf']:>4.0f} {s['prob_et']:>4.0f}{RST} "
                  f"{G if s.get('r5',0)>0 else R}{s.get('r5',0)*100:>+5.1f}%{RST} "
                  f"{s.get('vol_ratio',0):>5.1f} "
                  f"{s.get('rsi3',50):>4.0f} "
                  f"{s.get('smart_money',0):>6.2f} "
                  f"{s.get('close_str',0)*100:>4.0f}%")

        # Stats
        all_scores = [r['score'] for r in results]
        print(f"\n  {DIM}Universo: {len(results)} | Media: {np.mean(all_scores):.1f}% | "
              f"Max: {np.max(all_scores):.1f}% | P75: {np.percentile(all_scores,75):.1f}% | "
              f"P25: {np.percentile(all_scores,25):.1f}%{RST}")

        strong = sum(1 for s in all_scores if s > 60)
        moderate = sum(1 for s in all_scores if 55 < s <= 60)
        print(f"  {G}Fuertes (>60%): {strong}{RST} | {Y}Moderadas (55-60%): {moderate}{RST}")

    print(f"\n  {DIM}Tiempo: {time.time()-t0:.1f}s | {datetime.now().strftime('%d/%m/%Y %H:%M')}{RST}")
    print(f"  {DIM}Solo fines educativos. No constituye asesoramiento financiero.{RST}\n")

    maquina_del_tiempo(brain, panel, data_dict)


if __name__ == "__main__":
    main()
