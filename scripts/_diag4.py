from sqlalchemy import create_engine, text
URL = 'postgresql+psycopg://postgres.datdtnliztfzbmfbmobx:%40Supabase7786@aws-1-us-west-2.pooler.supabase.com:5432/postgres'
eng = create_engine(URL, connect_args={"connect_timeout": 20})
def q(sql):
    with eng.connect() as c: return c.execute(text(sql)).fetchall()

# --- WINRATE POR MODELO ---
print("=== WINRATE POR MODELO ===")
rows6 = q("""
    SELECT p.model_name, COUNT(*) total,
           ROUND(AVG(o.hit::numeric)*100,2) wr,
           ROUND(AVG(o.actual_return::numeric)*100,4) avg_ret,
           SUM(CASE WHEN o.actual_return=0.0 THEN 1 ELSE 0 END) ceros
    FROM outcomes o JOIN predictions p ON p.id=o.prediction_id
    GROUP BY p.model_name ORDER BY total DESC
""")
print(f"  {'modelo':45}  {'tot':>5}  {'WR%':>7}  {'avgRet%':>8}  {'ceros':>6}")
for m, tot, wr, avg, c in rows6:
    fl = ""
    if wr and (wr > 90 or wr < 10): fl += " WR_EXT"
    if avg and abs(avg) > 5: fl += " RET_GRANDE"
    if c > tot * 0.3: fl += " MUCHOS_CEROS"
    print(f"  {m[:45]:45}  {tot:>5}  {float(wr):>7.2f}  {float(avg):>8.4f}  {c:>6}{fl}")

# --- PRECIOS EN DB PARA ZEROS MAY 4-8 ---
print("\n=== PRECIOS EN DB PARA ZEROS MAY 4-8 ===")
rows7 = q("""
    SELECT DISTINCT p.ticker, p.prediction_date, p.target_date,
           pr1.close AS close_pred, pr2.close AS close_tgt
    FROM outcomes o
    JOIN predictions p ON p.id=o.prediction_id
    LEFT JOIN prices pr1 ON pr1.ticker=p.ticker AND pr1.date=p.prediction_date
    LEFT JOIN prices pr2 ON pr2.ticker=p.ticker AND pr2.date=p.target_date
    WHERE o.actual_return=0.0 AND p.target_date >= '2026-05-04'
    ORDER BY p.target_date, p.ticker
    LIMIT 50
""")
print(f"  {'ticker':8}  {'pred_date':12}  {'tgt_date':12}  {'close_pred':>12}  {'close_tgt':>12}  estado")
for ticker, pred_date, tgt_date, cp, ct in rows7:
    if cp is None and ct is None:
        estado = "SIN PRECIOS"
    elif cp is None:
        estado = "sin precio pred_date"
    elif ct is None:
        estado = "sin precio tgt_date (HOY?)"
    elif cp == ct:
        estado = "PRECIOS IDENTICOS"
    else:
        calc_ret = (ct - cp) / cp
        estado = f"calc_ret={calc_ret:+.6f}"
    cp_str = f"{cp:.4f}" if cp else "-"
    ct_str = f"{ct:.4f}" if ct else "-"
    print(f"  {ticker:8}  {pred_date}  {tgt_date}  {cp_str:>12}  {ct_str:>12}  {estado}")

# --- HISTORIAL PRECIOS TICKERS CLAVE ---
print("\n=== PRECIO HISTORICO TICKERS REPRESENTATIVOS (Apr 30 - May 9) ===")
rows8 = q("""
    SELECT ticker, date, close FROM prices
    WHERE ticker IN ('LMT','HON','AMD','ARM','MU','NVDA','RBLX','XRX')
      AND date BETWEEN '2026-04-30' AND '2026-05-09'
    ORDER BY ticker, date
""")
for t, d, c in rows8:
    print(f"  {t:8}  {d}  {c:.4f}")
