from sqlalchemy import create_engine, text
URL = 'postgresql+psycopg://postgres.datdtnliztfzbmfbmobx:%40Supabase7786@aws-1-us-west-2.pooler.supabase.com:5432/postgres'
eng = create_engine(URL, connect_args={"connect_timeout": 20})
def q(sql):
    with eng.connect() as c: return c.execute(text(sql)).fetchall()

print("=== SCHEMA TABLA PRICES ===")
cols = q("""
    SELECT column_name, data_type, is_nullable
    FROM information_schema.columns
    WHERE table_name='prices' ORDER BY ordinal_position
""")
for col,dtype,nullable in cols:
    print(f"  {col:20}  {dtype:20}  nullable={nullable}")

print("\n=== DATOS OPEN/CLOSE May 1-8 PARA TICKERS CON ZEROS ===")
rows = q("""
    SELECT ticker, date, open, close
    FROM prices
    WHERE ticker IN ('HON','LMT','MU','NVDA','PSX','RBLX','ROKU','AMD','QCOM','COIN')
      AND date BETWEEN '2026-05-01' AND '2026-05-08'
    ORDER BY ticker, date
""")
print(f"  {'ticker':8}  {'date':12}  {'open':>12}  {'close':>12}  {'open=close':>12}")
for t,d,o,c in rows:
    same = "IDENTICOS" if o is not None and c is not None and abs(float(o)-float(c)) < 0.0001 else ""
    o_str = f"{float(o):.4f}" if o is not None else "NULL"
    c_str = f"{float(c):.4f}" if c is not None else "NULL"
    print(f"  {t:8}  {d}  {o_str:>12}  {c_str:>12}  {same}")

print("\n=== VERIFICAR: ¿entry_open=close_pred para D1 models? ===")
# Para D1 models: entry_date = prediction_date + 1 dia = target_date
# entry_open = open(target_date), target_close = close(target_date)
# Si open(target_date) == close(target_date) -> return = 0.0 EXACTO
rows2 = q("""
    SELECT DISTINCT p.ticker, p.target_date,
           pr.open AS open_tgt, pr.close AS close_tgt,
           CASE WHEN pr.open IS NOT NULL AND pr.close IS NOT NULL AND pr.open != 0
                THEN (pr.close - pr.open) / pr.open ELSE NULL END AS intraday_ret
    FROM outcomes o
    JOIN predictions p ON p.id=o.prediction_id
    LEFT JOIN prices pr ON pr.ticker=p.ticker AND pr.date=p.target_date
    WHERE o.actual_return=0.0 AND p.target_date >= '2026-05-04'
      AND p.model_name LIKE '%D1%'
    ORDER BY p.target_date, p.ticker
""")
print(f"  {'ticker':8}  {'tgt_date':12}  {'open_tgt':>12}  {'close_tgt':>12}  {'intraday_ret':>14}")
for t,d,o,c,ret in rows2:
    o_str = f"{float(o):.4f}" if o is not None else "NULL"
    c_str = f"{float(c):.4f}" if c is not None else "NULL"
    r_str = f"{float(ret):+.6f}" if ret is not None else "NULL"
    same = " <- OPEN=CLOSE!" if o is not None and c is not None and abs(float(o)-float(c))<0.001 else ""
    print(f"  {t:8}  {d}  {o_str:>12}  {c_str:>12}  {r_str:>14}{same}")

print("\n=== CONTAR NULLS EN OPEN ===")
rows3 = q("""
    SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN open IS NULL THEN 1 ELSE 0 END) AS open_nulls,
        SUM(CASE WHEN open = close THEN 1 ELSE 0 END) AS open_eq_close,
        SUM(CASE WHEN open = 0 THEN 1 ELSE 0 END) AS open_zero
    FROM prices
    WHERE date >= '2026-05-01'
""")
for total, nulls, eq, zero in rows3:
    print(f"  total={total}  open_null={nulls}  open=close={eq}  open=0={zero}")
