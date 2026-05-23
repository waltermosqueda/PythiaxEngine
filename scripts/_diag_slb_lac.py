from sqlalchemy import create_engine, text
URL = "postgresql+psycopg://postgres.datdtnliztfzbmfbmobx:%40Supabase7786@aws-1-us-west-2.pooler.supabase.com:5432/postgres"
eng = create_engine(URL, connect_args={"connect_timeout": 15})
with eng.connect() as c:
    for ticker, tgt in [("SLB","2026-02-26"),("LAC","2026-04-23")]:
        preds = c.execute(text("""
            SELECT p.id, p.model_name, p.prediction_date::text, p.target_date::text, o.actual_return
            FROM predictions p JOIN outcomes o ON o.prediction_id=p.id
            WHERE p.ticker=:t AND p.target_date=:d AND o.actual_return=0.0
        """), {"t":ticker,"d":tgt}).fetchall()
        print(f"--- {ticker} target={tgt} ---")
        for r in preds:
            print(f"  pred_id={r[0]} model={r[1][:40]} pred_date={r[2]}")
        spy = c.execute(text("""
            SELECT date::text FROM prices WHERE ticker='SPY'
            AND date BETWEEN :start AND :end ORDER BY date
        """), {"start": "2026-01-01", "end": tgt}).fetchall()
        spy_dates = [r[0] for r in spy]
        if preds:
            pred_date = preds[0][2]
            idx = next((i for i,d in enumerate(spy_dates) if d==pred_date), None)
            entry_date = spy_dates[idx+1] if idx is not None and idx+1 < len(spy_dates) else None
            print(f"  entry_date={entry_date}")
            if entry_date:
                ep = c.execute(text("SELECT open,close FROM prices WHERE ticker=:t AND date=:d"),{"t":ticker,"d":entry_date}).fetchone()
                if ep:
                    flag = " OPEN=CLOSE" if abs(float(ep[0])-float(ep[1])) < 0.01 else ""
                    print(f"  entry prices: open={ep[0]} close={ep[1]}{flag}")
                else:
                    print("  entry prices: NO DATA")
            # Calcular retorno esperado
            tp = c.execute(text("SELECT open,close FROM prices WHERE ticker=:t AND date=:d"),{"t":ticker,"d":tgt}).fetchone()
            print(f"  target prices: open={tp[0]} close={tp[1]}" if tp else "  target: NO DATA")
