"""
Aplica Row Level Security (RLS) en todas las tablas sin protección.
- Tablas de datos (prices, predictions, outcomes): RLS ON + política SELECT para anon
- Tablas internas (alembic_version, etc.): RLS ON sin política = deny all para anon
"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sqlalchemy import create_engine, text

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
cloud_url = None
with open(env_path, encoding="utf-8") as f:
    for line in f:
        m = re.match(r"^\s*#\s*DATABASE_URL=(postgresql\+psycopg://postgres\..*)", line)
        if m:
            cloud_url = m.group(1).strip()
            break

eng = create_engine(cloud_url, connect_args={"connect_timeout": 10})

# Tablas que el dashboard necesita leer desde el browser (anon SELECT OK)
PUBLIC_READ_TABLES = {"prices", "predictions", "outcomes"}

with eng.connect() as c:
    # 1. Ver estado actual de RLS por tabla
    print("=" * 60)
    print("Estado actual de RLS por tabla")
    print("=" * 60)
    tables = c.execute(text("""
        SELECT schemaname, tablename, rowsecurity
        FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename
    """)).fetchall()

    no_rls = []
    for t in tables:
        status = "ON " if t[2] else "OFF ← VULNERABLE"
        print(f"  {t[1]:30s}  RLS={status}")
        if not t[2]:
            no_rls.append(t[1])

    print(f"\n  Tablas sin RLS: {len(no_rls)}")
    print(f"  → {no_rls}")

    # 2. Políticas existentes
    print("\n" + "=" * 60)
    print("Políticas RLS existentes")
    print("=" * 60)
    policies = c.execute(text("""
        SELECT tablename, policyname, cmd, roles
        FROM pg_policies
        WHERE schemaname = 'public'
        ORDER BY tablename, policyname
    """)).fetchall()
    if policies:
        for p in policies:
            print(f"  {p[0]:25s}  {p[1]:30s}  cmd={p[2]}  roles={p[3]}")
    else:
        print("  (ninguna)")

print()
print("=" * 60)
print("Aplicando RLS...")
print("=" * 60)

with eng.connect() as c:
    c.execute(text("BEGIN"))
    try:
        for table in no_rls:
            # Habilitar RLS
            c.execute(text(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY'))
            print(f"  ✅ RLS habilitado: {table}")

            if table in PUBLIC_READ_TABLES:
                # Crear política SELECT para anon y authenticated
                policy_name = f"allow_public_read_{table}"
                # Primero borrar si existe (idempotente)
                c.execute(text(f"""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM pg_policies
                            WHERE schemaname='public' AND tablename='{table}'
                            AND policyname='{policy_name}'
                        ) THEN
                            EXECUTE 'DROP POLICY {policy_name} ON public.{table}';
                        END IF;
                    END
                    $$
                """))
                c.execute(text(f"""
                    CREATE POLICY "{policy_name}"
                    ON public."{table}"
                    FOR SELECT
                    TO anon, authenticated
                    USING (true)
                """))
                print(f"  ✅ Política SELECT anon/authenticated: {table}")
            else:
                print(f"  🔒 Sin política anon (acceso interno solo): {table}")

        c.execute(text("COMMIT"))
        print("\n✅ Transacción completada exitosamente.")

    except Exception as e:
        c.execute(text("ROLLBACK"))
        print(f"\n❌ Error — ROLLBACK: {e}")
        raise

print()
print("=" * 60)
print("Estado final de RLS")
print("=" * 60)
with eng.connect() as c:
    tables_post = c.execute(text("""
        SELECT t.tablename, t.rowsecurity,
               COUNT(p.policyname) as policies
        FROM pg_tables t
        LEFT JOIN pg_policies p ON p.tablename = t.tablename AND p.schemaname = 'public'
        WHERE t.schemaname = 'public'
        GROUP BY t.tablename, t.rowsecurity
        ORDER BY t.tablename
    """)).fetchall()
    for t in tables_post:
        rls = "ON" if t[1] else "OFF"
        print(f"  {t[0]:30s}  RLS={rls}  policies={t[2]}")
