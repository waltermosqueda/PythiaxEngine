import sqlite3
db = sqlite3.connect("titan_system/data/titan.db")
tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print("TABLES:", [t[0] for t in tables])
pred_cols = db.execute("PRAGMA table_info(predictions)").fetchall()
print("PREDICTIONS cols:", [(c[1], c[2]) for c in pred_cols])
out_cols = db.execute("PRAGMA table_info(outcomes)").fetchall()
print("OUTCOMES cols:", [(c[1], c[2]) for c in out_cols])
# sample
rows = db.execute("SELECT prediction_date, target_date, model_name, outcome_return FROM predictions LIMIT 3").fetchall()
print("SAMPLE predictions:", rows)
