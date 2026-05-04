import sys
sys.path.insert(0, ".")
from titan_system.core.database import TitanDB

with TitanDB() as db:
    cur = db.conn.execute(
        "SELECT MIN(prediction_date), MAX(prediction_date), COUNT(*) "
        "FROM predictions WHERE model_name LIKE 'LEGACY_ML_BRAIN_V10%'"
    )
    row = cur.fetchone()
    print(f"brain_v10: min={row[0]}, max={row[1]}, total={row[2]}")

    cur2 = db.conn.execute("SELECT MAX(prediction_date) FROM predictions")
    print(f"all models max date: {cur2.fetchone()[0]}")
