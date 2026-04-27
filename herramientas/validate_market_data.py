#!/usr/bin/env python3
"""
VALIDAR CALIDAD DE DATOS DE MERCADO
==================================

Valida que titan.db este en condiciones antes de correr aprendizaje/scanner.

Checks actuales:
  - frescura global vs fecha objetivo de mercado
  - cobertura del universo esperado
  - tickers rezagados respecto a la ultima fecha global
  - OHLCV imposible y OHLCV dudoso en ventana reciente
  - corporate actions sospechosas
  - gaps raros recientes
  - metadata real de actualizacion de mercado

Salida:
  - exit code 0: solo PASS/WARN
  - exit code 1: existe al menos un FAIL

Uso:
  python herramientas/validate_market_data.py
  python herramientas/validate_market_data.py --expected-date YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from SCANNER import invertir_v11 as v11
from titan_system.core.data_loader import ACTIVOS, CONTEXT_TICKERS
from titan_system.core.database import TitanDB


LINE = "=" * 100
SUBLINE = "-" * 100
MARKET_CLOSE_HOUR = 19
RECENT_OHLC_DAYS = 15
GAP_LOOKBACK_DAYS = 30
SOFT_OHLC_FAIL_RATIO = 0.01
STALE_TICKER_FAIL_MIN = 5
STALE_TICKER_FAIL_RATIO = 0.02
KNOWN_OPTIONAL_TICKER_NOTES = {
    "SIEGY": "ADR fuera del universo operativo V11; puede rezagarse sin bloquear el pipeline.",
    "TEF": "Ticker excluido del universo descargable operativo por falta estructural de datos.",
}
KNOWN_CORPORATE_ACTION_EVENTS = {
    ("BKNG", "2026-04-02"): "Evento corporativo conocido y ya cuarentenado por el scanner.",
}
GAP_EXEMPT_TICKERS = {"VIX"}


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str]


def es_dia_bursatil(fecha: date) -> bool:
    return fecha.weekday() < 5


def dia_bursatil_anterior(fecha: date) -> date:
    cursor = fecha - timedelta(days=1)
    while not es_dia_bursatil(cursor):
        cursor -= timedelta(days=1)
    return cursor


def fecha_objetivo_mercado(ahora: datetime | None = None) -> date:
    ahora = ahora or datetime.now()
    hoy = ahora.date()

    if not es_dia_bursatil(hoy):
        return dia_bursatil_anterior(hoy)

    if ahora.hour < MARKET_CLOSE_HOUR:
        return dia_bursatil_anterior(hoy)

    return hoy


def business_days_between(start_date: date, end_date: date) -> int:
    if end_date <= start_date:
        return 0
    count = 0
    cursor = start_date + timedelta(days=1)
    while cursor <= end_date:
        if es_dia_bursatil(cursor):
            count += 1
        cursor += timedelta(days=1)
    return count


def build_required_universe() -> list[str]:
    return sorted(set(v11.UNIVERSE) | set(CONTEXT_TICKERS))


def build_optional_universe() -> list[str]:
    required = set(build_required_universe())
    return sorted(set(ACTIVOS) - required)


def check_global_freshness(latest_date: date | None, expected_date: date) -> CheckResult:
    if latest_date is None:
        return CheckResult(
            name="Frescura global",
            status="FAIL",
            summary="La DB no tiene fechas en la tabla prices.",
            details=[],
        )

    missing_days = business_days_between(latest_date, expected_date)
    if missing_days > 0:
        return CheckResult(
            name="Frescura global",
            status="FAIL",
            summary=(
                f"DB atrasada: ultima fecha {latest_date.isoformat()} vs objetivo {expected_date.isoformat()} "
                f"({missing_days} dias habiles)."
            ),
            details=["Actualizar antes de correr aprendizaje o scanner."],
        )

    return CheckResult(
        name="Frescura global",
        status="PASS",
        summary=f"DB al dia hasta {latest_date.isoformat()} (objetivo {expected_date.isoformat()}).",
        details=[],
    )


def check_universe_coverage(db: TitanDB) -> CheckResult:
    expected = build_required_universe()
    scan_only = len(set(v11.UNIVERSE))
    context_only = len(set(CONTEXT_TICKERS) - set(v11.UNIVERSE))
    available = set(db.get_all_tickers())
    missing = sorted(ticker for ticker in expected if ticker not in available)
    details: list[str] = [
        (
            f"Universo scanner V11: {scan_only} | Context tickers: {context_only} | "
            f"Universo extendido validacion: {len(expected)} | Presentes en DB: {len(available)} | "
            f"Faltantes operativos: {len(missing)}"
        )
    ]
    if missing:
        details.append("Faltantes operativos: " + ", ".join(missing[:15]))
        return CheckResult(
            name="Universo operativo",
            status="FAIL",
            summary=f"Faltan {len(missing)} tickers en el universo extendido que protege al scanner activo.",
            details=details,
        )
    return CheckResult(
        name="Universo operativo",
        status="PASS",
        summary=f"Cobertura completa del universo extendido de validacion ({len(expected)} tickers).",
        details=details,
    )


def check_optional_universe(db: TitanDB, latest_date: date) -> CheckResult:
    optional = set(build_optional_universe())
    available = set(db.get_all_tickers())
    missing = sorted(ticker for ticker in optional if ticker not in available)
    latest_df = db.execute_raw(
        """
        SELECT ticker, MAX(date) AS last_date, COUNT(*) AS rows
        FROM prices
        GROUP BY ticker
        ORDER BY ticker
        """
    )
    latest_df["last_date"] = pd.to_datetime(latest_df["last_date"]).dt.date
    stale = latest_df[(latest_df["ticker"].isin(optional)) & (latest_df["last_date"] < latest_date)].copy()

    if not missing and stale.empty:
        return CheckResult(
            name="Universo extendido",
            status="PASS",
            summary="Sin desalineaciones en el universo amplio fuera de V11.",
            details=[],
        )

    details = []
    for ticker in missing:
        note = KNOWN_OPTIONAL_TICKER_NOTES.get(ticker, "Ticker opcional fuera del universo operativo.")
        details.append(f"{ticker}: ausente | {note}")
    for row in stale.sort_values(["last_date", "ticker"]).itertuples(index=False):
        note = KNOWN_OPTIONAL_TICKER_NOTES.get(row.ticker, "Ticker opcional fuera del universo operativo.")
        details.append(f"{row.ticker}: ultimo {row.last_date.isoformat()} | filas {int(row.rows)} | {note}")

    return CheckResult(
        name="Universo extendido",
        status="INFO",
        summary="Hay tickers amplios no operativos con datos faltantes o rezagados, sin impacto en V11.",
        details=details[:12],
    )


def check_stale_tickers(db: TitanDB, latest_date: date) -> CheckResult:
    required = set(build_required_universe())
    latest_df = db.execute_raw(
        """
        SELECT ticker, MAX(date) AS last_date, COUNT(*) AS rows
        FROM prices
        GROUP BY ticker
        ORDER BY ticker
        """
    )
    latest_df["last_date"] = pd.to_datetime(latest_df["last_date"]).dt.date
    stale = latest_df[(latest_df["ticker"].isin(required)) & (latest_df["last_date"] < latest_date)].copy()

    if stale.empty:
        return CheckResult(
            name="Cobertura ultimo cierre",
            status="PASS",
            summary=f"Todos los tickers operativos tienen datos en {latest_date.isoformat()}.",
            details=[],
        )

    stale_count = int(len(stale))
    required_count = max(1, int(latest_df["ticker"].isin(required).sum()))
    fail_threshold = max(STALE_TICKER_FAIL_MIN, math.ceil(required_count * STALE_TICKER_FAIL_RATIO))
    details = [
        f"{row.ticker}: ultimo {row.last_date.isoformat()} | filas {int(row.rows)}"
        for row in stale.sort_values(["last_date", "ticker"]).itertuples(index=False)
    ]

    if "SPY" in stale["ticker"].values:
        return CheckResult(
            name="Cobertura ultimo cierre",
            status="FAIL",
            summary="SPY no tiene la ultima fecha global; el scanner no es confiable.",
            details=details[:10],
        )
    if stale_count >= fail_threshold:
        return CheckResult(
            name="Cobertura ultimo cierre",
            status="FAIL",
            summary=f"Hay {stale_count} tickers rezagados respecto a {latest_date.isoformat()}.",
            details=details[:15],
        )
    return CheckResult(
        name="Cobertura ultimo cierre",
        status="WARN",
        summary=f"Hay {stale_count} tickers rezagados respecto a {latest_date.isoformat()}.",
        details=details[:15],
    )


def load_recent_prices(db: TitanDB, latest_date: date, lookback_days: int) -> pd.DataFrame:
    start_date = latest_date - timedelta(days=lookback_days)
    df = db.execute_raw(
        """
        SELECT ticker, date, open, high, low, close, volume
        FROM prices
        WHERE date >= ?
        ORDER BY date ASC, ticker ASC
        """,
        (start_date.isoformat(),),
    )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def check_ohlcv_integrity(db: TitanDB, latest_date: date) -> list[CheckResult]:
    recent = load_recent_prices(db, latest_date, RECENT_OHLC_DAYS)
    if recent.empty:
        return [
            CheckResult(
                name="OHLCV severo",
                status="FAIL",
                summary="No hay datos recientes para validar integridad OHLCV.",
                details=[],
            )
        ]

    severe_mask = (
        (recent["open"] <= 0)
        | (recent["high"] <= 0)
        | (recent["low"] <= 0)
        | (recent["close"] <= 0)
        | (recent["volume"] < 0)
        | (recent["high"] < recent["low"])
    )
    severe = recent.loc[severe_mask].copy()

    price_ref = recent[["open", "close"]].abs().max(axis=1)
    tolerance = np.maximum(0.10, price_ref * 0.002)
    upper_ref = recent[["open", "close"]].max(axis=1)
    lower_ref = recent[["open", "close"]].min(axis=1)
    soft_mask = (~severe_mask) & (
        (recent["high"] + tolerance < upper_ref)
        | (recent["low"] - tolerance > lower_ref)
    )
    soft = recent.loc[soft_mask].copy()

    severe_details = [
        f"{row.ticker} {row.date.isoformat()} | O={row.open:.4f} H={row.high:.4f} L={row.low:.4f} C={row.close:.4f} V={int(row.volume)}"
        for row in severe.head(12).itertuples(index=False)
    ]
    soft_details = [
        f"{row.ticker} {row.date.isoformat()} | O={row.open:.4f} H={row.high:.4f} L={row.low:.4f} C={row.close:.4f} V={int(row.volume)}"
        for row in soft.head(12).itertuples(index=False)
    ]

    severe_result = CheckResult(
        name="OHLCV severo",
        status="FAIL" if not severe.empty else "PASS",
        summary=(
            f"{len(severe)} filas severamente invalidas en los ultimos {RECENT_OHLC_DAYS} dias."
            if not severe.empty
            else f"Sin filas OHLCV severamente invalidas en los ultimos {RECENT_OHLC_DAYS} dias."
        ),
        details=severe_details,
    )

    soft_ratio = float(len(soft) / len(recent)) if len(recent) else 0.0
    if soft.empty:
        soft_status = "PASS"
        soft_summary = f"Sin filas OHLCV dudosas en los ultimos {RECENT_OHLC_DAYS} dias."
    elif soft_ratio > SOFT_OHLC_FAIL_RATIO:
        soft_status = "FAIL"
        soft_summary = (
            f"{len(soft)} filas OHLCV dudosas ({soft_ratio:.2%}) superan el umbral tolerado "
            f"en {RECENT_OHLC_DAYS} dias."
        )
    else:
        soft_status = "WARN"
        soft_summary = (
            f"{len(soft)} filas OHLCV dudosas ({soft_ratio:.2%}) en los ultimos {RECENT_OHLC_DAYS} dias."
        )

    soft_result = CheckResult(
        name="OHLCV dudoso",
        status=soft_status,
        summary=soft_summary,
        details=soft_details,
    )

    return [severe_result, soft_result]


def compute_recent_event_rows(db: TitanDB, latest_date: date) -> pd.DataFrame:
    start_date = (latest_date - timedelta(days=GAP_LOOKBACK_DAYS)).isoformat()
    return db.execute_raw(
        """
        WITH recent AS (
            SELECT
                ticker,
                date,
                open,
                high,
                low,
                close,
                LAG(close) OVER (PARTITION BY ticker ORDER BY date) AS prev_close
            FROM prices
        )
        SELECT
            ticker,
            date,
            open,
            high,
            low,
            close,
            prev_close,
            CASE WHEN prev_close IS NOT NULL AND prev_close != 0 THEN (close / prev_close - 1.0) END AS ret1,
            CASE WHEN prev_close IS NOT NULL AND prev_close != 0 THEN (open / prev_close - 1.0) END AS gap_open,
            CASE WHEN open != 0 THEN (close / open - 1.0) END AS intraday,
            CASE WHEN open != 0 THEN ((high - low) / open) END AS range_pct
        FROM recent
        WHERE prev_close IS NOT NULL
          AND date >= ?
        ORDER BY date DESC, ticker ASC
        """,
        (start_date,),
    )


def check_corporate_actions_and_gaps(db: TitanDB, latest_date: date) -> list[CheckResult]:
    events = compute_recent_event_rows(db, latest_date)
    if events.empty:
        return [
            CheckResult("Corporate actions", "PASS", "Sin eventos recientes para revisar.", []),
            CheckResult("Gaps raros", "PASS", "Sin gaps raros recientes.", []),
        ]

    corp_mask = (
        events["ret1"].abs() >= 0.60
    ) & (
        events["intraday"].abs() < 0.15
    ) & (
        events["range_pct"] < 0.15
    )
    corp = events.loc[corp_mask].copy()

    gap_mask = (
        events["gap_open"].abs() >= 0.15
    ) & (~corp_mask) & (~events["ticker"].isin(GAP_EXEMPT_TICKERS))
    gaps = events.loc[gap_mask].copy()

    known_corp_mask = corp.apply(
        lambda row: (str(row["ticker"]), str(row["date"])) in KNOWN_CORPORATE_ACTION_EVENTS,
        axis=1,
    ) if not corp.empty else pd.Series(dtype=bool)
    known_corp = corp.loc[known_corp_mask].copy() if not corp.empty else corp.copy()
    corp = corp.loc[~known_corp_mask].copy() if not corp.empty else corp.copy()

    corp_details = [
        (
            f"{row.ticker} {row.date} | ret1 {row.ret1 * 100:+.1f}% | "
            f"intraday {row.intraday * 100:+.1f}% | rango {row.range_pct * 100:.1f}%"
        )
        for row in corp.head(8).itertuples(index=False)
    ]
    if not known_corp.empty:
        corp_details.extend(
            [
                f"{row.ticker} {row.date} | evento conocido: "
                f"{KNOWN_CORPORATE_ACTION_EVENTS.get((str(row.ticker), str(row.date)), 'ya cuarentenado')}"
                for row in known_corp.head(8).itertuples(index=False)
            ]
        )
    gap_details = [
        (
            f"{row.ticker} {row.date} | gap open {row.gap_open * 100:+.1f}% | "
            f"ret1 {row.ret1 * 100:+.1f}% | intraday {row.intraday * 100:+.1f}%"
        )
        for row in gaps.head(8).itertuples(index=False)
    ]

    corp_result = CheckResult(
        name="Corporate actions",
        status="WARN" if not corp.empty else "PASS",
        summary=(
            f"{len(corp)} eventos corporativos sospechosos en los ultimos {GAP_LOOKBACK_DAYS} dias."
            if not corp.empty
            else (
                f"Sin corporate actions sospechosas no explicadas en los ultimos {GAP_LOOKBACK_DAYS} dias."
                if known_corp.empty
                else f"Solo hay eventos corporativos ya conocidos/cuarentenados en los ultimos {GAP_LOOKBACK_DAYS} dias."
            )
        ),
        details=corp_details,
    )
    gap_result = CheckResult(
        name="Gaps raros",
        status="WARN" if not gaps.empty else "PASS",
        summary=(
            f"{len(gaps)} gaps raros >= 15% en los ultimos {GAP_LOOKBACK_DAYS} dias."
            if not gaps.empty
            else f"Sin gaps raros >= 15% en los ultimos {GAP_LOOKBACK_DAYS} dias."
        ),
        details=gap_details,
    )
    return [corp_result, gap_result]


def check_market_data_status(db: TitanDB, latest_date: date) -> CheckResult:
    status = db.get_market_data_status()
    latest_prices_date = status.get("latest_prices_date")
    updated_at = status.get("market_data_updated_at")

    if latest_prices_date == latest_date.isoformat() and updated_at:
        return CheckResult(
            name="Metadata mercado",
            status="PASS",
            summary=f"Metadata de mercado alineada con {latest_prices_date} ({updated_at}).",
            details=[],
        )

    details = []
    if latest_prices_date:
        details.append(f"latest_prices_date = {latest_prices_date}")
    if updated_at:
        details.append(f"market_data_updated_at = {updated_at}")
    if not details:
        details.append("Tabla data_status vacia o sin claves esperadas.")

    return CheckResult(
        name="Metadata mercado",
        status="WARN",
        summary="Falta metadata real de actualizacion o no coincide con la ultima fecha de precios.",
        details=details,
    )


def render_check(result: CheckResult) -> list[str]:
    lines = [f"[{result.status}] {result.name}: {result.summary}"]
    for detail in result.details:
        lines.append(f"  - {detail}")
    return lines


def run_validation(db: TitanDB, expected_date: date) -> tuple[list[CheckResult], date | None]:
    latest_text = db.execute_raw("SELECT MAX(date) AS max_date FROM prices").iloc[0, 0]
    if isinstance(latest_text, datetime):
        latest_date = latest_text.date()
    elif isinstance(latest_text, date):
        latest_date = latest_text
    else:
        latest_date = datetime.strptime(str(latest_text)[:10], "%Y-%m-%d").date() if latest_text else None

    checks: list[CheckResult] = []
    checks.append(check_global_freshness(latest_date, expected_date))
    if latest_date is None:
        return checks, None

    checks.append(check_universe_coverage(db))
    checks.append(check_optional_universe(db, latest_date))
    checks.append(check_stale_tickers(db, latest_date))
    checks.extend(check_ohlcv_integrity(db, latest_date))
    checks.extend(check_corporate_actions_and_gaps(db, latest_date))
    checks.append(check_market_data_status(db, latest_date))
    return checks, latest_date


def main() -> None:
    parser = argparse.ArgumentParser(description="Validar calidad de titan.db antes del pipeline diario.")
    parser.add_argument(
        "--expected-date",
        help="Fecha objetivo que deberia estar cerrada en la DB (YYYY-MM-DD). Si no se pasa, se calcula automaticamente.",
    )
    args = parser.parse_args()

    now = datetime.now()
    expected_date = (
        datetime.strptime(args.expected_date, "%Y-%m-%d").date()
        if args.expected_date
        else fecha_objetivo_mercado(now)
    )

    with TitanDB() as db:
        stats = db.db_stats()
        tickers_count = len(db.get_all_tickers())
        checks, latest_date = run_validation(db, expected_date)

    has_fail = any(check.status == "FAIL" for check in checks)
    has_warn = any(check.status == "WARN" for check in checks)

    print(LINE)
    print("  VALIDATE MARKET DATA")
    print(LINE)
    print(f"  Fecha validacion : {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Fecha objetivo   : {expected_date.isoformat()}")
    print(f"  Ultima fecha DB  : {latest_date.isoformat() if latest_date else 'sin datos'}")
    print(f"  Precios totales  : {stats.get('prices_count', 0):,}")
    print(f"  Tickers en DB    : {tickers_count}")
    print(SUBLINE)
    for check in checks:
        for line in render_check(check):
            print(line)
    print(SUBLINE)
    if has_fail:
        print("Resultado final: FAIL | Hay problemas que deben corregirse antes del pipeline.")
    elif has_warn:
        print("Resultado final: WARN | El pipeline puede continuar, pero conviene revisar las alertas.")
    else:
        print("Resultado final: PASS | La DB paso todos los checks productivos.")
    print(LINE)

    raise SystemExit(1 if has_fail else 0)


if __name__ == "__main__":
    main()
