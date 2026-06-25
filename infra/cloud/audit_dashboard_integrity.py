from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path regardless of CWD when invoked as subprocess
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from analisis.generar_tablero_maquina_pensante import (
    _FRESHNESS_SCRIPT,
    _FRESHNESS_SCRIPT_ID,
    _inject_mobile_responsive,
    build_integrity_snapshot,
    build_run_snapshot_from_db,
    build_dashboard_payload,
    load_market_dates,
    render_executive,
    render_index,
    render_lab,
    rewrite_dashboard_variant_hrefs,
    resolve_regime_label_from_db,
)
from herramientas.competencia_modelos import is_required_monitored_role
from herramientas.dashboard_paths import C1_PRO_BUNDLE_HTML, C1_PRO_TEMPLATE_HTML, EXECUTIVE_HTML, INDEX_HTML, LAB_HTML, SNAPSHOT_PATH
from herramientas.refrescar_datos_dashboard import render_dashboard_html
from herramientas.scanner_operativo_context import resolve_operational_scanner_context
from infra.db.config import get_database_url
from infra.db.migrate_sqlite_to_postgres import redact_url
from infra.db.runtime import RuntimeDB
from infra.db.session import create_db_engine
from infra.publish.dashboard_site import ENTRYPOINT_NAME, SITE_MANIFEST_NAME
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_PATH = ROOT / "docs" / "cloud" / "reports" / "dashboard_integrity_audit.json"
DEFAULT_SITE_DIR = ROOT / "dist" / "github-pages"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audita la integridad entre DB, snapshot del dashboard y bundle publicado "
            "con muestreo aleatorio reproducible."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=get_database_url(),
        help="URL SQLAlchemy del backend a contrastar.",
    )
    parser.add_argument(
        "--snapshot-path",
        type=Path,
        default=SNAPSHOT_PATH,
        help="Ruta del snapshot JSON generado del dashboard.",
    )
    parser.add_argument(
        "--dashboard-dir",
        type=Path,
        help="Directorio del bundle local del dashboard. Default: parent del snapshot.",
    )
    parser.add_argument(
        "--site-dir",
        type=Path,
        default=DEFAULT_SITE_DIR,
        help="Directorio del site bundle staged para Pages.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=5,
        help="Cantidad de modelos a muestrear aleatoriamente de la liga competitiva.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=130013,
        help="Semilla del muestreo aleatorio para que sea reproducible.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Ruta donde escribir el reporte JSON final.",
    )
    parser.add_argument(
        "--lightweight",
        action="store_true",
        default=False,
        help=(
            "Skip the full build_dashboard_payload() rebuild and use targeted "
            "integrity queries instead. Reduces Supabase egress by ~99%% for "
            "the audit step while still verifying integrity metrics, active "
            "model state, and all file-based checks."
        ),
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _sanitize_traceback(tb: str) -> str:
    """Sanitize traceback text to avoid leaking simple credentials (best-effort).

    This performs a conservative replacement of URL credentials of the form
    '://user:pass@' -> '://REDACTED@'. It's intentionally minimal so it won't
    produce false negatives/positives for other text.
    """
    try:
        return re.sub(r"://[^@\s]+@", "://REDACTED@", tb)
    except Exception:
        return tb


def normalize_float(value: Any, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def normalize_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                "ticker": str(row.get("ticker") or ""),
                "sector": str(row.get("sector") or ""),
                "confidence": normalize_float(row.get("confidence")),
                "score": normalize_float(row.get("score")),
                "target_date": str(row.get("target_date")) if row.get("target_date") else None,
            }
        )
    return sorted(normalized, key=lambda item: (item["ticker"], item["target_date"] or "", item["sector"]))


def normalize_window(window: dict[str, Any]) -> dict[str, Any]:
    return {
        "window_days": int(window.get("window_days") or 0),
        "active_days": int(window.get("active_days") or 0),
        "coverage_pct": normalize_float(window.get("coverage_pct"), digits=4),
        "evaluated": int(window.get("evaluated") or 0),
        "hits": int(window.get("hits") or 0),
        "misses": int(window.get("misses") or 0),
        "accuracy_pct": normalize_float(window.get("accuracy_pct"), digits=4),
        "avg_return_pct": normalize_float(window.get("avg_return_pct"), digits=4),
        "avg_confidence_pct": normalize_float(window.get("avg_confidence_pct"), digits=4),
    }


def normalize_competition_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": str(row.get("version") or ""),
        "role": str(row.get("role") or ""),
        "pred_days": int(row.get("pred_days") or 0),
        "total_preds": int(row.get("total_preds") or 0),
        "evaluated": int(row.get("evaluated") or 0),
        "accuracy_pct": normalize_float(row.get("accuracy_pct"), digits=4),
        "avg_return_pct": normalize_float(row.get("avg_return_pct"), digits=4),
        "latest_snapshot_date": str(row.get("latest_snapshot_date")) if row.get("latest_snapshot_date") else None,
        "latest_target_date": str(row.get("latest_target_date")) if row.get("latest_target_date") else None,
        "latest_picks": int(row.get("latest_picks") or 0),
        "latest_tickers": [str(item) for item in row.get("latest_tickers") or []],
        "latest_snapshot_signal_count": int(row.get("latest_snapshot_signal_count") or 0),
        "snapshot_stale_market_days": row.get("snapshot_stale_market_days"),
        "stale_market_days": row.get("stale_market_days"),
        "recent_10": normalize_window(row.get("recent_10") or {}),
        "recent_15": normalize_window(row.get("recent_15") or {}),
        "recent_30": normalize_window(row.get("recent_30") or {}),
    }


def latest_calendar_entry_date(row: dict[str, Any], window_key: str) -> str | None:
    calendar = ((row.get(window_key) or {}).get("calendar") or [])
    if not calendar:
        return None
    last = calendar[-1] or {}
    return str(last.get("date")) if last.get("date") else None


def latest_calendar_entry_picks(row: dict[str, Any], window_key: str) -> int | None:
    calendar = ((row.get(window_key) or {}).get("calendar") or [])
    if not calendar:
        return None
    last = calendar[-1] or {}
    return int(last.get("picks") or 0)


def build_expected_active_from_db(db: RuntimeDB) -> dict[str, Any]:
    operational = resolve_operational_scanner_context()
    market_dates = load_market_dates(db)
    version = operational.active_version
    active_snapshot = build_run_snapshot_from_db(db, version, market_dates) or {}
    latest_d = {"results": active_snapshot.get("results_d") or []}
    latest_e = {"results": active_snapshot.get("results_e") or []}
    return {
        "active_version": version,
        "analyzed_date": active_snapshot.get("analyzed_date"),
        "prediction_for": active_snapshot.get("prediction_for"),
        "regime_label": active_snapshot.get("regime_label") or resolve_regime_label_from_db(db, active_snapshot.get("analyzed_date"), version),
        "results_d": normalize_results(latest_d["results"]),
        "results_e": normalize_results(latest_e["results"]),
    }


def record_check(
    checks: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    *,
    label: str,
    actual: Any,
    expected: Any,
) -> None:
    ok = actual == expected
    checks.append({"label": label, "ok": ok})
    if not ok:
        failures.append({"label": label, "actual": actual, "expected": expected})


def record_contains(
    checks: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    *,
    label: str,
    text: str,
    needle: str,
) -> None:
    ok = needle in text
    checks.append({"label": label, "ok": ok})
    if not ok:
        failures.append({"label": label, "actual": f"missing:{needle}", "expected": "present"})


def compare_integrity(
    snapshot: dict[str, Any],
    expected_payload: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> None:
    published = snapshot.get("integrity") or {}
    expected = expected_payload.get("integrity") or {}

    scalar_fields = [
        "latest_market_date",
        "latest_prediction_date",
        "latest_outcome_date",
        "latest_regime_date",
        "predictions_count",
        "outcomes_count",
        "regimes_count",
        "prediction_models",
        "outcome_models",
    ]
    for field in scalar_fields:
        record_check(
            checks,
            failures,
            label=f"integrity.{field}",
            actual=published.get(field),
            expected=expected.get(field),
        )

    for scope in ["predictions", "outcomes", "regimes"]:
        for field in ["covered_days", "expected_days", "missing"]:
            record_check(
                checks,
                failures,
                label=f"integrity.coverage_last_30.{scope}.{field}",
                actual=((published.get("coverage_last_30") or {}).get(scope) or {}).get(field),
                expected=((expected.get("coverage_last_30") or {}).get(scope) or {}).get(field),
            )


def compare_active(
    snapshot: dict[str, Any],
    expected_active: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> None:
    active = snapshot.get("active") or {}
    active_run = active.get("active_run") or {}

    record_check(
        checks,
        failures,
        label="active.active_version",
        actual=active.get("active_version"),
        expected=expected_active.get("active_version"),
    )
    record_check(
        checks,
        failures,
        label="active.active_run.analyzed_date",
        actual=active_run.get("analyzed_date"),
        expected=expected_active.get("analyzed_date"),
    )
    record_check(
        checks,
        failures,
        label="active.active_run.prediction_for",
        actual=active_run.get("prediction_for"),
        expected=expected_active.get("prediction_for"),
    )
    record_check(
        checks,
        failures,
        label="active.active_run.regime_label",
        actual=active_run.get("regime_label"),
        expected=expected_active.get("regime_label"),
    )
    record_check(
        checks,
        failures,
        label="active.active_run.results_d",
        actual=normalize_results(active_run.get("results_d") or []),
        expected=expected_active.get("results_d"),
    )
    record_check(
        checks,
        failures,
        label="active.active_run.results_e",
        actual=normalize_results(active_run.get("results_e") or []),
        expected=expected_active.get("results_e"),
    )


def verify_active_run_invariants(
    snapshot: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> None:
    active_run = ((snapshot.get("active") or {}).get("active_run") or {})
    latest_market_date = str(((snapshot.get("integrity") or {}).get("latest_market_date") or ""))
    record_check(
        checks,
        failures,
        label="active.active_run.exists",
        actual=bool(active_run),
        expected=True,
    )

    analyzed_date = str(active_run.get("analyzed_date") or "")
    if latest_market_date:
        record_check(
            checks,
            failures,
            label="active.active_run.latest_market_date",
            actual=analyzed_date or None,
            expected=latest_market_date,
        )

    prediction_for = active_run.get("prediction_for")
    if prediction_for is not None:
        record_check(
            checks,
            failures,
            label="active.active_run.prediction_for_single_date",
            actual="->" not in str(prediction_for),
            expected=True,
        )

    if not analyzed_date:
        return

    live_results = (active_run.get("results_d") or []) + (active_run.get("results_e") or [])
    stale_targets = sorted(
        {
            str(row.get("target_date"))
            for row in live_results
            if row.get("target_date") and str(row.get("target_date")) < analyzed_date
        }
    )
    record_check(
        checks,
        failures,
        label="active.active_run.target_dates_not_before_analyzed_date",
        actual=stale_targets,
        expected=[],
    )


def verify_competition_invariants(
    snapshot: dict[str, Any],
    expected_payload: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> None:
    published_rows = snapshot.get("competition") or []
    expected_rows = expected_payload.get("competition") or []
    published_map = {str(row.get("version")): row for row in published_rows}
    expected_map = {str(row.get("version")): row for row in expected_rows}

    published_versions = sorted(published_map)
    expected_versions = sorted(expected_map)
    record_check(
        checks,
        failures,
        label="competition.versions",
        actual=published_versions,
        expected=expected_versions,
    )

    latest_market_date = str(((snapshot.get("integrity") or {}).get("latest_market_date") or ""))
    if not latest_market_date:
        return

    for version in sorted(set(published_map) & set(expected_map)):
        row = published_map[version]
        expected_row = expected_map[version]
        role = str(row.get("role") or expected_row.get("role") or "")

        record_check(
            checks,
            failures,
            label=f"competition[{version}].latest_snapshot_date_from_db",
            actual=row.get("latest_snapshot_date"),
            expected=expected_row.get("latest_snapshot_date"),
        )
        record_check(
            checks,
            failures,
            label=f"competition[{version}].latest_snapshot_signal_count_from_db",
            actual=int(row.get("latest_snapshot_signal_count") or 0),
            expected=int(expected_row.get("latest_snapshot_signal_count") or 0),
        )
        if not is_required_monitored_role(role):
            continue
        record_check(
            checks,
            failures,
            label=f"competition[{version}].latest_snapshot_date",
            actual=row.get("latest_snapshot_date"),
            expected=latest_market_date,
        )
        record_check(
            checks,
            failures,
            label=f"competition[{version}].snapshot_stale_market_days",
            actual=row.get("snapshot_stale_market_days"),
            expected=0,
        )
        record_check(
            checks,
            failures,
            label=f"competition[{version}].stale_market_days",
            actual=row.get("stale_market_days"),
            expected=0,
        )
        record_check(
            checks,
            failures,
            label=f"competition[{version}].recent_15.latest_market_date",
            actual=latest_calendar_entry_date(row, "recent_15"),
            expected=latest_market_date,
        )
        record_check(
            checks,
            failures,
            label=f"competition[{version}].recent_30.latest_market_date",
            actual=latest_calendar_entry_date(row, "recent_30"),
            expected=latest_market_date,
        )

        if row.get("latest_snapshot_date") == latest_market_date and int(row.get("latest_snapshot_signal_count") or 0) == 0:
            # NOTE: We intentionally do NOT check that competition calendar picks == 0
            # when signal_count == 0. The calendar's `picks` field counts ACTIVE positions
            # (including carry-over positions from previous signal dates), so a model in
            # SEGURO/HOLD regime with no new signals today can legitimately show picks > 0
            # due to positions entered on previous days still being open.
            # The signal-count consistency is already validated by
            # competition[{version}].latest_snapshot_signal_count_from_db above.
            pass


def compare_competition_sample(
    snapshot: dict[str, Any],
    expected_payload: dict[str, Any],
    *,
    sample_size: int,
    seed: int,
    checks: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> list[str]:
    published_map = {str(row.get("version")): row for row in snapshot.get("competition") or []}
    expected_map = {str(row.get("version")): row for row in expected_payload.get("competition") or []}
    common_versions = sorted(set(published_map) & set(expected_map))
    if not common_versions:
        failures.append(
            {
                "label": "competition.sample",
                "actual": [],
                "expected": "al menos un modelo comun entre snapshot y DB",
            }
        )
        return []

    rng = random.Random(seed)
    take = min(max(sample_size, 1), len(common_versions))
    sampled = sorted(rng.sample(common_versions, take))
    for version in sampled:
        record_check(
            checks,
            failures,
            label=f"competition[{version}]",
            actual=normalize_competition_row(published_map[version]),
            expected=normalize_competition_row(expected_map[version]),
        )

    record_check(
        checks,
        failures,
        label="competition_recent.equalized_days",
        actual=(snapshot.get("competition_recent") or {}).get("equalized_days"),
        expected=(expected_payload.get("competition_recent") or {}).get("equalized_days"),
    )
    return sampled


# ── Verification Committee checks ──────────────────────────────────────────
# These checks form the automated "agent committee" that guards dashboard
# quality before deploy.  They catch problems that pure DB-vs-snapshot
# diffing cannot: implausible returns, regime contradictions, duplicates.

RETURN_SPIKE_THRESHOLD = 30.0  # |daily avg return pct| above this is suspect
CUMULATIVE_RETURN_ABS_MAX = 100.0  # |cumulative return pct| above this is suspect


def verify_return_plausibility(
    snapshot: dict[str, Any],
    checks: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    """Flag any model whose sparkline contains implausible return spikes.

    Committee findings are advisory (warnings), not blocking failures.
    """
    rows = snapshot.get("competition") or []
    for row in rows:
        version = str(row.get("version") or "?")
        spark = row.get("spark_cumulative_return_pct") or []
        daily = row.get("spark_avg_return_pct") or []

        bad_days = [
            (i, float(v))
            for i, v in enumerate(daily)
            if v is not None and abs(float(v)) > RETURN_SPIKE_THRESHOLD
        ]
        if bad_days:
            warnings.append({
                "label": f"committee.return_spike[{version}]",
                "actual": f"{len(bad_days)} day(s) with |avg_return| > {RETURN_SPIKE_THRESHOLD}%: {bad_days[:3]}",
                "expected": "no implausible daily return spikes (possible corporate action contamination)",
            })
        else:
            checks.append({"label": f"committee.return_spike[{version}]", "ok": True})

        if spark:
            final_cum = float(spark[-1]) if spark[-1] is not None else 0.0
            if abs(final_cum) > CUMULATIVE_RETURN_ABS_MAX:
                warnings.append({
                    "label": f"committee.cumulative_extreme[{version}]",
                    "actual": f"cumulative return = {final_cum:.2f}%",
                    "expected": f"|cumulative| <= {CUMULATIVE_RETURN_ABS_MAX}%",
                })
            else:
                checks.append({"label": f"committee.cumulative_extreme[{version}]", "ok": True})


def verify_regime_consistency(
    snapshot: dict[str, Any],
    checks: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    """Ensure regime_label is consistent across all snapshot sections.

    Committee findings are advisory (warnings), not blocking failures.
    """
    active = snapshot.get("active") or {}
    active_run = active.get("active_run") or {}
    regime_active = active_run.get("regime_label")
    regime_root = snapshot.get("regime_label")

    sources: dict[str, str | None] = {
        "active.active_run.regime_label": regime_active,
        "root.regime_label": regime_root,
    }

    unique_regimes = {v for v in sources.values() if v is not None}
    if len(unique_regimes) <= 1:
        checks.append({"label": "committee.regime_consistency", "ok": True})
    else:
        warnings.append({
            "label": "committee.regime_consistency",
            "actual": str(sources),
            "expected": "all regime labels must agree",
        })


def verify_no_duplicate_models(
    snapshot: dict[str, Any],
    checks: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    """Detect models that occupy multiple competition slots with identical data.

    Committee findings are advisory (warnings), not blocking failures.
    """
    rows = snapshot.get("competition") or []
    seen: dict[str, str] = {}
    duplicates: list[tuple[str, str]] = []
    for row in rows:
        version = str(row.get("version") or "")
        key_fields = (
            str(row.get("total_preds")),
            str(row.get("evaluated")),
            str(row.get("accuracy_pct")),
            str(row.get("avg_return_pct")),
        )
        fingerprint = "|".join(key_fields)
        if fingerprint in seen and fingerprint != "0|0|None|None":
            duplicates.append((seen[fingerprint], version))
        else:
            seen[fingerprint] = version

    if duplicates:
        warnings.append({
            "label": "committee.duplicate_models",
            "actual": str(duplicates),
            "expected": "no duplicate models in competition",
        })
    else:
        checks.append({"label": "committee.duplicate_models", "ok": True})


def verify_dashboard_html(
    dashboard_dir: Path,
    snapshot: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> None:
    html_expectations = {
        INDEX_HTML.name: render_index(snapshot),
        EXECUTIVE_HTML.name: render_executive(snapshot),
        LAB_HTML.name: render_lab(snapshot),
    }
    for file_name, expected_html in html_expectations.items():
        path = dashboard_dir / file_name
        if not path.exists():
            failures.append({"label": f"dashboard_file[{file_name}]", "actual": "missing", "expected": "exists"})
            continue
        record_check(
            checks,
            failures,
            label=f"dashboard_file[{file_name}]",
            actual=path.read_text(encoding="utf-8"),
            expected=expected_html,
        )

    expected_preview_html: str | None = None
    if not C1_PRO_TEMPLATE_HTML.exists():
        failures.append(
            {
                "label": f"c1_template_file[{C1_PRO_TEMPLATE_HTML.name}]",
                "actual": "missing",
                "expected": "exists",
            }
        )
    else:
        template_html = C1_PRO_TEMPLATE_HTML.read_text(encoding="utf-8")
        try:
            expected_template_html = render_dashboard_html(template_html, snapshot, verbose=False)
        except ValueError as exc:
            failures.append(
                {
                    "label": f"c1_template_file[{C1_PRO_TEMPLATE_HTML.name}]",
                    "actual": "unrenderable",
                    "expected": str(exc),
                }
            )
        else:
            _preview_base = _inject_mobile_responsive(
                rewrite_dashboard_variant_hrefs(
                    expected_template_html,
                    dashboard_dir / C1_PRO_BUNDLE_HTML.name,
                )
            )
            # Apply the same idempotent freshness script injection as build_c1_pro_outputs()
            _script_tag = f'<script id="{_FRESHNESS_SCRIPT_ID}">'
            if _script_tag in _preview_base:
                _s = _preview_base.index(_script_tag)
                _e = _preview_base.index("</script>", _s) + len("</script>")
                _preview_base = _preview_base[:_s] + _preview_base[_e:]
            expected_preview_html = _preview_base.replace("</body>", _FRESHNESS_SCRIPT + "\n</body>", 1)

    preview_path = dashboard_dir / C1_PRO_BUNDLE_HTML.name
    if not preview_path.exists():
        failures.append(
            {
                "label": f"dashboard_file[{C1_PRO_BUNDLE_HTML.name}]",
                "actual": "missing",
                "expected": "exists",
            }
        )
        return

    if expected_preview_html is not None:
        record_check(
            checks,
            failures,
            label=f"dashboard_file[{C1_PRO_BUNDLE_HTML.name}]",
            actual=preview_path.read_text(encoding="utf-8"),
            expected=expected_preview_html,
        )


def verify_site_bundle(
    dashboard_dir: Path,
    site_dir: Path,
    snapshot: dict[str, Any],
    checks: list[dict[str, Any]],
    failures: list[dict[str, Any]],
) -> None:
    if not site_dir.exists():
        failures.append({"label": "site_dir", "actual": "missing", "expected": str(site_dir.resolve())})
        return

    site_manifest_path = site_dir / SITE_MANIFEST_NAME
    if not site_manifest_path.exists():
        failures.append({"label": "site_manifest", "actual": "missing", "expected": "exists"})
        return
    site_manifest = read_json(site_manifest_path)
    record_check(
        checks,
        failures,
        label="site_manifest.entrypoint",
        actual=site_manifest.get("entrypoint"),
        expected=ENTRYPOINT_NAME,
    )

    staged_snapshot_path = site_dir / SNAPSHOT_PATH.name
    if not staged_snapshot_path.exists():
        failures.append({"label": "site_snapshot", "actual": "missing", "expected": "exists"})
        return
    record_check(
        checks,
        failures,
        label="site_snapshot.json",
        actual=read_json(staged_snapshot_path),
        expected=snapshot,
    )

    entrypoint_path = site_dir / ENTRYPOINT_NAME
    preview_path = dashboard_dir / C1_PRO_BUNDLE_HTML.name
    if not entrypoint_path.exists():
        failures.append({"label": f"site_file[{ENTRYPOINT_NAME}]", "actual": "missing", "expected": "exists"})
    elif not preview_path.exists():
        failures.append(
            {
                "label": f"dashboard_file[{C1_PRO_BUNDLE_HTML.name}]",
                "actual": "missing",
                "expected": "exists for site comparison",
            }
        )
    else:
        record_check(
            checks,
            failures,
            label=f"site_file[{ENTRYPOINT_NAME}]",
            actual=entrypoint_path.read_text(encoding="utf-8"),
            expected=preview_path.read_text(encoding="utf-8"),
        )

    for file_name in [SNAPSHOT_PATH.name, INDEX_HTML.name, EXECUTIVE_HTML.name, LAB_HTML.name, C1_PRO_BUNDLE_HTML.name]:
        site_path = site_dir / file_name
        dashboard_path = dashboard_dir / file_name
        if not site_path.exists():
            failures.append({"label": f"site_file[{file_name}]", "actual": "missing", "expected": "exists"})
            continue
        if not dashboard_path.exists():
            failures.append(
                {
                    "label": f"dashboard_file[{file_name}]",
                    "actual": "missing",
                    "expected": "exists for site comparison",
                }
            )
            continue
        record_check(
            checks,
            failures,
            label=f"site_file[{file_name}]",
            actual=site_path.read_text(encoding="utf-8"),
            expected=dashboard_path.read_text(encoding="utf-8"),
        )

    index_alias = site_dir / ENTRYPOINT_NAME
    preview_path = site_dir / C1_PRO_BUNDLE_HTML.name
    if index_alias.exists() and preview_path.exists():
        record_check(
            checks,
            failures,
            label="site_entrypoint_alias",
            actual=index_alias.read_text(encoding="utf-8"),
            expected=preview_path.read_text(encoding="utf-8"),
        )


def audit_dashboard_integrity(
    *,
    database_url: str,
    snapshot_path: Path,
    dashboard_dir: Path | None = None,
    site_dir: Path | None = None,
    sample_size: int = 5,
    seed: int = 130013,
    report_path: Path | None = None,
    lightweight: bool = False,
) -> dict[str, Any]:
    snapshot_path = snapshot_path.resolve()
    dashboard_root = (dashboard_dir.resolve() if dashboard_dir else snapshot_path.parent.resolve())
    staged_site_dir = site_dir.resolve() if site_dir is not None else None
    snapshot = read_json(snapshot_path)

    # Initialize recording lists early so pre-DB checks can append results
    checks: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    # Check snapshot generated_at freshness (fail if too old)
    gen = snapshot.get("generated_at")
    if gen:
        try:
            # normalize trailing Z
            gen_norm = gen if not str(gen).endswith("Z") else str(gen).replace("Z", "+00:00")
            gen_dt = datetime.fromisoformat(gen_norm)
            age_secs = (datetime.now(timezone.utc) - gen_dt.astimezone(timezone.utc)).total_seconds()
            # fail if older than 60 minutes
            if age_secs > 3600:
                failures.append({
                    "label": "snapshot.generated_at_freshness",
                    "actual": gen,
                    "expected": "age <= 3600s",
                })
            else:
                checks.append({"label": "snapshot.generated_at_freshness", "ok": True})
        except Exception as exc:
            failures.append({"label": "snapshot.generated_at_parse", "actual": gen, "expected": str(exc)})

    if lightweight:
        # Lightweight mode: query only integrity metrics + active model from DB.
        # Use the snapshot's own competition data as expected (self-referential
        # for competition sample, but integrity and active checks still hit DB).
        # Saves ~180 MB egress per run vs full build_dashboard_payload().
        engine = create_db_engine(database_url=database_url)
        try:
            with RuntimeDB(engine) as db:
                market_dates = load_market_dates(db)
                db_integrity = build_integrity_snapshot(db, db, market_dates)
                expected_active = build_expected_active_from_db(db)
        finally:
            engine.dispose()
        expected_payload = dict(snapshot)
        expected_payload["integrity"] = db_integrity
    else:
        expected_payload = build_dashboard_payload(database_url=database_url)
        engine = create_db_engine(database_url=database_url)
        try:
            with RuntimeDB(engine) as db:
                expected_active = build_expected_active_from_db(db)
        finally:
            engine.dispose()

    # `checks` and `failures` were initialized earlier so we must not reassign them here.
    compare_integrity(snapshot, expected_payload, checks, failures)
    compare_active(snapshot, expected_active, checks, failures)
    verify_active_run_invariants(snapshot, checks, failures)
    verify_competition_invariants(snapshot, expected_payload, checks, failures)
    sampled_versions = compare_competition_sample(
        snapshot,
        expected_payload,
        sample_size=sample_size,
        seed=seed,
        checks=checks,
        failures=failures,
    )
    # Verification committee checks (automated agent panel).
    # Committee findings are advisory warnings — they flag anomalies worth
    # investigating but do NOT block the deploy (only critical integrity
    # mismatches in `failures` block it).
    warnings: list[dict[str, Any]] = []
    verify_return_plausibility(snapshot, checks, warnings)
    verify_regime_consistency(snapshot, checks, warnings)
    verify_no_duplicate_models(snapshot, checks, warnings)

    verify_dashboard_html(dashboard_root, snapshot, checks, failures)
    if staged_site_dir is not None and staged_site_dir.exists():
        verify_site_bundle(dashboard_root, staged_site_dir, snapshot, checks, failures)

    payload = {
        "generator": "infra.cloud.audit_dashboard_integrity",
        "database_url": redact_url(database_url),
        "snapshot_path": str(snapshot_path),
        "dashboard_dir": str(dashboard_root),
        "site_dir": str(staged_site_dir) if staged_site_dir is not None else None,
        "sample_size": sample_size,
        "seed": seed,
        "sampled_versions": sampled_versions,
        "checks_total": len(checks),
        "checks_ok": sum(1 for check in checks if check["ok"]),
        "checks_failed": len(failures),
        "committee_warnings": len(warnings),
        "checks": checks,
        "failures": failures,
        "warnings": warnings,
        # Timestamps and traceability fields
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_display": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "tracebacks": [],
    }
    if report_path is not None:
        write_json(report_path.resolve(), payload)
    return payload


def main() -> int:
    args = parse_args()
    payload = audit_dashboard_integrity(
        database_url=args.database_url,
        snapshot_path=args.snapshot_path,
        dashboard_dir=args.dashboard_dir,
        site_dir=args.site_dir,
        sample_size=args.sample_size,
        seed=args.seed,
        report_path=args.report_path,
        lightweight=args.lightweight,
    )
    print("Audit dashboard integrity:")
    print(f" - checks_total       : {payload['checks_total']}")
    print(f" - checks_ok          : {payload['checks_ok']}")
    print(f" - checks_failed      : {payload['checks_failed']}")
    print(f" - committee_warnings : {payload['committee_warnings']}")
    print(f" - sampled            : {', '.join(payload['sampled_versions']) if payload['sampled_versions'] else '-'}")
    print(f" - report             : {args.report_path.resolve()}")

    if payload['checks_failed']:
        print("\nDetalles de checks fallidos:")
        for idx, fail in enumerate(payload.get('failures', []), 1):
            print(f"  {idx}. {fail}")

    if payload['committee_warnings']:
        print("\nCommittee warnings (advisory, non-blocking):")
        for idx, warn in enumerate(payload.get('warnings', []), 1):
            print(f"  {idx}. {warn}")

    return 0 if payload["checks_failed"] == 0 else 1


if __name__ == "__main__":
    import traceback
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Siempre escribir el archivo de auditoría con el error y traceback
        args = None
        try:
            args = parse_args()
            report_path = args.report_path if args and hasattr(args, 'report_path') else DEFAULT_REPORT_PATH
        except Exception:
            report_path = DEFAULT_REPORT_PATH
        now = datetime.now(timezone.utc)
        raw_tb = traceback.format_exc()
        sanitized_tb = _sanitize_traceback(raw_tb)

        error_payload = {
            "generator": "infra.cloud.audit_dashboard_integrity",
            "error": str(exc),
            # Backwards-compatible single-string 'traceback'
            "traceback": sanitized_tb,
            # New field: list of tracebacks (best-effort, sanitized)
            "tracebacks": [sanitized_tb],
            "generated_at": now.isoformat(),
            "generated_at_display": now.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        }
        # If local `checks`/`failures` were created before the exception, include
        # them in the error payload to aid post-mortem analysis. Use a best-effort
        # approach so adding these fields never raises a new exception.
        try:
            _checks = locals().get('checks', None)
            if isinstance(_checks, list):
                error_payload['checks'] = _checks
            _failures = locals().get('failures', None)
            if isinstance(_failures, list):
                error_payload['failures'] = _failures
        except Exception:
            # Best-effort: do not mask original exception
            pass
        try:
            write_json(Path(report_path).resolve(), error_payload)
        except Exception as write_exc:
            print("[FATAL] No se pudo escribir el archivo de error de auditoría:", write_exc, file=sys.stderr)
        print("[ERROR] Auditoría abortada por excepción fatal. Detalles en dashboard_integrity_audit.json", file=sys.stderr)
        raise SystemExit(2)
