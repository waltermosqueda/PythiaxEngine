from sqlalchemy import create_engine, text
URL = 'postgresql+psycopg://postgres.datdtnliztfzbmfbmobx:%40Supabase7786@aws-1-us-west-2.pooler.supabase.com:5432/postgres'
eng = create_engine(URL, connect_args={"connect_timeout": 20})
def q(sql):
    with eng.connect() as c: return c.execute(text(sql)).fetchall()

print("=== FETCHED_AT PARA TICKERS CON ZEROS (May 4-8) ===")
rows = q("""
    SELECT ticker, date, open, close,
           fetched_at AT TIME ZONE 'UTC' AS fetched_utc,
           fetched_at AT TIME ZONE 'America/Argentina/Buenos_Aires' AS fetched_ar
    FROM prices
    WHERE ticker IN ('AMD','LMT','MU','NVDA','RBLX','QCOM','ARM','HON','PSX','COIN')
      AND date BETWEEN '2026-05-04' AND '2026-05-08'
    ORDER BY ticker, date
""")
print(f"  {'ticker':8}  {'date':12}  {'open':>10}  {'close':>10}  {'fetched_utc':25}  open=close")
for t,d,o,c,fut,far in rows:
    same = " IDENTICOS" if o and c and abs(float(o)-float(c)) < 0.001 else ""
    o_str = f"{float(o):.4f}" if o else "-"
    c_str = f"{float(c):.4f}" if c else "-"
    fut_str = str(fut)[:22] if fut else "-"
    print(f"  {t:8}  {d}  {o_str:>10}  {c_str:>10}  {fut_str:25}{same}")

print("\n=== FETCHED_AT PARA May 1 (precios CORRECTOS) ===")
rows2 = q("""
    SELECT ticker, date, open, close,
           fetched_at AT TIME ZONE 'UTC' AS fetched_utc
    FROM prices
    WHERE ticker IN ('AMD','LMT','MU','NVDA','RBLX')
      AND date = '2026-05-01'
    ORDER BY ticker
""")
for t,d,o,c,fut in rows2:
    o_str = f"{float(o):.4f}" if o else "-"
    c_str = f"{float(c):.4f}" if c else "-"
    fut_str = str(fut)[:22] if fut else "-"
    print(f"  {t:8}  {d}  open={o_str}  close={c_str}  fetched={fut_str}")

print("\n=== RANGO DE fetched_at PARA PRECIOS RECIENTES ===")
rows3 = q("""
    SELECT 
        date,
        MIN(fetched_at AT TIME ZONE 'UTC') AS earliest,
        MAX(fetched_at AT TIME ZONE 'UTC') AS latest,
        COUNT(*) AS n
    FROM prices
    WHERE date >= '2026-05-01'
    GROUP BY date ORDER BY date
""")
print(f"  {'date':12}  {'earliest_utc':25}  {'latest_utc':25}  {'n':>5}")
for d,e,l,n in rows3:
    print(f"  {d}  {str(e)[:22]:25}  {str(l)[:22]:25}  {n:>5}")
