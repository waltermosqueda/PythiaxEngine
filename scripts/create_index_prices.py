#!/usr/bin/env python3
"""Create index on prices(ticker, date) for query optimization - PostgreSQL."""

from titan_system.core.database import TitanDB
import sys

try:
    with TitanDB() as db:
        # Check if index already exists (PostgreSQL information_schema)
        existing = db.conn.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname = 'idx_prices_ticker_date' AND tablename = 'prices'"
        ).fetchone()
        
        if existing:
            print('[OK] Index idx_prices_ticker_date already exists')
            sys.exit(0)
        
        # Create index
        print("[*] Creating index idx_prices_ticker_date on prices(ticker, date)...")
        db.conn.execute('CREATE INDEX idx_prices_ticker_date ON prices(ticker, date)')
        db.conn.commit()
        
        # Verify creation
        verify = db.conn.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname = 'idx_prices_ticker_date' AND tablename = 'prices'"
        ).fetchone()
        
        if verify:
            print(f'[OK] Index created: {verify[0]}')
            sys.exit(0)
        else:
            print('[ERROR] Index creation failed')
            sys.exit(1)
            
except Exception as e:
    print(f'[ERROR] {type(e).__name__}: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
