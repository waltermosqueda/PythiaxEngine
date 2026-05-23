"""
Compara precios en Supabase vs Yahoo Finance para tickers con picks abiertos.
Uso: py scripts/_check_precios.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from sqlalchemy import create_engine, text
import re

# Leer DATABASE_URL del .env (línea comentada)
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
cloud_url = None
with open(env_path, encoding="utf-8") as f:
    for line in f:
        m = re.match(r"^\s*#\s*DATABASE_URL=(postgresql\+psycopg://postgres\..*)", line)
        if m:
            cloud_url = m.group(1).strip()
            break

if not cloud_url:
    print("ERROR: No se encontró DATABASE_URL en .env")
    sys.exit(1)

eng = create_engine(cloud_url, connect_args={"connect_timeout": 10})
cutoff = (date.today() - timedelta(days=30)).isoformat()
today = date.today().isoformat()
yesterday = (date.today() - timedelta(days=1)).isoformat()

print(f"=== Precios en Supabase (últimos 3 días) ===")
print(f"Hoy: {today} | Ayer: {yesterday}\n")

supabase_today = {}
supabase_yesterday = {}

with eng.connect() as c:
    rows = c.execute(text("""
        SELECT p2.ticker, p2.date::text, p2.close
        FROM prices p2
        WHERE p2.ticker IN (
            SELECT DISTINCT p.ticker FROM predictions p
            LEFT JOIN outcomes o ON p.id = o.prediction_id
            WHERE o.id IS NULL
              AND p.prediction_date >= :cutoff
        )
        AND p2.date >= CURRENT_DATE - INTERVAL '3 days'
        ORDER BY p2.ticker, p2.date DESC
    """), {"cutoff": cutoff}).fetchall()

if not rows:
    print("Sin precios encontrados. ¿No hay picks abiertos?")
    sys.exit(0)

tickers = []
for r in rows:
    ticker, dt, close = r[0], r[1], float(r[2])
    date_str = str(dt)[:10]
    print(f"  {ticker:6s}  {date_str}  ${close:.4f}")
    if date_str == today:
        supabase_today[ticker] = close
        if ticker not in tickers:
            tickers.append(ticker)
    elif date_str == yesterday:
        supabase_yesterday[ticker] = close
        if ticker not in tickers:
            tickers.append(ticker)

print(f"\n=== Comparación vs Yahoo Finance (precio actual) ===")
print(f"{'Ticker':6s}  {'Supabase':>10s}  {'YFinance':>10s}  {'Diff%':>8s}  Estado")
print("-" * 60)

try:
    import yfinance as yf
    for ticker in sorted(tickers):
        try:
            data = yf.download(ticker, period="1d", interval="1m", progress=False, auto_adjust=False)
            if data.empty:
                data = yf.download(ticker, period="2d", interval="1d", progress=False, auto_adjust=False)
            if data.empty:
                print(f"  {ticker:6s}  YF sin datos")
                continue
            yf_price = float(data["Close"].iloc[-1])
            sb_price = supabase_today.get(ticker) or supabase_yesterday.get(ticker)
            if sb_price is None:
                print(f"  {ticker:6s}  {'—':>10s}  {yf_price:>10.4f}  {'—':>8s}  ⚠ sin precio en SB")
                continue
            diff_pct = abs(yf_price - sb_price) / yf_price * 100
            src = "hoy" if ticker in supabase_today else "ayer"
            if diff_pct < 1.0:
                estado = f"✅ OK ({src})"
            elif diff_pct < 5.0:
                estado = f"⚠ warn {diff_pct:.1f}% ({src})"
            else:
                estado = f"❌ DIFF {diff_pct:.1f}% ({src})"
            print(f"  {ticker:6s}  {sb_price:>10.4f}  {yf_price:>10.4f}  {diff_pct:>7.2f}%  {estado}")
        except Exception as e:
            print(f"  {ticker:6s}  ERROR YF: {e}")
except ImportError:
    print("yfinance no disponible — solo mostrando precios Supabase")
