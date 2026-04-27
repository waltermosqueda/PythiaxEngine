from __future__ import annotations

import argparse
from pathlib import Path

from infra.db.config import get_database_url, get_sqlite_fallback_path
from infra.db.migrate_sqlite_to_postgres import (
    TABLE_ORDER,
    MigrationReport,
    migrate_sqlite_to_target,
    redact_url,
    sqlite_path_to_url,
    write_report,
)


def bootstrap_sqlite_from_target(
    *,
    source_url: str,
    target_sqlite_path: Path,
    table_names: list[str] | None = None,
    chunk_size: int = 5000,
    reset_target: bool = False,
) -> MigrationReport:
    target_path = target_sqlite_path.resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_url = sqlite_path_to_url(target_path)

    if source_url == target_url:
        raise ValueError("El source y el target SQLite no pueden ser el mismo backend.")

    return migrate_sqlite_to_target(
        source_url=source_url,
        target_url=target_url,
        table_names=table_names,
        chunk_size=chunk_size,
        reset_target=reset_target,
        ensure_schema=True,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materializa una SQLite runner-local a partir del target cloud para ejecutar "
            "la cadena legacy sin depender de una PC local."
        ),
    )
    parser.add_argument(
        "--source-url",
        default=get_database_url(),
        help="URL SQLAlchemy del target cloud. Default: DATABASE_URL actual.",
    )
    parser.add_argument(
        "--target-sqlite-path",
        type=Path,
        default=get_sqlite_fallback_path(),
        help="Ruta del archivo SQLite destino. Default: SQLite fallback configurado.",
    )
    parser.add_argument(
        "--tables",
        nargs="*",
        choices=TABLE_ORDER,
        help="Subset de tablas a copiar. Default: todas las tablas soportadas.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=5000,
        help="Cantidad de filas por chunk durante el bootstrap.",
    )
    parser.add_argument(
        "--reset-target",
        action="store_true",
        help="Borra el SQLite destino antes de copiar los datos.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Ruta opcional para escribir un reporte JSON.",
    )
    return parser


def print_report(report: MigrationReport, target_sqlite_path: Path) -> None:
    print("=" * 100)
    print("  TARGET -> SQLITE RUNNER BOOTSTRAP REPORT")
    print("=" * 100)
    print(f"  Source        : {report.source_url}")
    print(f"  Target        : {target_sqlite_path.resolve()}")
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


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    report = bootstrap_sqlite_from_target(
        source_url=args.source_url,
        target_sqlite_path=args.target_sqlite_path,
        table_names=args.tables,
        chunk_size=args.chunk_size,
        reset_target=args.reset_target,
    )
    print_report(report, args.target_sqlite_path)

    if args.report_path:
        write_report(args.report_path, report)

    mismatches = [
        result
        for result in report.results
        if result.source_exists and result.source_rows != result.target_rows
    ]
    if mismatches:
        print("  [ERROR] Hay tablas con conteos inconsistentes entre source cloud y SQLite runner.")
        return 1

    print(f"  Source URL    : {redact_url(args.source_url)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
