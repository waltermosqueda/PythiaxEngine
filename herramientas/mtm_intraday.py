#!/usr/bin/env python3
"""
MTM INTRADAY REFRESH
====================
Script liviano que actualiza los precios de cierre provisorio (intraday) para
los tickers con picks abiertos (sin outcome resuelto), permitiendo que el
dashboard muestre retornos MTM en tiempo real durante la jornada bursátil.

Qué hace:
  1. Lee de la DB los tickers con predicciones abiertas (sin outcome aun)
  2. Descarga el último precio disponible de Yahoo Finance vía yfinance
  3. Hace un upsert de ese precio en la tabla `prices` con la fecha de hoy
  4. Nada más — el snapshot se regenera en el siguiente paso del workflow

NO corre modelos ML, NO descarga OHLCV histórico, NO corre Alembic.
Tiempo estimado: 15–45 segundos dependiendo del universo de tickers.

Uso:
    python herramientas/mtm_intraday.py
    python herramientas/mtm_intraday.py --dry-run   # muestra precios sin guardar
    python herramientas/mtm_intraday.py --days-back 5  # busca picks de últimos N días
"""
from __future__ import annotations

import argparse
import sys
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import yfinance as yf

from infra.db.config import get_database_url
from infra.db.session import create_session_factory
from infra.db.models import Price
from sqlalchemy.dialects.postgresql import insert as pg_insert


# ── helpers ──────────────────────────────────────────────────────────────────

def _is_market_day(d: date) -> bool:
    return d.weekday() < 5  # lun-vie


def _log(msg: str) -> None:
    print(f"[mtm_intraday] {msg}", flush=True)


# ── core logic ────────────────────────────────────────────────────────────────

def fetch_open_tickers(session: Any, days_back: int) -> list[str]:
    """
    Devuelve los tickers con predicciones abiertas (sin outcome resuelto)
    cuya prediction_date esté dentro de los últimos `days_back` días hábiles.
    Sólo UP predictions — si hay DOWN en el universo también se incluyen para
    poder calcular MTM correctamente.
    """
    cutoff = date.today() - timedelta(days=days_back * 2)  # margen amplio
    sql = """
        SELECT DISTINCT p.ticker
        FROM predictions p
        LEFT JOIN outcomes o ON o.prediction_id = p.id
        WHERE o.actual_return IS NULL
          AND p.target_date >= :cutoff
        ORDER BY p.ticker
    """
    result = session.execute(
        __import__("sqlalchemy").text(sql),
        {"cutoff": str(cutoff)},
    )
    return [row[0] for row in result.fetchall()]


def _extract_from_download(data: object, tickers: list[str]) -> dict[str, float]:
    """Extrae precios no-NaN del DataFrame descargado por yfinance."""
    result: dict[str, float] = {}
    if data is None:
        return result
    try:
        import pandas as pd  # ya está en requirements; import local para evitar circular
        if not hasattr(data, "empty") or data.empty:  # type: ignore[union-attr]
            return result
        close_col = data.get("Close", data.get("close"))  # type: ignore[union-attr]
        if close_col is None or close_col.empty:
            return result
        last_row = close_col.iloc[-1]
        if hasattr(last_row, "items"):
            for ticker, price in last_row.items():
                if price and price == price:  # not NaN
                    result[str(ticker)] = float(price)
        else:
            # Single-ticker: close_col es una Series con timestamps
            if last_row and last_row == last_row:
                result[tickers[0]] = float(last_row)
    except Exception:
        pass
    return result


def download_live_prices(tickers: list[str]) -> dict[str, float]:
    """
    Descarga el último precio disponible de Yahoo Finance para cada ticker.
    Usa period='1d' + interval='1m' para obtener el precio intraday más reciente.
    Fallback a period='5d' interval='1d' para los tickers que faltan, luego
    fast_info ticker a ticker para los que aún queden sin precio.
    """
    if not tickers:
        return {}

    prices: dict[str, float] = {}
    _log(f"Descargando precios live para {len(tickers)} tickers: {', '.join(tickers)}")

    # ── Intento 1: batch intraday 1 minuto ────────────────────────────────────
    try:
        data = yf.download(
            tickers=" ".join(tickers),
            period="1d",
            interval="1m",
            progress=False,
            auto_adjust=True,
        )
        prices.update(_extract_from_download(data, tickers))
        _log(f"  Precios intraday (1m): {len(prices)}/{len(tickers)}")
    except Exception as exc:
        _log(f"  [WARN] Fallo descarga 1m: {exc}")

    # ── Intento 2: batch diario 5d para los tickers aún sin precio ────────────
    missing = [t for t in tickers if t not in prices]
    if missing:
        try:
            data = yf.download(
                tickers=" ".join(missing),
                period="5d",
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            prices.update(_extract_from_download(data, missing))
            _log(f"  Precios diarios (5d fallback): {len(prices)}/{len(tickers)}")
        except Exception as exc:
            _log(f"  [WARN] Fallo descarga 5d/1d: {exc}")

    # ── Intento 3: fast_info ticker a ticker para los que aún falten ──────────
    missing = [t for t in tickers if t not in prices]
    if missing:
        _log(f"  fast_info individual para {len(missing)} tickers restantes: {missing}")
        for ticker in missing:
            try:
                info = yf.Ticker(ticker).fast_info
                price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
                if price:
                    prices[ticker] = float(price)
            except Exception:
                pass

    missing_final = [t for t in tickers if t not in prices]
    if missing_final:
        _log(f"  [WARN] Sin precio para: {missing_final}")

    return prices


def upsert_prices(session: Any, price_map: dict[str, float], trade_date: date) -> int:
    """
    Inserta o actualiza la tabla `prices` con los precios intraday de hoy.
    Usa ON CONFLICT DO UPDATE para ser idempotente (se puede llamar múltiples
    veces en el día y siempre actualiza al precio más reciente).
    """
    if not price_map:
        return 0

    rows = [
        {
            "ticker": ticker,
            "date": trade_date,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": None,
            "adj_close": price,
        }
        for ticker, price in price_map.items()
    ]

    stmt = pg_insert(Price).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker", "date"],
        set_={
            "open":      stmt.excluded.open,
            "high":      stmt.excluded.high,
            "low":       stmt.excluded.low,
            "close":     stmt.excluded.close,
            "adj_close": stmt.excluded.adj_close,
        },
    )
    session.execute(stmt)
    session.commit()
    return len(rows)


# ── entry point ───────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Actualiza precios MTM intraday en Supabase.")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra precios descargados sin escribir en la DB.",
    )
    p.add_argument(
        "--days-back",
        type=int,
        default=10,
        help="Busca picks abiertos con target_date en los últimos N días (default: 10).",
    )
    p.add_argument(
        "--tickers",
        type=str,
        default="",
        help="Lista manual de tickers separados por coma (sobreescribe la detección automática).",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    today = date.today()

    _log(f"Inicio — fecha: {today} | dry_run={args.dry_run}")

    if not _is_market_day(today):
        _log("Hoy no es día hábil (fin de semana). Sin acción.")
        return 0

    database_url = get_database_url()
    if not database_url or "localhost" in database_url:
        require_cloud = os.environ.get("PYTHIAX_REQUIRE_CLOUD_DB", "0")
        if require_cloud == "1":
            _log("ERROR: DATABASE_URL apunta a localhost pero PYTHIAX_REQUIRE_CLOUD_DB=1")
            return 1
        _log("[WARN] DATABASE_URL parece local — ejecutando de todas formas.")

    SessionFactory = create_session_factory()

    with SessionFactory() as session:
        # ── 1. Obtener tickers abiertos ─────────────────────────────────────
        if args.tickers:
            tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
            _log(f"Tickers manuales: {tickers}")
        else:
            tickers = fetch_open_tickers(session, days_back=args.days_back)
            _log(f"Tickers con picks abiertos (últimos {args.days_back} días): {tickers or '(ninguno)'}")

        if not tickers:
            _log("No hay tickers abiertos. Sin acción.")
            return 0

        # ── 2. Descargar precios live ────────────────────────────────────────
        price_map = download_live_prices(tickers)

        if not price_map:
            _log("No se pudo obtener ningún precio. Abortando sin escribir.")
            return 1

        # Reporte
        missing = [t for t in tickers if t not in price_map]
        for ticker, price in sorted(price_map.items()):
            _log(f"  {ticker:<8} → ${price:.4f}")
        if missing:
            _log(f"  [WARN] Sin precio para: {', '.join(missing)}")

        # ── 3. Upsert en DB ──────────────────────────────────────────────────
        if args.dry_run:
            _log(f"DRY RUN — no se escribió nada en la DB ({len(price_map)} precios listos).")
            return 0

        n = upsert_prices(session, price_map, today)
        _log(f"Upsert completado: {n} filas en prices para fecha {today}.")

    _log("Fin OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
