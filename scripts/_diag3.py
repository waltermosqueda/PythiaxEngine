from sqlalchemy import create_engine, text
URL = 'postgresql+psycopg://postgres.datdtnliztfzbmfbmobx:%40Supabase7786@aws-1-us-west-2.pooler.supabase.com:5432/postgres'
eng = create_engine(URL, connect_args={"connect_timeout": 20})
def q(sql):
    with eng.connect() as c: return c.execute(text(sql)).fetchall()

print("=== SEC 12: PREDICCIONES SIN OUTCOMES (vencidas) ===")
rows4 = q("""
    SELECT model_name, COUNT(*) AS n, MIN(target_date), MAX(target_date)
    FROM predictions p
    WHERE NOT EXISTS (SELECT 1 FROM outcomes o WHERE o.prediction_id=p.id)
      AND target_date < CURRENT_DATE
    GROUP BY model_name ORDER BY n DESC
""")
if rows4:
    for m,n,d1,d2 in rows4: print(f"  {m[:45]:45}  {n:>4} sin outcome  ({d1}->{d2})")
else:
    print("  Todas las predicciones vencidas tienen outcomes")

print("\n=== SEC 13: DOBLE EVALUACION ===")
rows5 = q("SELECT prediction_id,COUNT(*) n FROM outcomes GROUP BY prediction_id HAVING COUNT(*)>1 LIMIT 10")
print(f"  Duplicados: {len(rows5)}")
for r in rows5: print(f"  prediction_id={r[0]}  n={r[1]}")

print("\n=== SEC 14: WINRATE POR MODELO ===")
rows6 = q("""
    SELECT p.model_name, COUNT(*) total,
           ROUND(AVG(o.hit::float)*100,2) wr,
           ROUND(AVG(o.actual_return)*100,4) avg_ret,
           SUM(CASE WHEN o.actual_return=0.0 THEN 1 ELSE 0 END) ceros
    FROM outcomes o JOIN predictions p ON p.id=o.prediction_id
    GROUP BY p.model_name ORDER BY total DESC
""")
print(f"  {'modelo':45}  {'total':>7}  {'WR%':>7}  {'avgRet%':>8}  {'ceros':>6}")
for m,tot,wr,avg,c in rows6:
    flags = []
    if wr is not None and (wr>90 or wr<10): flags.append("WR_EXTREMO")
    if avg is not None and abs(avg)>5: flags.append("RET_GRANDE")
    if c > tot*0.3: flags.append("MUCHOS_CEROS")
    fl = "  <- " + ",".join(flags) if flags else ""
    print(f"  {m[:45]:45}  {tot:>7}  {wr:>7.2f}  {avg:>8.4f}  {c:>6}{fl}")

print("\n=== PRECIOS EN DB PARA ZEROS MAY 4-8 ===")
rows7 = q("""
    SELECT p.ticker, p.prediction_date, p.target_date,
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
seen = set()
for ticker,pred_date,tgt_date,cp,ct in rows7:
    key = (ticker, str(pred_date), str(tgt_date))
    if key in seen: continue
    seen.add(key)
    if cp is None and ct is None: estado = "SIN PRECIOS EN DB"
    elif cp is None: estado = "sin precio pred_date"
    elif ct is None: estado = "sin precio tgt_date (HOY?)"
    elif cp == ct: estado = f"PRECIOS IDENTICOS"
    else:
        calc_ret = (ct - cp) / cp
        estado = f"calc_ret={calc_ret:+.6f}"
    cp_str = f"{cp:.4f}" if cp else "-"
    ct_str = f"{ct:.4f}" if ct else "-"
    print(f"  {ticker:8}  {pred_date}  {tgt_date}  {cp_str:>12}  {ct_str:>12}  {estado}")

print("\n=== PRECIO HISTORICO LMT Y HON May 1-5 ===")
rows8 = q("""
    SELECT ticker, date, close FROM prices
    WHERE ticker IN ('LMT','HON','AMD','ARM','MU','NVDA')
      AND date BETWEEN '2026-04-30' AND '2026-05-09'
    ORDER BY ticker, date
""")
for t,d,c in rows8: print(f"  {t:8}  {d}  {c:.4f}")
