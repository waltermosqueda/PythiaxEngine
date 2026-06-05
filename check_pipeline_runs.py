#!/usr/bin/env python3
"""Diagnostic: Check pipeline_runs table status."""

import os
from pathlib import Path
import re

# Read .env to get DATABASE_URL
env_path = Path(".env")
if not env_path.exists():
    print("ERROR: .env file not found")
    exit(1)

content = env_path.read_text()
# First try to find an ACTIVE (non-commented) DATABASE_URL
match = re.search(r'^DATABASE_URL=(.+)$', content, re.MULTILINE)
if not match:
    # Fall back to commented version
    match = re.search(r'#\s*DATABASE_URL=(.+)', content)
if not match:
    print("ERROR: DATABASE_URL not found in .env")
    exit(1)

db_url = match.group(1).strip()
# Convert SQLAlchemy URL to psycopg URL if needed
if db_url.startswith("postgresql+psycopg://"):
    db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)
print(f"Using DATABASE_URL from .env")

try:
    import psycopg
    conn = psycopg.connect(db_url)
    with conn.cursor() as cur:
        # Check schema
        cur.execute("""
            SELECT column_name, is_nullable, column_default, data_type
            FROM information_schema.columns
            WHERE table_name = 'pipeline_runs'
            ORDER BY ordinal_position
        """)
        print("\n=== pipeline_runs schema ===")
        for col, nullable, default, dtype in cur.fetchall():
            null_str = "NULL" if nullable == 'YES' else "NOT NULL"
            default_str = f" DEFAULT {default}" if default else ""
            print(f"  {col:30} {dtype:20} {null_str:10} {default_str}")
        
        # Check recent records
        cur.execute("""
            SELECT COUNT(*) FROM pipeline_runs
        """)
        count = cur.fetchone()[0]
        print(f"\n=== pipeline_runs stats ===")
        print(f"  Total records: {count}")
        
        if count > 0:
            cur.execute("""
                SELECT id, run_id, pipeline_name, status, created_at 
                FROM pipeline_runs 
                ORDER BY id DESC 
                LIMIT 5
            """)
            print(f"\n=== Recent records (5 most recent) ===")
            for id, run_id, pipeline_name, status, created_at in cur.fetchall():
                print(f"  {id:5} | {run_id[:40]:40} | {pipeline_name:25} | {status:10} | {str(created_at)[:19]}")
        else:
            print(f"\n  (empty table - NO RECORDS)")
        
        # Try an INSERT to see what error we get
        print(f"\n=== Testing INSERT ===")
        try:
            test_run_id = "diagnostic-test-" + str(os.getenv("GITHUB_RUN_ID", "local"))
            cur.execute("""
                INSERT INTO pipeline_runs (run_id, pipeline_name, status, run_source, run_date)
                VALUES (%s, %s, %s, %s, CURRENT_DATE)
            """, (test_run_id, "diagnostic_test", "TESTING", "diagnostic"))
            print(f"  ✓ INSERT succeeded for run_id={test_run_id}")
            # DON'T commit, just rollback
            conn.rollback()
            print(f"  (Rolled back)")
        except Exception as e:
            print(f"  ✗ INSERT failed: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
                
        conn.close()
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
