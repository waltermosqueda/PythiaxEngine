"""Reset predictions sequence y resume backfill desde 2025-05-22."""
import sys
sys.path.insert(0, ".")

from titan_system.core.database import TitanDB

with TitanDB() as db:
    result = db.conn.execute(
        "SELECT setval(pg_get_serial_sequence('predictions', 'id'), "
        "COALESCE((SELECT MAX(id) FROM predictions), 0) + 1, false)"
    )
    val = result.fetchone()
    print(f"[FIX] predictions_id_seq reseteada a: {val[0] if val else 'N/A'}")
    db.conn.commit()
    print("[FIX] OK — ahora puedes reanudar el backfill")
