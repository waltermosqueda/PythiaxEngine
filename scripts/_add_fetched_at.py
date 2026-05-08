"""
Agrega columna fetched_at TIMESTAMPTZ a prices en Supabase (Postgres).
No toca SQLite local. Las filas existentes quedan con fetched_at = NOW() (momento del ALTER).
Uso: py scripts/_add_fetched_at.py
"""
import os
import re
import sys

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
cloud_url = None
with open(env_path, encoding="utf-8") as f:
    for line in f:
        m = re.match(r"^\s*#\s*DATABASE_URL=(postgresql\+psycopg://postgres\..*)", line)
        if m:
            cloud_url = m.group(1).strip()
            break

if not cloud_url:
    print("ERROR: No se encontró DATABASE_URL en .env")
    sys.exit(1)

from sqlalchemy import create_engine, text

eng = create_engine(cloud_url, connect_args={"connect_timeout": 15})

with eng.connect() as c:
    # Verificar si ya existe
    exists = c.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'prices' AND column_name = 'fetched_at'
    """)).fetchone()

    if exists:
        print("fetched_at ya existe en prices. Nada que hacer.")
    else:
        c.execute(text("""
            ALTER TABLE prices
            ADD COLUMN fetched_at TIMESTAMPTZ DEFAULT NOW()
        """))
        c.commit()
        print("ALTER TABLE OK: columna fetched_at TIMESTAMPTZ DEFAULT NOW() agregada a prices.")

    # Verificar
    row = c.execute(text("""
        SELECT column_name, data_type, column_default
        FROM information_schema.columns
        WHERE table_name = 'prices' AND column_name = 'fetched_at'
    """)).fetchone()
    if row:
        print(f"Verificación: {row[0]} | {row[1]} | default={row[2]}")

    # Muestra un sample para confirmar
    sample = c.execute(text("""
        SELECT ticker, date::text, close, fetched_at
        FROM prices
        ORDER BY date DESC
        LIMIT 3
    """)).fetchall()
    print("\nSample (3 filas más recientes):")
    for r in sample:
        print(f"  {r[0]:6s}  {r[1]}  ${float(r[2]):.2f}  fetched_at={r[3]}")
