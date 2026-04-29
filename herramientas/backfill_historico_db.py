#!/usr/bin/env python3
"""
BACKFILL HISTORICO DE TITAN.DB
==============================

Amplia titan.db con una ventana historica mas larga que la usada por el
update diario. Pensado para ejecuciones controladas, no para la tarea diaria.

Uso:
  python herramientas/backfill_historico_db.py
  python herramientas/backfill_historico_db.py --years 6 --workers 8
  python herramientas/backfill_historico_db.py --years 6 --skip-validate
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from titan_system.core.database import TitanDB
from titan_system.core.data_loader import DataLoader
from herramientas.actualizar_datos import fecha_objetivo_mercado


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill historico seguro de titan.db")
    parser.add_argument("--years", type=int, default=6, help="Historia objetivo a descargar (default: 6)")
    parser.add_argument("--workers", type=int, default=8, help="Workers concurrentes (default: 8)")
    parser.add_argument("--retries", type=int, default=3, help="Reintentos por ticker (default: 3)")
    parser.add_argument("--skip-validate", action="store_true", help="No correr validate_market_data al final")
    parser.add_argument(
        "--end-date",
        help="Fecha tope YYYY-MM-DD. Default: ultima rueda cerrada segun calendario local.",
    )
    return parser.parse_args()


def run_validation(expected_date: str) -> int:
    cmd = [sys.executable, os.path.join("herramientas", "validate_market_data.py"), "--expected-date", expected_date]
    result = subprocess.run(
        cmd,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.returncode


def main() -> int:
    args = parse_args()
    now = datetime.now()
    target_date = (
        datetime.strptime(args.end_date, "%Y-%m-%d").date()
        if args.end_date
        else fecha_objetivo_mercado(now)
    )
    repair_start = (target_date - timedelta(days=args.years * 370)).isoformat()

    print("=" * 72)
    print("  BACKFILL HISTORICO DE TITAN.DB")
    print(f"  {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 72)
    print(f"  Historia objetivo : {args.years} anos")
    print(f"  Workers           : {args.workers}")
    print(f"  Reintentos        : {args.retries}")
    print(f"  Fecha tope        : {target_date.isoformat()}")

    with TitanDB() as db:
        stats_before = db.db_stats()
        latest_before = db.execute_raw("SELECT MAX(date) AS max_date FROM prices").iloc[0, 0]
        print("\n  Estado antes:")
        print(f"  Registros: {stats_before.get('prices_count', 0):,}")
        print(f"  Rango:     {stats_before.get('price_date_range', 'sin datos')}")
        print(f"  Tamano:    {stats_before.get('db_size_mb', 0):.1f} MB")

        loader = DataLoader(
            db,
            years_history=args.years,
            max_workers=args.workers,
            max_retries=args.retries,
        )
        results = loader.download_all(force_full=True, end_date=target_date.isoformat())
        refresh_stats = loader.refresh_invalid_recent_rows(end_date=target_date.isoformat())
        repaired_rows = db.repair_ohlcv_bounds(start_date=repair_start, end_date=target_date.isoformat())

        stats_after = db.db_stats()
        latest_after = db.execute_raw("SELECT MAX(date) AS max_date FROM prices").iloc[0, 0]

        if latest_after:
            market_status = db.get_market_data_status()
            needs_metadata = (
                market_status.get("latest_prices_date") != latest_after
                or not market_status.get("market_data_updated_at")
            )
            if latest_before != latest_after or needs_metadata:
                db.save_market_data_update(latest_after)

    print("\n  Estado despues:")
    print(f"  Registros: {stats_after.get('prices_count', 0):,}")
    print(f"  Rango:     {stats_after.get('price_date_range', 'sin datos')}")
    print(f"  Tamano:    {stats_after.get('db_size_mb', 0):.1f} MB")
    print(f"\n  Filas procesadas por Yahoo : {results.get('total_rows', 0):,}")
    print(f"  Exitosos                   : {results.get('success', 0)}")
    print(f"  Al dia / sin cambios       : {results.get('skipped', 0)}")
    print(f"  Sin datos                  : {results.get('empty', 0)}")
    print(f"  Fallidos                   : {results.get('failed', 0)}")
    invalid_rows = int(refresh_stats.get('invalid_rows', 0) or 0)
    remaining_invalid_rows = int(refresh_stats.get('remaining_invalid_rows', 0) or 0)
    if invalid_rows:
        resolved_invalid_rows = max(0, invalid_rows - remaining_invalid_rows)
        print(f"  Filas OHLCV severas reconsultadas: {resolved_invalid_rows}/{invalid_rows}")
        if remaining_invalid_rows:
            print(f"  Filas OHLCV severas restantes    : {remaining_invalid_rows}")
            for detail in (refresh_stats.get('remaining_details') or [])[:8]:
                print(f"    - {detail}")
        for detail in (refresh_stats.get('errors') or [])[:8]:
            print(f"    - refetch {detail}")
    print(f"  Filas OHLCV reparadas      : {repaired_rows}")

    if results.get("empty_details"):
        print("  Muestra sin datos:")
        for detail in results["empty_details"][:8]:
            print(f"    - {detail}")
    if results.get("errors"):
        print("  Muestra errores:")
        for detail in results["errors"][:8]:
            print(f"    - {detail}")

    print("\n  Backfill historico completado.")

    if args.skip_validate:
        return 0

    print("\n  Corriendo validate_market_data...\n")
    return run_validation(target_date.isoformat())


if __name__ == "__main__":
    raise SystemExit(main())
