"""
V7 ARCHITECTURE DECISION — A+C vs A+B+C
==========================================
Pregunta critica: Signal B (Williams+Squeeze) aporta o destruye valor?

Test: A+C7 vs A+B+C7 — cual es la mejor arquitectura para V7?
Incluye WF, MC, sensitivity para ambas.

Fecha: 2026-04-06
"""

import yfinance as yf
import pandas as pd
import numpy as np
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
    d=s.diff(); g=d.where(d>0,0.0); l=(-d).where(d<0,0.0)
    ag=g.ewm(com=p-1,min_periods=p).mean(); al=l.ewm(com=p-1,min_periods=p).mean()
    return 100-100/(1+ag/(al+1e-10))

def calc_macd(s):
    ef=s.ewm(span=12).mean(); es=s.ewm(span=26).mean(); m=ef-es
    return m,m.ewm(span=9).mean(),m-m.ewm(span=9).mean()

def calc_atr(h,l,c,p=14):
    tr=pd.concat([h-l,(h-c.shift(1)).abs(),(l-c.shift(1)).abs()],axis=1).max(axis=1)
    return tr.rolling(p).mean()

def calc_bollinger(c,p=20,sd=2):
    sma=c.rolling(p).mean(); std=c.rolling(p).std()
    return (c-(sma-sd*std))/((sma+sd*std)-(sma-sd*std)+1e-10),(sma+sd*std-(sma-sd*std))/sma*100

def calc_williams(h,l,c,p=14):
    return -100*(h.rolling(p).max()-c)/(h.rolling(p).max()-l.rolling(p).min()+1e-10)

def precompute(data, tickers):
    ind = {}
    spy_c = data['Close']['SPY']
    ind['_SPY'] = {'close':spy_c,'sma50':spy_c.rolling(50).mean(),
                   'vol':spy_c.pct_change().rolling(20).std()*100}
    for t in tickers:
        try:
            c=data['Close'][t].ffill(); h=data['High'][t]; l=data['Low'][t]; v=data['Volume'][t]
            rsi=calc_rsi(c); _,_,mh=calc_macd(c); s50=c.rolling(50).mean()
            atr=calc_atr(h,l,c); va=v.rolling(20).mean()
            bb_p,bb_w=calc_bollinger(c); wr=calc_williams(h,l,c)
            ind[t]={
                'close':c,'high':h,'low':l,'volume':v,'rsi':rsi,'macd_hist':mh,
                'sma50':s50,'atr':atr,'vol_avg':va,'bb_pctb':bb_p,'bb_width':bb_w,
                'williams_r':wr,'vol_ratio':v/(va+1e-10),'dist_sma50':(c/s50-1)*100,
                'roc10':(c/c.shift(10)-1)*100,
            }
        except: pass
    return ind

def regime(ind,i):
    try:
        s=ind['_SPY']
        return s['close'].iloc[i]>s['sma50'].iloc[i] and s['vol'].iloc[i]<1.0
    except: return False

# ================================================================
# SIGNALS
# ================================================================
def sig_a(ind,t,i):
    ti=ind[t]
    try:
        rsi=ti['rsi'].iloc[i]; m=ti['macd_hist'].iloc[i]; mp=ti['macd_hist'].iloc[i-1]
        dist=ti['dist_sma50'].iloc[i]; vr=ti['vol_ratio'].iloc[i]
        p=ti['close'].iloc[i]; atr=ti['atr'].iloc[i]
        if np.isnan(rsi) or np.isnan(dist): return None
        if rsi>=25 or m<=mp or dist>-10 or vr>1.5: return None
        rs=max(0,min(40,(30-rsi)/30*40)); ss=max(0,min(30,(abs(dist)-5)/15*30))
        ma=(m-mp)/(atr*0.01+1e-6); ms=max(0,min(20,ma*5)); vs=max(0,min(10,(1.5-vr)/1.5*10))
        if rs+ss+ms+vs<30: return None
        return {'signal':'A','price':p}
    except: return None

def sig_b(ind,t,i):
    ti=ind[t]
    try:
        wr=ti['williams_r'].iloc[i]; bw=ti['bb_width'].iloc[i]
        dist=ti['dist_sma50'].iloc[i]; p=ti['close'].iloc[i]
        if np.isnan(wr) or np.isnan(bw) or np.isnan(dist): return None
        if wr>=-90 or dist>-5: return None
        if i<50: return None
        bm=ti['bb_width'].iloc[i-50:i].min()
        if np.isnan(bm) or bw>bm*1.2: return None
        return {'signal':'B','price':p}
    except: return None

def sig_c(ind,t,i):
    ti=ind[t]
    try:
        roc=ti['roc10'].iloc[i]; vr=ti['vol_ratio'].iloc[i]; p=ti['close'].iloc[i]
        if np.isnan(roc) or np.isnan(vr): return None
        if roc>=-15 or vr<2.0: return None
        return {'signal':'C','price':p}
    except: return None

# ================================================================
# BACKTEST + METRICS + WF + MC
# ================================================================
def run_bt(ind, sig_funcs_regime, hold=7, start=60, ak=5):
    """sig_funcs_regime: list of (signal_func, needs_regime)"""
    trades=[]; le={}; dates=ind['_SPY']['close'].index
    for i in range(start, len(dates)-hold-1):
        reg = regime(ind,i)
        for t in TICKERS:
            if t not in ind: continue
            if t in le and (i-le[t])<ak: continue
            hit = None
            for sf, needs_reg in sig_funcs_regime:
                if needs_reg and not reg: continue
                hit = sf(ind,t,i)
                if hit: break
            if hit is None: continue
            pi=ind[t]['close'].iloc[i+1] if i+1<len(ind[t]['close']) else None
            oi=min(i+1+hold,len(ind[t]['close'])-1); po=ind[t]['close'].iloc[oi]
            if pi is None or np.isnan(pi) or np.isnan(po): continue
            trades.append({'ticker':t,'date':dates[i],'signal':hit['signal'],
                          'price_in':pi,'price_out':po,'return_pct':(po/pi-1)*100})
            le[t]=i
    return pd.DataFrame(trades)

def metrics(df):
    if df.empty: return {'n':0,'wr':0,'sh':0,'avg':0,'tot':0,'mdd':0}
    r=df['return_pct'].values; n=len(r)
    wr=(r>0).sum()/n*100; avg=r.mean(); std=r.std() if n>1 else 1
    sh=avg/std*np.sqrt(252/7) if std>0 else 0
    tot=(1+r/100).prod()*100-100
    eq=(1+r/100).cumprod(); pk=np.maximum.accumulate(eq)
    mdd=((eq-pk)/pk*100).min()
    return {'n':n,'wr':round(wr,1),'sh':round(sh,2),'avg':round(avg,2),
            'tot':round(tot,1),'mdd':round(mdd,1)}

def wf(ind, sig_funcs_regime, hold=7, nw=5, ak=5):
    dates=ind['_SPY']['close'].index; tot=len(dates)-60-hold-1
    if tot<100: return {'pct':0,'details':[]}
    ws=tot//nw; results=[]
    for w in range(nw):
        s=60+w*ws; e=min(s+ws,len(dates)-hold-1)
        trades=[]; le={}
        for i in range(s,e):
            reg=regime(ind,i)
            for t in TICKERS:
                if t not in ind: continue
                if t in le and (i-le[t])<ak: continue
                hit=None
                for sf,nr in sig_funcs_regime:
                    if nr and not reg: continue
                    hit=sf(ind,t,i)
                    if hit: break
                if hit is None: continue
                pi=ind[t]['close'].iloc[i+1] if i+1<len(ind[t]['close']) else None
                oi=min(i+1+hold,len(ind[t]['close'])-1); po=ind[t]['close'].iloc[oi]
                if pi is None or np.isnan(pi) or np.isnan(po): continue
                trades.append((po/pi-1)*100); le[t]=i
        if trades:
            a=np.mean(trades); st=np.std(trades) if len(trades)>1 else 1
            sh=a/st*np.sqrt(252/7) if st>0 else 0
        else: a,sh=0,0
        results.append({'w':w+1,'n':len(trades),'sh':round(sh,2),'pos':sh>0})
    pos=sum(r['pos'] for r in results)
    avg_sh=np.mean([r['sh'] for r in results if r['n']>0])
    return {'pct':round(pos/nw*100),'pos':pos,'nw':nw,
            'avg_sh':round(avg_sh,2) if not np.isnan(avg_sh) else 0,'details':results}

def mc(df, ns=2000):
    if len(df)<5: return {}
    r=df['return_pct'].values; n=len(r)
    shs=[]; mdds=[]
    for _ in range(ns):
        s=np.random.choice(r,n,replace=True)
        a=s.mean(); st=s.std()
        shs.append(a/st*np.sqrt(252/7) if st>0 else 0)
        eq=(1+s/100).cumprod(); pk=np.maximum.accumulate(eq)
        mdds.append(((eq-pk)/pk*100).min())
    return {'p_sh':round(np.mean([s>0 for s in shs])*100,1),
            'med_sh':round(np.median(shs),2),'w1_sh':round(np.percentile(shs,1),2),
            'w1_mdd':round(np.percentile(mdds,1),1),'w5_mdd':round(np.percentile(mdds,5),1)}

# ================================================================
# MAIN
# ================================================================
def main():
    print("="*80)
    print("  V7 ARCHITECTURE DECISION")
    print("  A+C vs A+B+C vs V6(A+B) — Cual es la mejor arquitectura?")
    print("="*80)

    print("\n[1] Descargando datos...")
    data = yf.download(TICKERS+['SPY'], start='2024-03-01', end='2026-04-06', progress=False)
    print(f"  {data.index[0].strftime('%Y-%m-%d')} -> {data.index[-1].strftime('%Y-%m-%d')}")

    print("[2] Calculando indicadores...")
    ind = precompute(data, TICKERS)
    print(f"  {len([t for t in TICKERS if t in ind])} tickers")

    # Define architectures
    archs = {
        'V6 (A+B)':       [(sig_a, True), (sig_b, True)],
        'A only':          [(sig_a, True)],
        'B only':          [(sig_b, True)],
        'C only':          [(sig_c, False)],
        'A+C (V7 opt1)':   [(sig_a, True), (sig_c, False)],
        'A+B+C (V7 opt2)': [(sig_a, True), (sig_b, True), (sig_c, False)],
        'B+C':             [(sig_b, True), (sig_c, False)],
    }

    # ═════════════════════════════════════════════════════════════
    # PART 1: FULL PERIOD BACKTEST
    # ═════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  PART 1: FULL PERIOD — Todas las arquitecturas")
    print("="*80)

    all_trades = {}
    print(f"\n  {'Arquitectura':20s} {'Trades':>7s} {'WR':>7s} {'Sharpe':>8s} {'Avg':>8s} "
          f"{'Total':>9s} {'MDD':>8s}")
    print(f"  {'-'*70}")

    for name, sigs in archs.items():
        df = run_bt(ind, sigs, hold=7)
        all_trades[name] = df
        m = metrics(df)
        flag = ""
        if name == 'V6 (A+B)': flag = " <-- ACTUAL"
        elif name == 'A+C (V7 opt1)': flag = " *** CANDIDATO 1"
        elif name == 'A+B+C (V7 opt2)': flag = " *** CANDIDATO 2"
        print(f"  {name:20s} {m['n']:7d} {m['wr']:6.1f}% {m['sh']:8.2f} {m['avg']:+7.2f}% "
              f"{m['tot']:+8.1f}% {m['mdd']:7.1f}%{flag}")

    # ═════════════════════════════════════════════════════════════
    # PART 2: WALK-FORWARD (5w y 7w)
    # ═════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  PART 2: WALK-FORWARD — 5 y 7 ventanas")
    print("="*80)

    key_archs = ['V6 (A+B)', 'A+C (V7 opt1)', 'A+B+C (V7 opt2)']

    for name in key_archs:
        sigs = archs[name]
        print(f"\n  --- {name} ---")
        for nw in [5, 7]:
            w = wf(ind, sigs, hold=7, nw=nw)
            status = "PASS" if w['pct']>=80 else "FAIL"
            print(f"  {nw}w: WF {w['pct']}% ({w['pos']}/{nw}) Avg Sharpe {w['avg_sh']} [{status}]")
            for d in w['details']:
                print(f"    W{d['w']}: {d['n']:3d} trades, Sharpe {d['sh']:+6.2f} "
                      f"{'OK' if d['pos'] else 'NEG'}")

    # ═════════════════════════════════════════════════════════════
    # PART 3: MONTE CARLO
    # ═════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  PART 3: MONTE CARLO (2000 sims)")
    print("="*80)

    for name in key_archs:
        df = all_trades[name]
        if df.empty: continue
        m_mc = mc(df, 2000)
        m_bt = metrics(df)
        print(f"\n  {name}:")
        print(f"    Trades: {m_bt['n']} | Sharpe: {m_bt['sh']} | Total: {m_bt['tot']}%")
        print(f"    P(Sharpe>0):     {m_mc['p_sh']}%")
        print(f"    Median Sharpe:   {m_mc['med_sh']}")
        print(f"    Worst 1% Sharpe: {m_mc['w1_sh']}")
        print(f"    Worst 1% MDD:    {m_mc['w1_mdd']}%")
        print(f"    Worst 5% MDD:    {m_mc['w5_mdd']}%")

    # ═════════════════════════════════════════════════════════════
    # PART 4: SIGNAL CONTRIBUTION — B adds or destroys value?
    # ═════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  PART 4: SIGNAL B CONTRIBUTION — Aporta o destruye valor?")
    print("="*80)

    df_b = all_trades.get('B only', pd.DataFrame())
    if not df_b.empty:
        m_b = metrics(df_b)
        print(f"\n  Signal B alone: {m_b['n']} trades | WR {m_b['wr']}% | Sharpe {m_b['sh']} | "
              f"MDD {m_b['mdd']}%")

        # B trades que estan en A+B+C pero no en A+C
        df_ac = all_trades.get('A+C (V7 opt1)', pd.DataFrame())
        df_abc = all_trades.get('A+B+C (V7 opt2)', pd.DataFrame())

        if not df_ac.empty and not df_abc.empty:
            ac_set = set(zip(df_ac['ticker'], df_ac['date'].dt.strftime('%Y-%m-%d')))
            abc_set = set(zip(df_abc['ticker'], df_abc['date'].dt.strftime('%Y-%m-%d')))
            b_unique = abc_set - ac_set

            print(f"  B contribuye {len(b_unique)} trades unicos a A+B+C")

            # Metricas de esos trades unicos de B
            if b_unique and not df_abc.empty:
                b_only_trades = df_abc[df_abc.apply(
                    lambda r: (r['ticker'], r['date'].strftime('%Y-%m-%d')) in b_unique, axis=1)]
                if not b_only_trades.empty:
                    m_b_unique = metrics(b_only_trades)
                    print(f"  Esos trades B unicos: WR {m_b_unique['wr']}% | Sharpe {m_b_unique['sh']} | "
                          f"Avg {m_b_unique['avg']:+.2f}%")
                    if m_b_unique['sh'] > 0:
                        print(f"  -> Signal B APORTA valor positivo")
                    else:
                        print(f"  -> Signal B DESTRUYE valor")

    # ═════════════════════════════════════════════════════════════
    # PART 5: HOLD PERIOD OPTIMIZATION per signal
    # ═════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  PART 5: HOLD ADAPTATIVO — A+C con diferentes holds")
    print("="*80)

    # Test A con hold X, C con hold Y
    for h_a, h_c in [(5,7), (7,7), (7,10), (10,7), (10,10), (7,14), (5,10)]:
        # Run separately and merge
        df_a = run_bt(ind, [(sig_a, True)], hold=h_a)
        df_c_only = run_bt(ind, [(sig_c, False)], hold=h_c)
        combined = pd.concat([df_a, df_c_only]).drop_duplicates(subset=['ticker','date'])
        m = metrics(combined)
        flag = " <-- ACTUAL" if h_a==7 and h_c==7 else ""
        print(f"  A={h_a:2d}d C={h_c:2d}d | Trades:{m['n']:3d} | WR:{m['wr']:5.1f}% | "
              f"Sharpe:{m['sh']:5.2f} | Total:{m['tot']:+8.1f}% | MDD:{m['mdd']:5.1f}%{flag}")

    # ═════════════════════════════════════════════════════════════
    # PART 6: OVERLAP ANALYSIS
    # ═════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  PART 6: OVERLAP — Trades compartidos entre signals")
    print("="*80)

    for pair in [('A only','B only'), ('A only','C only'), ('B only','C only')]:
        n1, n2 = pair
        df1 = all_trades.get(n1, pd.DataFrame())
        df2 = all_trades.get(n2, pd.DataFrame())
        if df1.empty or df2.empty:
            print(f"  {n1} vs {n2}: datos insuficientes")
            continue
        s1 = set(zip(df1['ticker'], df1['date'].dt.strftime('%Y-%m-%d')))
        s2 = set(zip(df2['ticker'], df2['date'].dt.strftime('%Y-%m-%d')))
        ovlp = s1 & s2
        print(f"  {n1:10s} vs {n2:10s}: {len(ovlp)} overlap "
              f"({len(ovlp)/max(len(s1|s2),1)*100:.1f}% del total)")

    # ═════════════════════════════════════════════════════════════
    # PART 7: DISTRIBUTION COMPARISON
    # ═════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  PART 7: DISTRIBUCION DE RETORNOS")
    print("="*80)

    for name in key_archs:
        df = all_trades[name]
        if df.empty: continue
        r = df['return_pct'].values
        print(f"\n  {name}: n={len(r)}")
        print(f"    Mean: {r.mean():+.2f}% | Median: {np.median(r):+.2f}% | Std: {r.std():.2f}%")
        print(f"    Min: {r.min():+.2f}% | Max: {r.max():+.2f}%")
        print(f"    Skew: {pd.Series(r).skew():.2f} | Kurt: {pd.Series(r).kurtosis():.2f}")
        # Win/loss breakdown
        wins = r[r>0]; losses = r[r<=0]
        print(f"    Wins:  n={len(wins)}, avg={wins.mean():+.2f}%" if len(wins)>0 else "    Wins: 0")
        print(f"    Losses: n={len(losses)}, avg={losses.mean():+.2f}%" if len(losses)>0 else "    Losses: 0")
        print(f"    Profit Factor: {wins.sum()/abs(losses.sum()):.2f}" if len(losses)>0 and losses.sum()!=0 else "")

    # ═════════════════════════════════════════════════════════════
    # VEREDICTO FINAL
    # ═════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  VEREDICTO FINAL — ARQUITECTURA V7")
    print("="*80)

    # Tabla comparativa final
    print(f"\n  {'':25s} {'V6 (A+B)':>12s} {'A+C':>12s} {'A+B+C':>12s}")
    print(f"  {'-'*65}")

    for name in key_archs:
        m = metrics(all_trades[name])
        w5 = wf(ind, archs[name], hold=7, nw=5)
        w7 = wf(ind, archs[name], hold=7, nw=7)
        m_mc = mc(all_trades[name], 2000) if not all_trades[name].empty else {}

        if name == key_archs[0]:
            row = 'V6 (A+B)'
        elif name == key_archs[1]:
            row = 'A+C'
        else:
            row = 'A+B+C'

    # Print final comparison
    results_final = {}
    for name in key_archs:
        m_bt = metrics(all_trades[name])
        w5 = wf(ind, archs[name], hold=7, nw=5)
        w7 = wf(ind, archs[name], hold=7, nw=7)
        m_mc = mc(all_trades[name], 2000) if not all_trades[name].empty else {}
        results_final[name] = {'m': m_bt, 'w5': w5, 'w7': w7, 'mc': m_mc}

    rows = [
        ('Trades',      lambda r: f"{r['m']['n']}"),
        ('WR',          lambda r: f"{r['m']['wr']}%"),
        ('Sharpe',      lambda r: f"{r['m']['sh']}"),
        ('Total Ret',   lambda r: f"{r['m']['tot']:+.1f}%"),
        ('MDD',         lambda r: f"{r['m']['mdd']}%"),
        ('WF 5w',       lambda r: f"{r['w5']['pct']}%"),
        ('WF 7w',       lambda r: f"{r['w7']['pct']}%"),
        ('MC P(Sh>0)',   lambda r: f"{r['mc'].get('p_sh',0)}%"),
        ('MC Med Sh',    lambda r: f"{r['mc'].get('med_sh',0)}"),
        ('MC W1% Sh',    lambda r: f"{r['mc'].get('w1_sh',0)}"),
        ('MC W1% MDD',   lambda r: f"{r['mc'].get('w1_mdd',0)}%"),
    ]

    print(f"\n  {'Metrica':20s}", end="")
    for name in key_archs:
        label = name.replace(' (V7 opt1)','').replace(' (V7 opt2)','')
        print(f" {label:>15s}", end="")
    print()
    print(f"  {'-'*70}")

    for row_name, fn in rows:
        print(f"  {row_name:20s}", end="")
        for name in key_archs:
            print(f" {fn(results_final[name]):>15s}", end="")
        print()

    # Determine winner
    print(f"""
  =====================================================================
  PROTOCOLO 6 — Convergencia 3 angulos:

  Angulo 1 (TECNICO):
    A+C:   Sharpe {results_final['A+C (V7 opt1)']['m']['sh']} > V6 {results_final['V6 (A+B)']['m']['sh']}
    A+B+C: Sharpe {results_final['A+B+C (V7 opt2)']['m']['sh']} > V6 {results_final['V6 (A+B)']['m']['sh']}
    -> Ambos superan V6. A+C tiene Sharpe mas alto que A+B+C.

  Angulo 2 (RIESGO):
    A+C MDD:   {results_final['A+C (V7 opt1)']['m']['mdd']}%
    A+B+C MDD: {results_final['A+B+C (V7 opt2)']['m']['mdd']}%
    V6 MDD:    {results_final['V6 (A+B)']['m']['mdd']}%
    -> A+C tiene mejor MDD que V6 y A+B+C.

  Angulo 3 (SIMPLICIDAD):
    A+C:   2 senales, una con 4 filtros + una con 2 filtros = 6 total
    A+B+C: 3 senales = mas complejo
    V6:    2 senales, una con 4 filtros + una con 3 filtros = 7 total
    -> A+C es mas simple que V6 y que A+B+C.

  DECISION:
  =====================================================================
""")

    # Auto-determine best
    ac = results_final['A+C (V7 opt1)']
    abc = results_final['A+B+C (V7 opt2)']
    v6 = results_final['V6 (A+B)']

    ac_score = 0; abc_score = 0
    if ac['m']['sh'] > abc['m']['sh']: ac_score += 1
    else: abc_score += 1
    if abs(ac['m']['mdd']) < abs(abc['m']['mdd']): ac_score += 1
    else: abc_score += 1
    if ac['w5']['pct'] >= abc['w5']['pct']: ac_score += 1
    else: abc_score += 1
    if ac['w7']['pct'] >= abc['w7']['pct']: ac_score += 1
    else: abc_score += 1
    if ac['mc'].get('p_sh',0) >= abc['mc'].get('p_sh',0): ac_score += 1
    else: abc_score += 1

    winner = 'A+C' if ac_score > abc_score else 'A+B+C'
    print(f"  A+C score:   {ac_score}/5")
    print(f"  A+B+C score: {abc_score}/5")
    print(f"\n  GANADOR: {winner}")
    print(f"\n  {'A+C = V7 sera Signal A (V5 mean rev) + Signal C (Crash+Volume)' if winner=='A+C' else 'A+B+C = V7 sera Triple-Signal'}")
    print(f"  Signal A: RSI<25 + MACD up + SMA<-10% + Score>30 (con SPY regime)")
    print(f"  Signal C: ROC 10d < -15% + Volume > 2x (SIN regime — contrarian)")
    print(f"  Hold: 7 dias para ambas")

if __name__ == '__main__':
    main()
