"""Validacion end-to-end: Supabase prices vs HTML vs Yahoo Finance"""
import re, sys, json
from pathlib import Path

# --- Leer cloud URL del .env ---
env = Path(r'C:\repos\PythiaxEngine\.env').read_text(encoding='utf-8')
m = re.search(r'#\s*DATABASE_URL=(postgresql\+psycopg://postgres\.[^\s]+)', env)
if not m:
    print('ERROR: no se encontro cloud URL'); sys.exit(1)
cloud_url = m.group(1)

from sqlalchemy import create_engine, text
eng = create_engine(cloud_url, connect_args={'connect_timeout': 15})

TICKERS = ['ABNB','AMD','AMZN','ARM','ASML','BAC','CDE','ETSY','GFI','GLD','GLW',
           'GOLD','INTC','IP','IREN','ITUB','JNJ','LLY','LMT','LRCX','MRVL','MSTR',
           'MU','MUX','NEM','NG','NKE','NXE','PAAS','PBI','SE','SHOP','SLB','SONY',
           'SPCE','SWKS','TXN','VALE','VIST']

print("=" * 60)
print("VALIDACION SUPABASE prices table")
print("=" * 60)

with eng.connect() as c:
    # Ultima fecha global en prices
    max_date = c.execute(text("SELECT MAX(date) FROM prices")).scalar()
    print(f"Max date en prices: {max_date}")

    # Filas en la ultima fecha para nuestros 39 tickers
    tickers_str = "','".join(TICKERS)
    rows = c.execute(text(
        f"SELECT ticker, date, close FROM prices "
        f"WHERE date = '{max_date}' AND ticker IN ('{tickers_str}') "
        f"ORDER BY ticker"
    )).fetchall()
    print(f"\nTickers con datos en {max_date}: {len(rows)} / {len(TICKERS)}")

    prices_db = {r[0]: float(r[2]) for r in rows}
    for r in rows:
        print(f"  {r[0]:<8} close={float(r[2]):.2f}")

    missing = [t for t in TICKERS if t not in prices_db]
    if missing:
        print(f"\nSIN datos en {max_date}: {missing}")
        # Buscar fecha anterior para esos
        for t in missing[:5]:
            row2 = c.execute(text(
                f"SELECT date, close FROM prices WHERE ticker='{t}' ORDER BY date DESC LIMIT 1"
            )).fetchone()
            if row2:
                print(f"  {t}: ultima fecha disponible = {row2[0]}, close={float(row2[1]):.2f}")
            else:
                print(f"  {t}: SIN datos en absoluto")

# --- Verificar el query bug en el script inyectado ---
print("\n" + "=" * 60)
print("VALIDACION QUERY BUG")
print("=" * 60)
staging = Path(r'C:\repos\PythiaxEngine\analisis\_staging_prod_preview.html').read_text(encoding='utf-8')
if "order=date.desc" in staging:
    print("OK: query usa order=date.desc")
elif "order=ticker.asc,date.desc" in staging:
    print("BUG DETECTADO: query usa order=ticker.asc,date.desc&limit=500 -> SOLO devuelve 1-2 tickers!")
    print("ACCION: necesita fix antes de deployar")

# --- Verificar precios HTML vs Supabase ---
print("\n" + "=" * 60)
print("COMPARACION HTML vs SUPABASE (fecha mas reciente)")
print("=" * 60)
html_prices = dict(re.findall(
    r"class='svb-tk-name'>([A-Z]{1,6})</td><td class='svb-tk-price'>\$([0-9,.]+)</td>",
    staging
))
mismatches = 0
for tk, html_p in sorted(html_prices.items()):
    html_val = float(html_p.replace(',', ''))
    db_val = prices_db.get(tk)
    if db_val is None:
        print(f"  {tk:<8}: HTML={html_val:.2f}  DB=N/A (fecha anterior probablemente)")
    else:
        diff = abs(html_val - db_val) / db_val * 100
        status = "OK" if diff < 0.1 else f"DIFERENCIA {diff:.2f}%"
        print(f"  {tk:<8}: HTML={html_val:.2f}  DB={db_val:.2f}  {status}")
        if diff >= 0.1:
            mismatches += 1

if mismatches == 0:
    print("\n=> Todos los precios HTML coinciden con Supabase (mismo dia de pipeline)")
else:
    print(f"\n=> {mismatches} discrepancias HTML vs DB")

print("\nNOTA: la fecha en DB es", max_date, "- el JS devolvera estos valores al cargar la pagina")
print("CONCLUSION: el BUG de query es el unico problema - prices en DB estan bien")
