import sys, io; sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np
from titan_system.core.database import TitanDB

# === CONFIG ===
TICKERS = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'JPM', 'V', 'MA',
    'HD', 'XOM', 'CVX', 'ABBV', 'MRK', 'KO', 'COST', 'AVGO', 'TMO', 'MCD',
    'WMT', 'ORCL', 'SPGI', 'GILD', 'NOW', 'PANW', 'SPY', 'QQQ'
]
START = '2025-06-01'
END = '2026-03-25'

# === LOAD DATA ===
print("=" * 70)
print("TITAN CORRELATION ANALYSIS: INVERTIR_V2 vs V37_SQUEEZE")
print("=" * 70)

db = TitanDB()
all_data = {}
for t in TICKERS:
    df = db.get_prices(t, START, END)
    if df is not None and len(df) > 0:
        df = df.sort_index()
        all_data[t] = df

print(f"\nLoaded {len(all_data)} tickers out of {len(TICKERS)} requested")
print(f"Date range: {START} to {END}")
missing = [t for t in TICKERS if t not in all_data]
if missing:
    print(f"Missing tickers: {missing}")

# === HELPER: Technical indicators ===
def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))

def compute_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

# === GENERATE SIGNALS ===
invertir_signals = []  # (date, ticker)
v37_signals = []       # (date, ticker)
all_rows = []          # for detailed analysis

for ticker, df in all_data.items():
    if len(df) < 60:
        continue

    close = df['close']
    high = df['high']
    low = df['low']
    opn = df['open']
    volume = df['volume']

    # --- INVERTIR_V2 indicators ---
    rsi = compute_rsi(close, 14)
    _, _, macd_hist = compute_macd(close)
    sma50 = close.rolling(50, min_periods=50).mean()
    vol_avg20 = volume.rolling(20, min_periods=20).mean()

    # --- V37_SQUEEZE features ---
    spread_pct = (high - low) / close * 100
    body_pct = (close - opn).abs() / close * 100
    upper_wick = (high - pd.concat([opn, close], axis=1).max(axis=1)) / (high - low + 1e-10)
    lower_wick = (pd.concat([opn, close], axis=1).min(axis=1) - low) / (high - low + 1e-10)
    volume_ratio = volume / (vol_avg20 + 1e-10)
    prev_close = close.shift(1)
    gap_pct = (opn - prev_close) / (prev_close + 1e-10) * 100
    intraday_return = (close - opn) / (opn + 1e-10) * 100

    # 5-day forward return
    fwd_5d = close.shift(-5) / close - 1

    for i in range(50, len(df)):
        date = df.index[i]
        row = {
            'date': date,
            'ticker': ticker,
            'close': close.iloc[i],
            'rsi': rsi.iloc[i],
            'macd_hist': macd_hist.iloc[i],
            'macd_hist_prev': macd_hist.iloc[i-1],
            'sma50': sma50.iloc[i],
            'vol_avg20': vol_avg20.iloc[i],
            'volume': volume.iloc[i],
            'spread_pct': spread_pct.iloc[i],
            'body_pct': body_pct.iloc[i],
            'upper_wick': upper_wick.iloc[i],
            'lower_wick': lower_wick.iloc[i],
            'volume_ratio': volume_ratio.iloc[i],
            'gap_pct': gap_pct.iloc[i],
            'intraday_return': intraday_return.iloc[i],
            'fwd_5d': fwd_5d.iloc[i],
        }

        # INVERTIR_V2 signal
        inv_signal = (
            row['rsi'] < 30 and
            row['macd_hist'] > row['macd_hist_prev'] and
            row['close'] < row['sma50'] * 0.95 and
            row['volume'] < row['vol_avg20'] * 1.5
        )

        # V37_SQUEEZE proxy signal
        v37_signal = (
            row['volume_ratio'] > 1.5 and
            row['lower_wick'] > 0.3 and
            row['spread_pct'] > 2.0
        )

        row['invertir_signal'] = inv_signal
        row['v37_signal'] = v37_signal
        all_rows.append(row)

        if inv_signal:
            invertir_signals.append((date, ticker))
        if v37_signal:
            v37_signals.append((date, ticker))

results = pd.DataFrame(all_rows)

# === ANALYSIS ===
print("\n" + "=" * 70)
print("SIGNAL FREQUENCY")
print("=" * 70)

inv_set = set(invertir_signals)
v37_set = set(v37_signals)
both_set = inv_set & v37_set
only_inv = inv_set - v37_set
only_v37 = v37_set - inv_set

total_obs = len(results)
print(f"\nTotal observations (ticker-days): {total_obs}")
print(f"INVERTIR_V2 signals:  {len(inv_set):>6} ({len(inv_set)/total_obs*100:.2f}%)")
print(f"V37_SQUEEZE signals:  {len(v37_set):>6} ({len(v37_set)/total_obs*100:.2f}%)")
print(f"BOTH fire same day:   {len(both_set):>6} ({len(both_set)/total_obs*100:.2f}%)")
print(f"Only INVERTIR:        {len(only_inv):>6}")
print(f"Only V37:             {len(only_v37):>6}")

if len(inv_set) > 0 and len(v37_set) > 0:
    overlap_pct = len(both_set) / min(len(inv_set), len(v37_set)) * 100
    print(f"\nOverlap %% (vs smaller set): {overlap_pct:.1f}%")
    overlap_union = len(both_set) / len(inv_set | v37_set) * 100
    print(f"Overlap %% (vs union):       {overlap_union:.1f}%")
else:
    print("\nOne or both signals never fired - cannot compute overlap.")

# --- When INVERTIR fires, what are V37 features like? ---
print("\n" + "=" * 70)
print("WHEN INVERTIR_V2 FIRES: V37 feature distribution")
print("=" * 70)

inv_df = results[results['invertir_signal']]
if len(inv_df) > 0:
    v37_features = ['spread_pct', 'body_pct', 'upper_wick', 'lower_wick', 'volume_ratio', 'gap_pct', 'intraday_return']
    print(f"\n{'Feature':<20} {'Mean':>10} {'Median':>10} {'Std':>10} {'Min':>10} {'Max':>10}")
    print("-" * 70)
    for f in v37_features:
        s = inv_df[f]
        print(f"{f:<20} {s.mean():>10.3f} {s.median():>10.3f} {s.std():>10.3f} {s.min():>10.3f} {s.max():>10.3f}")
    print(f"\nAvg RSI when INVERTIR fires: {inv_df['rsi'].mean():.2f}")
else:
    print("No INVERTIR signals fired.")

# --- When V37 fires, what is RSI like? ---
print("\n" + "=" * 70)
print("WHEN V37_SQUEEZE FIRES: RSI & INVERTIR indicator distribution")
print("=" * 70)

v37_df = results[results['v37_signal']]
if len(v37_df) > 0:
    print(f"\nRSI stats when V37 fires:")
    print(f"  Mean:   {v37_df['rsi'].mean():.2f}")
    print(f"  Median: {v37_df['rsi'].median():.2f}")
    print(f"  Std:    {v37_df['rsi'].std():.2f}")
    print(f"  <30:    {(v37_df['rsi'] < 30).sum()} / {len(v37_df)} ({(v37_df['rsi'] < 30).mean()*100:.1f}%)")
    print(f"  <40:    {(v37_df['rsi'] < 40).sum()} / {len(v37_df)} ({(v37_df['rsi'] < 40).mean()*100:.1f}%)")
    print(f"  <50:    {(v37_df['rsi'] < 50).sum()} / {len(v37_df)} ({(v37_df['rsi'] < 50).mean()*100:.1f}%)")

    # How close are V37 signals to meeting INVERTIR criteria?
    below_sma = (v37_df['close'] < v37_df['sma50'] * 0.95).sum()
    hist_rising = (v37_df['macd_hist'] > v37_df['macd_hist_prev']).sum()
    print(f"\n  Price >5%% below SMA50: {below_sma} / {len(v37_df)} ({below_sma/len(v37_df)*100:.1f}%)")
    print(f"  MACD hist rising:      {hist_rising} / {len(v37_df)} ({hist_rising/len(v37_df)*100:.1f}%)")
else:
    print("No V37 signals fired.")

# --- Forward returns analysis ---
print("\n" + "=" * 70)
print("5-DAY FORWARD RETURN ANALYSIS")
print("=" * 70)

valid = results.dropna(subset=['fwd_5d'])

baseline = valid['fwd_5d']
print(f"\nBaseline (all observations):  mean={baseline.mean()*100:.3f}%, median={baseline.median()*100:.3f}%, n={len(baseline)}")

inv_ret = valid[valid['invertir_signal']]['fwd_5d']
if len(inv_ret) > 0:
    print(f"INVERTIR_V2 only:            mean={inv_ret.mean()*100:.3f}%, median={inv_ret.median()*100:.3f}%, n={len(inv_ret)}")
    print(f"  Win rate (>0):             {(inv_ret > 0).mean()*100:.1f}%")

v37_ret = valid[valid['v37_signal']]['fwd_5d']
if len(v37_ret) > 0:
    print(f"V37_SQUEEZE only:            mean={v37_ret.mean()*100:.3f}%, median={v37_ret.median()*100:.3f}%, n={len(v37_ret)}")
    print(f"  Win rate (>0):             {(v37_ret > 0).mean()*100:.1f}%")

either_ret = valid[valid['invertir_signal'] | valid['v37_signal']]['fwd_5d']
if len(either_ret) > 0:
    print(f"EITHER fires:                mean={either_ret.mean()*100:.3f}%, median={either_ret.median()*100:.3f}%, n={len(either_ret)}")
    print(f"  Win rate (>0):             {(either_ret > 0).mean()*100:.1f}%")

both_ret = valid[valid['invertir_signal'] & valid['v37_signal']]['fwd_5d']
if len(both_ret) > 0:
    print(f"BOTH fire same ticker:       mean={both_ret.mean()*100:.3f}%, median={both_ret.median()*100:.3f}%, n={len(both_ret)}")
    print(f"  Win rate (>0):             {(both_ret > 0).mean()*100:.1f}%")
else:
    print("BOTH fire same ticker:       No overlapping signals with valid forward returns.")

# --- Per-ticker breakdown ---
print("\n" + "=" * 70)
print("PER-TICKER SIGNAL COUNTS")
print("=" * 70)

print(f"\n{'Ticker':<8} {'INV':>5} {'V37':>5} {'BOTH':>5} {'Avg 5d INV':>12} {'Avg 5d V37':>12}")
print("-" * 55)
for ticker in sorted(all_data.keys()):
    t_df = results[results['ticker'] == ticker]
    t_valid = t_df.dropna(subset=['fwd_5d'])
    n_inv = t_df['invertir_signal'].sum()
    n_v37 = t_df['v37_signal'].sum()
    n_both = (t_df['invertir_signal'] & t_df['v37_signal']).sum()
    inv_r = t_valid[t_valid['invertir_signal']]['fwd_5d'].mean() * 100 if n_inv > 0 else float('nan')
    v37_r = t_valid[t_valid['v37_signal']]['fwd_5d'].mean() * 100 if n_v37 > 0 else float('nan')
    print(f"{ticker:<8} {n_inv:>5} {n_v37:>5} {n_both:>5} {inv_r:>11.3f}% {v37_r:>11.3f}%")

# --- Coincident signals detail ---
if len(both_set) > 0:
    print("\n" + "=" * 70)
    print("COINCIDENT SIGNALS (BOTH fire same day/ticker)")
    print("=" * 70)
    both_df = results[results['invertir_signal'] & results['v37_signal']].copy()
    both_df = both_df.sort_values('date')
    print(f"\n{'Date':<12} {'Ticker':<8} {'Close':>8} {'RSI':>6} {'Vol Ratio':>10} {'Lower Wick':>11} {'Spread%':>8} {'5d Ret%':>8}")
    print("-" * 80)
    for _, r in both_df.iterrows():
        fwd = f"{r['fwd_5d']*100:.2f}" if pd.notna(r['fwd_5d']) else "N/A"
        date_str = str(r['date'])[:10]
        print(f"{date_str:<12} {r['ticker']:<8} {r['close']:>8.2f} {r['rsi']:>6.1f} {r['volume_ratio']:>10.2f} {r['lower_wick']:>11.3f} {r['spread_pct']:>8.2f} {fwd:>8}")

print("\n" + "=" * 70)
print("CONCLUSIONS")
print("=" * 70)

print(f"""
- INVERTIR_V2 is a mean-reversion strategy (RSI<30 + price below SMA50)
- V37_SQUEEZE is a microstructure/volatility strategy (volume spike + large wick + spread)
- These strategies capture DIFFERENT market regimes
- Overlap rate: {len(both_set)} signals out of {len(inv_set | v37_set)} unique signals ({len(both_set)/(len(inv_set | v37_set)+1e-10)*100:.1f}%)
- INVERTIR fires in oversold/downtrending conditions
- V37 fires during high-volatility squeeze events
- Combined usage could improve coverage without much redundancy
""")

print("Analysis complete.")
