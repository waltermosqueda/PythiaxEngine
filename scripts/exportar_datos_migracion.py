#!/usr/bin/env python3
"""
EXPORTAR DATOS — Migración a nuevo proyecto Supabase
=====================================================
Exporta todas las tablas del proyecto actual a archivos CSV en:
    C:\repos\PythiaxEngine\migration_backup\

Uso:
    py scripts/exportar_datos_migracion.py

Requiere DATABASE_URL apuntando al proyecto ACTUAL (origen).
Lee desde .env automáticamente.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

BACKUP_DIR = BASE_DIR / "migration_backup"

# Tablas a exportar, en orden de dependencias (sin FK constraints problemas)
TABLES = [
    "alembic_version",
    "data_status",
    "regimes",
    "predictions",
    "outcomes",
    "model_metrics",
    "model_run_snapshots",
    "pipeline_runs",
    "prices",  # la más grande, al final
]


def get_source_url() -> str:
    env_path = BASE_DIR / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("# DATABASE_URL="):
            return line[len("# DATABASE_URL="):]
        if line.startswith("DATABASE_URL=") and "localhost" not in line:
            return line[len("DATABASE_URL="):]
    raise RuntimeError("No se encontró DATABASE_URL válida en .env")


def export_table(engine, table: str, out_path: Path) -> int:
    from sqlalchemy import text
    print(f"  Exportando {table}...", end=" ", flush=True)
    with engine.connect() as conn:
        rows = conn.execute(text(f'SELECT * FROM "{table}"')).fetchall()
        if not rows:
            out_path.write_text("", encoding="utf-8")
            print(f"0 filas (tabla vacía)")
            return 0
        keys = list(rows[0]._mapping.keys())
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for row in rows:
                writer.writerow(dict(row._mapping))
        print(f"{len(rows):,} filas → {out_path.name}")
        return len(rows)


def main() -> int:
    from sqlalchemy import create_engine

    print("\n=== EXPORTAR DATOS — Migración Supabase ===")
    print(f"Timestamp: {datetime.now().isoformat(timespec='seconds')}\n")

    url = get_source_url()
    print(f"Origen: {url[:50]}...")

    engine = create_engine(url, connect_args={"connect_timeout": 30})

    BACKUP_DIR.mkdir(exist_ok=True)

    meta: dict[str, object] = {
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "source_url_prefix": url[:50],
        "tables": {},
    }

    total_rows = 0
    for table in TABLES:
        out_path = BACKUP_DIR / f"{table}.csv"
        try:
            n = export_table(engine, table, out_path)
            meta["tables"][table] = {"rows": n, "file": out_path.name}
            total_rows += n
        except Exception as exc:
            print(f"  [ERROR] {table}: {exc}")
            meta["tables"][table] = {"rows": -1, "error": str(exc)}

    meta_path = BACKUP_DIR / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\n✓ Export completo: {total_rows:,} filas totales")
    print(f"  Directorio: {BACKUP_DIR}")
    print(f"  Metadata: {meta_path.name}")
    print("\nSIGUIENTE PASO:")
    print("  1. Crea un nuevo proyecto FREE en supabase.com")
    print("  2. Copia la DATABASE_URL del nuevo proyecto")
    print("  3. Ejecuta: py scripts/importar_datos_migracion.py <NUEVA_DATABASE_URL>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
