import sys
sys.path.insert(0, ".")
from titan_system.core.database import TitanDB

with TitanDB() as db:
    cur = db.conn.execute(
        "SELECT COUNT(*) FROM predictions WHERE model_name LIKE 'LEGACY_ML_BRAIN_V10%'"
    )
    count_before = cur.fetchone()[0]
    print(f"[CLEAN] Filas brain_v10 a eliminar: {count_before}")

    db.conn.execute(
        "DELETE FROM predictions WHERE model_name LIKE 'LEGACY_ML_BRAIN_V10%'"
    )
    db.conn.commit()

    cur2 = db.conn.execute(
        "SELECT COUNT(*) FROM predictions WHERE model_name LIKE 'LEGACY_ML_BRAIN_V10%'"
    )
    count_after = cur2.fetchone()[0]
    print(f"[CLEAN] Filas restantes: {count_after}")
    print("[CLEAN] OK — listo para relanzar desde 2025-12-18")
