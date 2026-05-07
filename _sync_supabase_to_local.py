"""
sync_supabase_to_local.py
Sincroniza Supabase → Docker local para las tablas:
  - prices        (upsert por ticker+date)
  - predictions   (upsert por model_name+ticker+prediction_date)
  - outcomes      (upsert por prediction_id local mapeado)
  - regimes       (upsert por date)
  - model_metrics (upsert por model_name+period_start+period_end)

SEGURO: solo inserta, nunca borra ni sobreescribe datos locales existentes.
"""
import re, os, sys
from datetime import datetime
from sqlalchemy import create_engine, text
import dotenv

dotenv.load_dotenv()

# ── Conexiones ───────────────────────────────────────────────────────────────
local_url = os.getenv('DATABASE_URL')
with open('.env') as f:
    env_content = f.read()
match = re.search(r'^\s*#\s*DATABASE_URL=(postgresql\+psycopg://postgres\.[^\s]+)', env_content, re.MULTILINE)
if not match:
    print("ERROR: no se encontró la URL de Supabase en .env"); sys.exit(1)

cloud_url = match.group(1)
print(f"LOCAL : {local_url[:50]}")
print(f"CLOUD : {cloud_url[:50]}")
print()

local_eng = create_engine(local_url)
cloud_eng = create_engine(cloud_url, connect_args={"connect_timeout": 20})

# ── helpers ──────────────────────────────────────────────────────────────────
def count(eng, table, where=""):
    with eng.connect() as c:
        q = f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else "")
        return c.execute(text(q)).scalar()

# ═══════════════════════════════════════════════════════════════════════════════
# 1. PRICES
# ═══════════════════════════════════════════════════════════════════════════════
print("=" * 60)
print("1. PRICES")
print("=" * 60)

with cloud_eng.connect() as src, local_eng.connect() as dst:
    # Leer todas las fechas/tickers que ya existen en local
    local_keys = set(
        (r[0], r[1]) for r in dst.execute(text("SELECT ticker, date FROM prices"))
    )
    print(f"  Local tiene: {len(local_keys):,} registros")

    # Traer de Supabase lo que no existe en local
    cloud_rows = src.execute(text(
        "SELECT ticker, date, open, high, low, close, volume, adj_close FROM prices ORDER BY date, ticker"
    )).fetchall()
    print(f"  Supabase tiene: {len(cloud_rows):,} registros")

    nuevos = [r for r in cloud_rows if (r[0], r[1]) not in local_keys]
    print(f"  Insertando: {len(nuevos):,} nuevos registros...")

    if nuevos:
        inserted = 0
        BATCH = 500
        for i in range(0, len(nuevos), BATCH):
            batch = nuevos[i:i+BATCH]
            dst.execute(text("""
                INSERT INTO prices (ticker, date, open, high, low, close, volume, adj_close)
                VALUES (:ticker, :date, :open, :high, :low, :close, :volume, :adj_close)
                ON CONFLICT (ticker, date) DO NOTHING
            """), [{"ticker": r[0], "date": r[1], "open": r[2], "high": r[3],
                    "low": r[4], "close": r[5], "volume": r[6], "adj_close": r[7]}
                   for r in batch])
            inserted += len(batch)
            if inserted % 5000 == 0:
                print(f"    ... {inserted:,} insertados")
        dst.commit()
        print(f"  ✅ prices: {len(nuevos):,} nuevas filas insertadas")
    else:
        print("  ✅ prices: ya sincronizado")

# ═══════════════════════════════════════════════════════════════════════════════
# 2. REGIMES
# ═══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("2. REGIMES")
print("=" * 60)

with cloud_eng.connect() as src, local_eng.connect() as dst:
    local_dates = set(r[0] for r in dst.execute(text("SELECT date FROM regimes")))
    cloud_rows = src.execute(text(
        "SELECT date, trend_regime, vol_regime, credit_regime, composite, vix_level, spy_return_20d, details FROM regimes ORDER BY date"
    )).fetchall()
    nuevos = [r for r in cloud_rows if r[0] not in local_dates]
    print(f"  Local: {len(local_dates):,} | Supabase: {len(cloud_rows):,} | Nuevos: {len(nuevos):,}")
    if nuevos:
        dst.execute(text("""
            INSERT INTO regimes (date, trend_regime, vol_regime, credit_regime, composite, vix_level, spy_return_20d, details)
            VALUES (:date, :trend, :vol, :credit, :comp, :vix, :spy, :details)
            ON CONFLICT (date) DO NOTHING
        """), [{"date": r[0], "trend": r[1], "vol": r[2], "credit": r[3],
                "comp": r[4], "vix": r[5], "spy": r[6], "details": r[7]} for r in nuevos])
        dst.commit()
        print(f"  ✅ regimes: {len(nuevos):,} nuevas filas")
    else:
        print("  ✅ regimes: ya sincronizado")

# ═══════════════════════════════════════════════════════════════════════════════
# 3. PREDICTIONS
# ═══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("3. PREDICTIONS")
print("=" * 60)

# Mapa: (model_name, ticker, prediction_date) → local_id
with local_eng.connect() as c:
    local_pred_map = {
        (r[1], r[2], r[3]): r[0]
        for r in c.execute(text("SELECT id, model_name, ticker, prediction_date FROM predictions"))
    }

with cloud_eng.connect() as src:
    cloud_preds = src.execute(text(
        "SELECT id, model_name, model_version, ticker, prediction_date, target_date, "
        "direction, confidence, score, regime, sector, created_at "
        "FROM predictions ORDER BY prediction_date, model_name, ticker"
    )).fetchall()

print(f"  Local: {len(local_pred_map):,} | Supabase: {len(cloud_preds):,}")

nuevos_preds = [r for r in cloud_preds if (r[1], r[3], r[4]) not in local_pred_map]
print(f"  Insertando: {len(nuevos_preds):,} predictions nuevas...")

cloud_id_to_local_id = {}  # para mapear outcomes después

if nuevos_preds:
    with local_eng.connect() as dst:
        for r in nuevos_preds:
            result = dst.execute(text("""
                INSERT INTO predictions (model_name, model_version, ticker, prediction_date,
                    target_date, direction, confidence, score, regime, sector, created_at)
                VALUES (:mn, :mv, :tk, :pd, :td, :dir, :conf, :score, :reg, :sec, :ca)
                ON CONFLICT DO NOTHING
                RETURNING id
            """), {"mn": r[1], "mv": r[2], "tk": r[3], "pd": r[4], "td": r[5],
                   "dir": r[6], "conf": r[7], "score": r[8], "reg": r[9],
                   "sec": r[10], "ca": r[11]})
            row = result.fetchone()
            if row:
                cloud_id_to_local_id[r[0]] = row[0]
        dst.commit()

    print(f"  ✅ predictions: {len(cloud_id_to_local_id):,} insertadas")
else:
    print("  ✅ predictions: ya sincronizado")

# Rebuild completo del mapa local (incluye los recién insertados)
with local_eng.connect() as c:
    local_pred_map = {
        (r[1], r[2], r[3]): r[0]
        for r in c.execute(text("SELECT id, model_name, ticker, prediction_date FROM predictions"))
    }

# Completar el mapa cloud→local para predictions que ya existían
for r in cloud_preds:
    cid = r[0]
    key = (r[1], r[3], r[4])
    if cid not in cloud_id_to_local_id and key in local_pred_map:
        cloud_id_to_local_id[cid] = local_pred_map[key]

print(f"  Mapa cloud→local: {len(cloud_id_to_local_id):,} predictions mapeadas")

# ═══════════════════════════════════════════════════════════════════════════════
# 4. OUTCOMES
# ═══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("4. OUTCOMES")
print("=" * 60)

with local_eng.connect() as c:
    local_outcome_pids = set(r[0] for r in c.execute(text("SELECT prediction_id FROM outcomes")))

with cloud_eng.connect() as src:
    cloud_outcomes = src.execute(text(
        "SELECT prediction_id, actual_direction, actual_return, hit, evaluated_at FROM outcomes"
    )).fetchall()

print(f"  Local outcomes: {len(local_outcome_pids):,} | Supabase: {len(cloud_outcomes):,}")

nuevos_outcomes = []
skipped = 0
for r in cloud_outcomes:
    local_pid = cloud_id_to_local_id.get(r[0])
    if local_pid is None:
        skipped += 1
        continue
    if local_pid not in local_outcome_pids:
        nuevos_outcomes.append({"pid": local_pid, "adir": r[1], "aret": r[2],
                                 "hit": r[3], "eat": r[4]})

print(f"  Nuevos outcomes: {len(nuevos_outcomes):,} | Sin mapeo: {skipped}")

if nuevos_outcomes:
    with local_eng.connect() as dst:
        BATCH = 500
        for i in range(0, len(nuevos_outcomes), BATCH):
            dst.execute(text("""
                INSERT INTO outcomes (prediction_id, actual_direction, actual_return, hit, evaluated_at)
                VALUES (:pid, :adir, :aret, :hit, :eat)
                ON CONFLICT DO NOTHING
            """), nuevos_outcomes[i:i+BATCH])
        dst.commit()
    print(f"  ✅ outcomes: {len(nuevos_outcomes):,} insertados")
else:
    print("  ✅ outcomes: ya sincronizado")

# ═══════════════════════════════════════════════════════════════════════════════
# 5. MODEL_METRICS
# ═══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("5. MODEL_METRICS")
print("=" * 60)

with local_eng.connect() as c:
    local_metrics_keys = set(
        (r[0], r[1], r[2]) for r in c.execute(text("SELECT model_name, period_start, period_end FROM model_metrics"))
    )
with cloud_eng.connect() as src:
    try:
        cloud_metrics = src.execute(text(
            "SELECT model_name, period_start, period_end, total_predictions, correct_predictions, "
            "accuracy, avg_confidence, avg_return_when_right, avg_return_when_wrong, "
            "profit_factor, sharpe_ratio, max_drawdown, calculated_at FROM model_metrics"
        )).fetchall()
    except Exception as e:
        cloud_metrics = []
        print(f"  (tabla no disponible en Supabase: {e})")

nuevos = [r for r in cloud_metrics if (r[0], r[1], r[2]) not in local_metrics_keys]
print(f"  Local: {len(local_metrics_keys):,} | Supabase: {len(cloud_metrics):,} | Nuevos: {len(nuevos):,}")
if nuevos:
    with local_eng.connect() as dst:
        dst.execute(text("""
            INSERT INTO model_metrics (model_name, period_start, period_end, total_predictions,
                correct_predictions, accuracy, avg_confidence, avg_return_when_right,
                avg_return_when_wrong, profit_factor, sharpe_ratio, max_drawdown, calculated_at)
            VALUES (:mn,:ps,:pe,:tp,:cp,:acc,:ac,:arwr,:arww,:pf,:sr,:md,:ca)
            ON CONFLICT DO NOTHING
        """), [{"mn":r[0],"ps":r[1],"pe":r[2],"tp":r[3],"cp":r[4],"acc":r[5],
                "ac":r[6],"arwr":r[7],"arww":r[8],"pf":r[9],"sr":r[10],"md":r[11],"ca":r[12]}
               for r in nuevos])
        dst.commit()
    print(f"  ✅ model_metrics: {len(nuevos):,} nuevas filas")
else:
    print("  ✅ model_metrics: ya sincronizado")

# ═══════════════════════════════════════════════════════════════════════════════
# RESUMEN FINAL
# ═══════════════════════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("RESUMEN FINAL")
print("=" * 60)
with local_eng.connect() as c:
    for tbl in ['prices', 'predictions', 'outcomes', 'regimes', 'model_metrics']:
        n = c.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
        print(f"  {tbl:<20}: {n:,} filas")
print()
print("✅ Sync completo")
