from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

from infra.db.config import get_database_url
from infra.db.session import create_db_engine


def coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text_value = str(value).strip()
    if not text_value:
        return None
    return datetime.fromisoformat(text_value.replace("Z", "+00:00"))


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
    parser.add_argument(
        "--max-stale-hours",
        type=int,
        default=0,
        help="Fuerza refresh si el ultimo deploy tiene mas de N horas de antiguedad (0 = desactivado).",
    )
    return parser.parse_args()


def decide_cloud_refresh(*, database_url: str | None = None, force: bool = False, max_stale_hours: int = 0) -> dict[str, Any]:
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
            last_publish_finished_at = None
            if inspector.has_table("pipeline_runs"):
                row = connection.execute(
                    text(
                        """
                        SELECT latest_prices_date, run_id, finished_at
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
                    last_publish_finished_at = coerce_datetime(row[2])

            latest_snapshot_created_at = None
            if inspector.has_table("model_run_snapshots") and latest_prices_date is not None:
                latest_snapshot_created_at = coerce_datetime(
                    connection.execute(
                        text(
                            """
                            SELECT MAX(created_at)
                            FROM model_run_snapshots
                            WHERE analyzed_date = :analyzed_date
                            """
                        ),
                        {"analyzed_date": str(latest_prices_date)},
                    ).scalar()
                )

        latest_prices_text = str(latest_prices_date) if latest_prices_date is not None else None
        last_publish_finished_text = last_publish_finished_at.isoformat() if last_publish_finished_at is not None else None
        latest_snapshot_created_text = (
            latest_snapshot_created_at.isoformat() if latest_snapshot_created_at is not None else None
        )
        snapshot_newer_than_publish = bool(latest_snapshot_created_at) and (
            last_publish_finished_at is None or latest_snapshot_created_at > last_publish_finished_at
        )
        should_refresh = bool(force)
        if not should_refresh:
            should_refresh = bool(latest_prices_text) and latest_prices_text != last_publish_market_date
        if not should_refresh:
            should_refresh = snapshot_newer_than_publish
        stale_deploy = False
        if not should_refresh and max_stale_hours > 0:
            now_utc = datetime.now(tz=timezone.utc)
            if last_publish_finished_at is None:
                stale_deploy = True
            else:
                finished = last_publish_finished_at
                if finished.tzinfo is None:
                    finished = finished.replace(tzinfo=timezone.utc)
                elapsed_hours = (now_utc - finished) / timedelta(hours=1)
                stale_deploy = elapsed_hours > max_stale_hours
            if stale_deploy:
                should_refresh = True

        return {
            "backend": backend,
            "force": force,
            "latest_prices_date": latest_prices_text,
            "last_publish_market_date": last_publish_market_date,
            "last_publish_run_id": last_publish_run_id,
            "last_publish_finished_at": last_publish_finished_text,
            "latest_snapshot_created_at": latest_snapshot_created_text,
            "snapshot_newer_than_publish": snapshot_newer_than_publish,
            "stale_deploy": stale_deploy,
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
        max_stale_hours=args.max_stale_hours,
    )
    print(json.dumps(payload, ensure_ascii=True))
    if args.github_output:
        write_github_output(Path(args.github_output), payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
