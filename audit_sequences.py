#!/usr/bin/env python3
"""Audit all table sequences after Supabase migration."""

import re
from pathlib import Path

env_path = Path(".env")
content = env_path.read_text()
match = re.search(r'^DATABASE_URL=(.+)$', content, re.MULTILINE)
if not match:
    print("ERROR: No active DATABASE_URL found in .env")
    exit(1)

db_url = match.group(1).strip()
if db_url.startswith("postgresql+psycopg://"):
    db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)

print(f"Auditing all table sequences in Supabase...\n")

try:
    import psycopg
    conn = psycopg.connect(db_url)
    with conn.cursor() as cur:
        # Find all tables with serial/bigserial ID columns
        cur.execute("""
            SELECT table_name, column_name, column_default, data_type
            FROM information_schema.columns
            WHERE column_default LIKE '%nextval%'
            AND table_schema = 'public'
            ORDER BY table_name
        """)
        
        tables_with_seq = cur.fetchall()
        if not tables_with_seq:
            print("No tables with auto-increment sequences found")
            conn.close()
            exit(0)
        
        print(f"Found {len(tables_with_seq)} table(s) with sequences:\n")
        
        issues = []
        for table_name, column_name, column_default, data_type in tables_with_seq:
            # Extract sequence name from default
            seq_match = re.search(r"nextval\('([^']+)'", column_default)
            if not seq_match:
                continue
            
            seq_name = seq_match.group(1)
            
            # Get max ID in table
            cur.execute(f"SELECT COUNT(*), MAX({column_name}) FROM {table_name}")
            count, max_id = cur.fetchone()
            
            # Get current sequence value
            cur.execute(f"SELECT nextval('{seq_name}'::regclass)")
            seq_value = cur.fetchone()[0]
            # Go back one to see actual current value
            cur.execute(f"SELECT currval('{seq_name}'::regclass)")
            curr_value = cur.fetchone()[0]
            
            is_ok = curr_value >= (max_id or 0)
            status = "✓ OK" if is_ok else "✗ BROKEN"
            
            print(f"  Table: {table_name}")
            print(f"    Column: {column_name} ({data_type})")
            print(f"    Sequence: {seq_name}")
            print(f"    Rows: {count}, Max ID: {max_id or 'N/A'}, Seq: {curr_value}")
            print(f"    Status: {status}\n")
            
            if not is_ok:
                issues.append((table_name, seq_name, max_id, curr_value))
        
        if issues:
            print(f"\n🔧 Found {len(issues)} sequence(s) that need fixing:\n")
            for table_name, seq_name, max_id, curr_value in issues:
                next_val = (max_id or 0) + 1
                print(f"  {table_name}: Reset {seq_name} from {curr_value} to {next_val}")
                print(f"    SQL: SELECT setval('{seq_name}', {next_val});")
        else:
            print(f"\n✓ All sequences are correct!")
            
    conn.close()
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
