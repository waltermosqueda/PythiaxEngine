"""
Migración completa de datos: Supabase viejo → Supabase nuevo.
Uso:
    py scripts/_migrate_supabase.py --step export
    py scripts/_migrate_supabase.py --step import
    py scripts/_migrate_supabase.py --step verify
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT_DIR = ROOT / "_migration_export"

OLD_URL = (
    "postgresql://postgres.okbqqhitseeknruoycby:ev0Q19tVQr1shqAX"
    "@aws-1-us-east-1.pooler.supabase.com:6543/postgres"
)
NEW_URL_POOLER = (
    "postgresql://postgres.jrbutrmhykhxevpgjjoa:MlIfjRMt4Zlxrmdu"
    "@aws-1-us-east-2.pooler.supabase.com:6543/postgres"
)
NEW_URL_DIRECT = (
    "postgresql://postgres.jrbutrmhykhxevpgjjoa:MlIfjRMt4Zlxrmdu"
    "@aws-1-us-east-2.pooler.supabase.com:5432/postgres"
)
# TCP directo sin pgbouncer (para COPY bulk)
NEW_URL_TCP = (
    "postgresql://postgres:MlIfjRMt4Zlxrmdu"
    "@db.jrbutrmhykhxevpgjjoa.supabase.co:5432/postgres"
)
# El mismo pero con prefijo SQLAlchemy para alembic/app
NEW_URL_SQLALCHEMY = (
    "postgresql+psycopg://postgres.jrbutrmhykhxevpgjjoa:MlIfjRMt4Zlxrmdu"
    "@aws-1-us-east-2.pooler.supabase.com:6543/postgres"
)

# Tablas en orden FK-safe (outcomes depende de predictions)
TABLES = [
    "prices",
    "regimes",
    "data_status",
    "model_metrics",
    "pipeline_runs",
    "predictions",
    "outcomes",
    "model_run_snapshots",
]

# Tablas con columna id serial (necesitan reset de secuencia)
SERIAL_TABLES = [
    "predictions",
    "outcomes",
    "model_metrics",
    "pipeline_runs",
    "model_run_snapshots",
]


def _get_conn(url: str):
    import psycopg
    return psycopg.connect(
        url,
        prepare_threshold=None,   # deshabilita prepared statements (pgbouncer)
        sslmode="require",
        connect_timeout=30,
        options="-c TimeZone=UTC",
    )


def _serial(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"No serializable: {type(obj)}")


# ─── PASO 1: EXPORT ───────────────────────────────────────────────────────────

def do_export():
    EXPORT_DIR.mkdir(exist_ok=True)
    print(f"=== EXPORT desde DB vieja ===")
    print(f"Host: aws-1-us-east-1.pooler.supabase.com")

    with _get_conn(OLD_URL) as conn:
        total_rows = 0
        for table in TABLES:
            print(f"  [{table}]", end=" ", flush=True)
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM {table}")
                cols = [d.name for d in cur.description]
                rows = cur.fetchall()
            data = [dict(zip(cols, row)) for row in rows]
            out = EXPORT_DIR / f"{table}.json"
            out.write_text(json.dumps(data, default=_serial, ensure_ascii=False), encoding="utf-8")
            print(f"{len(data):,} filas → {out.name}")
            total_rows += len(data)

    print(f"\nExport completo: {total_rows:,} filas totales en {EXPORT_DIR}")


# ─── PASO 2: ALEMBIC MIGRATE ──────────────────────────────────────────────────

def do_alembic():
    print(f"\n=== ALEMBIC upgrade head en DB nueva ===")
    print(f"Host: aws-1-us-east-2.pooler.supabase.com (session mode port 5432)")

    env = os.environ.copy()
    env["DATABASE_URL"] = (
        "postgresql+psycopg://postgres.jrbutrmhykhxevpgjjoa:MlIfjRMt4Zlxrmdu"
        "@aws-1-us-east-2.pooler.supabase.com:5432/postgres"
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if result.returncode != 0:
        print(f"\n[ERROR] alembic falló con código {result.returncode}")
        sys.exit(1)
    print("Alembic OK")


# ─── PASO 3: IMPORT ───────────────────────────────────────────────────────────

def _to_copy_val(v):
    """Convierte valores Python a tipos compatibles con psycopg COPY."""
    if v is None:
        return None
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def do_import():
    print(f"\n=== IMPORT hacia DB nueva (via COPY bulk) ===")
    # COPY necesita una conexión dedicada — usar session pooler (port 5432, no transaction mode)
    import_url = NEW_URL_DIRECT
    print(f"Host: aws-1-us-east-2.pooler.supabase.com:5432 (session pooler)")

    with _get_conn(import_url) as conn:
        # Truncate en orden inverso para respetar FKs
        print("  Truncando tablas existentes...")
        with conn.cursor() as cur:
            tables_rev = ", ".join(reversed(TABLES))
            cur.execute(f"TRUNCATE {tables_rev} RESTART IDENTITY CASCADE")
        conn.commit()

        total_rows = 0
        for table in TABLES:
            data_path = EXPORT_DIR / f"{table}.json"
            if not data_path.exists():
                print(f"  [{table}] SKIP — no hay archivo de export")
                continue

            data = json.loads(data_path.read_text(encoding="utf-8"))
            if not data:
                print(f"  [{table}] vacía, skip")
                continue

            cols = list(data[0].keys())
            col_list = ", ".join(f'"{c}"' for c in cols)

            print(f"  [{table}]", end=" ", flush=True)
            with conn.cursor() as cur:
                with cur.copy(f'COPY {table} ({col_list}) FROM STDIN') as copy:
                    for row in data:
                        copy.write_row([_to_copy_val(row.get(c)) for c in cols])
            conn.commit()
            print(f"{len(data):,} filas")
            total_rows += len(data)

        # Reset secuencias para tablas con id serial
        print("\n  Reseteando secuencias...")
        with conn.cursor() as cur:
            for table in SERIAL_TABLES:
                cur.execute(
                    f"SELECT setval("
                    f"pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1)"
                    f")"
                )
        conn.commit()
        print("  Secuencias OK")

    print(f"\nImport completo: {total_rows:,} filas totales")


# ─── PASO 4: VERIFY ───────────────────────────────────────────────────────────

def do_verify():
    """Compara conteos del nuevo DB contra los archivos JSON del export."""
    print(f"\n=== VERIFICACIÓN: JSON export vs nuevo DB ===")

    results = []
    with _get_conn(NEW_URL_POOLER) as new_conn:
        for table in TABLES:
            data_path = EXPORT_DIR / f"{table}.json"
            expected = (
                len(json.loads(data_path.read_text(encoding="utf-8")))
                if data_path.exists()
                else 0
            )
            with new_conn.cursor() as c:
                c.execute(f"SELECT COUNT(*) FROM {table}")
                actual = c.fetchone()[0]
            ok = "✅" if expected == actual else "❌"
            results.append((table, expected, actual, ok))
            print(f"  {ok} {table}: esperado={expected:,}  nuevo={actual:,}")

    failed = [r for r in results if r[3] == "❌"]
    if failed:
        print(f"\n[WARN] {len(failed)} tabla(s) con conteo diferente")
        sys.exit(1)
    else:
        print(f"\nTodas las tablas coinciden ✅")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--step",
        choices=["export", "alembic", "import", "verify", "all"],
        required=True,
    )
    args = parser.parse_args()

    if args.step in ("export", "all"):
        do_export()
    if args.step in ("alembic", "all"):
        do_alembic()
    if args.step in ("import", "all"):
        do_import()
    if args.step in ("verify", "all"):
        do_verify()


if __name__ == "__main__":
    main()
