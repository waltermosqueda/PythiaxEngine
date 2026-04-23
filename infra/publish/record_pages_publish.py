from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from herramientas.dashboard_paths import SNAPSHOT_PATH
from infra.db import get_database_url, start_pipeline_run
from infra.publish.dashboard_site import SITE_MANIFEST_NAME, read_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Registra en pipeline_runs la publicacion de GitHub Pages.")
    parser.add_argument("--site-dir", required=True, help="Directorio del site bundle publicado.")
    parser.add_argument("--page-url", default=None, help="URL final publicada por GitHub Pages.")
    return parser.parse_args()


def build_publish_metadata(site_manifest: dict[str, Any], snapshot: dict[str, Any], page_url: str | None) -> dict[str, Any]:
    build = site_manifest.get("build") or {}
    return {
        "generator": "infra.publish.record_pages_publish",
        "page_url": page_url,
        "entrypoint": site_manifest.get("entrypoint"),
        "published_files": site_manifest.get("published_files") or [],
        "source_manifest_name": site_manifest.get("source_manifest_name"),
        "source_artifact_count": site_manifest.get("source_artifact_count"),
        "dashboard_pipeline_run_id": build.get("pipeline_run_id"),
        "dashboard_workflow_run_id": build.get("run_id"),
        "dashboard_run_attempt": build.get("run_attempt"),
        "active_version": snapshot.get("operational_context", {}).get("active_version"),
        "reference_version": snapshot.get("operational_context", {}).get("reference_version"),
    }


def record_github_pages_publish(
    *,
    site_dir: Path,
    page_url: str | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    site_dir = site_dir.resolve()
    site_manifest = read_json(site_dir / SITE_MANIFEST_NAME)
    snapshot = read_json(site_dir / SNAPSHOT_PATH.name)
    build = site_manifest.get("build") or {}
    metadata_json = build_publish_metadata(site_manifest, snapshot, page_url)
    recorder = start_pipeline_run(
        "github_pages_publish",
        database_url=database_url or get_database_url(),
        active_scanner_version=str(snapshot.get("operational_context", {}).get("active_version") or ""),
        db_backend=build.get("db_backend"),
        run_date=site_manifest.get("generated_at"),
        metadata_json=metadata_json,
    )
    recorder.finish(
        status="SUCCESS",
        run_date=site_manifest.get("generated_at"),
        active_scanner_version=str(snapshot.get("operational_context", {}).get("active_version") or ""),
        db_backend=build.get("db_backend"),
        latest_prices_date=snapshot.get("integrity", {}).get("latest_market_date"),
        warnings_count=0,
        artifact_manifest=site_manifest,
        metadata_json=metadata_json,
    )
    return {
        "persisted": recorder.persisted,
        "run_id": recorder.run_id,
        "skipped_reason": recorder.skipped_reason,
        "error_message": recorder.error_message,
        "page_url": page_url,
    }


def main() -> int:
    args = parse_args()
    payload = record_github_pages_publish(
        site_dir=Path(args.site_dir),
        page_url=args.page_url,
    )
    if payload["persisted"]:
        print(f"github_pages_publish ledger: {payload['run_id']} | SUCCESS")
    elif payload["skipped_reason"]:
        print(f"github_pages_publish ledger: skipped ({payload['skipped_reason']})")
    else:
        print("github_pages_publish ledger: not persisted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
