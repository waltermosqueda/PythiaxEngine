import yfinance as yf
import pandas as pd

print("=== YFINANCE REAL OPEN/CLOSE May 1-8 ===")
tickers = ['AMD', 'LMT', 'MU', 'NVDA', 'RBLX', 'QCOM', 'ARM']
df = yf.download(tickers, start='2026-04-30', end='2026-05-09', auto_adjust=False, progress=False)

print(f"Columns: {list(df.columns.get_level_values(0).unique())}")
print()
for t in tickers:
    print(f"--- {t} ---")
    try:
        sub = df[['Open','Close']].xs(t, axis=1, level=1)
        for idx, row in sub.iterrows():
            o = float(row['Open']) if pd.notna(row['Open']) else None
            c = float(row['Close']) if pd.notna(row['Close']) else None
            same = " <- OPEN=CLOSE!" if o and c and abs(o-c) < 0.01 else ""
            print(f"  {idx.date()}  open={o:.4f}  close={c:.4f}{same}")
    except Exception as e:
        print(f"  Error: {e}")
