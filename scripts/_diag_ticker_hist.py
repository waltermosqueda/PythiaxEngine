import sys
from pathlib import Path
sys.path.insert(0, r"C:\repos\PythiaxEngine")
import yfinance as yf

print("=== TEST: yf.Ticker.history(auto_adjust=False) vs yf.download ===")
print()

tickers = ['AMD', 'MU', 'NVDA', 'LMT']
for t in tickers:
    print(f"--- {t} via Ticker.history(auto_adjust=False) ---")
    df = yf.Ticker(t).history(start='2026-04-30', end='2026-05-09', auto_adjust=False)
    print(f"  Columnas: {list(df.columns)}")
    for idx, row in df.iterrows():
        o = float(row.get('Open', 0)) if hasattr(row.get('Open'), '__float__') else row.get('Open')
        c = float(row.get('Close', 0)) if hasattr(row.get('Close'), '__float__') else row.get('Close')
        import pandas as pd
        if pd.notna(o) and pd.notna(c):
            same = " <- OPEN=CLOSE!" if abs(o - c) < 0.01 else ""
            print(f"  {idx.date()}  open={o:.4f}  close={c:.4f}{same}")
    print()

print("=== TEST: yf.Ticker.history() SIN auto_adjust (default) ===")
for t in ['AMD', 'MU']:
    print(f"--- {t} default ---")
    df = yf.Ticker(t).history(start='2026-04-30', end='2026-05-09')
    for idx, row in df.iterrows():
        o = float(row.get('Open', 0))
        c = float(row.get('Close', 0))
        same = " <- OPEN=CLOSE!" if abs(o - c) < 0.01 else ""
        print(f"  {idx.date()}  open={o:.4f}  close={c:.4f}{same}")
    print()
