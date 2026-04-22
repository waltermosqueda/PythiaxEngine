"""
DEEP ANALYSIS — Williams %R + Bollinger Squeeze (Estrategia D)
================================================================
Análisis profundo del candidato que superó V5 en walk-forward.

Preguntas a responder:
  1. ¿Qué trades genera? ¿Son los mismos que V5 o diferentes?
  2. ¿Qué pasa si combinamos V5 + D? (OR = más trades, AND = mejores trades)
  3. ¿La señal RSI>50 como exit mejora D?
  4. Walk-forward detallado con más granularidad
  5. Monte Carlo bootstrap para robustez
  6. ¿Cuál es el modelo superador óptimo?
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import warnings, sys, os

warnings.filterwarnings('ignore')
if sys.platform == 'win32':
    try: sys.stdout.reconfigure(encoding='utf-8')
    except: pass

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
# INDICADORES
# ================================================================
def calc_rsi(s, p=14):
    d = s.diff()
    g = d.where(d>0,0.0)
    l = (-d).where(d<0,0.0)
    ag = g.ewm(com=p-1, min_periods=p).mean()
    al = l.ewm(com=p-1, min_periods=p).mean()
    return 100 - 100/(1 + ag/al)

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
    return (c - (sma-sd*std))/((sma+sd*std)-(sma-sd*std)+1e-10), (sma+sd*std-(sma-sd*std))/sma*100

def calc_williams(h, l, c, p=14):
    return -100*(h.rolling(p).max()-c)/(h.rolling(p).max()-l.rolling(p).min()+1e-10)

def precompute(data, tickers):
    ind = {}
    spy_c = data['Close']['SPY']
    ind['_SPY'] = {'close': spy_c, 'sma50': spy_c.rolling(50).mean(),
                   'vol': spy_c.pct_change().rolling(20).std()*100}

    for t in tickers:
        try:
            c = data['Close'][t]; h = data['High'][t]; l = data['Low'][t]; v = data['Volume'][t]
            rsi = calc_rsi(c)
            _, _, macd_hist = calc_macd(c)
            sma50 = c.rolling(50).mean()
            atr = calc_atr(h,l,c)
            vol_avg = v.rolling(20).mean()
            bb_pctb, bb_width = calc_bollinger(c)
            wr = calc_williams(h,l,c)
            ind[t] = {
                'close':c,'high':h,'low':l,'volume':v,
                'rsi':rsi,'rsi_prev':rsi.shift(1),'macd_hist':macd_hist,
                'sma50':sma50,'atr':atr,'vol_avg':vol_avg,
                'bb_pctb':bb_pctb,'bb_width':bb_width,'williams_r':wr,
            }
        except: pass
    return ind

def check_regime(ind, i):
    try:
        s = ind['_SPY']
        return s['close'].iloc[i] > s['sma50'].iloc[i] and s['vol'].iloc[i] < 1.0
    except: return False

# ================================================================
# SEÑALES
# ================================================================
def signal_v5(ind, t, i):
    ti = ind[t]
    rsi=ti['rsi'].iloc[i]; mn=ti['macd_hist'].iloc[i]; mp=ti['macd_hist'].iloc[i-1]
    p=ti['close'].iloc[i]; s50=ti['sma50'].iloc[i]; vr=ti['volume'].iloc[i]/(ti['vol_avg'].iloc[i]+1e-10)
    atr=ti['atr'].iloc[i]; ds=(p/s50-1)*100; ma=mn-mp; man=ma/(atr*0.01+1e-6)
    if np.isnan(rsi) or np.isnan(s50) or np.isnan(atr): return False,{}
    if rsi>=25 or mn<=mp or ds>-10 or vr>1.5: return False,{}
    sc=min(40,max(0,(30-rsi)/30*40))+min(30,max(0,(abs(ds)-5)/15*30))+min(20,max(0,man*5))+min(10,max(0,(1.5-vr)/1.5*10))
    if sc<30: return False,{}
    return True,{'rsi':rsi,'dist_sma':ds,'score':sc,'price':p}

def signal_williams_squeeze(ind, t, i):
    ti = ind[t]
    wr=ti['williams_r'].iloc[i]; bw=ti['bb_width'].iloc[i]
    bw_min = ti['bb_width'].iloc[max(0,i-50):i+1].min() if i>=50 else np.nan
    p=ti['close'].iloc[i]; s50=ti['sma50'].iloc[i]; ds=(p/s50-1)*100
    rsi=ti['rsi'].iloc[i]
    if np.isnan(wr) or np.isnan(bw) or np.isnan(bw_min) or np.isnan(rsi): return False,{}
    if wr>=-90 or bw>bw_min*1.2 or ds>-5: return False,{}
    return True,{'williams_r':wr,'bb_width':bw,'dist_sma':ds,'rsi':rsi,'price':p}

def signal_v5_or_d(ind, t, i):
    """UNION: V5 OR Williams+Squeeze — más trades."""
    s1,i1 = signal_v5(ind,t,i)
    s2,i2 = signal_williams_squeeze(ind,t,i)
    if s1: return True, {**i1, 'source': 'V5'}
    if s2: return True, {**i2, 'source': 'D'}
    return False, {}

def signal_v5_and_d(ind, t, i):
    """INTERSECCION: V5 AND algún overlap con D conditions."""
    s1,i1 = signal_v5(ind,t,i)
    if not s1: return False,{}
    ti = ind[t]
    wr=ti['williams_r'].iloc[i]
    bw=ti['bb_width'].iloc[i]
    bw_min = ti['bb_width'].iloc[max(0,i-50):i+1].min() if i>=50 else np.nan
    if np.isnan(wr) or np.isnan(bw) or np.isnan(bw_min): return True, i1  # Fall back to V5
    i1['williams_r'] = wr
    i1['bb_squeeze'] = bw <= bw_min * 1.5  # Relaxed squeeze
    return True, i1

def signal_d_relaxed(ind, t, i):
    """D con Williams %R < -85 (un poco más relajado)."""
    ti = ind[t]
    wr=ti['williams_r'].iloc[i]; bw=ti['bb_width'].iloc[i]
    bw_min = ti['bb_width'].iloc[max(0,i-50):i+1].min() if i>=50 else np.nan
    p=ti['close'].iloc[i]; s50=ti['sma50'].iloc[i]; ds=(p/s50-1)*100
    rsi=ti['rsi'].iloc[i]
    if np.isnan(wr) or np.isnan(bw) or np.isnan(bw_min) or np.isnan(rsi): return False,{}
    if wr>=-85 or bw>bw_min*1.3 or ds>-5: return False,{}
    return True,{'williams_r':wr,'bb_width':bw,'dist_sma':ds,'rsi':rsi,'price':p}

# ================================================================
# BACKTEST con múltiples tipos de salida
# ================================================================
def backtest_multi_exit(ind, tickers, signal_fn, start='2024-09-01', end='2026-04-05',
                        commission=0.001):
    dates = ind['_SPY']['close'].index
    mask = (dates >= start) & (dates <= end)
    valid = np.where(mask)[0]
    trades = []; last = {}

    for i in valid:
        if i < 260 or i + 25 >= len(dates): continue
        if not check_regime(ind, i): continue
        for t in tickers:
            if t not in ind: continue
            if t in last and (dates[i]-last[t]).days < 5: continue
            try:
                sig, info = signal_fn(ind, t, i)
                if not sig: continue
                ep = ind[t]['close'].iloc[i]

                # Multiple exit returns
                rets = {}
                for h in [5,7,10,15]:
                    try:
                        xp = ind[t]['close'].iloc[i+h]
                        rets[f'hold_{h}d'] = xp/ep-1-2*commission
                    except: pass

                # RSI>50 exit (max 20d)
                rsi_exit_ret = None; rsi_exit_days = None
                for d in range(1,21):
                    try:
                        if ind[t]['rsi'].iloc[i+d] > 50:
                            rsi_exit_ret = ind[t]['close'].iloc[i+d]/ep-1-2*commission
                            rsi_exit_days = d
                            break
                    except: break
                if rsi_exit_ret is None:
                    try:
                        rsi_exit_ret = ind[t]['close'].iloc[i+20]/ep-1-2*commission
                        rsi_exit_days = 20
                    except: pass

                # MFE/MAE
                mfe,mae = 0,0
                for d in range(1,16):
                    try:
                        mfe = max(mfe, ind[t]['high'].iloc[i+d]/ep-1)
                        mae = min(mae, ind[t]['low'].iloc[i+d]/ep-1)
                    except: pass

                trades.append({
                    'date': dates[i], 'ticker': t,
                    **rets,
                    'rsi_exit': rsi_exit_ret, 'rsi_exit_days': rsi_exit_days,
                    'mfe': mfe, 'mae': mae,
                    **info,
                })
                last[t] = dates[i]
            except: continue

    return pd.DataFrame(trades)

def metrics_from_series(r, name=""):
    if len(r)==0: return {'name':name,'trades':0,'wr':0,'avg':0,'sharpe':0,'mdd':0,'total':0}
    w=r[r>0]; l=r[r<=0]
    eq=(1+r).cumprod(); pk=eq.expanding().max()
    std=r.std()
    return {
        'name':name, 'trades':len(r), 'wins':len(w), 'losses':len(l),
        'wr':round(len(w)/len(r)*100,1), 'avg':round(r.mean()*100,2),
        'sharpe':round(r.mean()/std*np.sqrt(252),2) if std>0 else 0,
        'mdd':round(((eq-pk)/pk).min()*100,1),
        'total':round((eq.iloc[-1]-1)*100,1),
        'pf':round(w.sum()/abs(l.sum()),2) if len(l)>0 and l.sum()!=0 else 999,
    }

def pm(m):
    if m['trades']==0: print(f"    {m['name']:<35} 0 trades"); return
    print(f"    {m['name']:<35} T:{m['trades']:>3} WR:{m['wr']:>5.1f}% Avg:{m['avg']:>+6.2f}% "
          f"Sharpe:{m['sharpe']:>7.2f} MDD:{m['mdd']:>6.1f}% Total:{m['total']:>7.1f}% PF:{m['pf']:>5.2f}")

# ================================================================
# WALK-FORWARD DETALLADO
# ================================================================
def detailed_wf(ind, tickers, signal_fn, hold_col='hold_7d', name=""):
    dates = ind['_SPY']['close'].index
    end = dates[-1]
    windows = []
    current = pd.Timestamp('2024-09-01')
    while True:
        te = current + pd.DateOffset(months=6)
        vs = te; ve = vs + pd.DateOffset(months=2)
        if ve > end + pd.DateOffset(months=1): break
        windows.append((current.strftime('%Y-%m-%d'),te.strftime('%Y-%m-%d'),
                        vs.strftime('%Y-%m-%d'),ve.strftime('%Y-%m-%d')))
        current += pd.DateOffset(months=2)

    print(f"\n    {name} — Walk-Forward Detallado")
    print(f"    {'Window':<10} {'TrainT':>6} {'TestT':>5} {'TestWR':>6} {'TestAvg':>8} {'TestSharpe':>10} {'OK':>4}")
    print(f"    {'-'*55}")

    results = []
    for ts, te, vs, ve in windows:
        df_test = backtest_multi_exit(ind, tickers, signal_fn, vs, ve)
        if len(df_test) > 0 and hold_col in df_test.columns:
            r = df_test[hold_col].dropna()
            m = metrics_from_series(r, f"Test {vs[:7]}")
        else:
            m = {'trades':0,'wr':0,'avg':0,'sharpe':0}

        df_train = backtest_multi_exit(ind, tickers, signal_fn, ts, te)
        train_n = len(df_train)
        ok = 'Y' if m['trades']>0 and m['sharpe']>0 else 'N' if m['trades']>0 else '-'
        print(f"    {vs[:7]:<10} {train_n:>6} {m['trades']:>5} {m['wr']:>5.1f}% {m['avg']:>+7.2f}% {m['sharpe']:>10.2f} {ok:>4}")
        results.append({'trades':m['trades'],'sharpe':m['sharpe'],'ok':ok})

    with_trades = [r for r in results if r['trades']>0]
    pos = sum(1 for r in with_trades if r['sharpe']>0)
    if with_trades:
        pct = pos/len(with_trades)*100
        avg_s = np.mean([r['sharpe'] for r in with_trades])
        print(f"    {'='*55}")
        print(f"    Positivas: {pos}/{len(with_trades)} ({pct:.0f}%) | Avg Sharpe: {avg_s:.2f}")
        return pct, len(with_trades), avg_s
    return 0, 0, 0

# ================================================================
# MONTE CARLO
# ================================================================
def monte_carlo(returns, n_sims=1000, name=""):
    print(f"\n    {name} — Monte Carlo ({n_sims} sims)")
    r = returns.values
    sharpes = []; wrs = []; mdds = []; totals = []
    for _ in range(n_sims):
        sample = np.random.choice(r, size=len(r), replace=True)
        s_series = pd.Series(sample)
        eq = (1+s_series).cumprod()
        pk = eq.expanding().max()
        std = s_series.std()
        sharpes.append(s_series.mean()/std*np.sqrt(252) if std>0 else 0)
        wrs.append((s_series>0).mean()*100)
        mdds.append(((eq-pk)/pk).min()*100)
        totals.append((eq.iloc[-1]-1)*100)

    print(f"    {'Metric':<12} {'P5':>8} {'P25':>8} {'P50':>8} {'P75':>8} {'P95':>8}")
    print(f"    {'-'*52}")
    for name_m, vals in [('Sharpe',sharpes),('WR%',wrs),('MDD%',mdds),('Total%',totals)]:
        p = np.percentile(vals, [5,25,50,75,95])
        print(f"    {name_m:<12} {p[0]:>8.2f} {p[1]:>8.2f} {p[2]:>8.2f} {p[3]:>8.2f} {p[4]:>8.2f}")

    print(f"\n    P(Sharpe>0): {(np.array(sharpes)>0).mean()*100:.1f}%")
    print(f"    P(Total>0%): {(np.array(totals)>0).mean()*100:.1f}%")
    print(f"    Worst 1% Sharpe: {np.percentile(sharpes,1):.2f}")
    print(f"    Worst 1% MDD: {np.percentile(mdds,1):.1f}%")

# ================================================================
# MAIN
# ================================================================
def main():
    start_time = datetime.now()
    print("=" * 80)
    print("  DEEP ANALYSIS — Williams+Squeeze + Variantes + RSI Exit")
    print(f"  {start_time.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)

    all_t = list(set(TICKERS + ['SPY']))
    data = yf.download(all_t, start='2024-03-01', end='2026-04-05', progress=False, threads=True)
    available = [t for t in TICKERS if t in data['Close'].columns and data['Close'][t].dropna().shape[0]>200]
    print(f"  {len(available)} tickers disponibles")
    ind = precompute(data, available)
    print(f"  Indicadores precomputados")

    # ── SECCION 1: Trades individuales de D vs V5 ──
    print("\n" + "=" * 80)
    print("  SECCION 1: COMPARACION TRADE-POR-TRADE V5 vs D")
    print("=" * 80)

    df_v5 = backtest_multi_exit(ind, available, signal_v5)
    df_d = backtest_multi_exit(ind, available, signal_williams_squeeze)

    print(f"\n  V5 trades ({len(df_v5)}):")
    if len(df_v5) > 0:
        for _, row in df_v5.iterrows():
            h7 = row.get('hold_7d', np.nan)
            print(f"    {str(row['date'])[:10]} {row['ticker']:<6} RSI:{row.get('rsi',0):.1f} "
                  f"SMA:{row.get('dist_sma',0):.1f}% → 7d:{h7*100:+.1f}%")

    print(f"\n  D trades ({len(df_d)}):")
    if len(df_d) > 0:
        for _, row in df_d.iterrows():
            h7 = row.get('hold_7d', np.nan)
            re = row.get('rsi_exit', np.nan)
            red = row.get('rsi_exit_days', np.nan)
            print(f"    {str(row['date'])[:10]} {row['ticker']:<6} WR:{row.get('williams_r',0):.1f} "
                  f"BB:{row.get('bb_width',0):.1f} RSI:{row.get('rsi',0):.1f} "
                  f"→ 7d:{h7*100:+.1f}% | RSI>50:{re*100:+.1f}%({red:.0f}d)" if not np.isnan(h7) and not np.isnan(re) else
                  f"    {str(row['date'])[:10]} {row['ticker']:<6}")

    # Overlap
    v5_pairs = set(zip(df_v5['date'].astype(str), df_v5['ticker'])) if len(df_v5)>0 else set()
    d_pairs = set(zip(df_d['date'].astype(str), df_d['ticker'])) if len(df_d)>0 else set()
    overlap = v5_pairs & d_pairs
    print(f"\n  Overlap: {len(overlap)} trades en común")
    print(f"  V5 únicos: {len(v5_pairs - d_pairs)}")
    print(f"  D únicos: {len(d_pairs - v5_pairs)}")

    # ── SECCION 2: Todas las variantes con múltiples salidas ──
    print("\n" + "=" * 80)
    print("  SECCION 2: VARIANTES x SALIDAS (matriz completa)")
    print("=" * 80)

    strategies = {
        'V5':               signal_v5,
        'D: W+Squeeze':     signal_williams_squeeze,
        'D Relaxed':        signal_d_relaxed,
        'V5 OR D':          signal_v5_or_d,
    }

    exit_cols = ['hold_5d','hold_7d','hold_10d','hold_15d','rsi_exit']

    print(f"\n  {'Strategy':<20}", end="")
    for ec in exit_cols:
        print(f" {ec:>12}", end="")
    print()
    print(f"  {'-'*80}")

    all_results = {}
    for sname, sfn in strategies.items():
        df = backtest_multi_exit(ind, available, sfn)
        all_results[sname] = df
        print(f"  {sname:<20}", end="")
        for ec in exit_cols:
            if len(df)>0 and ec in df.columns:
                r = df[ec].dropna()
                if len(r)>0:
                    m = metrics_from_series(r)
                    print(f"  S:{m['sharpe']:>5.1f}/{m['trades']}t", end="")
                else:
                    print(f"  {'---':>12}", end="")
            else:
                print(f"  {'---':>12}", end="")
        print()

    # Detailed metrics for top combos
    print(f"\n  --- Métricas detalladas ---")
    for sname in strategies:
        df = all_results[sname]
        if len(df) == 0: continue
        for ec in ['hold_7d', 'rsi_exit']:
            if ec in df.columns:
                r = df[ec].dropna()
                if len(r) > 0:
                    m = metrics_from_series(r, f"{sname} / {ec}")
                    pm(m)

    # ── SECCION 3: Walk-Forward detallado ──
    print("\n" + "=" * 80)
    print("  SECCION 3: WALK-FORWARD DETALLADO")
    print("=" * 80)

    for sname, sfn in strategies.items():
        for ec in ['hold_7d', 'rsi_exit']:
            detailed_wf(ind, available, sfn, hold_col=ec, name=f"{sname} / {ec}")

    # ── SECCION 4: Monte Carlo para D ──
    print("\n" + "=" * 80)
    print("  SECCION 4: MONTE CARLO")
    print("=" * 80)

    df_d = all_results.get('D: W+Squeeze', pd.DataFrame())
    if len(df_d) > 0:
        for ec in ['hold_7d', 'rsi_exit']:
            if ec in df_d.columns:
                r = df_d[ec].dropna()
                if len(r) >= 5:
                    monte_carlo(r, name=f"D: W+Squeeze / {ec}")

    df_union = all_results.get('V5 OR D', pd.DataFrame())
    if len(df_union) > 0:
        for ec in ['hold_7d', 'rsi_exit']:
            if ec in df_union.columns:
                r = df_union[ec].dropna()
                if len(r) >= 5:
                    monte_carlo(r, name=f"V5 OR D / {ec}")

    # ── SECCION 5: Veredicto ──
    print("\n" + "=" * 80)
    print("  SECCION 5: VEREDICTO")
    print("=" * 80)

    print("""
  Protocolo 6 — Convergencia 3 Ángulos:

  ANGULO 1 (Técnico): [ver métricas arriba]
  ANGULO 2 (Riesgo): [ver MDD y Monte Carlo worst-case]
  ANGULO 3 (Simplicidad): V5=4 filtros, D=3 filtros, Union=4+3 filtros

  Pregunta clave: ¿Modelo superador es D solo, V5+D unión, o V5 se mantiene?
""")

    elapsed = (datetime.now() - start_time).total_seconds() / 60
    print(f"  Tiempo: {elapsed:.1f} min")
    print("=" * 80)

if __name__ == '__main__':
    main()
