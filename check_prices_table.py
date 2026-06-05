#!/usr/bin/env python3
import os
from sqlalchemy import create_engine, text

# Get DATABASE_URL from .env - find the ACTIVE one (not commented)
db_url = None
with open('.env') as f:
    for line in f:
        line = line.strip()
        if line.startswith('DATABASE_URL=') and not line.startswith('# DATABASE_URL='):
            db_url = line.replace('DATABASE_URL=', '')
            break

if not db_url:
    print("❌ DATABASE_URL not found in .env!")
    exit(1)

print(f"Connecting to: {db_url[:80]}...")

try:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        # Check if prices table exists
        result = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'prices')"
        )).fetchone()
        exists = result[0]
        print(f'\nPrices table exists: {exists}')

        if exists:
            # Count rows
            count = conn.execute(text('SELECT COUNT(*) FROM prices')).fetchone()[0]
            print(f'Prices row count: {count}')
            
            # Sample query
            samples = conn.execute(text(
                'SELECT ticker, price, fetched_at FROM prices ORDER BY fetched_at DESC LIMIT 3'
            )).fetchall()
            print(f'\nLatest 3 price records:')
            for row in samples:
                print(f'  {row}')
        
        print('\n✅ Connection successful!')
        
except Exception as e:
    print(f'❌ Error: {e}')
    import traceback
    traceback.print_exc()
