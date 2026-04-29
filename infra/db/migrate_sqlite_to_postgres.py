from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
from time import sleep
from time import perf_counter
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, OperationalError

from infra.db import models  # noqa: F401
from infra.db.base import Base
from infra.db.config import get_database_url, get_sqlite_fallback_path
from infra.db.session import create_db_engine


TABLE_ORDER = [
    "prices",
    "predictions",
    "outcomes",
    "model_metrics",
    "regimes",
    "data_status",
    "pipeline_runs",
]
DELETE_ORDER = list(reversed(TABLE_ORDER))

JSON_COLUMNS: dict[str, tuple[str, ...]] = {
    "pipeline_runs": ("artifact_manifest", "metadata_json"),
}

DATE_COLUMNS: dict[str, tuple[str, ...]] = {
    "prices": ("date",),
    "predictions": ("prediction_date", "target_date"),
    "model_metrics": ("period_start", "period_end"),
    "regimes": ("date",),
    "pipeline_runs": ("run_date", "expected_market_date", "latest_prices_date"),
}

DATETIME_COLUMNS: dict[str, tuple[str, ...]] = {
    "predictions": ("created_at",),
    "outcomes": ("evaluated_at",),
    "model_metrics": ("calculated_at",),
    "data_status": ("updated_at",),
    "pipeline_runs": ("started_at", "finished_at", "created_at"),
}

FLOAT_COLUMNS: dict[str, tuple[str, ...]] = {
    "prices": ("open", "high", "low", "close", "adj_close"),
    "predictions": ("confidence", "score"),
    "outcomes": ("actual_return",),
    "model_metrics": (
        "accuracy",
        "avg_confidence",
        "avg_return_when_right",
        "avg_return_when_wrong",
        "profit_factor",
        "sharpe_ratio",
        "max_drawdown",
    ),
    "regimes": ("vix_level", "spy_return_20d"),
}

INTEGER_COLUMNS: dict[str, tuple[str, ...]] = {
    "prices": ("volume",),
    "predictions": ("id",),
    "outcomes": ("id", "prediction_id", "hit"),
    "model_metrics": ("id", "total_predictions", "correct_predictions"),
    "pipeline_runs": ("id", "rows_inserted", "warnings_count"),
}


@dataclass
class TableMigrationResult:
    table_name: str
    source_exists: bool
    source_rows: int
    inserted_rows: int
    target_rows: int
    skipped: bool = False


@dataclass
class MigrationReport:
    source_url: str
    target_url: str
    reset_target: bool
    ensure_schema: bool
    chunk_size: int
    tables: list[str]
    duration_seconds: float
    results: list[TableMigrationResult]


def sqlite_path_to_url(path: Path) -> str:
    return f"sqlite:///{path.resolve().as_posix()}"


def default_source_url() -> str:
    return sqlite_path_to_url(get_sqlite_fallback_path())


def build_engine(url: str) -> Engine:
    return create_db_engine(database_url=url)


def is_retryable_db_error(exc: Exception) -> bool:
    if isinstance(exc, DBAPIError) and getattr(exc, "connection_invalidated", False):
        return True
    if not isinstance(exc, (OperationalError, DBAPIError)):
        return False

    message = str(exc).lower()
    retryable_markers = [
        "adminshutdown",
        "terminating connection due to administrator command",
        "server closed the connection unexpectedly",
        "connection not open",
        "connection timed out",
        "timeout expired",
        "could not connect",
        "connection refused",
        "ssl connection has been closed unexpectedly",
    ]
    return any(marker in message for marker in retryable_markers)


def run_db_operation_with_retry(
    *,
    operation_name: str,
    engine: Engine,
    func: Any,
    attempts: int = 3,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_error = exc
            if not is_retryable_db_error(exc) or attempt >= attempts:
                raise
            engine.dispose()
            sleep(attempt * 2)
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Operacion retryable sin resultado: {operation_name}")


def normalize_table_names(table_names: list[str] | None) -> list[str]:
    if not table_names:
        return list(TABLE_ORDER)

    normalized: list[str] = []
    seen: set[str] = set()
    for table_name in table_names:
        if table_name not in TABLE_ORDER:
            valid = ", ".join(TABLE_ORDER)
            raise ValueError(f"Tabla no soportada: {table_name}. Validas: {valid}")
        if table_name not in seen:
            normalized.append(table_name)
            seen.add(table_name)
    return normalized


def redact_url(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, host = rest.rsplit("@", 1)
    if ":" not in credentials:
        return f"{scheme}://***@{host}"
    username, _ = credentials.split(":", 1)
    return f"{scheme}://{username}:***@{host}"


def normalize_date_value(value: Any) -> date | Any | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        try:
            return date.fromisoformat(text_value[:10])
        except ValueError:
            return value
    return value


def normalize_datetime_value(value: Any) -> datetime | Any | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        if text_value.endswith("Z"):
            text_value = text_value[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text_value)
        except ValueError:
            try:
                parsed = pd.Timestamp(text_value).to_pydatetime()
            except Exception:
                return value
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return value


def count_rows(engine: Engine, table_name: str) -> int:
    def operation() -> int:
        with engine.connect() as connection:
            return int(connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one())

    return int(
        run_db_operation_with_retry(
            operation_name=f"count_rows:{table_name}",
            engine=engine,
            func=operation,
        )
    )


def source_table_exists(engine: Engine, table_name: str) -> bool:
    return bool(inspect(engine).has_table(table_name))


def ensure_target_tables(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def reset_target_tables(engine: Engine, table_names: list[str]) -> None:
    selected = {table_name for table_name in table_names}
    for table_name in DELETE_ORDER:
        if table_name not in selected:
            continue
        if not inspect(engine).has_table(table_name):
            continue

        def operation(table_name: str = table_name) -> None:
            with engine.begin() as connection:
                connection.execute(text(f"DELETE FROM {table_name}"))

        run_db_operation_with_retry(
            operation_name=f"reset_target:{table_name}",
            engine=engine,
            func=operation,
        )


def normalize_chunk(table_name: str, chunk: pd.DataFrame) -> pd.DataFrame:
    normalized = chunk.where(pd.notna(chunk), None).copy()

    for column_name in JSON_COLUMNS.get(table_name, ()):
        if column_name not in normalized.columns:
            continue

        def parse_json(value: Any) -> Any:
            if value in (None, ""):
                return None
            if isinstance(value, (dict, list)):
                return value
            if isinstance(value, str):
                return json.loads(value)
            return value

        normalized[column_name] = normalized[column_name].apply(parse_json)

    for column_name in DATE_COLUMNS.get(table_name, ()):
        if column_name not in normalized.columns:
            continue
        normalized[column_name] = normalized[column_name].apply(normalize_date_value)

    for column_name in DATETIME_COLUMNS.get(table_name, ()):
        if column_name not in normalized.columns:
            continue
        normalized[column_name] = normalized[column_name].apply(normalize_datetime_value)

    for column_name in FLOAT_COLUMNS.get(table_name, ()):
        if column_name not in normalized.columns:
            continue
        series = pd.to_numeric(normalized[column_name], errors="coerce")
        normalized[column_name] = series.where(series.notna(), None)

    for column_name in INTEGER_COLUMNS.get(table_name, ()):
        if column_name not in normalized.columns:
            continue
        series = pd.to_numeric(normalized[column_name], errors="coerce")
        normalized[column_name] = series.apply(lambda value: int(value) if pd.notna(value) else None)

    return normalized


def adapt_chunk_for_target_backend(
    table_name: str,
    chunk: pd.DataFrame,
    *,
    target_backend: str,
) -> pd.DataFrame:
    if target_backend != "sqlite" or not JSON_COLUMNS.get(table_name):
        return chunk

    adapted = chunk.copy()
    for column_name in JSON_COLUMNS.get(table_name, ()):
        if column_name not in adapted.columns:
            continue
        adapted[column_name] = adapted[column_name].apply(
            lambda value: json.dumps(value, ensure_ascii=False)
            if isinstance(value, (dict, list))
            else value
        )
    return adapted


def resolve_insert_chunk_size(
    *,
    target_engine: Engine,
    normalized_chunk: pd.DataFrame,
    requested_chunk_size: int,
) -> int:
    if target_engine.dialect.name != "sqlite":
        return requested_chunk_size

    # SQLite tiene un limite bajo de bind params por sentencia. Como usamos
    # method="multi", ajustamos dinamicamente para no exceder el tope.
    safe_bind_limit = 900
    column_count = max(len(normalized_chunk.columns), 1)
    max_rows_per_insert = max(safe_bind_limit // column_count, 1)
    return max(1, min(requested_chunk_size, max_rows_per_insert))


def build_source_select_sql(source_engine: Engine, table_name: str) -> text:
    if not source_engine.dialect.name.startswith("postgres"):
        return text(f"SELECT * FROM {table_name}")

    columns = inspect(source_engine).get_columns(table_name)
    if not columns:
        return text(f"SELECT * FROM {table_name}")

    datetime_columns = set(DATETIME_COLUMNS.get(table_name, ()))
    select_parts: list[str] = []
    for column in columns:
        column_name = str(column["name"])
        if column_name in datetime_columns:
            select_parts.append(f"{column_name}::text AS {column_name}")
        else:
            select_parts.append(column_name)
    return text(f"SELECT {', '.join(select_parts)} FROM {table_name}")


def migrate_table(
    *,
    source_engine: Engine,
    target_engine: Engine,
    table_name: str,
    chunk_size: int,
) -> TableMigrationResult:
    if not source_table_exists(source_engine, table_name):
        target_rows = count_rows(target_engine, table_name) if source_table_exists(target_engine, table_name) else 0
        return TableMigrationResult(
            table_name=table_name,
            source_exists=False,
            source_rows=0,
            inserted_rows=0,
            target_rows=target_rows,
            skipped=True,
        )

    source_rows = count_rows(source_engine, table_name)
    inserted_rows = 0

    if source_rows == 0:
        target_rows = count_rows(target_engine, table_name)
        return TableMigrationResult(
            table_name=table_name,
            source_exists=True,
            source_rows=0,
            inserted_rows=0,
            target_rows=target_rows,
            skipped=False,
        )

    query = build_source_select_sql(source_engine, table_name)
    with source_engine.connect() as source_connection:
        chunk_iter = pd.read_sql_query(query, source_connection, chunksize=chunk_size)
        for chunk in chunk_iter:
            normalized_chunk = normalize_chunk(table_name, chunk)
            prepared_chunk = adapt_chunk_for_target_backend(
                table_name,
                normalized_chunk,
                target_backend=target_engine.dialect.name,
            )
            insert_chunk_size = resolve_insert_chunk_size(
                target_engine=target_engine,
                normalized_chunk=prepared_chunk,
                requested_chunk_size=chunk_size,
            )

            run_db_operation_with_retry(
                operation_name=f"insert_chunk:{table_name}",
                engine=target_engine,
                func=lambda prepared_chunk=prepared_chunk, insert_chunk_size=insert_chunk_size: prepared_chunk.to_sql(
                    table_name,
                    target_engine,
                    if_exists="append",
                    index=False,
                    chunksize=insert_chunk_size,
                    method="multi",
                ),
            )
            inserted_rows += len(prepared_chunk.index)

    target_rows = count_rows(target_engine, table_name)
    return TableMigrationResult(
        table_name=table_name,
        source_exists=True,
        source_rows=source_rows,
        inserted_rows=inserted_rows,
        target_rows=target_rows,
        skipped=False,
    )


def migrate_sqlite_to_target(
    *,
    source_url: str,
    target_url: str,
    table_names: list[str] | None = None,
    chunk_size: int = 5000,
    reset_target: bool = False,
    ensure_schema: bool = False,
) -> MigrationReport:
    selected_tables = normalize_table_names(table_names)
    started = perf_counter()

    source_engine = build_engine(source_url)
    target_engine = build_engine(target_url)

    try:
        if ensure_schema:
            ensure_target_tables(target_engine)

        missing_in_target = [
            table_name
            for table_name in selected_tables
            if not source_table_exists(target_engine, table_name)
        ]
        if missing_in_target:
            joined = ", ".join(missing_in_target)
            raise RuntimeError(
                "Faltan tablas en el target. Ejecuta `alembic upgrade head` o usa "
                f"`--ensure-schema`. Tablas faltantes: {joined}"
            )

        if reset_target:
            reset_target_tables(target_engine, selected_tables)

        results = [
            migrate_table(
                source_engine=source_engine,
                target_engine=target_engine,
                table_name=table_name,
                chunk_size=chunk_size,
            )
            for table_name in selected_tables
        ]
    finally:
        source_engine.dispose()
        target_engine.dispose()

    duration_seconds = round(perf_counter() - started, 3)
    return MigrationReport(
        source_url=redact_url(source_url),
        target_url=redact_url(target_url),
        reset_target=reset_target,
        ensure_schema=ensure_schema,
        chunk_size=chunk_size,
        tables=selected_tables,
        duration_seconds=duration_seconds,
        results=results,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migra datos operativos desde SQLite hacia un target SQLAlchemy, pensado para Postgres cloud (por ejemplo Supabase).",
    )
    parser.add_argument(
        "--source-sqlite-path",
        type=Path,
        default=get_sqlite_fallback_path(),
        help="Ruta al archivo SQLite fuente. Default: SQLite fallback configurado.",
    )
    parser.add_argument(
        "--target-url",
        default=get_database_url(),
        help="URL SQLAlchemy del target. Default: DATABASE_URL actual.",
    )
    parser.add_argument(
        "--tables",
        nargs="*",
        choices=TABLE_ORDER,
        help="Subset de tablas a migrar. Default: todas las tablas soportadas.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=5000,
        help="Cantidad de filas por chunk durante la migracion.",
    )
    parser.add_argument(
        "--reset-target",
        action="store_true",
        help="Borra los datos existentes de las tablas seleccionadas antes de migrar.",
    )
    parser.add_argument(
        "--ensure-schema",
        action="store_true",
        help="Crea las tablas target desde SQLAlchemy metadata si todavia no existen.",
    )
    parser.add_argument(
        "--allow-sqlite-target",
        action="store_true",
        help="Permite usar SQLite como target para smoke tests locales. No recomendado para cutover.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Ruta opcional para escribir un reporte JSON con el resultado de la migracion.",
    )
    return parser


def print_report(report: MigrationReport) -> None:
    print("=" * 100)
    print("  SQLITE -> TARGET MIGRATION REPORT")
    print("=" * 100)
    print(f"  Source        : {report.source_url}")
    print(f"  Target        : {report.target_url}")
    print(f"  Reset target  : {report.reset_target}")
    print(f"  Ensure schema : {report.ensure_schema}")
    print(f"  Chunk size    : {report.chunk_size}")
    print(f"  Duration (s)  : {report.duration_seconds}")
    print("-" * 100)
    for result in report.results:
        state = "SKIP" if result.skipped else "OK"
        print(
            f"  [{state}] {result.table_name:<14} "
            f"source={result.source_rows:<8} inserted={result.inserted_rows:<8} target={result.target_rows:<8}"
        )
    print("=" * 100)


def write_report(path: Path, report: MigrationReport) -> None:
    payload = {
        **asdict(report),
        "results": [asdict(result) for result in report.results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    source_url = sqlite_path_to_url(args.source_sqlite_path)
    target_url = args.target_url

    if source_url == target_url:
        parser.error("El source y el target no pueden ser el mismo backend.")

    if target_url.startswith("sqlite:") and not args.allow_sqlite_target:
        parser.error(
            "El target es SQLite. Usa --allow-sqlite-target solo para smoke tests locales. "
            "Para produccion, apunta a un Postgres cloud, por ejemplo Supabase."
        )

    report = migrate_sqlite_to_target(
        source_url=source_url,
        target_url=target_url,
        table_names=args.tables,
        chunk_size=args.chunk_size,
        reset_target=args.reset_target,
        ensure_schema=args.ensure_schema,
    )
    print_report(report)

    mismatches = [
        result
        for result in report.results
        if result.source_exists and result.source_rows != result.target_rows
    ]
    if args.report_path:
        write_report(args.report_path, report)

    if mismatches:
        print("  [ERROR] Hay tablas con conteos inconsistentes entre source y target.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
