#!/usr/bin/env python3
"""Fix: Reset pipeline_runs sequence after Supabase migration."""

import os
import re
from pathlib import Path

# Read active DATABASE_URL from .env
env_path = Path(".env")
content = env_path.read_text()
match = re.search(r'^DATABASE_URL=(.+)$', content, re.MULTILINE)
if not match:
    print("ERROR: No active DATABASE_URL found in .env")
    exit(1)

db_url = match.group(1).strip()
if db_url.startswith("postgresql+psycopg://"):
    db_url = db_url.replace("postgresql+psycopg://", "postgresql://", 1)

print(f"Connecting to Supabase (new)...")

try:
    import psycopg
    conn = psycopg.connect(db_url)
    with conn.cursor() as cur:
        # Get the max ID currently in the table
        cur.execute("SELECT MAX(id) FROM pipeline_runs")
        max_id = cur.fetchone()[0]
        print(f"  Max ID in pipeline_runs: {max_id}")
        
        # Get current sequence value
        cur.execute("SELECT nextval('pipeline_runs_id_seq'::regclass)")
        current_seq = cur.fetchone()[0]
        print(f"  Current sequence value: {current_seq}")
        
        if current_seq <= max_id:
            print(f"  ⚠️  PROBLEM: Sequence is BEHIND max ID")
            print(f"  🔧 Fixing: Setting sequence to {max_id + 1}...")
            
            # Reset the sequence to the next value after the max ID
            cur.execute(f"SELECT setval('pipeline_runs_id_seq', {max_id + 1})")
            conn.commit()
            
            # Verify it worked
            cur.execute("SELECT nextval('pipeline_runs_id_seq'::regclass)")
            new_seq = cur.fetchone()[0]
            print(f"  ✓ New sequence value: {new_seq}")
            print(f"\n✓ FIXED: Sequence has been reset")
        else:
            print(f"  ✓ Sequence is correct (ahead of max ID)")
            
    conn.close()
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
