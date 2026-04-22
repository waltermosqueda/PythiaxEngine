"""
INVESTIGACION V8 — EJES ORTOGONALES DE INFORMACION
=====================================================
Los 12 indicadores previos eran variantes de osciladores Close-price.
Aqui testeamos informacion GENUINAMENTE NUEVA:

1. SECTOR DISLOCATION — stock vs sector ETF (relativo vs absoluto)
2. CLOSE LOCATION VALUE (CLV) — estructura intrabar (H-L-C)
3. GAP ANALYSIS — overnight vs intraday (Open price, nunca usado)
4. RETURN AUTOCORRELATION — regimen mean-reverting del stock
5. RANGE COMPRESSION — inside bars / narrow range

Cada eje usa datos que nuestros filtros actuales NO tocan:
- V7 actual usa: Close (RSI, SMA, MACD, ROC), Volume, SPY regime
- Nuevo: Sector spreads, Open price, H-L range patterns, autocorrelation

Pipeline: backtest -> WF 5w+7w -> overlap V7 -> MC -> veredicto

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

# ================================================================
# UNIVERSO + SECTOR MAPPING
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

SECTOR_ETFS = ['XLK','XLF','XLV','XLE','XLI','XLP','XLC','XLY']

SECTOR_MAP = {
    # Tech
    'AAPL':'XLK','MSFT':'XLK','GOOGL':'XLC','AMZN':'XLY','META':'XLC',
    'NVDA':'XLK','AMD':'XLK','TSLA':'XLY','NFLX':'XLC','CRM':'XLK',
    'ORCL':'XLK','ADBE':'XLK','INTC':'XLK','AVGO':'XLK','QCOM':'XLK',
    'MU':'XLK','AMAT':'XLK','LRCX':'XLK','TXN':'XLK','PLTR':'XLK',
    # Financials
    'JPM':'XLF','BAC':'XLF','WFC':'XLF','GS':'XLF','V':'XLF',
    'MA':'XLF','AXP':'XLF','C':'XLF','PYPL':'XLF','COIN':'XLF',
    # Healthcare
    'JNJ':'XLV','PFE':'XLV','UNH':'XLV','MRK':'XLV','ABBV':'XLV',
    'LLY':'XLV','TMO':'XLV','ABT':'XLV','BMY':'XLV','AMGN':'XLV',
    # Energy
    'XOM':'XLE','CVX':'XLE','COP':'XLE','SLB':'XLE','OXY':'XLE',
    'HAL':'XLE','DVN':'XLE','MPC':'XLE','VLO':'XLE','EOG':'XLE',
    # Consumer Staples
    'KO':'XLP','PEP':'XLP','PG':'XLP','WMT':'XLP','COST':'XLP',
    'MCD':'XLY','NKE':'XLY','SBUX':'XLY','TGT':'XLY','HD':'XLY',
    # Industrials
    'CAT':'XLI','BA':'XLI','GE':'XLI','RTX':'XLI','HON':'XLI',
    'LMT':'XLI','UPS':'XLI','FDX':'XLI','DE':'XLI','MMM':'XLI',
}

# ================================================================
# INDICADORES BASE
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

# ================================================================
# PRECOMPUTE — incluye nuevos ejes
# ================================================================
def precompute(data, tickers):
    ind = {}

    # SPY
    spy_c = data['Close']['SPY']
    ind['_SPY'] = {'close':spy_c,'sma50':spy_c.rolling(50).mean(),
                   'vol':spy_c.pct_change().rolling(20).std()*100}

    # Sector ETFs
    for etf in SECTOR_ETFS:
        try:
            ec = data['Close'][etf]
            ind[f'_ETF_{etf}'] = {'close': ec, 'ret20': ec.pct_change(20)*100}
        except:
            pass

    for t in tickers:
        try:
            c=data['Close'][t].ffill(); h=data['High'][t]; l=data['Low'][t]
            v=data['Volume'][t]; o=data['Open'][t]
            if c.isna().sum() > len(c)*0.3: continue

            rsi=calc_rsi(c); _,_,mh=calc_macd(c); s50=c.rolling(50).mean()
            atr=calc_atr(h,l,c); va=v.rolling(20).mean()

            # === EJE 1: Sector Dislocation ===
            sector_etf = SECTOR_MAP.get(t)
            sector_spread = pd.Series(np.nan, index=c.index)
            if sector_etf and f'_ETF_{sector_etf}' in ind:
                stock_ret20 = c.pct_change(20) * 100
                etf_ret20 = ind[f'_ETF_{sector_etf}']['ret20']
                sector_spread = stock_ret20 - etf_ret20

            # === EJE 2: CLV (Close Location Value) ===
            clv = (c - l) / (h - l + 1e-10)
            clv_3d = clv.rolling(3).mean()

            # === EJE 3: Gap Analysis ===
            gap = (o / c.shift(1) - 1) * 100      # overnight gap %
            intraday = (c / o - 1) * 100           # intraday move %
            gap_fill = (gap < -1) & (intraday > 0) # gap down pero recover

            # === EJE 4: Autocorrelation ===
            rets = c.pct_change()
            autocorr = rets.rolling(20, min_periods=15).apply(
                lambda x: x.autocorr(lag=1) if len(x)>=15 else np.nan, raw=False)

            # === EJE 5: Range Compression ===
            daily_range = h - l
            atr_val = atr
            range_ratio = daily_range / (atr_val + 1e-10)
            inside_bar = (h < h.shift(1)) & (l > l.shift(1))
            nr7 = daily_range == daily_range.rolling(7).min()

            ind[t] = {
                'close':c,'high':h,'low':l,'open':o,'volume':v,
                'rsi':rsi,'macd_hist':mh,'sma50':s50,'atr':atr,'vol_avg':va,
                'vol_ratio':v/(va+1e-10),'dist_sma50':(c/s50-1)*100,
                'roc10':(c/c.shift(10)-1)*100,
                # Nuevos ejes
                'sector_spread':sector_spread,
                'clv':clv,'clv_3d':clv_3d,
                'gap':gap,'intraday':intraday,'gap_fill':gap_fill,
                'autocorr':autocorr,
                'range_ratio':range_ratio,'inside_bar':inside_bar,'nr7':nr7,
            }
        except: pass
    return ind

def regime(ind,i):
    try:
        s=ind['_SPY']
        return s['close'].iloc[i]>s['sma50'].iloc[i] and s['vol'].iloc[i]<1.0
    except: return False

# ================================================================
# V7 SIGNALS (reference)
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

def sig_c(ind,t,i):
    ti=ind[t]
    try:
        roc=ti['roc10'].iloc[i]; vr=ti['vol_ratio'].iloc[i]; p=ti['close'].iloc[i]
        if np.isnan(roc) or np.isnan(vr): return None
        if roc>=-15 or vr<2.0: return None
        return {'signal':'C','price':p}
    except: return None

# ================================================================
# NUEVAS SENALES — EJES ORTOGONALES
# ================================================================

def sig_d1_sector_dislocation(ind, t, i):
    """Stock underperforms su sector por >10% en 20d + RSI<35."""
    ti = ind[t]
    try:
        spread = ti['sector_spread'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(spread) or np.isnan(rsi): return None
        if spread >= -10: return None  # Stock underperforma sector por 10%+
        if rsi >= 35: return None
        return {'signal':'D1_SectorDis','price':price,'spread':spread,'rsi':rsi}
    except: return None

def sig_d1b_sector_extreme(ind, t, i):
    """Stock underperforms sector por >15% + RSI<30 (mas estricto)."""
    ti = ind[t]
    try:
        spread = ti['sector_spread'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(spread) or np.isnan(rsi): return None
        if spread >= -15: return None
        if rsi >= 30: return None
        return {'signal':'D1b_SectExtr','price':price,'spread':spread,'rsi':rsi}
    except: return None

def sig_d2_clv_accumulation(ind, t, i):
    """CLV shift: 3d avg era <0.3 (sellers), ahora >0.6 (buyers) + RSI<40."""
    ti = ind[t]
    try:
        clv = ti['clv'].iloc[i]
        clv_prev = ti['clv_3d'].iloc[i-1] if i > 0 else 0.5
        rsi = ti['rsi'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(clv) or np.isnan(clv_prev) or np.isnan(rsi): return None
        if clv_prev >= 0.3: return None   # Ayer sellers dominaban
        if clv < 0.6: return None          # Hoy buyers dominan
        if rsi >= 40: return None          # Oversold zone
        if dist > 0: return None           # Debajo SMA
        return {'signal':'D2_CLV','price':price,'clv':clv,'rsi':rsi}
    except: return None

def sig_d2b_clv_strict(ind, t, i):
    """CLV shift + RSI<30 + debajo SMA50 > 5% (mas estricto)."""
    ti = ind[t]
    try:
        clv = ti['clv'].iloc[i]
        clv_prev = ti['clv_3d'].iloc[i-1] if i > 0 else 0.5
        rsi = ti['rsi'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(clv) or np.isnan(clv_prev) or np.isnan(rsi): return None
        if clv_prev >= 0.25: return None
        if clv < 0.65: return None
        if rsi >= 30: return None
        if dist > -5: return None
        return {'signal':'D2b_CLVstr','price':price,'clv':clv,'rsi':rsi}
    except: return None

def sig_d3_gap_recovery(ind, t, i):
    """Gap down > 3% + intraday recovery > 1% en ultimos 3 dias + RSI<40."""
    ti = ind[t]
    try:
        rsi = ti['rsi'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(rsi): return None
        if rsi >= 40: return None
        if dist > 0: return None

        # Buscar gap-fill en ultimos 3 dias
        gap_fills = 0
        for j in range(max(0,i-2), i+1):
            try:
                g = ti['gap'].iloc[j]
                intra = ti['intraday'].iloc[j]
                if not np.isnan(g) and not np.isnan(intra):
                    if g < -2 and intra > 0.5:
                        gap_fills += 1
            except: pass

        if gap_fills < 1: return None  # Al menos 1 gap-fill
        return {'signal':'D3_GapRecov','price':price,'rsi':rsi,'gap_fills':gap_fills}
    except: return None

def sig_d3b_gap_strict(ind, t, i):
    """Gap down > 4% con recovery intraday > 2% + RSI<35."""
    ti = ind[t]
    try:
        rsi = ti['rsi'].iloc[i]
        price = ti['close'].iloc[i]
        gap = ti['gap'].iloc[i]
        intra = ti['intraday'].iloc[i]
        if np.isnan(rsi) or np.isnan(gap) or np.isnan(intra): return None
        if gap >= -4: return None      # Gap down fuerte
        if intra < 2: return None      # Recovery intraday fuerte
        if rsi >= 35: return None
        return {'signal':'D3b_GapStr','price':price,'gap':gap,'intra':intra,'rsi':rsi}
    except: return None

def sig_d4_autocorr_mean_rev(ind, t, i):
    """Autocorrelacion negativa (<-0.15) + RSI<30 + debajo SMA."""
    ti = ind[t]
    try:
        ac = ti['autocorr'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(ac) or np.isnan(rsi) or np.isnan(dist): return None
        if ac >= -0.15: return None     # Stock en regimen mean-reverting
        if rsi >= 30: return None
        if dist > -5: return None
        return {'signal':'D4_AutoCorr','price':price,'autocorr':ac,'rsi':rsi}
    except: return None

def sig_d4b_autocorr_extreme(ind, t, i):
    """Autocorrelacion muy negativa + RSI<25."""
    ti = ind[t]
    try:
        ac = ti['autocorr'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(ac) or np.isnan(rsi) or np.isnan(dist): return None
        if ac >= -0.25: return None
        if rsi >= 25: return None
        if dist > -8: return None
        return {'signal':'D4b_ACextr','price':price,'autocorr':ac,'rsi':rsi}
    except: return None

def sig_d5_range_compression(ind, t, i):
    """Inside bar o NR7 + RSI<35 + debajo SMA = selling exhaustion."""
    ti = ind[t]
    try:
        ib = ti['inside_bar'].iloc[i]
        nr = ti['nr7'].iloc[i]
        rr = ti['range_ratio'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(rsi) or np.isnan(dist): return None
        if not (ib or nr): return None  # Requiere inside bar o NR7
        if rsi >= 35: return None
        if dist > -3: return None
        return {'signal':'D5_RangeComp','price':price,'rsi':rsi,'inside':bool(ib),'nr7':bool(nr)}
    except: return None

def sig_d5b_range_strict(ind, t, i):
    """Range ratio < 0.5 (rango < mitad del ATR) + RSI<30."""
    ti = ind[t]
    try:
        rr = ti['range_ratio'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(rr) or np.isnan(rsi): return None
        if rr >= 0.5: return None       # Rango comprimido
        if rsi >= 30: return None
        if dist > -5: return None
        return {'signal':'D5b_RgStrict','price':price,'range_r':rr,'rsi':rsi}
    except: return None

# ================================================================
# BACKTEST ENGINE
# ================================================================
def run_bt(ind, sig_func, use_regime=True, hold=7, start=60, ak=5):
    trades=[]; le={}; dates=ind['_SPY']['close'].index
    for i in range(start, len(dates)-hold-1):
        if use_regime and not regime(ind,i): continue
        for t in TICKERS:
            if t not in ind: continue
            if t in le and (i-le[t])<ak: continue
            sig = sig_func(ind,t,i)
            if sig is None: continue
            pi=ind[t]['close'].iloc[i+1] if i+1<len(ind[t]['close']) else None
            oi=min(i+1+hold,len(ind[t]['close'])-1); po=ind[t]['close'].iloc[oi]
            if pi is None or np.isnan(pi) or np.isnan(po): continue
            trades.append({'ticker':t,'date':dates[i],'signal':sig.get('signal',''),
                          'price_in':pi,'price_out':po,'return_pct':(po/pi-1)*100})
            le[t]=i
    return pd.DataFrame(trades)

def metrics(df):
    if df.empty: return {'n':0,'wr':0,'sh':0,'avg':0,'tot':0,'mdd':0,'pf':0}
    r=df['return_pct'].values; n=len(r)
    wr=(r>0).sum()/n*100; avg=r.mean(); std=r.std() if n>1 else 1
    sh=avg/std*np.sqrt(252/7) if std>0 else 0
    tot=(1+r/100).prod()*100-100
    eq=(1+r/100).cumprod(); pk=np.maximum.accumulate(eq)
    mdd=((eq-pk)/pk*100).min()
    w=r[r>0]; lo=r[r<=0]
    pf=w.sum()/abs(lo.sum()) if len(lo)>0 and lo.sum()!=0 else 99
    return {'n':n,'wr':round(wr,1),'sh':round(sh,2),'avg':round(avg,2),
            'tot':round(tot,1),'mdd':round(mdd,1),'pf':round(pf,2)}

def walk_forward(ind, sig_func, use_regime, hold=7, nw=5, ak=5):
    dates=ind['_SPY']['close'].index; tot=len(dates)-60-hold-1
    if tot<100: return {'pct':0,'details':[]}
    ws=tot//nw; results=[]
    for w in range(nw):
        s=60+w*ws; e=min(s+ws,len(dates)-hold-1)
        trades=[]; le={}
        for i in range(s,e):
            if use_regime and not regime(ind,i): continue
            for t in TICKERS:
                if t not in ind: continue
                if t in le and (i-le[t])<ak: continue
                sig=sig_func(ind,t,i)
                if sig is None: continue
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

def monte_carlo(df, ns=2000):
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
            'w1_mdd':round(np.percentile(mdds,1),1)}

# ================================================================
# MAIN
# ================================================================
def main():
    print("="*80)
    print("  INVESTIGACION V8 — EJES ORTOGONALES DE INFORMACION")
    print("  5 dimensiones que V7 NO toca: Sector, CLV, Gap, AutoCorr, Range")
    print("="*80)

    # Download
    print("\n[1] Descargando datos (tickers + sector ETFs + SPY)...")
    all_t = TICKERS + SECTOR_ETFS + ['SPY']
    data = yf.download(all_t, start='2024-03-01', end='2026-04-06', progress=False)
    print(f"  {data.index[0].strftime('%Y-%m-%d')} -> {data.index[-1].strftime('%Y-%m-%d')}")

    # Precompute
    print("[2] Calculando indicadores (base + 5 ejes nuevos)...")
    ind = precompute(data, TICKERS)
    valid = [t for t in TICKERS if t in ind]
    etfs_ok = [e for e in SECTOR_ETFS if f'_ETF_{e}' in ind]
    print(f"  {len(valid)} tickers, {len(etfs_ok)} sector ETFs")

    # ════════════════════════════════════════════════════════════
    # PARTE 1: BACKTEST TODAS LAS ESTRATEGIAS
    # ════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  PARTE 1: BACKTEST — V7 ref + 10 nuevas senales")
    print("="*80)

    strategies = {
        # V7 reference
        'V7_A (MeanRev)':  (sig_a, True),
        'V7_C (CrashVol)': (sig_c, False),
        # Eje 1: Sector
        'D1_SectorDis':     (sig_d1_sector_dislocation, True),
        'D1b_SectExtr':     (sig_d1b_sector_extreme, True),
        # Eje 2: CLV
        'D2_CLV':           (sig_d2_clv_accumulation, True),
        'D2b_CLVstrict':    (sig_d2b_clv_strict, True),
        # Eje 3: Gap
        'D3_GapRecov':      (sig_d3_gap_recovery, True),
        'D3b_GapStrict':    (sig_d3b_gap_strict, True),
        # Eje 4: Autocorrelation
        'D4_AutoCorr':      (sig_d4_autocorr_mean_rev, True),
        'D4b_ACextreme':    (sig_d4b_autocorr_extreme, True),
        # Eje 5: Range
        'D5_RangeComp':     (sig_d5_range_compression, True),
        'D5b_RangeStrict':  (sig_d5b_range_strict, True),
    }

    # Test with AND without regime
    all_results = {}
    all_trades = {}

    print(f"\n  {'Nombre':20s} {'Regime':>6s} {'Trades':>7s} {'WR':>7s} {'Sharpe':>8s} "
          f"{'Avg':>8s} {'Total':>9s} {'MDD':>8s} {'PF':>6s}")
    print(f"  {'-'*85}")

    for name, (sf, default_reg) in strategies.items():
        # Con regime default
        df = run_bt(ind, sf, use_regime=default_reg, hold=7)
        m = metrics(df)
        all_results[name] = m
        all_trades[name] = df
        flag = " ***" if m['sh'] > 2 and m['n'] >= 10 else ""
        print(f"  {name:20s} {'Yes' if default_reg else 'No':>6s} {m['n']:7d} {m['wr']:6.1f}% "
              f"{m['sh']:8.2f} {m['avg']:+7.2f}% {m['tot']:+8.1f}% {m['mdd']:7.1f}% {m['pf']:5.2f}{flag}")

    # Sin regime para las nuevas
    print(f"\n  --- Sin regime (contrarian mode) ---\n")
    for name, (sf, _) in strategies.items():
        if name.startswith('V7_'): continue
        key = f'{name}_NR'
        df = run_bt(ind, sf, use_regime=False, hold=7)
        m = metrics(df)
        all_results[key] = m
        all_trades[key] = df
        flag = " ***" if m['sh'] > 2 and m['n'] >= 10 else ""
        print(f"  {key:20s} {'No':>6s} {m['n']:7d} {m['wr']:6.1f}% "
              f"{m['sh']:8.2f} {m['avg']:+7.2f}% {m['tot']:+8.1f}% {m['mdd']:7.1f}% {m['pf']:5.2f}{flag}")

    # ════════════════════════════════════════════════════════════
    # PARTE 2: WALK-FORWARD de todo lo que tiene Sharpe > 0 y trades >= 5
    # ════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  PARTE 2: WALK-FORWARD (5w + 7w)")
    print("="*80)

    wf_candidates = [(n,m) for n,m in all_results.items()
                     if m['sh']>0 and m['n']>=5]
    wf_candidates.sort(key=lambda x: x[1]['sh'], reverse=True)

    wf_results = {}
    for name, m in wf_candidates[:15]:
        # Find signal func
        base_name = name.replace('_NR','')
        if base_name in strategies:
            sf, _ = strategies[base_name]
        else:
            continue
        use_reg = not name.endswith('_NR')
        if base_name == 'V7_C (CrashVol)': use_reg = False

        print(f"\n  {name} (Sharpe {m['sh']}, {m['n']} trades):")
        for nw in [5, 7]:
            w = walk_forward(ind, sf, use_reg, hold=7, nw=nw)
            wf_results[f'{name}_{nw}w'] = w
            status = "PASS" if w['pct']>=80 else "FAIL"
            print(f"    {nw}w: WF {w['pct']}% ({w['pos']}/{nw}) Avg Sharpe {w['avg_sh']} [{status}]")
            for d in w['details']:
                print(f"      W{d['w']}: {d['n']:3d} trades, Sharpe {d['sh']:+6.2f} "
                      f"{'OK' if d['pos'] else 'NEG'}")

    # ════════════════════════════════════════════════════════════
    # PARTE 3: OVERLAP con V7
    # ════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  PARTE 3: OVERLAP con V7 (A+C)")
    print("="*80)

    v7_a = all_trades.get('V7_A (MeanRev)', pd.DataFrame())
    v7_c = all_trades.get('V7_C (CrashVol)', pd.DataFrame())
    v7_union = pd.concat([v7_a, v7_c]).drop_duplicates(subset=['ticker','date'])
    v7_set = set()
    if not v7_union.empty:
        v7_set = set(zip(v7_union['ticker'], v7_union['date'].dt.strftime('%Y-%m-%d')))

    print(f"\n  V7 (A+C) tiene {len(v7_set)} trades unicos\n")

    for name in all_results:
        if name.startswith('V7_'): continue
        df = all_trades.get(name, pd.DataFrame())
        if df.empty: continue
        s = set(zip(df['ticker'], df['date'].dt.strftime('%Y-%m-%d')))
        ovlp = len(v7_set & s)
        ovlp_pct = ovlp/len(s)*100 if s else 0
        m = all_results[name]
        flag = " *** NEW" if ovlp_pct < 30 and m['sh'] > 1.5 and m['n'] >= 8 else ""
        print(f"  {name:20s} | {len(s):3d} trades | Overlap: {ovlp:2d} ({ovlp_pct:4.1f}%) | "
              f"Unique: {len(s)-ovlp:3d} | Sharpe:{m['sh']:5.2f}{flag}")

    # ════════════════════════════════════════════════════════════
    # PARTE 4: UNION V7 + mejores candidatos
    # ════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  PARTE 4: UNION V7 + mejores candidatos")
    print("="*80)

    # Filtrar candidatos que pasaron WF >= 60% en 5w
    good_candidates = []
    for name in all_results:
        if name.startswith('V7_'): continue
        wf5_key = f'{name}_5w'
        if wf5_key in wf_results and wf_results[wf5_key]['pct'] >= 60:
            good_candidates.append(name)

    if good_candidates:
        print(f"\n  Candidatos con WF 5w >= 60%: {len(good_candidates)}\n")
        for name in good_candidates:
            df = all_trades[name]
            if df.empty: continue
            union = pd.concat([v7_union, df]).drop_duplicates(subset=['ticker','date'])
            m_union = metrics(union)
            m_v7 = metrics(v7_union)
            delta_sh = m_union['sh'] - m_v7['sh']
            delta_mdd = m_union['mdd'] - m_v7['mdd']
            print(f"  V7+{name:20s} | Trades:{m_union['n']:3d} | Sharpe:{m_union['sh']:5.2f} "
                  f"({delta_sh:+.2f}) | MDD:{m_union['mdd']:5.1f}% ({delta_mdd:+.1f}%) | "
                  f"PF:{m_union['pf']:4.2f}")
    else:
        print("\n  Ningun candidato paso WF 5w >= 60%.")

    # ════════════════════════════════════════════════════════════
    # PARTE 5: MC de V7 vs mejor union
    # ════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  PARTE 5: MONTE CARLO")
    print("="*80)

    mc_v7 = monte_carlo(v7_union, 2000) if not v7_union.empty else {}
    print(f"\n  V7 (A+C): {metrics(v7_union)['n']} trades")
    if mc_v7:
        print(f"    P(Sharpe>0): {mc_v7['p_sh']}% | Median: {mc_v7['med_sh']} | "
              f"W1%: {mc_v7['w1_sh']} | W1% MDD: {mc_v7['w1_mdd']}%")

    if good_candidates:
        for name in good_candidates[:3]:
            df = all_trades[name]
            union = pd.concat([v7_union, df]).drop_duplicates(subset=['ticker','date'])
            m_mc = monte_carlo(union, 2000)
            m_bt = metrics(union)
            if m_mc:
                print(f"\n  V7+{name}: {m_bt['n']} trades, Sharpe {m_bt['sh']}")
                print(f"    P(Sharpe>0): {m_mc['p_sh']}% | Median: {m_mc['med_sh']} | "
                      f"W1%: {m_mc['w1_sh']} | W1% MDD: {m_mc['w1_mdd']}%")

    # ════════════════════════════════════════════════════════════
    # VEREDICTO
    # ════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  VEREDICTO FINAL")
    print("="*80)

    print(f"""
  Resumen de ejes ortogonales:

  Eje 1 (Sector Dislocation): [resultado de WF arriba]
  Eje 2 (CLV Accumulation):   [resultado de WF arriba]
  Eje 3 (Gap Recovery):       [resultado de WF arriba]
  Eje 4 (Autocorrelation):    [resultado de WF arriba]
  Eje 5 (Range Compression):  [resultado de WF arriba]

  Si algun eje paso WF >= 80% con overlap < 30% y Sharpe > 2:
  -> Candidato para V8 (Signal D)
  -> Requiere deep analysis antes de implementar

  Si ninguno paso:
  -> V7 (A+C) se confirma como optimo con datos actuales
  -> Los ejes ortogonales no tienen edge suficiente como senales independientes
  -> PERO pueden tener valor como FILTROS de refinamiento sobre A o C
""")

if __name__ == '__main__':
    main()
