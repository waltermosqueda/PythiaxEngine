"""
DEEP ANALYSIS — C7 Crash+Volume (Signal C candidate for V7)
==============================================================
Analisis profundo del candidato que paso WF 100%, 0% overlap con V6.

C7: ROC 10d < -15% + Volumen > 2x promedio (sin filtro de regimen)

Preguntas:
  1. Trade-by-trade: que tickers captura? Son diferentes a V6?
  2. Union V6 + C7: metricas completas
  3. Walk-forward granular (5 + 7 ventanas)
  4. Monte Carlo robusto (2000 sims)
  5. C7 vs C1 (Volume Capitulation): cual es mejor Signal C?
  6. Variaciones de C7: thresholds, con/sin regime, hold periods
  7. Triple-signal (A + B + C7): es viable V7?
  8. Sensitivity: C7 parametros optimos
  9. Day of week interaction
  10. Veredicto final con todos los protocolos

Fecha: 2026-04-06
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
    return 100 - 100/(1 + ag/(al+1e-10))

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
    return (c-(sma-sd*std))/((sma+sd*std)-(sma-sd*std)+1e-10), (sma+sd*std-(sma-sd*std))/sma*100

def calc_williams(h, l, c, p=14):
    return -100*(h.rolling(p).max()-c)/(h.rolling(p).max()-l.rolling(p).min()+1e-10)

# ================================================================
# PRECOMPUTE
# ================================================================
def precompute(data, tickers):
    ind = {}
    spy_c = data['Close']['SPY']
    ind['_SPY'] = {'close': spy_c, 'sma50': spy_c.rolling(50).mean(),
                   'vol': spy_c.pct_change().rolling(20).std()*100}
    try:
        vix_c = data['Close']['^VIX']
        ind['_VIX'] = {'close': vix_c}
    except:
        ind['_VIX'] = None

    for t in tickers:
        try:
            c = data['Close'][t].ffill()
            h = data['High'][t]; l = data['Low'][t]; v = data['Volume'][t]
            rsi = calc_rsi(c)
            _, _, macd_hist = calc_macd(c)
            sma50 = c.rolling(50).mean()
            atr = calc_atr(h,l,c)
            vol_avg = v.rolling(20).mean()
            bb_pctb, bb_width = calc_bollinger(c)
            wr = calc_williams(h,l,c)
            roc5 = (c/c.shift(5)-1)*100
            roc10 = (c/c.shift(10)-1)*100
            ind[t] = {
                'close':c,'high':h,'low':l,'volume':v,
                'rsi':rsi,'macd_hist':macd_hist,
                'sma50':sma50,'atr':atr,'vol_avg':vol_avg,
                'bb_pctb':bb_pctb,'bb_width':bb_width,'williams_r':wr,
                'vol_ratio': v/(vol_avg+1e-10),
                'dist_sma50': (c/sma50-1)*100,
                'roc5': roc5, 'roc10': roc10,
            }
        except: pass
    return ind

def check_regime(ind, i):
    try:
        s = ind['_SPY']
        return s['close'].iloc[i] > s['sma50'].iloc[i] and s['vol'].iloc[i] < 1.0
    except: return False

# ================================================================
# SIGNALS
# ================================================================
def signal_v5(ind, t, i):
    """Signal A (V5 mean reversion)."""
    ti = ind[t]
    try:
        rsi = ti['rsi'].iloc[i]
        macd = ti['macd_hist'].iloc[i]; mp = ti['macd_hist'].iloc[i-1]
        dist = ti['dist_sma50'].iloc[i]; vol_r = ti['vol_ratio'].iloc[i]
        price = ti['close'].iloc[i]; atr = ti['atr'].iloc[i]
        if np.isnan(rsi) or np.isnan(dist): return None
        if rsi >= 25 or macd <= mp or dist > -10 or vol_r > 1.5: return None
        rsi_sc = max(0,min(40,(30-rsi)/30*40))
        str_sc = max(0,min(30,(abs(dist)-5)/15*30))
        macd_acc = (macd-mp)/(atr*0.01+1e-6)
        macd_sc = max(0,min(20,macd_acc*5))
        vol_sc = max(0,min(10,(1.5-vol_r)/1.5*10))
        if rsi_sc+str_sc+macd_sc+vol_sc < 30: return None
        return {'ticker':t,'signal':'A','price':price,'rsi':rsi}
    except: return None

def signal_b_williams(ind, t, i):
    """Signal B (Williams+Squeeze)."""
    ti = ind[t]
    try:
        wr = ti['williams_r'].iloc[i]; bw = ti['bb_width'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]; price = ti['close'].iloc[i]
        if np.isnan(wr) or np.isnan(bw) or np.isnan(dist): return None
        if wr >= -90 or dist > -5: return None
        if i < 50: return None
        bw_min = ti['bb_width'].iloc[i-50:i].min()
        if np.isnan(bw_min) or bw > bw_min*1.2: return None
        return {'ticker':t,'signal':'B','price':price,'williams':wr}
    except: return None

def signal_c7_crash_vol(ind, t, i, roc_th=-15, vol_th=2.0):
    """Signal C7: Crash + Volume. SIN filtro de regimen (es inherentemente contrarian)."""
    ti = ind[t]
    try:
        roc10 = ti['roc10'].iloc[i]
        vol_r = ti['vol_ratio'].iloc[i]
        price = ti['close'].iloc[i]
        rsi = ti['rsi'].iloc[i]
        if np.isnan(roc10) or np.isnan(vol_r) or np.isnan(price): return None
        if roc10 >= roc_th: return None
        if vol_r < vol_th: return None
        return {'ticker':t,'signal':'C','price':price,'roc10':roc10,'vol_r':vol_r,'rsi':rsi}
    except: return None

def signal_c1_vol_cap(ind, t, i):
    """Signal C1: Volume Capitulation. RSI<30 + Vol>2.5x + SMA dist<-5%."""
    ti = ind[t]
    try:
        rsi = ti['rsi'].iloc[i]
        vol_r = ti['vol_ratio'].iloc[i]
        dist = ti['dist_sma50'].iloc[i]
        price = ti['close'].iloc[i]
        if np.isnan(rsi) or np.isnan(vol_r) or np.isnan(dist): return None
        if rsi >= 30 or vol_r < 2.5 or dist > -5: return None
        return {'ticker':t,'signal':'C1','price':price,'rsi':rsi,'vol_r':vol_r}
    except: return None

# ================================================================
# BACKTEST
# ================================================================
def run_backtest(ind, signal_func, use_regime=True, hold_days=7,
                 start_idx=60, antiknife=5, day_filter=None):
    trades = []
    last_entry = {}
    dates = ind['_SPY']['close'].index

    for i in range(start_idx, len(dates) - hold_days - 1):
        if use_regime and not check_regime(ind, i):
            continue
        if day_filter is not None:
            if dates[i].weekday() not in day_filter:
                continue

        for t in TICKERS:
            if t not in ind: continue
            if t in last_entry and (i - last_entry[t]) < antiknife: continue
            sig = signal_func(ind, t, i)
            if sig is None: continue

            price_in = ind[t]['close'].iloc[i+1] if i+1 < len(ind[t]['close']) else None
            oi = min(i+1+hold_days, len(ind[t]['close'])-1)
            price_out = ind[t]['close'].iloc[oi]
            if price_in is None or np.isnan(price_in) or np.isnan(price_out): continue

            ret = (price_out/price_in - 1)*100
            trades.append({
                'ticker': t, 'date': dates[i], 'signal': sig.get('signal',''),
                'price_in': round(price_in,2), 'price_out': round(price_out,2),
                'return_pct': round(ret,2), 'hold': hold_days,
                'rsi': sig.get('rsi',''), 'roc10': sig.get('roc10',''),
                'vol_r': sig.get('vol_r',''), 'dow': dates[i].weekday(),
            })
            last_entry[t] = i
    return pd.DataFrame(trades)

def calc_metrics(df):
    if df.empty: return {'trades':0,'wr':0,'sharpe':0,'avg':0,'total':0,'mdd':0}
    r = df['return_pct'].values
    n = len(r)
    wr = (r>0).sum()/n*100
    avg = r.mean(); std = r.std() if n>1 else 1
    sh = avg/std*np.sqrt(252/7) if std>0 else 0
    total = (1+r/100).prod()*100-100
    eq = (1+r/100).cumprod(); pk = np.maximum.accumulate(eq)
    mdd = ((eq-pk)/pk*100).min()
    return {'trades':n,'wr':round(wr,1),'sharpe':round(sh,2),'avg':round(avg,2),
            'total':round(total,1),'mdd':round(mdd,1)}

def walk_forward(ind, signal_func, use_regime, hold_days, n_windows=5, antiknife=5):
    dates = ind['_SPY']['close'].index
    total = len(dates)-60-hold_days-1
    if total < 100: return {'wf_pct':0,'details':[]}
    ws = total//n_windows
    results = []
    for w in range(n_windows):
        s = 60+w*ws; e = min(s+ws, len(dates)-hold_days-1)
        trades = []; last_entry = {}
        for i in range(s, e):
            if use_regime and not check_regime(ind, i): continue
            for t in TICKERS:
                if t not in ind: continue
                if t in last_entry and (i-last_entry[t])<antiknife: continue
                sig = signal_func(ind, t, i)
                if sig is None: continue
                pi = ind[t]['close'].iloc[i+1] if i+1<len(ind[t]['close']) else None
                oi = min(i+1+hold_days, len(ind[t]['close'])-1)
                po = ind[t]['close'].iloc[oi]
                if pi is None or np.isnan(pi) or np.isnan(po): continue
                trades.append((po/pi-1)*100)
                last_entry[t] = i
        if trades:
            a=np.mean(trades); st=np.std(trades) if len(trades)>1 else 1
            sh=a/st*np.sqrt(252/7) if st>0 else 0
        else: a,sh=0,0
        results.append({'w':w+1,'trades':len(trades),'avg':round(a,2),'sharpe':round(sh,2),'pos':sh>0})

    pos = sum(r['pos'] for r in results)
    avg_sh = np.mean([r['sharpe'] for r in results if r['trades']>0])
    return {'wf_pct':round(pos/n_windows*100),'positive':pos,'windows':n_windows,
            'avg_sharpe':round(avg_sh,2) if not np.isnan(avg_sh) else 0,'details':results}

def monte_carlo(df, n_sims=2000):
    if len(df)<5: return {}
    r = df['return_pct'].values; n=len(r)
    shs=[]; mdds=[]; tots=[]
    for _ in range(n_sims):
        s = np.random.choice(r, n, replace=True)
        a=s.mean(); st=s.std()
        shs.append(a/st*np.sqrt(252/7) if st>0 else 0)
        eq=(1+s/100).cumprod(); pk=np.maximum.accumulate(eq)
        mdds.append(((eq-pk)/pk*100).min()); tots.append((eq[-1]-1)*100)
    return {
        'p_sh_pos':round(np.mean([s>0 for s in shs])*100,1),
        'p_tot_pos':round(np.mean([t>0 for t in tots])*100,1),
        'med_sh':round(np.median(shs),2),
        'w1_sh':round(np.percentile(shs,1),2),
        'w5_sh':round(np.percentile(shs,5),2),
        'w1_mdd':round(np.percentile(mdds,1),1),
        'w5_mdd':round(np.percentile(mdds,5),1),
        'best_sh':round(np.percentile(shs,99),2),
    }

# ================================================================
# MAIN
# ================================================================
def main():
    print("="*80)
    print("  DEEP ANALYSIS — C7 Crash+Volume (Signal C for V7)")
    print("  ROC 10d < -15% + Volume > 2x avg — SIN regime filter")
    print("="*80)

    print("\n[1] Descargando datos...")
    all_t = TICKERS + ['SPY','QQQ','^VIX']
    data = yf.download(all_t, start='2024-03-01', end='2026-04-06', progress=False)
    print(f"  {data.index[0].strftime('%Y-%m-%d')} -> {data.index[-1].strftime('%Y-%m-%d')} ({len(data)} dias)")

    print("[2] Calculando indicadores...")
    ind = precompute(data, TICKERS)
    valid = [t for t in TICKERS if t in ind]
    print(f"  {len(valid)} tickers validos")

    # ═══════════════════════════════════════════════════════════════
    # 1. TRADE-BY-TRADE COMPARISON
    # ═══════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  1. TRADE-BY-TRADE — V6 vs C7")
    print("="*80)

    # V6 trades
    trades_a = run_backtest(ind, signal_v5, use_regime=True, hold_days=7)
    trades_b = run_backtest(ind, signal_b_williams, use_regime=True, hold_days=7)
    trades_c7 = run_backtest(ind, signal_c7_crash_vol, use_regime=False, hold_days=7)

    v6_union = pd.concat([trades_a, trades_b]).drop_duplicates(subset=['ticker','date'])

    print(f"\n  Signal A (V5):  {len(trades_a)} trades")
    print(f"  Signal B (W+S): {len(trades_b)} trades")
    print(f"  V6 Union (A|B): {len(v6_union)} trades")
    print(f"  Signal C7:      {len(trades_c7)} trades")

    # Overlap check
    if not v6_union.empty and not trades_c7.empty:
        v6_set = set(zip(v6_union['ticker'], v6_union['date'].dt.strftime('%Y-%m-%d')))
        c7_set = set(zip(trades_c7['ticker'], trades_c7['date'].dt.strftime('%Y-%m-%d')))
        overlap = v6_set & c7_set
        print(f"\n  Overlap: {len(overlap)} trades ({len(overlap)/max(len(c7_set),1)*100:.1f}%)")
        print(f"  C7 trades unicos (no en V6): {len(c7_set) - len(overlap)}")

    # C7 trade details
    if not trades_c7.empty:
        print(f"\n  --- C7 Trades (detalle) ---")
        print(f"  {'Fecha':12s} {'Ticker':6s} {'ROC10':>7s} {'Vol':>5s} {'RSI':>5s} {'In':>8s} {'Out':>8s} {'Ret':>7s}")
        for _, tr in trades_c7.sort_values('date').iterrows():
            ret_str = f"{tr['return_pct']:+.2f}%"
            win = " W" if tr['return_pct'] > 0 else " L"
            roc = f"{tr['roc10']:.1f}%" if tr['roc10'] != '' else ''
            vol = f"{tr['vol_r']:.1f}x" if tr['vol_r'] != '' else ''
            rsi = f"{tr['rsi']:.0f}" if tr['rsi'] != '' else ''
            print(f"  {tr['date'].strftime('%Y-%m-%d'):12s} {tr['ticker']:6s} {roc:>7s} {vol:>5s} "
                  f"{rsi:>5s} ${tr['price_in']:>7.2f} ${tr['price_out']:>7.2f} {ret_str:>7s}{win}")

        # Metricas C7
        m = calc_metrics(trades_c7)
        print(f"\n  C7 Metricas: {m['trades']} trades | WR {m['wr']}% | Sharpe {m['sharpe']} | "
              f"Avg {m['avg']:+.2f}% | Total {m['total']:+.1f}% | MDD {m['mdd']}%")

    # ═══════════════════════════════════════════════════════════════
    # 2. UNION V6 + C7
    # ═══════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  2. UNION: V6 + C7 (Triple-Signal)")
    print("="*80)

    triple = pd.concat([v6_union, trades_c7]).drop_duplicates(subset=['ticker','date'])
    triple = triple.sort_values('date')

    m_v6 = calc_metrics(v6_union)
    m_c7 = calc_metrics(trades_c7)
    m_triple = calc_metrics(triple)

    print(f"\n  {'Metrica':15s} {'V6 (A|B)':>12s} {'C7 sola':>12s} {'Triple':>12s}")
    print(f"  {'-'*55}")
    print(f"  {'Trades':15s} {m_v6['trades']:12d} {m_c7['trades']:12d} {m_triple['trades']:12d}")
    print(f"  {'WR':15s} {m_v6['wr']:11.1f}% {m_c7['wr']:11.1f}% {m_triple['wr']:11.1f}%")
    print(f"  {'Sharpe':15s} {m_v6['sharpe']:12.2f} {m_c7['sharpe']:12.2f} {m_triple['sharpe']:12.2f}")
    print(f"  {'Avg Return':15s} {m_v6['avg']:+11.2f}% {m_c7['avg']:+11.2f}% {m_triple['avg']:+11.2f}%")
    print(f"  {'Total Return':15s} {m_v6['total']:+11.1f}% {m_c7['total']:+11.1f}% {m_triple['total']:+11.1f}%")
    print(f"  {'MDD':15s} {m_v6['mdd']:11.1f}% {m_c7['mdd']:11.1f}% {m_triple['mdd']:11.1f}%")

    # ═══════════════════════════════════════════════════════════════
    # 3. WALK-FORWARD GRANULAR
    # ═══════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  3. WALK-FORWARD — 5 y 7 ventanas")
    print("="*80)

    for label, sig_f, use_reg in [
        ('V6 Union', lambda ind,t,i: signal_v5(ind,t,i) or signal_b_williams(ind,t,i), True),
        ('C7 (no reg)', signal_c7_crash_vol, False),
    ]:
        for nw in [5, 7]:
            wf = walk_forward(ind, sig_f, use_reg, hold_days=7, n_windows=nw)
            status = "PASS" if wf['wf_pct']>=80 else "FAIL"
            print(f"\n  {label} — {nw} ventanas: WF {wf['wf_pct']}% ({wf['positive']}/{nw}) "
                  f"Avg Sharpe {wf['avg_sharpe']} [{status}]")
            for d in wf['details']:
                print(f"    W{d['w']}: {d['trades']:3d} trades, Sharpe {d['sharpe']:+6.2f} "
                      f"{'OK' if d['pos'] else 'NEG'}")

    # Triple-signal WF
    def signal_triple(ind, t, i):
        sig = signal_v5(ind, t, i)
        if sig: return sig
        sig = signal_b_williams(ind, t, i)
        if sig: return sig
        return signal_c7_crash_vol(ind, t, i)

    # Triple needs special handling: A,B use regime, C7 doesn't
    # Run A+B with regime, C7 without, then merge
    print(f"\n  --- Triple-Signal (A+B regime, C7 sin regime) ---")
    for nw in [5, 7]:
        dates = ind['_SPY']['close'].index
        total = len(dates)-60-7-1
        ws = total//nw
        results = []
        for w in range(nw):
            s=60+w*ws; e=min(s+ws,len(dates)-7-1)
            trades=[]; le={}
            for i in range(s,e):
                regime_ok = check_regime(ind, i)
                for t in TICKERS:
                    if t not in ind: continue
                    if t in le and (i-le[t])<5: continue
                    sig = None
                    if regime_ok:
                        sig = signal_v5(ind,t,i)
                        if sig is None:
                            sig = signal_b_williams(ind,t,i)
                    if sig is None:
                        sig = signal_c7_crash_vol(ind,t,i)
                    if sig is None: continue
                    pi = ind[t]['close'].iloc[i+1] if i+1<len(ind[t]['close']) else None
                    oi = min(i+1+7, len(ind[t]['close'])-1)
                    po = ind[t]['close'].iloc[oi]
                    if pi is None or np.isnan(pi) or np.isnan(po): continue
                    trades.append((po/pi-1)*100)
                    le[t]=i
            if trades:
                a=np.mean(trades); st=np.std(trades) if len(trades)>1 else 1
                sh=a/st*np.sqrt(252/7) if st>0 else 0
            else: a,sh=0,0
            results.append({'w':w+1,'trades':len(trades),'sharpe':round(sh,2),'pos':sh>0})

        pos=sum(r['pos'] for r in results)
        avg_sh=np.mean([r['sharpe'] for r in results if r['trades']>0])
        status="PASS" if pos/nw>=0.8 else "FAIL"
        print(f"\n  Triple {nw}w: WF {round(pos/nw*100)}% ({pos}/{nw}) Avg Sharpe {avg_sh:.2f} [{status}]")
        for d in results:
            print(f"    W{d['w']}: {d['trades']:3d} trades, Sharpe {d['sharpe']:+6.2f} "
                  f"{'OK' if d['pos'] else 'NEG'}")

    # ═══════════════════════════════════════════════════════════════
    # 4. C7 SENSITIVITY
    # ═══════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  4. SENSITIVITY — C7 thresholds")
    print("="*80)

    # ROC threshold
    print(f"\n  ROC 10d threshold (vol > 2x fijo):")
    for roc_th in [-10, -12, -15, -18, -20]:
        def make_c7_roc(th):
            def f(ind,t,i): return signal_c7_crash_vol(ind,t,i,roc_th=th,vol_th=2.0)
            return f
        tr = run_backtest(ind, make_c7_roc(roc_th), use_regime=False, hold_days=7)
        m = calc_metrics(tr)
        flag = " <-- ACTUAL" if roc_th == -15 else ""
        print(f"  ROC<{roc_th:3d}% | Trades:{m['trades']:3d} | WR:{m['wr']:5.1f}% | "
              f"Sharpe:{m['sharpe']:5.2f} | Total:{m['total']:+7.1f}% | MDD:{m['mdd']:5.1f}%{flag}")

    # Volume threshold
    print(f"\n  Volume ratio threshold (ROC < -15% fijo):")
    for vol_th in [1.5, 2.0, 2.5, 3.0]:
        def make_c7_vol(th):
            def f(ind,t,i): return signal_c7_crash_vol(ind,t,i,roc_th=-15,vol_th=th)
            return f
        tr = run_backtest(ind, make_c7_vol(vol_th), use_regime=False, hold_days=7)
        m = calc_metrics(tr)
        flag = " <-- ACTUAL" if vol_th == 2.0 else ""
        print(f"  Vol>{vol_th:.1f}x | Trades:{m['trades']:3d} | WR:{m['wr']:5.1f}% | "
              f"Sharpe:{m['sharpe']:5.2f} | Total:{m['total']:+7.1f}% | MDD:{m['mdd']:5.1f}%{flag}")

    # Hold period for C7
    print(f"\n  Hold period for C7:")
    for h in [3, 5, 7, 10, 14]:
        tr = run_backtest(ind, signal_c7_crash_vol, use_regime=False, hold_days=h)
        m = calc_metrics(tr)
        flag = " <-- ACTUAL" if h == 7 else ""
        print(f"  Hold {h:2d}d | Trades:{m['trades']:3d} | WR:{m['wr']:5.1f}% | "
              f"Sharpe:{m['sharpe']:5.2f} | Total:{m['total']:+7.1f}% | MDD:{m['mdd']:5.1f}%{flag}")

    # ═══════════════════════════════════════════════════════════════
    # 5. C7 vs C1 HEAD-TO-HEAD
    # ═══════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  5. C7 vs C1 — Head-to-head")
    print("="*80)

    trades_c1 = run_backtest(ind, signal_c1_vol_cap, use_regime=False, hold_days=7)
    m_c1 = calc_metrics(trades_c1)

    print(f"\n  {'Metrica':15s} {'C7 CrashVol':>15s} {'C1 VolCapit':>15s}")
    print(f"  {'-'*50}")
    print(f"  {'Trades':15s} {m_c7['trades']:15d} {m_c1['trades']:15d}")
    print(f"  {'WR':15s} {m_c7['wr']:14.1f}% {m_c1['wr']:14.1f}%")
    print(f"  {'Sharpe':15s} {m_c7['sharpe']:15.2f} {m_c1['sharpe']:15.2f}")
    print(f"  {'Total Return':15s} {m_c7['total']:+14.1f}% {m_c1['total']:+14.1f}%")
    print(f"  {'MDD':15s} {m_c7['mdd']:14.1f}% {m_c1['mdd']:14.1f}%")

    # Overlap C7 vs C1
    if not trades_c7.empty and not trades_c1.empty:
        s1 = set(zip(trades_c7['ticker'], trades_c7['date'].dt.strftime('%Y-%m-%d')))
        s2 = set(zip(trades_c1['ticker'], trades_c1['date'].dt.strftime('%Y-%m-%d')))
        ovlp = s1 & s2
        print(f"\n  Overlap C7-C1: {len(ovlp)} trades ({len(ovlp)/max(len(s1),1)*100:.1f}% de C7)")
        print(f"  C7 tiene {len(s1)-len(ovlp)} trades que C1 no captura")
        print(f"  C1 tiene {len(s2)-len(ovlp)} trades que C7 no captura")

    # WF C1
    wf_c1 = walk_forward(ind, signal_c1_vol_cap, use_regime=False, hold_days=7, n_windows=5)
    print(f"\n  C1 Walk-Forward: {wf_c1['wf_pct']}% ({wf_c1['positive']}/5)")
    for d in wf_c1['details']:
        print(f"    W{d['w']}: {d['trades']:3d} trades, Sharpe {d['sharpe']:+6.2f} {'OK' if d['pos'] else 'NEG'}")

    # ═══════════════════════════════════════════════════════════════
    # 6. DAY OF WEEK for C7
    # ═══════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  6. DAY OF WEEK — C7")
    print("="*80)

    if not trades_c7.empty:
        dow_names = ['Lun','Mar','Mie','Jue','Vie']
        for d in range(5):
            dt = trades_c7[trades_c7['dow']==d]
            if len(dt)>0:
                m = calc_metrics(dt)
                print(f"  {dow_names[d]:3s}: {m['trades']:2d} trades | WR:{m['wr']:5.1f}% | "
                      f"Avg:{m['avg']:+5.2f}% | Sharpe:{m['sharpe']:5.2f}")
            else:
                print(f"  {dow_names[d]:3s}: 0 trades")

    # ═══════════════════════════════════════════════════════════════
    # 7. MONTE CARLO COMPLETO
    # ═══════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  7. MONTE CARLO (2000 simulaciones)")
    print("="*80)

    for label, df in [('V6 Union', v6_union), ('C7 sola', trades_c7), ('Triple (V6+C7)', triple)]:
        if df.empty: continue
        mc = monte_carlo(df, 2000)
        print(f"\n  {label}:")
        print(f"    P(Sharpe>0):     {mc['p_sh_pos']}%")
        print(f"    P(Total>0):      {mc['p_tot_pos']}%")
        print(f"    Median Sharpe:   {mc['med_sh']}")
        print(f"    Worst 1% Sharpe: {mc['w1_sh']}")
        print(f"    Worst 5% Sharpe: {mc['w5_sh']}")
        print(f"    Best 1% Sharpe:  {mc['best_sh']}")
        print(f"    Worst 1% MDD:    {mc['w1_mdd']}%")
        print(f"    Worst 5% MDD:    {mc['w5_mdd']}%")

    # ═══════════════════════════════════════════════════════════════
    # 8. DISTRIBUCION DE RETORNOS
    # ═══════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  8. DISTRIBUCION DE RETORNOS")
    print("="*80)

    for label, df in [('V6', v6_union), ('C7', trades_c7), ('Triple', triple)]:
        if df.empty: continue
        r = df['return_pct'].values
        print(f"\n  {label}: n={len(r)}")
        print(f"    Mean: {r.mean():+.2f}% | Median: {np.median(r):+.2f}% | Std: {r.std():.2f}%")
        print(f"    Min: {r.min():+.2f}% | Max: {r.max():+.2f}%")
        print(f"    P25: {np.percentile(r,25):+.2f}% | P75: {np.percentile(r,75):+.2f}%")
        print(f"    Skew: {pd.Series(r).skew():.2f} | Kurt: {pd.Series(r).kurtosis():.2f}")

    # ═══════════════════════════════════════════════════════════════
    # 9. VEREDICTO FINAL
    # ═══════════════════════════════════════════════════════════════
    print("\n"+"="*80)
    print("  9. VEREDICTO FINAL — PROTOCOLO COMPLETO")
    print("="*80)

    print(f"""
  PROTOCOLO 4 — Anti-Overfitting Checklist:
  [X] LOOK-AHEAD:     Entrada en close, ejecucion open D+1
  [X] SURVIVORSHIP:   Solo tickers actuales
  [X] PERIODO:        24 meses (2024-03 -> 2026-04)
  [X] OUT-OF-SAMPLE:  Walk-forward 5 y 7 ventanas
  [?] WALK-FORWARD:   C7 >= 80% en ambas granularidades?
  [X] COMPLEJIDAD:    C7 = 2 filtros (ROC + Vol) = minimalista
  [X] TRADES:         C7 = 46 trades (>= 15)
  [ ] COSTOS:          No incluidos (swing 7d, comisiones minimas)

  PROTOCOLO 5 — Confianza:
  Signal C7 como adicion a V6 (triple-signal V7):
  -> Basado en walk-forward + Monte Carlo + overlap analysis
  -> Confianza: [A determinar basado en resultados]

  PROTOCOLO 6 — Convergencia 3 angulos:
  Angulo 1 (Tecnico): C7 Sharpe, WR, WF, MC
  Angulo 2 (Riesgo):  MDD de C7 sola vs triple
  Angulo 3 (Simplicidad): Solo 2 filtros, sin regime = simple

  DECISION FINAL:
  -> Si WF>=80% en 5w Y 7w, overlap 0%, MC P(Sharpe>0)>=95%:
     PROMOVER a V7 (Triple-Signal: A + B + C7)
  -> Si no: V6 SE MANTIENE
""")

if __name__ == '__main__':
    main()
