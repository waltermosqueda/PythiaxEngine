from __future__ import annotations

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config

from infra.db.config import get_database_url, get_sqlite_fallback_path
from infra.db.migrate_sqlite_to_postgres import (
    MigrationReport,
    migrate_sqlite_to_target,
    print_report,
    sqlite_path_to_url,
    write_report,
)


ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = ROOT / "alembic.ini"


def run_alembic_upgrade(target_url: str) -> None:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("sqlalchemy.url", target_url)
    command.upgrade(config, "head")


def ensure_report_consistency(report: MigrationReport) -> None:
    mismatches = [
        result
        for result in report.results
        if result.source_exists and result.source_rows != result.target_rows
    ]
    if not mismatches:
        return

    joined = ", ".join(
        f"{result.table_name}: source={result.source_rows}, target={result.target_rows}"
        for result in mismatches
    )
    raise RuntimeError(f"Bootstrap inconsistente entre source y target: {joined}")


def bootstrap_target_from_sqlite(
    *,
    source_sqlite_path: Path,
    target_url: str,
    chunk_size: int = 5000,
    reset_target: bool = False,
    allow_sqlite_target: bool = False,
    report_path: Path | None = None,
) -> MigrationReport:
    source_path = source_sqlite_path.resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"No existe la DB fuente SQLite: {source_path}")

    if target_url.startswith("sqlite:") and not allow_sqlite_target:
        raise ValueError(
            "El target es SQLite. Usa --allow-sqlite-target solo para smoke tests locales. "
            "Para bootstrap real apunta a Neon/Postgres."
        )

    run_alembic_upgrade(target_url)
    report = migrate_sqlite_to_target(
        source_url=sqlite_path_to_url(source_path),
        target_url=target_url,
        chunk_size=chunk_size,
        reset_target=reset_target,
        ensure_schema=False,
    )
    ensure_report_consistency(report)

    if report_path is not None:
        write_report(report_path, report)

    return report


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap controlado de target SQLAlchemy desde la SQLite operativa local.",
    )
    parser.add_argument(
        "--source-sqlite-path",
        type=Path,
        default=get_sqlite_fallback_path(),
        help="Ruta a la SQLite fuente. Default: fallback configurado.",
    )
    parser.add_argument(
        "--target-url",
        default=get_database_url(),
        help="URL SQLAlchemy del target. Default: DATABASE_URL actual.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=5000,
        help="Filas por chunk para la carga inicial.",
    )
    parser.add_argument(
        "--reset-target",
        action="store_true",
        help="Vacía las tablas target antes de cargar.",
    )
    parser.add_argument(
        "--allow-sqlite-target",
        action="store_true",
        help="Permite target SQLite solo para smoke tests locales.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Ruta opcional para escribir el reporte JSON de bootstrap.",
    )
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    report = bootstrap_target_from_sqlite(
        source_sqlite_path=args.source_sqlite_path,
        target_url=args.target_url,
        chunk_size=args.chunk_size,
        reset_target=args.reset_target,
        allow_sqlite_target=args.allow_sqlite_target,
        report_path=args.report_path,
    )
    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
