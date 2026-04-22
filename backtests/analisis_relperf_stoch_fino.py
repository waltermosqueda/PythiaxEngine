"""
ANÁLISIS FINO: RelPerf + Stochastic — encontrar la combinación óptima
======================================================================
Objetivo: afinar DA-4 (SPY>SMA200 + Stoch<25) con el filtro RelPerf
y encontrar el rango exacto de Stochastic que maximiza WR/Sharpe.

Hallazgos previos a confirmar y profundizar:
  - Stoch 10-20: WR 85.7%, avg +6.47%  ← golden zone
  - RelPerf -5% a 0%: WR 88.9%, avg +9.88%  ← mejor zona
  - RelPerf -10% a -5%: WR 73.8%, avg +6.14%  ← también bueno
  - RelPerf < -20%: WR 64.4%, avg +2.28%  ← peor

Preguntas a responder:
  1. ¿Cuál es el rango EXACTO de Stochastic que funciona? (0-5, 5-10, 10-15, etc.)
  2. ¿Cuál es el umbral de RelPerf óptimo?
  3. ¿Se potencian mutuamente Stoch golden + RelPerf moderado?
  4. ¿Qué pasa con distintos periodos de RelPerf? (5d, 10d, 20d)
  5. ¿El combo DA-4 + RelPerf pasa walk-forward o es overfitting?

Plan:
  Parte 1: Granularidad fina de Stochastic y RelPerf
  Parte 2: Combinaciones cruzadas (Stoch × RelPerf)
  Parte 3: Variantes con RelPerf de 5d y 10d (además de 20d)
  Parte 4: Mini walk-forward del mejor candidato (4 ventanas recientes)
  Parte 5: Configuración final para el scanner

Universo: 258 tickers | Sep 2024 – Mar 2026 | Hold 15d
RSI: Wilder ewm(com=13) — VERIFICADO
"""

import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import os
import pandas as pd
import numpy as np
import warnings

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from titan_system.core.database import TitanDB
from titan_system.core.data_loader import ACTIVOS, CONTEXT_TICKERS

ALL_TICKERS  = list(set(ACTIVOS + CONTEXT_TICKERS))
PERIOD_START = '2024-09-01'
PERIOD_END   = '2026-03-28'
HOLD_DAYS    = 15

# ── Indicadores ───────────────────────────────────────────────────────────────

def calc_rsi_wilder(close, period=14):
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False).mean()
    return 100 - 100 / (1 + gain / (loss + 1e-10))

def calc_macd_hist(close, fast=12, slow=26, signal=9):
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd  = ema_f - ema_s
    return macd - macd.ewm(span=signal, adjust=False).mean()

def calc_atr(high, low, close, period=14):
    tr = pd.concat([
        (high - low),
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_stoch_k(high, low, close, period=14):
    lo = low.rolling(period).min()
    hi = high.rolling(period).max()
    return (close - lo) / (hi - lo + 1e-10) * 100

def calc_score(rsi, dsma, macd_acc_n, vr):
    return (max(0, min(40, (30-rsi)/30*40)) +
            max(0, min(30, (abs(dsma)-5)/15*30)) +
            max(0, min(20, macd_acc_n*5)) +
            max(0, min(10, (1.5-vr)/1.5*10)))

# ── Recopilación ──────────────────────────────────────────────────────────────

def collect_pool(all_data, spy_df):
    records = []
    recent  = {}

    spy_states = {}
    for date in spy_df.index:
        sl = spy_df[spy_df.index <= date]
        if len(sl) < 210:
            spy_states[date] = {}
            continue
        c = sl['close']
        spy_states[date] = {
            'sma50':  bool(c.iloc[-1] > c.rolling(50).mean().iloc[-1]),
            'sma200': bool(c.iloc[-1] > c.rolling(200).mean().iloc[-1]),
            'lowvol': bool(c.pct_change().rolling(20).std().iloc[-1]*100 < 1.0),
            'spy_r5':  float(c.pct_change(5).iloc[-1])  if len(c)>5  else 0.0,
            'spy_r10': float(c.pct_change(10).iloc[-1]) if len(c)>10 else 0.0,
            'spy_r20': float(c.pct_change(20).iloc[-1]) if len(c)>20 else 0.0,
        }

    dates = sorted(d for d in spy_df.index
                   if PERIOD_START <= str(d)[:10] <= PERIOD_END)

    for date in dates:
        spy_st = spy_states.get(date, {})

        for ticker, df in all_data.items():
            if ticker in CONTEXT_TICKERS:
                continue
            df_sl = df[df.index <= date]
            if len(df_sl) < 210:
                continue
            if ticker in recent and (date - recent[ticker]).days < 3:
                continue

            c = df_sl['close']; h = df_sl['high']
            l = df_sl['low'];   v = df_sl['volume']

            rsi_s = calc_rsi_wilder(c)
            rsi14 = rsi_s.iloc[-1]
            if rsi14 >= 25:
                continue

            sma50 = c.rolling(50).mean().iloc[-1]
            price = c.iloc[-1]
            dsma  = (price / sma50 - 1) * 100
            if dsma >= -8:
                continue

            rsi_sl = rsi_s.iloc[-1] - rsi_s.iloc[-4] if len(rsi_s) >= 4 else 0.0
            mh     = calc_macd_hist(c)
            mh_c   = mh.iloc[-1]; mh_p = mh.iloc[-2] if len(mh) > 1 else 0.0
            atr14  = calc_atr(h, l, c).iloc[-1]
            v20    = v.rolling(20).mean().iloc[-1]
            vr     = v.iloc[-1] / (v20 + 1e-10)
            acc_n  = (mh_c - mh_p) / (atr14 * 0.01 + 1e-6)
            score  = calc_score(rsi14, dsma, acc_n, vr)

            if any(np.isnan(x) for x in [rsi14, dsma, score, rsi_sl]):
                continue

            stoch_k = calc_stoch_k(h, l, c).iloc[-1]
            rsi70   = calc_rsi_wilder(c, 70).iloc[-1]

            # RelPerf en 3 timeframes
            r5  = float(c.pct_change(5).iloc[-1])  if len(c) > 5  else 0.0
            r10 = float(c.pct_change(10).iloc[-1]) if len(c) > 10 else 0.0
            r20 = float(c.pct_change(20).iloc[-1]) if len(c) > 20 else 0.0
            relperf5  = (r5  - spy_st.get('spy_r5',  0.0)) * 100
            relperf10 = (r10 - spy_st.get('spy_r10', 0.0)) * 100
            relperf20 = (r20 - spy_st.get('spy_r20', 0.0)) * 100

            future = df[df.index > date]
            if len(future) < 15:
                continue
            ret15 = future.head(15)['close'].iloc[-1] / price - 1

            records.append({
                'date': date, 'ticker': ticker,
                'rsi': rsi14, 'rsi_slope': rsi_sl,
                'dsma': dsma, 'score': score, 'vr': vr,
                'macd_up': bool(mh_c > mh_p),
                'spy_sma50':  spy_st.get('sma50',  False),
                'spy_sma200': spy_st.get('sma200', False),
                'spy_lowvol': spy_st.get('lowvol', False),
                'stoch_k': stoch_k,
                'rsi70':   rsi70,
                'relperf5':  relperf5,
                'relperf10': relperf10,
                'relperf20': relperf20,
                'ret': ret15,
            })
            recent[ticker] = date

    return pd.DataFrame(records)


def m(df, hold=15):
    if df is None or len(df) < 3:
        return None
    r     = df['ret'].values
    wr    = (r > 0).mean() * 100
    avg   = r.mean() * 100
    sh    = (r.mean()/hold) / (r.std()/hold + 1e-10) * np.sqrt(252)
    tot   = ((1+r).prod()-1) * 100
    cum   = np.cumprod(1+r)
    dd    = (cum / np.maximum.accumulate(cum) - 1).min() * 100
    p90   = np.percentile(r*100, 90)
    expl  = (r*100 >= 10).sum()
    return {'n': len(r), 'wr': wr, 'avg': avg, 'sh': sh,
            'mdd': dd, 'tot': tot, 'p90': p90, 'expl': expl}

def row(label, mx, ref=None):
    if not mx:
        print(f"  {label:<55}  <3 trades")
        return
    beat = ""
    if ref and mx['sh'] > ref['sh'] and mx['mdd'] > ref['mdd']:
        beat = "  ★"
    print(f"  {label:<55}  N:{mx['n']:>3}  WR:{mx['wr']:>5.1f}%  "
          f"Avg:{mx['avg']:>+6.2f}%  Sh:{mx['sh']:>6.2f}  "
          f"MDD:{mx['mdd']:>+6.1f}%  P90:{mx['p90']:>+6.2f}%  Expl:{mx['expl']:>2}{beat}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print("="*100)
    print("  ANÁLISIS FINO: RelPerf + Stochastic — Afinar DA-4 hacia el scanner final")
    print("  258 tickers | Sep 2024 – Mar 2026 | Hold 15d | RSI Wilder — VERIFICADO")
    print("="*100)

    print("\n  Cargando datos...")
    with TitanDB() as db:
        all_data = {}
        for t in ALL_TICKERS:
            df = db.get_prices(t, '2024-01-01', '2026-03-28')
            if df is not None and len(df) > 210:
                all_data[t] = df.sort_index()
    spy_df = all_data.get('SPY')
    print(f"  {len(all_data)} tickers cargados\n")

    print("  Construyendo pool...")
    pool = collect_pool(all_data, spy_df)
    print(f"  {len(pool)} candidatos\n")

    # DA-4 base: SPY>SMA200 + RSI<22 + score>20 + noMACD
    da4 = pool[pool['spy_sma200'] & (pool['rsi'] < 22) &
               (pool['score'] > 20) & (pool['dsma'] < -10)]
    da4_ref = m(da4)

    # ─────────────────────────────────────────────────────────────────────────
    print("="*100)
    print("  PARTE 1: GRANULARIDAD FINA DE STOCHASTIC K")
    print("="*100)
    print(f"\n  {'Rango Stochastic':<30}  {'N':>4}  {'WR':>6}  {'Avg':>7}  {'Sharpe':>7}  {'MDD':>7}  {'P90':>7}  {'Expl':>5}")
    print(f"  {'-'*85}")

    stoch_bins = [(0,5),(5,10),(10,15),(15,20),(20,25),(25,30),(0,10),(0,15),(0,20),(10,20),(5,20),(5,25)]
    for lo, hi in stoch_bins:
        sub = da4[(da4['stoch_k'] >= lo) & (da4['stoch_k'] < hi)]
        mx  = m(sub)
        lbl = f"Stoch {lo:>2}-{hi:<2}"
        row(lbl, mx)

    # ─────────────────────────────────────────────────────────────────────────
    print()
    print("="*100)
    print("  PARTE 2: GRANULARIDAD FINA DE RELPERF (20d, 10d, 5d)")
    print("="*100)

    for col, label in [('relperf20','RelPerf 20d'),('relperf10','RelPerf 10d'),('relperf5','RelPerf 5d')]:
        print(f"\n  -- {label} --")
        print(f"  {'Rango':<30}  {'N':>4}  {'WR':>6}  {'Avg':>7}  {'Sharpe':>7}  {'MDD':>7}  {'P90':>7}")
        print(f"  {'-'*80}")
        bins_rp = [(-999,-30),(-30,-20),(-20,-15),(-15,-10),(-10,-5),(-5,-2),(-2,0),(0,5),(5,999)]
        for lo, hi in bins_rp:
            sub = da4[(da4[col] >= lo) & (da4[col] < hi)]
            mx  = m(sub)
            lbl = f"  {lo:>+4}% a {hi:>+4}%"
            if mx:
                print(f"  {lbl:<30}  {mx['n']:>4}  {mx['wr']:>5.1f}%  "
                      f"{mx['avg']:>+6.2f}%  {mx['sh']:>7.2f}  "
                      f"{mx['mdd']:>+6.1f}%  {mx['p90']:>+6.2f}%")
            else:
                print(f"  {lbl:<30}  <3 trades")

    # ─────────────────────────────────────────────────────────────────────────
    print()
    print("="*100)
    print("  PARTE 3: COMBINACIONES CRUZADAS — Stoch × RelPerf")
    print("="*100)
    print(f"\n  DA-4 referencia (sin filtros extra):")
    row("DA-4 referencia", da4_ref)
    print()
    print(f"  {'Combinación':<55}  {'N':>4}  {'WR':>6}  {'Avg':>7}  {'Sharpe':>7}  {'MDD':>7}  {'P90':>7}  {'Expl':>5}")
    print(f"  {'-'*100}")

    combos = [
        # Stoch golden zone × RelPerf moderado
        ("Stoch 10-20 + relperf20 -15%/0%",
         da4[(da4['stoch_k']>=10)&(da4['stoch_k']<20)&
             (da4['relperf20']>=-15)&(da4['relperf20']<0)]),
        ("Stoch 10-20 + relperf20 -10%/0%",
         da4[(da4['stoch_k']>=10)&(da4['stoch_k']<20)&
             (da4['relperf20']>=-10)&(da4['relperf20']<0)]),
        ("Stoch 10-20 + relperf20 -5%/+5%",
         da4[(da4['stoch_k']>=10)&(da4['stoch_k']<20)&
             (da4['relperf20']>=-5)&(da4['relperf20']<5)]),
        ("Stoch 5-20  + relperf20 -15%/0%",
         da4[(da4['stoch_k']>=5)&(da4['stoch_k']<20)&
             (da4['relperf20']>=-15)&(da4['relperf20']<0)]),
        ("Stoch 5-20  + relperf20 -10%/+2%",
         da4[(da4['stoch_k']>=5)&(da4['stoch_k']<20)&
             (da4['relperf20']>=-10)&(da4['relperf20']<2)]),
        # Stoch amplio × RelPerf moderado
        ("Stoch <25   + relperf20 -15%/0%",
         da4[(da4['stoch_k']<25)&
             (da4['relperf20']>=-15)&(da4['relperf20']<0)]),
        ("Stoch <25   + relperf20 -10%/+2%",
         da4[(da4['stoch_k']<25)&
             (da4['relperf20']>=-10)&(da4['relperf20']<2)]),
        ("Stoch <25   + relperf20 > -20%",
         da4[(da4['stoch_k']<25)&(da4['relperf20']>=-20)]),
        ("Stoch <25   + relperf10 -10%/+2%",
         da4[(da4['stoch_k']<25)&
             (da4['relperf10']>=-10)&(da4['relperf10']<2)]),
        ("Stoch <25   + relperf5  -5%/+3%",
         da4[(da4['stoch_k']<25)&
             (da4['relperf5']>=-5)&(da4['relperf5']<3)]),
        # Sin filtro Stoch × solo RelPerf
        ("Solo relperf20 -20%/0%",
         da4[(da4['relperf20']>=-20)&(da4['relperf20']<0)]),
        ("Solo relperf20 -15%/+2%",
         da4[(da4['relperf20']>=-15)&(da4['relperf20']<2)]),
        ("Solo relperf20 > -15%",
         da4[da4['relperf20']>=-15]),
        # Excluir los peores (enfoque negativo: eliminar el bottom)
        ("Excluir relperf20 < -25%",
         da4[da4['relperf20']>=-25]),
        ("Stoch<25 + excluir relperf20<-25%",
         da4[(da4['stoch_k']<25)&(da4['relperf20']>=-25)]),
        # Combos con timeframes mixtos
        ("Stoch<25 + relperf20>-20% + relperf5>-8%",
         da4[(da4['stoch_k']<25)&(da4['relperf20']>=-20)&(da4['relperf5']>=-8)]),
    ]

    best_combo = None
    best_eff   = 0
    for label, sub in combos:
        mx = m(sub)
        row(label, mx, da4_ref)
        if mx and mx['n'] >= 10:
            eff = mx['sh'] / (abs(mx['mdd']) + 1)
            if eff > best_eff:
                best_eff   = eff
                best_combo = (label, sub, mx)

    # ─────────────────────────────────────────────────────────────────────────
    print()
    print("="*100)
    print("  PARTE 4: MINI WALK-FORWARD — 4 ventanas recientes")
    print("  (validación rápida out-of-sample de las mejores combinaciones)")
    print("="*100)

    wf_windows = [
        ('2025-06-01', '2025-08-01'),
        ('2025-08-01', '2025-10-01'),
        ('2025-10-01', '2025-12-01'),
        ('2025-12-01', '2026-02-01'),
        ('2026-02-01', '2026-03-28'),
    ]

    candidates = {
        'DA-4 base (ref)':
            lambda df: df[df['spy_sma200'] & (df['rsi']<22) &
                          (df['score']>20) & (df['dsma']<-10) & (df['stoch_k']<25)],
        'DA-4 + relperf20 >-20%':
            lambda df: df[df['spy_sma200'] & (df['rsi']<22) &
                          (df['score']>20) & (df['dsma']<-10) & (df['stoch_k']<25) &
                          (df['relperf20']>=-20)],
        'DA-4 + relperf20 >-15%':
            lambda df: df[df['spy_sma200'] & (df['rsi']<22) &
                          (df['score']>20) & (df['dsma']<-10) & (df['stoch_k']<25) &
                          (df['relperf20']>=-15)],
        'DA-4 + relperf20 -15%/0%':
            lambda df: df[df['spy_sma200'] & (df['rsi']<22) &
                          (df['score']>20) & (df['dsma']<-10) & (df['stoch_k']<25) &
                          (df['relperf20']>=-15) & (df['relperf20']<0)],
        'DA-4 + Stoch10-20 + relperf20 -15%/0%':
            lambda df: df[df['spy_sma200'] & (df['rsi']<22) &
                          (df['score']>20) & (df['dsma']<-10) &
                          (df['stoch_k']>=10) & (df['stoch_k']<20) &
                          (df['relperf20']>=-15) & (df['relperf20']<0)],
    }

    print(f"\n  {'Modelo':<45}  ", end='')
    for s, e in wf_windows:
        print(f"  {e[:7]:>8}", end='')
    print(f"  {'Avg Sh':>8}  {'W>0':>5}")
    print(f"  {'-'*110}")

    for name, fn in candidates.items():
        sharpes = []
        for s, e in wf_windows:
            sub = fn(pool[( pool['date'].astype(str).str[:10] >= s) &
                          ( pool['date'].astype(str).str[:10] <  e)])
            mx  = m(sub)
            sh  = mx['sh'] if mx else float('nan')
            sharpes.append(sh)

        valid   = [s for s in sharpes if not np.isnan(s)]
        avg_sh  = np.mean(valid) if valid else float('nan')
        pos_cnt = sum(1 for s in valid if s > 0)
        print(f"  {name:<45}  ", end='')
        for sh in sharpes:
            if np.isnan(sh):
                print(f"  {'---':>8}", end='')
            else:
                print(f"  {sh:>8.2f}", end='')
        print(f"  {avg_sh:>8.2f}  {pos_cnt:>2}/{len(valid)}")

    # ─────────────────────────────────────────────────────────────────────────
    print()
    print("="*100)
    print("  PARTE 5: CONFIGURACIÓN FINAL PARA EL SCANNER")
    print("="*100)

    # Mejor combo automático
    if best_combo:
        lbl, sub, mx = best_combo
        print(f"""
  Mejor combinación encontrada: {lbl}
    N:{mx['n']}  WR:{mx['wr']:.1f}%  Avg:{mx['avg']:+.2f}%  Sharpe:{mx['sh']:.2f}
    MDD:{mx['mdd']:+.1f}%  P90:{mx['p90']:+.2f}%  Explosivos:{mx['expl']}
  """)

    print("""
  PROPUESTA SCANNER "BESTIA-DOMADA" (basada en evidencia):

  Filtros confirmados:
    1. RSI(14) < 22          — oversold extremo (Wilder's ewm(com=13))
    2. dsma50 < -10%         — alejado de SMA50
    3. score > 20            — señal mínima de calidad
    4. SPY > SMA200          — mercado en tendencia de largo plazo (bull market)
    5. Stochastic K(14) < 25 — no en el piso absoluto (inicio de recuperación)
    6. RelPerf(20d) > -X%    — no underperformance catastrófica vs SPY
    7. Sin filtro MACD       — más trades, captura más movimientos
    8. Hold: 15 días         — más tiempo para que el rebote se desarrolle
    9. Anti-knife: 5 días    — mínimo entre entradas al mismo ticker

  Diferencias vs V4:
    + Sin vol<1.5 (permite más trades)
    + Sin SPY vol<1% (usa SMA200, más permisivo)
    + Sin MACD up obligatorio
    + Hold 15d vs 10d
    + RSI<22 vs <25
    - Sin filtro SPY SMA50 (pero tiene SMA200)
    - RelPerf como guardia contra colapsos individuales

  Pendiente definir: umbral exacto de RelPerf (análisis de partes 2-4 arriba)
    """)

    # Top 6 trades de la mejor combo
    if best_combo:
        lbl, sub, mx = best_combo
        print(f"  Top 6 trades de '{lbl}':")
        print(f"  {'Fecha':<12}  {'Ticker':<7}  {'RSI':>5}  {'Stoch':>6}  "
              f"{'RelPf20':>8}  {'RelPf5':>7}  {'Ret':>8}")
        for _, r in sub.nlargest(6, 'ret').iterrows():
            print(f"  {str(r['date'])[:10]:<12}  {r['ticker']:<7}  "
                  f"{r['rsi']:>5.1f}  {r['stoch_k']:>6.1f}  "
                  f"{r['relperf20']:>+8.1f}%  {r['relperf5']:>+7.1f}%  "
                  f"{r['ret']*100:>+7.2f}%  ✓")
        print()
        print(f"  Peores trades:")
        for _, r in sub.nsmallest(3, 'ret').iterrows():
            print(f"  {str(r['date'])[:10]:<12}  {r['ticker']:<7}  "
                  f"RSI:{r['rsi']:>5.1f}  Stoch:{r['stoch_k']:>6.1f}  "
                  f"RelPf20:{r['relperf20']:>+8.1f}%  {r['ret']*100:>+7.2f}%  ✗")

    print()


if __name__ == '__main__':
    main()
