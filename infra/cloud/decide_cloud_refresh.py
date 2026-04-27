from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

from infra.db.config import get_database_url
from infra.db.session import create_db_engine


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Decide si el workflow cloud debe reconstruir y publicar el dashboard."
    )
    parser.add_argument("--database-url", default=None, help="DATABASE_URL a consultar.")
    parser.add_argument(
        "--github-output",
        default=None,
        help="Ruta del archivo GITHUB_OUTPUT para exportar outputs del workflow.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fuerza el refresh aunque la ultima publicacion ya coincida.",
    )
    return parser.parse_args()


def decide_cloud_refresh(*, database_url: str | None = None, force: bool = False) -> dict[str, Any]:
    engine = create_db_engine(database_url=database_url or get_database_url())
    try:
        backend = engine.dialect.name
        inspector = inspect(engine)
        with engine.connect() as connection:
            latest_prices_date = connection.execute(
                text("SELECT value FROM data_status WHERE key = 'latest_prices_date'")
            ).scalar()

            last_publish_market_date = None
            last_publish_run_id = None
            if inspector.has_table("pipeline_runs"):
                row = connection.execute(
                    text(
                        """
                        SELECT latest_prices_date, run_id
                        FROM pipeline_runs
                        WHERE pipeline_name = 'github_pages_publish' AND status = 'SUCCESS'
                        ORDER BY finished_at DESC NULLS LAST, created_at DESC
                        LIMIT 1
                        """
                    )
                ).fetchone()
                if row is not None:
                    last_publish_market_date = str(row[0]) if row[0] is not None else None
                    last_publish_run_id = row[1]

        latest_prices_text = str(latest_prices_date) if latest_prices_date is not None else None
        should_refresh = bool(force)
        if not should_refresh:
            should_refresh = bool(latest_prices_text) and latest_prices_text != last_publish_market_date

        return {
            "backend": backend,
            "force": force,
            "latest_prices_date": latest_prices_text,
            "last_publish_market_date": last_publish_market_date,
            "last_publish_run_id": last_publish_run_id,
            "should_refresh": should_refresh,
        }
    finally:
        engine.dispose()


def write_github_output(path: Path, payload: dict[str, Any]) -> None:
    lines = []
    for key, value in payload.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif value is None:
            rendered = ""
        else:
            rendered = str(value)
        lines.append(f"{key}={rendered}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    payload = decide_cloud_refresh(
        database_url=args.database_url,
        force=bool(args.force),
    )
    print(json.dumps(payload, ensure_ascii=True))
    if args.github_output:
        write_github_output(Path(args.github_output), payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
