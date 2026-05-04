import sys
sys.path.insert(0, ".")
from titan_system.core.database import TitanDB

with TitanDB() as db:
    cur = db.conn.execute("""
        SELECT 
            model_name,
            MIN(prediction_date) as primera,
            MAX(prediction_date) as ultima,
            COUNT(*) as total
        FROM predictions
        GROUP BY model_name
        ORDER BY ultima DESC, model_name
    """)
    rows = cur.fetchall()
    print(f"{'MODELO':<45} {'DESDE':<12} {'HASTA':<12} {'TOTAL':>6}")
    print("-"*80)
    for r in rows:
        print(f"{r[0]:<45} {str(r[1]):<12} {str(r[2]):<12} {r[3]:>6}")

    # también rangos de outcomes / evaluaciones
    print()
    cur2 = db.conn.execute("""
        SELECT MIN(prediction_date), MAX(prediction_date), COUNT(*) FROM predictions
    """)
    row = cur2.fetchone()
    print(f"TOTAL DB: {row[2]} predicciones  |  desde {row[0]}  hasta {row[1]}")
