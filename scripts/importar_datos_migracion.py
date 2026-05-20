#!/usr/bin/env python3
"""
IMPORTAR DATOS — Migración a nuevo proyecto Supabase
=====================================================
Importa los datos exportados por exportar_datos_migracion.py
al NUEVO proyecto Supabase.

Uso:
    py scripts/importar_datos_migracion.py "postgresql+psycopg://postgres.<proyecto>:<pass>@aws-0-us-east-1.pooler.supabase.com:6543/postgres"

Pasos que hace este script:
    1. Conecta al nuevo proyecto
    2. Corre alembic upgrade head (crea schema)
    3. Importa cada tabla desde migration_backup/*.csv
    4. Verifica row counts
    5. Imprime nueva DATABASE_URL para copiar a .env y GitHub Secret
"""
from __future__ import annotations

import ast
import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

BACKUP_DIR = BASE_DIR / "migration_backup"

# Tablas a importar, en orden correcto de FK
TABLES_IMPORT_ORDER = [
    "alembic_version",
    "data_status",
    "regimes",
    "predictions",
    "outcomes",
    "model_metrics",
    "model_run_snapshots",
    "pipeline_runs",
    "prices",
]

# Tablas que maneja alembic (no insertar alembic_version manualmente)
SKIP_INSERT = {"alembic_version"}

# Columnas JSON que fueron exportadas como Python dict repr (str() en vez de json.dumps())
# Síntoma: error "invalid input syntax for type json, Token '\"'\"' is invalid"
JSON_REPR_COLUMNS: dict[str, set[str]] = {
    "pipeline_runs": {"artifact_manifest", "metadata_json"},
    "model_run_snapshots": {"snapshot_json"},
}


def _fix_json_value(v: str | None) -> str | None:
    """Convierte Python dict repr a JSON válido para columnas de tipo JSON."""
    if v is None or v == "":
        return None
    try:
        json.loads(v)
        return v  # ya es JSON válido
    except (json.JSONDecodeError, ValueError):
        try:
            obj = ast.literal_eval(v)
            return json.dumps(obj, ensure_ascii=False, default=str)
        except (ValueError, SyntaxError):
            return v  # dejar como está


def import_table(engine, table: str, csv_path: Path) -> int:
    from sqlalchemy import text

    if not csv_path.exists() or csv_path.stat().st_size == 0:
        print(f"  {table}: sin datos (vacío o no existe)")
        return 0

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"  {table}: 0 filas")
        return 0

    print(f"  Importando {table}: {len(rows):,} filas...", end=" ", flush=True)

    # Detectar columnas que realmente existen en el schema destino
    # (evita errores si el CSV tiene columnas extras que no están en alembic)
    with engine.connect() as conn:
        existing = {r[0] for r in conn.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name=:t"),
            {"t": table}
        ).fetchall()}

    csv_cols = list(rows[0].keys())
    cols = [c for c in csv_cols if c in existing]
    skipped = set(csv_cols) - existing
    if skipped:
        print(f"\n    [WARN] {table}: ignorando columnas no en schema destino: {skipped}", end=" ", flush=True)

    placeholders = ", ".join(f":{c}" for c in cols)
    col_names = ", ".join(f'"{c}"' for c in cols)

    # Limpiar tabla antes de insertar (por si alembic creó rows de prueba)
    with engine.begin() as conn:
        conn.execute(text(f'DELETE FROM "{table}"'))

    # Insertar en chunks para no saturar la conexión
    chunk_size = 500
    inserted = 0
    json_cols = JSON_REPR_COLUMNS.get(table, set())
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        # Convertir strings vacíos a None; fix JSON repr → JSON válido para cols JSON
        cleaned = []
        for row in chunk:
            clean = {}
            for k, v in row.items():
                if k not in existing:
                    continue  # skip columnas no en schema destino
                if v == "":
                    clean[k] = None
                elif k in json_cols:
                    clean[k] = _fix_json_value(v)
                else:
                    clean[k] = v
            cleaned.append(clean)
        with engine.begin() as conn:
            conn.execute(
                text(f'INSERT INTO "{table}" ({col_names}) VALUES ({placeholders})'),
                cleaned,
            )
        inserted += len(chunk)

    print(f"OK ({inserted:,} insertadas)")
    return inserted


def verify_counts(engine, tables: list[str]) -> bool:
    from sqlalchemy import text

    print("\n=== Verificación de row counts ===")
    all_ok = True
    for table in tables:
        if table in SKIP_INSERT:
            continue
        csv_path = BACKUP_DIR / f"{table}.csv"
        if not csv_path.exists():
            continue
        with csv_path.open(newline="", encoding="utf-8") as f:
            expected = sum(1 for _ in csv.reader(f)) - 1  # -1 header
        with engine.connect() as conn:
            actual = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
        status = "✓" if actual == expected else "✗"
        print(f"  {status} {table}: esperado={expected:,} actual={actual:,}")
        if actual != expected:
            all_ok = False
    return all_ok


def main() -> int:
    from sqlalchemy import create_engine

    if len(sys.argv) < 2:
        print("Uso: py scripts/importar_datos_migracion.py <NUEVA_DATABASE_URL>")
        print("\nEjemplo:")
        print('  py scripts/importar_datos_migracion.py "postgresql+psycopg://postgres.XXXX:PASS@aws-0-us-east-1.pooler.supabase.com:6543/postgres"')
        return 1

    new_url = sys.argv[1].strip()
    if "localhost" in new_url:
        print("ERROR: La URL apunta a localhost. Proporciona la URL del NUEVO proyecto Supabase.")
        return 1

    if not BACKUP_DIR.exists():
        print(f"ERROR: No existe {BACKUP_DIR}. Ejecuta primero exportar_datos_migracion.py")
        return 1

    print("\n=== IMPORTAR DATOS — Nuevo proyecto Supabase ===")
    print(f"Timestamp: {datetime.now().isoformat(timespec='seconds')}")
    print(f"Destino: {new_url[:60]}...")
    print()

    # prepare_threshold=None: deshabilita prepared statements (incompatibles con
    # Supabase transaction pooler — psycopg3 default causa DuplicatePreparedStatement)
    engine = create_engine(new_url, connect_args={"connect_timeout": 30, "prepare_threshold": None})

    # Verificar conectividad
    try:
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        print("✓ Conexión al nuevo proyecto: OK")
    except Exception as exc:
        print(f"✗ No se pudo conectar al nuevo proyecto: {exc}")
        return 1

    # Correr alembic upgrade head para crear el schema
    print("\n--- Aplicando schema (alembic upgrade head) ---")
    env = os.environ.copy()
    env["DATABASE_URL"] = new_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BASE_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"✗ alembic upgrade head falló:\n{result.stderr}")
        return 1
    print("✓ Schema creado OK")

    # Importar tablas
    print("\n--- Importando datos ---")
    total = 0
    for table in TABLES_IMPORT_ORDER:
        if table in SKIP_INSERT:
            continue
        csv_path = BACKUP_DIR / f"{table}.csv"
        try:
            n = import_table(engine, table, csv_path)
            total += n
        except Exception as exc:
            print(f"  [ERROR] {table}: {exc}")
            return 1

    # Verificar
    all_ok = verify_counts(engine, TABLES_IMPORT_ORDER)

    print(f"\n{'✓' if all_ok else '⚠'} Migración {'completada' if all_ok else 'con diferencias'}: {total:,} filas importadas")

    print("\n=== PASOS FINALES ===")
    print(f"\n1. ACTUALIZAR .env — reemplazar la línea DATABASE_URL comentada:")
    print(f"   # DATABASE_URL={new_url}")
    print(f"\n2. ACTUALIZAR GitHub Secret:")
    print(f"   → https://github.com/waltermosqueda/PythiaxEngine/settings/secrets/actions")
    print(f"   → Editar DATABASE_URL → pegar nueva URL")
    print(f"\n3. VERIFICAR pipeline:")
    print(f"   → Hacer un commit cualquiera y verificar que CI corre con nueva DB")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
