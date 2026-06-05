#!/usr/bin/env python
import os
import psycopg
from datetime import datetime, timezone

# Get DB URL from .env
with open('.env', 'r') as f:
    for line in f:
        if line.startswith('DATABASE_URL='):
            db_url = line.split('=', 1)[1].strip()
            break

# Convert SQLAlchemy URL to psycopg URL
db_url = db_url.replace('postgresql+psycopg://', 'postgresql://')

# Connect and query
with psycopg.connect(db_url) as conn:
    with conn.cursor() as cur:
        # Get all columns with their constraints
        cur.execute("""
            SELECT 
                column_name, 
                data_type,
                is_nullable,
                column_default
            FROM information_schema.columns 
            WHERE table_name = 'pipeline_runs'
            ORDER BY ordinal_position
        """)
        
        print('Pipeline_runs full schema:')
        print('Column Name | Data Type | Nullable | Default')
        print('-' * 60)
        for row in cur.fetchall():
            nullable = 'YES' if row[2] == 'YES' else 'NO'
            default = row[3] if row[3] else '(none)'
            print(f'{row[0]:20} | {row[1]:15} | {nullable:8} | {default}')





