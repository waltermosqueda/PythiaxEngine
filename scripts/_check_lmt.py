"""
Detalle completo de LMT: historial en Supabase + logs de runs intraday hoy.
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import create_engine, text
import yfinance as yf
from datetime import datetime, timezone, timedelta

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
cloud_url = None
with open(env_path, encoding="utf-8") as f:
    for line in f:
        m = re.match(r"^\s*#\s*DATABASE_URL=(postgresql\+psycopg://postgres\..*)", line)
        if m:
            cloud_url = m.group(1).strip()
            break

eng = create_engine(cloud_url, connect_args={"connect_timeout": 10})

# Primero ver columnas disponibles en prices
with eng.connect() as c:
    cols = c.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='prices' ORDER BY ordinal_position
    """)).fetchall()
print("Columnas de prices:", [r[0] for r in cols])
print()

print("=" * 60)
print("LMT — Historial completo en tabla `prices` (últimos 10 días)")
print("=" * 60)
with eng.connect() as c:
    rows = c.execute(text("""
        SELECT date::text, close
        FROM prices
        WHERE ticker = 'LMT'
        ORDER BY date DESC
        LIMIT 10
    """)).fetchall()

for r in rows:
    print(f"  fecha={r[0]}  close={float(r[1]):.4f}")

print()
print("=" * 60)
print("Columnas de predictions:")
print("=" * 60)
with eng.connect() as c:
    pcols = c.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='predictions' ORDER BY ordinal_position
    """)).fetchall()
print([r[0] for r in pcols])

print()
print("=" * 60)
print("LMT — Pick(s) abierto(s) en `predictions`")
print("=" * 60)
with eng.connect() as c:
    preds = c.execute(text("""
        SELECT p.id, p.model_name, p.ticker, p.prediction_date,
               p.target_date, p.direction, p.confidence, p.score,
               o.id AS outcome_id
        FROM predictions p
        LEFT JOIN outcomes o ON p.id = o.prediction_id
        WHERE p.ticker = 'LMT'
          AND o.id IS NULL
        ORDER BY p.prediction_date DESC
        LIMIT 5
    """)).fetchall()

for r in preds:
    print(f"  pred_id={r[0]}  model={r[1]}  pred_date={r[3]}  target={r[4]}")
    print(f"    dir={r[5]}  confidence={r[6]}  score={r[7]}  outcome=ABIERTO")

print()
print("=" * 60)
print("LMT — Yahoo Finance intraday hoy (últimos 10 ticks 1m)")
print("=" * 60)
data = yf.download("LMT", period="1d", interval="1m", progress=False, auto_adjust=False)
if not data.empty:
    # yfinance puede devolver MultiIndex si solo hay 1 ticker
    close = data["Close"]
    if hasattr(close.columns if hasattr(close, 'columns') else None, '__iter__'):
        close = close.iloc[:, 0]  # tomar primera columna si es DataFrame
    last10 = close.dropna().tail(10)
    for ts, price in last10.items():
        try:
            p = float(price)
        except Exception:
            p = float(price.iloc[0]) if hasattr(price, 'iloc') else 0
        if hasattr(ts, 'astimezone'):
            ts_ar = ts.astimezone(timezone(timedelta(hours=-3)))
            ts_str = ts_ar.strftime('%H:%M') + " AR"
        else:
            ts_str = str(ts)
        print(f"  {ts_str}  ${p:.4f}")
    try:
        yf_last = float(last10.iloc[-1])
    except Exception:
        yf_last = float(last10.iloc[-1].iloc[0])
    print()
    # Precio en supabase para hoy
    with eng.connect() as c:
        sb = c.execute(text("""
            SELECT close FROM prices
            WHERE ticker='LMT' AND date=CURRENT_DATE
        """)).fetchone()
    if sb:
        sb_price = float(sb[0])
        diff = abs(yf_last - sb_price) / yf_last * 100
        ok = "OK (<1%)" if diff < 1 else "WARN (mercado siguio moviendose)"
        print(f"  Supabase hoy:  ${sb_price:.4f}")
        print(f"  YF ultimo:     ${yf_last:.4f}")
        print(f"  Diferencia:    {diff:.2f}%  [{ok}]")
