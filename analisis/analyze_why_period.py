#!/usr/bin/env python3
"""
OPCION B: Por que INVERTIR funciono en Jun2025-Mar2026 pero FALLO en Sep2024-Jun2025?
Analisis profundo de regimenes de mercado.
"""
import sys, os, io, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings("ignore")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from titan_system.core.database import TitanDB

db = TitanDB()

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

# ═══════════════════════════════════════════════════════════════════════════════
#  1. ANALISIS DE SPY/QQQ - Regimen del mercado general
# ═══════════════════════════════════════════════════════════════════════════════

print("=" * 75)
print("  1. REGIMEN DEL MERCADO GENERAL (SPY)")
print("=" * 75)

for idx_ticker in ['SPY', 'QQQ']:
    df = db.get_prices(idx_ticker, '2024-03-25', '2026-03-25')
    if df is None or len(df) == 0:
        continue
    df = df.reset_index()
    df.columns = [c.lower() for c in df.columns]
    df = df.sort_values('date')
    df['ret'] = df['close'].pct_change() * 100
    df['cumret'] = (1 + df['close'].pct_change()).cumprod()
    df['vol_20d'] = df['ret'].rolling(20).std()
    df['sma50'] = df['close'].rolling(50).mean()
    df['dist_sma50'] = (df['close'] / df['sma50'] - 1) * 100

    print(f"\n  --- {idx_ticker} ---")

    # Period 1: OOS (Sep2024 - Jun2025) - where strategy FAILED
    p1 = df[(df['date'] >= '2024-09-01') & (df['date'] <= '2025-06-01')]
    # Period 2: In-sample (Jun2025 - Mar2026) - where strategy WORKED
    p2 = df[(df['date'] >= '2025-06-01') & (df['date'] <= '2026-03-25')]

    for label, p in [("OOS Sep24-Jun25 (FALLO)", p1), ("IS Jun25-Mar26 (GANO)", p2)]:
        if len(p) < 10:
            print(f"  {label}: insufficient data")
            continue
        total_ret = (p['close'].iloc[-1] / p['close'].iloc[0] - 1) * 100
        avg_vol = p['vol_20d'].mean()
        max_dd_price = (p['close'] / p['close'].cummax() - 1).min() * 100
        avg_dist_sma50 = p['dist_sma50'].mean()
        days_below_sma50 = (p['dist_sma50'] < 0).sum()
        days_below_5pct = (p['dist_sma50'] < -5).sum()
        pct_down_days = (p['ret'] < 0).sum() / len(p) * 100
        avg_down_day = p.loc[p['ret'] < 0, 'ret'].mean() if (p['ret'] < 0).any() else 0
        avg_up_day = p.loc[p['ret'] > 0, 'ret'].mean() if (p['ret'] > 0).any() else 0
        big_drops = (p['ret'] < -2).sum()
        big_pops = (p['ret'] > 2).sum()

        print(f"\n  {label}:")
        print(f"    Return total:      {total_ret:+.1f}%")
        print(f"    Max Drawdown:      {max_dd_price:.1f}%")
        print(f"    Volatilidad 20d:   {avg_vol:.2f}%")
        print(f"    Dist promedio SMA50: {avg_dist_sma50:+.1f}%")
        print(f"    Dias bajo SMA50:   {days_below_sma50} de {len(p)} ({days_below_sma50/len(p)*100:.0f}%)")
        print(f"    Dias >5% bajo SMA50: {days_below_5pct}")
        print(f"    Dias negativos:    {pct_down_days:.0f}%")
        print(f"    Avg dia positivo:  {avg_up_day:+.2f}%")
        print(f"    Avg dia negativo:  {avg_down_day:+.2f}%")
        print(f"    Caidas >2%:        {big_drops}")
        print(f"    Subas >2%:         {big_pops}")


# ═══════════════════════════════════════════════════════════════════════════════
#  2. ANALISIS DE SENALES INVERTIR - Trade by trade en ambos periodos
# ═══════════════════════════════════════════════════════════════════════════════

print("\n\n" + "=" * 75)
print("  2. ANALISIS TRADE-BY-TRADE EN AMBOS PERIODOS")
print("=" * 75)

# Load all data
all_data = {}
for t in TICKERS_80:
    df = db.get_prices(t, '2024-03-25', '2026-03-25')
    if df is not None and len(df) > 0:
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        df = df.sort_values('date').reset_index(drop=True)
        df['date_str'] = df['date'].astype(str)
        all_data[t] = df

print(f"  Loaded {len(all_data)} tickers")

# Find all INVERTIR signals in full period
all_trades = []
dates = pd.date_range('2024-09-01', '2026-03-25', freq='B')

for date in dates:
    date_str = date.strftime('%Y-%m-%d')
    for ticker, df in all_data.items():
        mask = df['date_str'] <= date_str
        hist = df[mask].copy()
        if len(hist) < 55:
            continue

        close = hist['close']
        volume = hist['volume']
        rsi = calc_rsi(close)
        _, _, macd_hist = calc_macd(close)
        sma50 = close.rolling(50).mean()

        curr_rsi = rsi.iloc[-1]
        curr_hist = macd_hist.iloc[-1]
        prev_hist = macd_hist.iloc[-2] if len(macd_hist) > 1 else 0
        price = close.iloc[-1]
        curr_sma50 = sma50.iloc[-1]
        dist_sma50 = (price / curr_sma50 - 1) * 100
        vol_avg = volume.iloc[-20:].mean()
        vol_ratio = volume.iloc[-1] / (vol_avg + 1e-10)

        # INVERTIR_V2 signal (same as backtest: RSI<30 + MACD up + >5% below + vol<1.5)
        if curr_rsi < 30 and curr_hist > prev_hist and dist_sma50 < -5 and vol_ratio < 1.5:
            future = df[df['date_str'] > date_str].head(10)
            if len(future) < 5:
                continue

            ret_1d = (future['close'].iloc[0] / price - 1) * 100
            ret_5d = (future['close'].iloc[4] / price - 1) * 100 if len(future) >= 5 else None
            ret_10d = (future['close'].iloc[-1] / price - 1) * 100 if len(future) >= 10 else None
            max_up = (future['close'].max() / price - 1) * 100
            max_down = (future['close'].min() / price - 1) * 100

            # Get SPY context
            spy_df = all_data.get('SPY')
            spy_ret_5d = None
            if spy_df is not None:
                spy_future = spy_df[spy_df['date_str'] > date_str].head(5)
                spy_today = spy_df[spy_df['date_str'] <= date_str]
                if len(spy_future) >= 5 and len(spy_today) > 0:
                    spy_ret_5d = (spy_future['close'].iloc[4] / spy_today['close'].iloc[-1] - 1) * 100

            period = "OOS" if date < pd.Timestamp('2025-06-01') else "IS"

            all_trades.append({
                'date': date_str,
                'ticker': ticker,
                'period': period,
                'rsi': round(curr_rsi, 1),
                'dist_sma50': round(dist_sma50, 1),
                'vol_ratio': round(vol_ratio, 2),
                'ret_1d': round(ret_1d, 2),
                'ret_5d': round(ret_5d, 2) if ret_5d else None,
                'ret_10d': round(ret_10d, 2) if ret_10d else None,
                'max_up_10d': round(max_up, 2),
                'max_down_10d': round(max_down, 2),
                'spy_ret_5d': round(spy_ret_5d, 2) if spy_ret_5d else None,
            })

df_trades = pd.DataFrame(all_trades)
print(f"\n  Total signals both periods: {len(df_trades)}")

for period_label in ['OOS', 'IS']:
    sub = df_trades[df_trades['period'] == period_label]
    print(f"\n  --- Periodo: {period_label} ({len(sub)} signals) ---")
    if len(sub) == 0:
        continue

    for col in ['ret_1d', 'ret_5d', 'ret_10d']:
        vals = sub[col].dropna()
        if len(vals) == 0:
            continue
        wr = (vals > 0).mean() * 100
        avg = vals.mean()
        avg_win = vals[vals > 0].mean() if (vals > 0).any() else 0
        avg_loss = vals[vals <= 0].mean() if (vals <= 0).any() else 0
        print(f"    {col}: WR={wr:.0f}%, avg={avg:+.2f}%, avg_win={avg_win:+.2f}%, avg_loss={avg_loss:+.2f}%")

    # Max up vs max down asymmetry
    print(f"    Max up 10d: avg={sub['max_up_10d'].mean():+.2f}%, median={sub['max_up_10d'].median():+.2f}%")
    print(f"    Max down 10d: avg={sub['max_down_10d'].mean():+.2f}%, median={sub['max_down_10d'].median():+.2f}%")
    print(f"    Asymmetry (up/|down|): {sub['max_up_10d'].mean() / (abs(sub['max_down_10d'].mean()) + 0.01):.2f}x")

    # SPY context when signals fire
    spy_vals = sub['spy_ret_5d'].dropna()
    if len(spy_vals) > 0:
        print(f"    SPY next 5d when signal fires: avg={spy_vals.mean():+.2f}%, WR={( spy_vals > 0).mean()*100:.0f}%")

    # Top 5 worst trades
    worst = sub.nsmallest(5, 'ret_5d')[['date','ticker','rsi','dist_sma50','ret_5d','max_down_10d','spy_ret_5d']]
    print(f"\n    WORST 5 TRADES:")
    for _, row in worst.iterrows():
        spy_str = f"SPY:{row['spy_ret_5d']:+.1f}%" if pd.notna(row['spy_ret_5d']) else "SPY:?"
        print(f"      {row['date']} {row['ticker']:<6} RSI={row['rsi']} dist={row['dist_sma50']}% "
              f"ret5d={row['ret_5d']:+.1f}% maxDown={row['max_down_10d']:+.1f}% {spy_str}")

    # Top 5 best trades
    best = sub.nlargest(5, 'ret_5d')[['date','ticker','rsi','dist_sma50','ret_5d','max_up_10d','spy_ret_5d']]
    print(f"    BEST 5 TRADES:")
    for _, row in best.iterrows():
        spy_str = f"SPY:{row['spy_ret_5d']:+.1f}%" if pd.notna(row['spy_ret_5d']) else "SPY:?"
        print(f"      {row['date']} {row['ticker']:<6} RSI={row['rsi']} dist={row['dist_sma50']}% "
              f"ret5d={row['ret_5d']:+.1f}% maxUp={row['max_up_10d']:+.1f}% {spy_str}")


# ═══════════════════════════════════════════════════════════════════════════════
#  3. MONTHLY BREAKDOWN - When exactly did it work / fail?
# ═══════════════════════════════════════════════════════════════════════════════

print("\n\n" + "=" * 75)
print("  3. BREAKDOWN MENSUAL - Cuando funciona y cuando no")
print("=" * 75)

df_trades['month'] = df_trades['date'].str[:7]
monthly = df_trades.groupby('month').agg(
    trades=('ret_5d', 'count'),
    wr=('ret_5d', lambda x: (x.dropna() > 0).mean() * 100),
    avg_ret=('ret_5d', lambda x: x.dropna().mean()),
    spy_5d=('spy_ret_5d', lambda x: x.dropna().mean()),
).round(2)

print(f"\n  {'Mes':<10} {'Trades':>7} {'WR':>7} {'Avg Ret':>9} {'SPY 5d':>8} {'Verdict':>10}")
print("  " + "-" * 55)
for month, row in monthly.iterrows():
    verdict = "WIN" if row['avg_ret'] > 0 else "LOSE"
    marker = " <--" if abs(row['avg_ret']) > 3 else ""
    print(f"  {month:<10} {int(row['trades']):>7} {row['wr']:>6.0f}% {row['avg_ret']:>+8.2f}% "
          f"{row['spy_5d']:>+7.2f}% {verdict:>10}{marker}")


# ═══════════════════════════════════════════════════════════════════════════════
#  4. THE KEY QUESTION: What was SPY doing when INVERTIR worked vs failed?
# ═══════════════════════════════════════════════════════════════════════════════

print("\n\n" + "=" * 75)
print("  4. CORRELACION CON DIRECCION DEL MERCADO")
print("=" * 75)

for label, condition in [
    ("SPY subiendo (5d > 0)", df_trades['spy_ret_5d'] > 0),
    ("SPY cayendo (5d < 0)", df_trades['spy_ret_5d'] <= 0),
    ("SPY subiendo fuerte (5d > 1%)", df_trades['spy_ret_5d'] > 1),
    ("SPY cayendo fuerte (5d < -1%)", df_trades['spy_ret_5d'] < -1),
]:
    sub = df_trades[condition & df_trades['ret_5d'].notna()]
    if len(sub) > 3:
        wr = (sub['ret_5d'] > 0).mean() * 100
        avg = sub['ret_5d'].mean()
        print(f"\n  {label}:")
        print(f"    Signals: {len(sub)}, WR: {wr:.0f}%, Avg ret: {avg:+.2f}%")

print("\n\nANALYSIS COMPLETE")
