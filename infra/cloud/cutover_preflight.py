from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from analisis.generar_tablero_maquina_pensante import generate_dashboard_bundle
from herramientas.dashboard_paths import DASHBOARD_DIR
from infra.db import get_database_url, start_pipeline_run
from infra.db.bootstrap_target import bootstrap_target_from_sqlite
from infra.db.config import get_sqlite_fallback_path
from infra.db.runtime import RuntimeDB
from infra.db.session import create_db_engine
from infra.publish.dashboard_site import SITE_MANIFEST_NAME, stage_dashboard_site


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_PATH = ROOT / "docs" / "cloud" / "reports" / "cutover_preflight_report.json"
DEFAULT_BOOTSTRAP_REPORT_PATH = ROOT / "docs" / "cloud" / "reports" / "sqlite_to_target_bootstrap.json"
DEFAULT_PAGES_OUTPUT_DIR = ROOT / "dist" / "cutover-preflight-pages"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Orquesta bootstrap, smoke cloud, dashboard build y site bundle para preflight de cutover.",
    )
    parser.add_argument(
        "--source-sqlite-path",
        type=Path,
        default=get_sqlite_fallback_path(),
        help="Ruta de la SQLite fuente operativa.",
    )
    parser.add_argument(
        "--target-url",
        default=get_database_url(),
        help="URL SQLAlchemy del target.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=5000,
        help="Filas por chunk para el bootstrap.",
    )
    parser.add_argument(
        "--variant",
        choices=["all", "executive", "lab"],
        default="all",
        help="Variante del dashboard a generar.",
    )
    parser.add_argument(
        "--reset-target",
        action="store_true",
        help="Vacia el target antes del bootstrap.",
    )
    parser.add_argument(
        "--allow-sqlite-target",
        action="store_true",
        help="Permite usar SQLite como target para smoke tests locales.",
    )
    parser.add_argument(
        "--skip-bootstrap",
        action="store_true",
        help="Asume que el target ya fue cargado y salta la fase bootstrap.",
    )
    parser.add_argument(
        "--bootstrap-report-path",
        type=Path,
        default=DEFAULT_BOOTSTRAP_REPORT_PATH,
        help="Ruta del reporte JSON de bootstrap.",
    )
    parser.add_argument(
        "--pages-output-dir",
        type=Path,
        default=DEFAULT_PAGES_OUTPUT_DIR,
        help="Directorio destino del site bundle para Pages.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Ruta del reporte final de preflight.",
    )
    return parser.parse_args()


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def runtime_smoke(target_url: str) -> dict[str, Any]:
    engine = create_db_engine(database_url=target_url)
    try:
        with RuntimeDB(engine) as db:
            row = db.execute(
                """
                SELECT
                    COUNT(*) AS prices_count,
                    (SELECT COUNT(*) FROM predictions) AS predictions_count,
                    (SELECT COUNT(*) FROM outcomes) AS outcomes_count,
                    (SELECT COUNT(*) FROM model_metrics) AS model_metrics_count,
                    (SELECT COUNT(*) FROM regimes) AS regimes_count,
                    (SELECT COUNT(*) FROM data_status) AS data_status_count,
                    (SELECT COUNT(*) FROM pipeline_runs) AS pipeline_runs_count,
                    (SELECT MAX(date) FROM prices WHERE ticker = 'SPY') AS latest_market_date
                FROM prices
                """
            ).fetchone()
            return {
                "backend": db.backend.name,
                "database_url": db.backend.database_url,
                "prices_count": int(row[0] or 0),
                "predictions_count": int(row[1] or 0),
                "outcomes_count": int(row[2] or 0),
                "model_metrics_count": int(row[3] or 0),
                "regimes_count": int(row[4] or 0),
                "data_status_count": int(row[5] or 0),
                "pipeline_runs_count": int(row[6] or 0),
                "latest_market_date": str(row[7]) if row[7] else None,
            }
    finally:
        engine.dispose()


def build_cutover_metadata(
    *,
    variant: str,
    pages_output_dir: Path,
    bootstrap_skipped: bool,
    dashboard_result: dict[str, Any],
    site_manifest: dict[str, Any],
) -> dict[str, Any]:
    payload = dashboard_result["payload"]
    ledger = dashboard_result["ledger"]
    return {
        "generator": "infra.cloud.cutover_preflight",
        "variant": variant,
        "pages_output_dir": str(pages_output_dir.resolve()),
        "bootstrap_skipped": bootstrap_skipped,
        "dashboard_pipeline_run_id": ledger.get("run_id"),
        "dashboard_pipeline_persisted": ledger.get("persisted"),
        "dashboard_pipeline_skipped_reason": ledger.get("skipped_reason"),
        "dashboard_build": payload.get("build") or {},
        "site_entrypoint": site_manifest.get("entrypoint"),
        "site_published_files": site_manifest.get("published_files") or [],
    }


def run_cutover_preflight(
    *,
    source_sqlite_path: Path,
    target_url: str,
    chunk_size: int = 5000,
    variant: str = "all",
    reset_target: bool = False,
    allow_sqlite_target: bool = False,
    skip_bootstrap: bool = False,
    bootstrap_report_path: Path = DEFAULT_BOOTSTRAP_REPORT_PATH,
    pages_output_dir: Path = DEFAULT_PAGES_OUTPUT_DIR,
    report_path: Path = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    bootstrap_report: dict[str, Any] | None = None
    if not skip_bootstrap:
        ensure_parent_dir(bootstrap_report_path)
        bootstrap = bootstrap_target_from_sqlite(
            source_sqlite_path=source_sqlite_path,
            target_url=target_url,
            chunk_size=chunk_size,
            reset_target=reset_target,
            allow_sqlite_target=allow_sqlite_target,
            report_path=bootstrap_report_path,
        )
        bootstrap_report = json.loads(bootstrap_report_path.read_text(encoding="utf-8"))

    smoke = runtime_smoke(target_url)
    dashboard_result = generate_dashboard_bundle(variant=variant, database_url=target_url)
    staged_paths = stage_dashboard_site(DASHBOARD_DIR, pages_output_dir)
    site_manifest = read_json(pages_output_dir / SITE_MANIFEST_NAME)

    recorder = start_pipeline_run(
        "cutover_preflight",
        database_url=target_url,
        run_date=datetime.now().isoformat(timespec="seconds"),
        active_scanner_version=str(
            dashboard_result["payload"].get("operational_context", {}).get("active_version") or ""
        ),
        db_backend=smoke["backend"],
    )
    recorder.finish(
        status="SUCCESS",
        run_date=datetime.now().isoformat(timespec="seconds"),
        active_scanner_version=str(
            dashboard_result["payload"].get("operational_context", {}).get("active_version") or ""
        ),
        db_backend=smoke["backend"],
        latest_prices_date=smoke.get("latest_market_date"),
        warnings_count=0,
        artifact_manifest=site_manifest,
        metadata_json=build_cutover_metadata(
            variant=variant,
            pages_output_dir=pages_output_dir,
            bootstrap_skipped=skip_bootstrap,
            dashboard_result=dashboard_result,
            site_manifest=site_manifest,
        ),
    )

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target_url": target_url,
        "source_sqlite_path": str(source_sqlite_path.resolve()),
        "chunk_size": chunk_size,
        "variant": variant,
        "bootstrap_skipped": skip_bootstrap,
        "bootstrap_report_path": str(bootstrap_report_path.resolve()) if not skip_bootstrap else None,
        "bootstrap_report": bootstrap_report,
        "runtime_smoke": smoke,
        "dashboard": {
            "build": dashboard_result["payload"].get("build") or {},
            "written_files": [str(path.resolve()) for path in dashboard_result["written"]],
            "artifact_manifest": dashboard_result["artifact_manifest"],
            "ledger": dashboard_result["ledger"],
        },
        "pages_site": {
            "output_dir": str(pages_output_dir.resolve()),
            "written_files": [str(path.resolve()) for path in staged_paths],
            "site_manifest": site_manifest,
        },
        "cutover_ledger": {
            "persisted": recorder.persisted,
            "run_id": recorder.run_id,
            "skipped_reason": recorder.skipped_reason,
            "error_message": recorder.error_message,
        },
    }

    ensure_parent_dir(report_path)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    args = parse_args()
    result = run_cutover_preflight(
        source_sqlite_path=args.source_sqlite_path,
        target_url=args.target_url,
        chunk_size=args.chunk_size,
        variant=args.variant,
        reset_target=args.reset_target,
        allow_sqlite_target=args.allow_sqlite_target,
        skip_bootstrap=args.skip_bootstrap,
        bootstrap_report_path=args.bootstrap_report_path,
        pages_output_dir=args.pages_output_dir,
        report_path=args.report_path,
    )
    print("Cutover preflight completado:")
    print(f" - Runtime smoke backend: {result['runtime_smoke']['backend']}")
    print(f" - Dashboard run: {result['dashboard']['ledger']['run_id']}")
    print(f" - Pages site: {result['pages_site']['output_dir']}")
    print(f" - Reporte final: {args.report_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
