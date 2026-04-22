#!/usr/bin/env python3
"""
ACTUALIZAR BASE DE DATOS DE MERCADO
==================================
Descarga los datos mas recientes de Yahoo Finance y los guarda en titan.db.

Ubicacion: herramientas/actualizar_datos.py
Modo de uso:
    python herramientas/actualizar_datos.py

Que hace:
  1. Abre titan_system/data/titan.db
  2. Revisa la ultima fecha que tiene cada ticker
  3. Descarga solo los dias nuevos desde esa fecha
  4. Guarda en la DB y muestra estadisticas

Tiempo estimado: 1-3 min.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

# Subir un nivel desde herramientas/ a la raiz del proyecto.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from titan_system.core.database import TitanDB
from titan_system.core.data_loader import DataLoader


# Hora local a partir de la cual el mercado de NY se considera cerrado con seguridad.
# NYSE cierra 16:00 ET. En verano (EDT, UTC-4) eso es 17:00 Argentina (UTC-3).
# En invierno (EST, UTC-5) eso es 18:00 Argentina (UTC-3).
# Con MARKET_CLOSE_HOUR=19 el pipeline de Task Scheduler (19:15) funciona siempre.
# Si necesitas forzar hoy antes de esa hora usa --force-today.
MARKET_CLOSE_HOUR = 19


def es_dia_bursatil(fecha):
    return fecha.weekday() < 5


def dia_bursatil_anterior(fecha):
    cursor = fecha - timedelta(days=1)
    while not es_dia_bursatil(cursor):
        cursor -= timedelta(days=1)
    return cursor


def fecha_objetivo_mercado(ahora=None, force_today: bool = False):
    ahora = ahora or datetime.now()
    hoy = ahora.date()

    if not es_dia_bursatil(hoy):
        return dia_bursatil_anterior(hoy)

    if force_today:
        return hoy

    if ahora.hour < MARKET_CLOSE_HOUR:
        return dia_bursatil_anterior(hoy)

    return hoy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Actualiza titan.db con datos de Yahoo Finance.")
    parser.add_argument(
        "--force-today",
        action="store_true",
        help=(
            "Fuerza descargar los datos de HOY ignorando MARKET_CLOSE_HOUR. "
            "Usar cuando el mercado ya cerro pero son antes de las 19:00 locales "
            "(tipico en verano: NYSE cierra ~17:00 Argentina)."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now = datetime.now()
    target_date = fecha_objetivo_mercado(now, force_today=args.force_today)
    exit_code = 0

    print("=" * 60)
    print("  ACTUALIZAR BASE DE DATOS DE MERCADO")
    print(f"  {now.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    with TitanDB() as db:
        stats = db.db_stats()
        ultima_antes = db.execute_raw("SELECT MAX(date) AS max_date FROM prices").iloc[0, 0]
        print("\n  Estado actual:")
        print(f"  Registros: {stats.get('prices_count', 0):,}")
        print(f"  Rango:     {stats.get('price_date_range', 'sin datos')}")
        print(f"  Tamano:    {stats.get('db_size_mb', 0):.1f} MB")
        print(f"  Objetivo:  cerrar hasta {target_date.isoformat()}")

        loader = DataLoader(db, years_history=2, max_workers=10)
        results = loader.update_daily(end_date=target_date.isoformat())
        repair_start = (target_date - timedelta(days=45)).isoformat()
        repaired_rows = db.repair_ohlcv_bounds(start_date=repair_start, end_date=target_date.isoformat())

        stats = db.db_stats()
        ultima_despues = db.execute_raw("SELECT MAX(date) AS max_date FROM prices").iloc[0, 0]
        print("\n  Estado actualizado:")
        print(f"  Registros: {stats.get('prices_count', 0):,}")
        print(f"  Rango:     {stats.get('price_date_range', 'sin datos')}")
        print(f"  Tamano:    {stats.get('db_size_mb', 0):.1f} MB")

        print(f"\n  Filas nuevas agregadas: {results.get('total_rows', 0):,}")
        if repaired_rows:
            print(f"  Filas OHLCV reparadas: {repaired_rows}")
        if results.get('empty', 0) > 0:
            print(f"  Tickers sin datos: {results['empty']}")
        if results.get('failed', 0) > 0:
            print(f"  Tickers con error: {results['failed']}")
        if ultima_antes and ultima_antes < target_date.isoformat() and results.get('total_rows', 0) == 0:
            print("  [ALERTA] No hubo avance real en la DB pese a faltar ruedas cerradas.")
            print(f"  [ALERTA] DB en {ultima_antes}, objetivo {target_date.isoformat()}.")
            print("  [ALERTA] Si el mercado ya cerro y son antes de las 19:00, re-ejecuta con --force-today")
            exit_code = 2
        elif ultima_despues:
            print(f"  Ultima fecha final: {ultima_despues}")
            if ultima_despues < target_date.isoformat():
                print("  [ALERTA] La DB sigue por detras de la fecha objetivo.")
                print(f"  [ALERTA] DB en {ultima_despues}, objetivo {target_date.isoformat()}.")
                print("  [ALERTA] Si el mercado ya cerro y son antes de las 19:00, re-ejecuta con --force-today")
                exit_code = 2

        if ultima_despues:
            market_status = db.get_market_data_status()
            needs_metadata = (
                market_status.get("latest_prices_date") != ultima_despues
                or not market_status.get("market_data_updated_at")
            )
            if ultima_antes != ultima_despues or needs_metadata:
                db.save_market_data_update(ultima_despues)

    print("\n  Listo. DB actualizada.")
    print("  Validar DB    : python herramientas/validate_market_data.py")
    print("  Ejecutar scanner: python SCANNER/invertir_v11.py")
    print("=" * 60)
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
