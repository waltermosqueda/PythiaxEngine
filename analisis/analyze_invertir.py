#!/usr/bin/env python3
"""
Deep analysis of INVERTIR strategy - understand WHY it works before improving it.
"""
import sys, os, io, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from titan_system.core.database import TitanDB

TICKERS_80 = [
    'AAPL','MSFT','GOOGL','AMZN','NVDA','META','TSLA','BRK-B','UNH','JNJ',
    'JPM','V','PG','MA','HD','XOM','CVX','ABBV','MRK','KO',
    'PEP','COST','AVGO','TMO','MCD','WMT','CSCO','ABT','DHR','ACN',
    'NEE','LIN','TXN','UNP','PM','ORCL','RTX','HON','LOW','SPGI',
    'AMGN','ELV','ISRG','SYK','MDLZ','BLK','ADI','GILD','PLD','ADP',
    'VRTX','REGN','CI','LRCX','DUK','SO','CME','ZTS','NOW','PANW',
    'CL','ICE','MCK','PSA','SHW','MPC','AZO','AIG','WM','USB',
    'COP','EOG','SLB','GS','MS','SCHW','C','BAC','SPY','QQQ',
]

def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period-1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period-1, adjust=False).mean()
    rs = gain / (loss + 1e-10)
    return 100 - 100 / (1 + rs)

def calc_macd(close):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sig = macd.ewm(span=9, adjust=False).mean()
    return macd, sig, macd - sig

db = TitanDB()
all_data = {}
for t in TICKERS_80:
    df = db.get_prices(t, '2025-01-01', '2026-03-25')
    if df is not None and len(df) > 0:
        df = df.reset_index()  # date index → column
        df.columns = [c.capitalize() if c != 'adj_close' else 'Adj_close' for c in df.columns]
        df = df.rename(columns={'Date': 'date'})
        df['date'] = df['date'].astype(str)
        df = df.sort_values('date').reset_index(drop=True)
        all_data[t] = df

print(f"Loaded {len(all_data)} tickers")

# Simulate day by day - capture every signal and its outcome
trades = []
dates = pd.date_range('2025-06-01', '2026-03-25', freq='B')

for i, date in enumerate(dates):
    date_str = date.strftime('%Y-%m-%d')

    for ticker, df in all_data.items():
        mask = df['date'] <= date_str
        hist = df[mask].copy()
        if len(hist) < 35:
            continue

        close = hist['Close']
        volume = hist['Volume'] if 'Volume' in hist.columns else None
        rsi = calc_rsi(close)
        macd_line, sig_line, macd_hist = calc_macd(close)

        current_rsi = rsi.iloc[-1]
        current_hist = macd_hist.iloc[-1]
        prev_hist = macd_hist.iloc[-2]

        # Original signal
        if current_rsi < 30 and current_hist > prev_hist:
            entry_price = close.iloc[-1]

            # Look ahead: what happened next 1, 3, 5, 10 days?
            future = df[df['date'] > date_str].head(10)
            if len(future) == 0:
                continue

            ret_1d = (future['Close'].iloc[0] / entry_price - 1) * 100 if len(future) >= 1 else None
            ret_3d = (future['Close'].iloc[2] / entry_price - 1) * 100 if len(future) >= 3 else None
            ret_5d = (future['Close'].iloc[4] / entry_price - 1) * 100 if len(future) >= 5 else None
            ret_10d = (future['Close'].iloc[-1] / entry_price - 1) * 100 if len(future) >= 10 else None
            max_up = (future['Close'].max() / entry_price - 1) * 100
            max_down = (future['Close'].min() / entry_price - 1) * 100

            # Additional context at signal time
            sma50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else None
            sma20 = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else None
            dist_sma50 = (entry_price / sma50 - 1) * 100 if sma50 else None

            vol_ratio = None
            if volume is not None and len(volume) >= 20:
                avg_vol = volume.iloc[-20:].mean()
                if avg_vol > 0:
                    vol_ratio = volume.iloc[-1] / avg_vol

            # RSI velocity
            rsi_prev = rsi.iloc[-2]
            rsi_turning_up = current_rsi > rsi_prev

            # MACD acceleration
            macd_accel = current_hist - prev_hist

            # How many days RSI has been < 30?
            days_oversold = 0
            for j in range(len(rsi)-1, -1, -1):
                if rsi.iloc[j] < 30:
                    days_oversold += 1
                else:
                    break

            # Bollinger Band position
            bb_mid = close.rolling(20).mean().iloc[-1]
            bb_std = close.rolling(20).std().iloc[-1]
            bb_lower = bb_mid - 2 * bb_std
            below_bb = entry_price < bb_lower

            trades.append({
                'date': date_str,
                'ticker': ticker,
                'entry_price': round(entry_price, 2),
                'rsi': round(current_rsi, 2),
                'macd_hist': round(current_hist, 4),
                'macd_accel': round(macd_accel, 4),
                'rsi_turning_up': rsi_turning_up,
                'days_oversold': days_oversold,
                'vol_ratio': round(vol_ratio, 2) if vol_ratio else None,
                'dist_sma50': round(dist_sma50, 2) if dist_sma50 else None,
                'below_bb': below_bb,
                'ret_1d': round(ret_1d, 2) if ret_1d else None,
                'ret_3d': round(ret_3d, 2) if ret_3d else None,
                'ret_5d': round(ret_5d, 2) if ret_5d else None,
                'ret_10d': round(ret_10d, 2) if ret_10d else None,
                'max_up_10d': round(max_up, 2),
                'max_down_10d': round(max_down, 2),
            })

df_trades = pd.DataFrame(trades)
print(f"\nTotal signals: {len(df_trades)}")
print(f"Date range: {df_trades['date'].min()} to {df_trades['date'].max()}")

print("\n" + "="*70)
print("  OVERALL STATISTICS")
print("="*70)
for horizon in ['ret_1d', 'ret_3d', 'ret_5d', 'ret_10d']:
    col = df_trades[horizon].dropna()
    wins = (col > 0).sum()
    total = len(col)
    print(f"\n  {horizon.upper()}:")
    print(f"    Trades: {total}, Wins: {wins} ({wins/total*100:.1f}%)")
    print(f"    Mean: {col.mean():+.2f}%, Median: {col.median():+.2f}%")
    print(f"    Avg Win: {col[col>0].mean():+.2f}%, Avg Loss: {col[col<=0].mean():+.2f}%")
    print(f"    Best: {col.max():+.2f}%, Worst: {col.min():+.2f}%")

print(f"\n  MAX UPSIDE (10d): mean={df_trades['max_up_10d'].mean():+.2f}%, median={df_trades['max_up_10d'].median():+.2f}%")
print(f"  MAX DOWNSIDE (10d): mean={df_trades['max_down_10d'].mean():+.2f}%, median={df_trades['max_down_10d'].median():+.2f}%")

# ── ANALYZE WHAT MAKES A GOOD SIGNAL ──
print("\n" + "="*70)
print("  WHAT MAKES A WINNING SIGNAL?")
print("="*70)

# By RSI depth
print("\n  BY RSI DEPTH (using ret_5d):")
for low, high, label in [(0,15,"RSI 0-15 (extreme)"), (15,22,"RSI 15-22 (very low)"), (22,27,"RSI 22-27 (low)"), (27,30,"RSI 27-30 (mild)")]:
    sub = df_trades[(df_trades['rsi'] >= low) & (df_trades['rsi'] < high)]
    if len(sub) > 0:
        wr = (sub['ret_5d'].dropna() > 0).mean() * 100
        avg = sub['ret_5d'].dropna().mean()
        print(f"    {label}: n={len(sub)}, WR={wr:.0f}%, avg_ret={avg:+.2f}%")

# By volume
print("\n  BY VOLUME RATIO (using ret_5d):")
for low, high, label in [(0,0.8,"Low vol (<0.8x)"), (0.8,1.2,"Normal vol (0.8-1.2x)"), (1.2,2.0,"High vol (1.2-2x)"), (2.0,100,"Very high vol (>2x)")]:
    sub = df_trades[(df_trades['vol_ratio'] >= low) & (df_trades['vol_ratio'] < high)]
    if len(sub) > 0:
        wr = (sub['ret_5d'].dropna() > 0).mean() * 100
        avg = sub['ret_5d'].dropna().mean()
        print(f"    {label}: n={len(sub)}, WR={wr:.0f}%, avg_ret={avg:+.2f}%")

# By RSI turning up
print("\n  BY RSI DIRECTION (using ret_5d):")
for val, label in [(True, "RSI turning UP"), (False, "RSI still falling")]:
    sub = df_trades[df_trades['rsi_turning_up'] == val]
    if len(sub) > 0:
        wr = (sub['ret_5d'].dropna() > 0).mean() * 100
        avg = sub['ret_5d'].dropna().mean()
        print(f"    {label}: n={len(sub)}, WR={wr:.0f}%, avg_ret={avg:+.2f}%")

# By days oversold
print("\n  BY DAYS OVERSOLD (using ret_5d):")
for low, high, label in [(1,2,"Fresh (1 day)"), (2,4,"2-3 days"), (4,7,"4-6 days"), (7,100,"7+ days (chronic)")]:
    sub = df_trades[(df_trades['days_oversold'] >= low) & (df_trades['days_oversold'] < high)]
    if len(sub) > 0:
        wr = (sub['ret_5d'].dropna() > 0).mean() * 100
        avg = sub['ret_5d'].dropna().mean()
        print(f"    {label}: n={len(sub)}, WR={wr:.0f}%, avg_ret={avg:+.2f}%")

# By distance from SMA50
print("\n  BY DISTANCE FROM SMA50 (using ret_5d):")
for low, high, label in [(-100,-10,"Very stretched (>10% below)"), (-10,-5,"Stretched (5-10% below)"), (-5,0,"Slightly below"), (0,100,"Above SMA50")]:
    sub = df_trades[(df_trades['dist_sma50'] >= low) & (df_trades['dist_sma50'] < high)]
    if len(sub) > 0:
        wr = (sub['ret_5d'].dropna() > 0).mean() * 100
        avg = sub['ret_5d'].dropna().mean()
        print(f"    {label}: n={len(sub)}, WR={wr:.0f}%, avg_ret={avg:+.2f}%")

# By Bollinger Band
print("\n  BY BOLLINGER BAND (using ret_5d):")
for val, label in [(True, "Below lower BB"), (False, "Above lower BB")]:
    sub = df_trades[df_trades['below_bb'] == val]
    if len(sub) > 0:
        wr = (sub['ret_5d'].dropna() > 0).mean() * 100
        avg = sub['ret_5d'].dropna().mean()
        print(f"    {label}: n={len(sub)}, WR={wr:.0f}%, avg_ret={avg:+.2f}%")

# COMBINED: best filter combos
print("\n" + "="*70)
print("  BEST FILTER COMBINATIONS (ret_5d)")
print("="*70)

combos = [
    ("Original (RSI<30 + MACD up)", df_trades),
    ("+ RSI turning up", df_trades[df_trades['rsi_turning_up'] == True]),
    ("+ Below BB", df_trades[df_trades['below_bb'] == True]),
    ("+ High volume (>1.2x)", df_trades[df_trades['vol_ratio'] >= 1.2] if df_trades['vol_ratio'].notna().any() else pd.DataFrame()),
    ("+ RSI < 25", df_trades[df_trades['rsi'] < 25]),
    ("+ Fresh oversold (1-3d)", df_trades[df_trades['days_oversold'] <= 3]),
    ("RSI<25 + RSI up + vol>1.0", df_trades[(df_trades['rsi']<25) & (df_trades['rsi_turning_up']==True) & (df_trades['vol_ratio']>=1.0)]),
    ("RSI<25 + below BB", df_trades[(df_trades['rsi']<25) & (df_trades['below_bb']==True)]),
    ("Fresh(<=3d) + RSI up + vol>1.0", df_trades[(df_trades['days_oversold']<=3) & (df_trades['rsi_turning_up']==True) & (df_trades['vol_ratio']>=1.0)]),
]

for label, sub in combos:
    if len(sub) > 0:
        col = sub['ret_5d'].dropna()
        if len(col) > 0:
            wr = (col > 0).mean() * 100
            avg = col.mean()
            med = col.median()
            print(f"\n  {label}:")
            print(f"    Signals: {len(sub)}, WR: {wr:.0f}%, Mean: {avg:+.2f}%, Median: {med:+.2f}%")

# Top winners and losers
print("\n" + "="*70)
print("  TOP 10 BEST TRADES (by ret_5d)")
print("="*70)
top = df_trades.nlargest(10, 'ret_5d')[['date','ticker','rsi','vol_ratio','dist_sma50','days_oversold','ret_1d','ret_5d','ret_10d']]
print(top.to_string(index=False))

print("\n" + "="*70)
print("  TOP 10 WORST TRADES (by ret_5d)")
print("="*70)
bot = df_trades.nsmallest(10, 'ret_5d')[['date','ticker','rsi','vol_ratio','dist_sma50','days_oversold','ret_1d','ret_5d','ret_10d']]
print(bot.to_string(index=False))

print("\nANALYSIS COMPLETE")
