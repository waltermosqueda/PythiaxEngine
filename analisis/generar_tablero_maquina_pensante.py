#!/usr/bin/env python3
"""
Genera tableros visuales del estado operativo del proyecto.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import subprocess
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.competencia_modelos import monitored_entries
from herramientas.competencia_topn_estandar import build_standardized_competition_snapshot
from herramientas.dashboard_paths import (
    C1_PRO_BUNDLE_HTML,
    C1_PRO_TEMPLATE_HTML,
    DASHBOARD_DIR as OUTPUT_DIR,
    EXECUTIVE_HTML,
    INDEX_HTML,
    LAB_HTML,
    MANIFEST_PATH,
    SNAPSHOT_PATH,
    dashboard_relative_href,
    ensure_dashboard_dir,
)
from herramientas.scanner_operativo_context import resolve_operational_scanner_context
from infra.db import get_database_url, resolve_ci_run_id, resolve_run_attempt, start_pipeline_run
from infra.db.model_run_snapshots import fetch_latest_model_run_snapshot
from infra.db.session import create_db_engine
from infra.db.runtime import (
    RuntimeDB,
    aggregate_distinct_sql,
    connect_runtime_db,
    require_cloud_database_runtime,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genera el tablero visual de la maquina pensante")
    parser.add_argument(
        "--variant",
        choices=["all", "executive", "lab"],
        default="all",
        help="Variante HTML a renderizar",
    )
    return parser.parse_args()


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def safe(text: Any) -> str:
    return html.escape("" if text is None else str(text))


def json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def sparkline_labels_from_calendar(window: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for item in (window.get("calendar") or []):
        date_text = item.get("date")
        if date_text:
            labels.append(str(date_text))
    return labels


def sparkline_labels_from_series(items: list[dict[str, Any]], fallback_prefix: str = "Punto") -> list[str]:
    labels: list[str] = []
    for idx, item in enumerate(items, start=1):
        label = item.get("date") or item.get("label") or item.get("prediction_date")
        labels.append(str(label) if label else f"{fallback_prefix} {idx}")
    return labels


def dom_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    parts: list[str] = []
    last_dash = False
    for ch in text:
        if ch.isalnum():
            parts.append(ch)
            last_dash = False
        elif not last_dash:
            parts.append("-")
            last_dash = True
    return "".join(parts).strip("-") or "item"


def fmt_int(value: Any) -> str:
    return f"{to_int(value):,}"


def fmt_pct(value: Any, digits: int = 2, signed: bool = False) -> str:
    numeric = to_float(value)
    if numeric is None or math.isnan(numeric):
        return "-"
    sign = "+" if signed else ""
    return f"{numeric:{sign}.{digits}f}%"


def fmt_ratio(value: Any, digits: int = 2) -> str:
    numeric = to_float(value)
    if numeric is None or math.isnan(numeric):
        return "-"
    return f"{numeric:.{digits}f}"


def fmt_date(value: Any) -> str:
    if not value:
        return "-"
    return str(value)


def resolve_default_run_id(build_source: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"dashboard-build-{build_source}-{stamp}"


def build_dashboard_metadata(db_backend: str, pipeline_run_id: str | None = None) -> dict[str, Any]:
    commit_sha = os.getenv("PYTHIAX_COMMIT_SHA") or os.getenv("GITHUB_SHA")
    build_source = "github_actions" if os.getenv("GITHUB_ACTIONS") == "true" else "local"
    resolved_run_id = resolve_ci_run_id() or pipeline_run_id or resolve_default_run_id(build_source)
    run_attempt = resolve_run_attempt()
    workflow = os.getenv("GITHUB_WORKFLOW")
    actor = os.getenv("GITHUB_ACTOR")
    return {
        "generator": "analisis.generar_tablero_maquina_pensante",
        "build_source": build_source,
        "db_backend": db_backend,
        "commit_sha": commit_sha,
        "commit_short": commit_sha[:7] if commit_sha else None,
        "run_id": resolved_run_id,
        "pipeline_run_id": pipeline_run_id or resolved_run_id,
        "run_attempt": run_attempt,
        "workflow": workflow,
        "actor": actor,
    }


def build_status_label(payload: dict[str, Any]) -> str:
    build = payload.get("build") or {}
    parts = [build.get("build_source"), build.get("db_backend"), build.get("commit_short")]
    run_label = build.get("pipeline_run_id") or build.get("run_id")
    if run_label:
        parts.append(f"run {run_label}")
    return " | ".join(str(part) for part in parts if part) or "sin metadata de build"


def parse_ticker_csv(value: Any) -> list[str]:
    if not value:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in str(value).split(","):
        ticker = raw.strip()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        out.append(ticker)
    return out


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def build_artifact_manifest(payload: dict[str, Any], artifacts: list[Path]) -> dict[str, Any]:
    artifact_rows: list[dict[str, Any]] = []
    for path in artifacts:
        resolved = path.resolve()
        relative_path = resolved.relative_to(ROOT).as_posix() if resolved.is_relative_to(ROOT) else path.name
        artifact_rows.append(
            {
                "name": path.name,
                "relative_path": relative_path,
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return {
        "generated_at": payload.get("generated_at"),
        "build": payload.get("build") or {},
        "artifact_count": len(artifact_rows),
        "artifacts": artifact_rows,
    }


def run_c1_pro_builder(*builder_args: str) -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "herramientas" / "_build_c1pro.py"), *builder_args],
        cwd=ROOT,
        check=True,
    )


def run_c1_pro_refresher() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "herramientas" / "refrescar_datos_dashboard.py")],
        cwd=ROOT,
        check=True,
    )


def rewrite_dashboard_variant_hrefs(html_text: str, output_path: Path) -> str:
    replacements = {
        INDEX_HTML.name: dashboard_relative_href(output_path, INDEX_HTML),
        EXECUTIVE_HTML.name: dashboard_relative_href(output_path, EXECUTIVE_HTML),
        LAB_HTML.name: dashboard_relative_href(output_path, LAB_HTML),
    }
    for file_name, relative_href in replacements.items():
        html_text = re.sub(
            rf'href="(?:\.\./)?(?:dashboards/maquina_pensante/)?{re.escape(file_name)}"',
            f'href="{relative_href}"',
            html_text,
        )
    return html_text


def build_c1_pro_outputs() -> list[Path]:
    if not C1_PRO_TEMPLATE_HTML.exists():
        raise FileNotFoundError(
            f"No existe la plantilla canonica de C1 Pro en {C1_PRO_TEMPLATE_HTML}. "
            "Restaurala antes de construir el bundle."
        )

    run_c1_pro_refresher()

    local_html = C1_PRO_TEMPLATE_HTML.read_text(encoding="utf-8")
    published_html = rewrite_dashboard_variant_hrefs(local_html, C1_PRO_BUNDLE_HTML)
    C1_PRO_BUNDLE_HTML.write_text(published_html, encoding="utf-8")
    return [C1_PRO_BUNDLE_HTML]


def model_filter(entry: dict[str, Any], alias: str = "p") -> tuple[str, tuple[Any, ...]]:
    prefix = str(entry["prefix"])
    if entry.get("exact_model_name"):
        return f"{alias}.model_name = ?", (prefix,)
    return f"{alias}.model_name LIKE ?", (f"{prefix}_%",)


def collapse_target_dates(values: list[Any]) -> str | None:
    target_dates = sorted({str(value) for value in values if value})
    if not target_dates:
        return None
    if len(target_dates) == 1:
        return target_dates[0]
    return f"{target_dates[0]} -> {target_dates[-1]}"


def next_operational_session(analyzed_date: str | None, market_dates: list[str]) -> str | None:
    if not analyzed_date:
        return None
    if analyzed_date in market_dates:
        idx = market_dates.index(analyzed_date)
        if idx + 1 < len(market_dates):
            return market_dates[idx + 1]
    try:
        cursor = date.fromisoformat(analyzed_date)
    except ValueError:
        return None
    while True:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            return cursor.isoformat()


def query_df(con: RuntimeDB, sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    return con.read_df(sql, params=params)


def empty_window_metrics(window_dates: list[str]) -> dict[str, Any]:
    start_date = window_dates[0] if window_dates else None
    end_date = window_dates[-1] if window_dates else None
    return {
        "window_days": len(window_dates),
        "start_date": start_date,
        "end_date": end_date,
        "active_days": 0,
        "coverage_pct": 0.0,
        "evaluated": 0,
        "hits": 0,
        "misses": 0,
        "accuracy_pct": None,
        "avg_return_pct": None,
        "avg_return_right_pct": None,
        "avg_return_wrong_pct": None,
        "avg_picks_per_day": None,
        "positive_days": 0,
        "negative_days": 0,
        "best_day_return_pct": None,
        "best_day_date": None,
        "worst_day_return_pct": None,
        "worst_day_date": None,
        "spark_avg_return_pct": [],
        "calendar": [],
    }


def build_window_metrics(
    con: RuntimeDB,
    entry: dict[str, Any],
    daily_df: pd.DataFrame,
    window_dates: list[str],
) -> dict[str, Any]:
    base = empty_window_metrics(window_dates)
    if not window_dates:
        return base

    where_clause, params = model_filter(entry, alias="p")
    start_date = window_dates[0]
    end_date = window_dates[-1]

    summary = query_df(
        con,
        f"""
        SELECT
            COUNT(o.id) AS evaluated,
            SUM(o.hit) AS hits,
            COUNT(DISTINCT p.target_date) AS active_days,
            AVG(o.hit) * 100.0 AS accuracy_pct,
            AVG(o.actual_return) * 100.0 AS avg_return_pct,
            AVG(CASE WHEN o.hit = 1 THEN o.actual_return END) * 100.0 AS avg_return_right_pct,
            AVG(CASE WHEN o.hit = 0 THEN o.actual_return END) * 100.0 AS avg_return_wrong_pct
        FROM predictions p
        JOIN outcomes o ON p.id = o.prediction_id
        WHERE {where_clause} AND p.target_date >= ? AND p.target_date <= ?
        """,
        params + (start_date, end_date),
    ).iloc[0]

    subset = daily_df[(daily_df["date"] >= start_date) & (daily_df["date"] <= end_date)].copy()
    daily_map = {str(row["date"]): row for _, row in subset.iterrows()}
    calendar: list[dict[str, Any]] = []
    spark: list[float] = []
    for date_text in window_dates:
        row = daily_map.get(date_text)
        if row is None:
            calendar.append(
                {
                    "date": date_text,
                    "picks": 0,
                    "accuracy_pct": None,
                    "avg_return_pct": None,
                    "tickers": [],
                }
            )
            continue
        avg_return = to_float(row["avg_return_pct"])
        accuracy = to_float(row["accuracy_pct"])
        tickers = parse_ticker_csv(row.get("tickers_csv"))
        spark.append(avg_return or 0.0)
        calendar.append(
            {
                "date": date_text,
                "picks": to_int(row["picks"]),
                "accuracy_pct": accuracy,
                "avg_return_pct": avg_return,
                "tickers": tickers,
            }
        )

    if subset.empty:
        base.update(
            {
                "hits": to_int(summary["hits"]),
                "misses": max(0, to_int(summary["evaluated"]) - to_int(summary["hits"])),
                "accuracy_pct": to_float(summary["accuracy_pct"]),
                "avg_return_pct": to_float(summary["avg_return_pct"]),
                "avg_return_right_pct": to_float(summary["avg_return_right_pct"]),
                "avg_return_wrong_pct": to_float(summary["avg_return_wrong_pct"]),
            }
        )
        return base

    returns = subset["avg_return_pct"].apply(to_float).fillna(0.0)
    best_idx = returns.idxmax()
    worst_idx = returns.idxmin()
    active_days = to_int(summary["active_days"])
    evaluated = to_int(summary["evaluated"])
    hits = to_int(summary["hits"])

    return {
        "window_days": len(window_dates),
        "start_date": start_date,
        "end_date": end_date,
        "active_days": active_days,
        "coverage_pct": round(active_days * 100.0 / max(len(window_dates), 1), 1),
        "evaluated": evaluated,
        "hits": hits,
        "misses": max(0, evaluated - hits),
        "accuracy_pct": to_float(summary["accuracy_pct"]),
        "avg_return_pct": to_float(summary["avg_return_pct"]),
        "avg_return_right_pct": to_float(summary["avg_return_right_pct"]),
        "avg_return_wrong_pct": to_float(summary["avg_return_wrong_pct"]),
        "avg_picks_per_day": round(evaluated / max(active_days, 1), 2) if evaluated else None,
        "positive_days": int((returns > 0).sum()),
        "negative_days": int((returns < 0).sum()),
        "best_day_return_pct": to_float(subset.loc[best_idx, "avg_return_pct"]),
        "best_day_date": str(subset.loc[best_idx, "date"]),
        "worst_day_return_pct": to_float(subset.loc[worst_idx, "avg_return_pct"]),
        "worst_day_date": str(subset.loc[worst_idx, "date"]),
        "spark_avg_return_pct": spark,
        "calendar": calendar,
    }


def load_market_dates(con: RuntimeDB) -> list[str]:
    df = query_df(
        con,
        """
        SELECT DISTINCT date
        FROM prices
        WHERE ticker = 'SPY'
        ORDER BY date
        """,
    )
    return [str(value) for value in df["date"].tolist()]


def market_staleness(latest_model_date: str | None, market_dates: list[str]) -> int | None:
    if not latest_model_date or latest_model_date not in market_dates:
        return None
    return max(0, len(market_dates) - 1 - market_dates.index(latest_model_date))


def build_integrity_snapshot(db: RuntimeDB, con: RuntimeDB, market_dates: list[str]) -> dict[str, Any]:
    db_stats = db.db_stats()
    latest_prediction_date_raw = query_df(con, "SELECT MAX(prediction_date) AS d FROM predictions")["d"].iloc[0]
    latest_outcome_date_raw = query_df(
        con,
        """
        SELECT MAX(p.target_date) AS d
        FROM outcomes o
        JOIN predictions p ON p.id = o.prediction_id
        """,
    )["d"].iloc[0]
    latest_regime_date_raw = query_df(con, "SELECT MAX(date) AS d FROM regimes")["d"].iloc[0]
    latest_snapshot_date_raw = query_df(
        con,
        "SELECT MAX(analyzed_date) AS d FROM model_run_snapshots",
    )["d"].iloc[0]
    latest_prediction_date = str(latest_prediction_date_raw) if pd.notna(latest_prediction_date_raw) else None
    latest_outcome_date = str(latest_outcome_date_raw) if pd.notna(latest_outcome_date_raw) else None
    latest_regime_date = str(latest_regime_date_raw) if pd.notna(latest_regime_date_raw) else None
    latest_snapshot_date = str(latest_snapshot_date_raw) if pd.notna(latest_snapshot_date_raw) else None
    prediction_models = to_int(
        query_df(con, "SELECT COUNT(DISTINCT model_name) AS n FROM predictions")["n"].iloc[0]
    )
    outcome_models = to_int(
        query_df(
            con,
            """
            SELECT COUNT(DISTINCT p.model_name) AS n
            FROM outcomes o
            JOIN predictions p ON p.id = o.prediction_id
            """,
        )["n"].iloc[0]
    )

    recent_market = market_dates[-30:]
    recent_market_set = set(recent_market)

    def coverage(sql: str) -> dict[str, Any]:
        df = query_df(con, sql)
        dates = {str(value) for value in df["date"].tolist() if pd.notna(value)}
        missing = sorted(recent_market_set - dates)
        return {
            "covered_days": len(dates & recent_market_set),
            "expected_days": len(recent_market),
            "missing": missing,
        }

    prediction_cov = coverage(
        """
        SELECT DISTINCT prediction_date AS date
        FROM predictions
        WHERE prediction_date >= (
            SELECT date FROM prices WHERE ticker = 'SPY' ORDER BY date DESC LIMIT 1 OFFSET 29
        )
        """
    )
    outcome_cov = coverage(
        """
        SELECT DISTINCT p.target_date AS date
        FROM outcomes o
        JOIN predictions p ON p.id = o.prediction_id
        WHERE p.target_date >= (
            SELECT date FROM prices WHERE ticker = 'SPY' ORDER BY date DESC LIMIT 1 OFFSET 29
        )
        """
    )
    regime_cov = coverage(
        """
        SELECT DISTINCT date
        FROM regimes
        WHERE date >= (
            SELECT date FROM prices WHERE ticker = 'SPY' ORDER BY date DESC LIMIT 1 OFFSET 29
        )
        """
    )

    return {
        "latest_market_date": market_dates[-1] if market_dates else None,
        "latest_prediction_date": latest_prediction_date,
        "latest_outcome_date": latest_outcome_date,
        "latest_regime_date": latest_regime_date,
        "latest_snapshot_date": latest_snapshot_date,
        "predictions_count": db_stats["predictions_count"],
        "outcomes_count": db_stats["outcomes_count"],
        "regimes_count": db_stats["regimes_count"],
        "model_run_snapshots_count": db_stats["model_run_snapshots_count"],
        "prediction_models": prediction_models,
        "outcome_models": outcome_models,
        "db_size_mb": db_stats.get("db_size_mb"),
        "coverage_last_30": {
            "predictions": prediction_cov,
            "outcomes": outcome_cov,
            "regimes": regime_cov,
        },
    }


def build_ingestion_series(con: RuntimeDB) -> dict[str, list[dict[str, Any]]]:
    pred = query_df(
        con,
        """
        SELECT prediction_date AS date, COUNT(*) AS count
        FROM predictions
        GROUP BY prediction_date
        ORDER BY prediction_date DESC
        LIMIT 45
        """,
    ).sort_values("date")
    out = query_df(
        con,
        """
        SELECT p.target_date AS date, COUNT(*) AS count
        FROM outcomes o
        JOIN predictions p ON p.id = o.prediction_id
        GROUP BY p.target_date
        ORDER BY p.target_date DESC
        LIMIT 45
        """,
    ).sort_values("date")
    reg = query_df(
        con,
        """
        SELECT date, 1 AS count
        FROM regimes
        ORDER BY date DESC
        LIMIT 45
        """,
    ).sort_values("date")
    return {
        "predictions": pred.to_dict(orient="records"),
        "outcomes": out.to_dict(orient="records"),
        "regimes": reg.to_dict(orient="records"),
    }


def fetch_entry_summary(con: RuntimeDB, entry: dict[str, Any], market_dates: list[str]) -> dict[str, Any]:
    tickers_csv_sql = aggregate_distinct_sql("p.ticker", "tickers_csv", con.backend.name)
    where_clause, params = model_filter(entry, alias="p")
    summary = query_df(
        con,
        f"""
        SELECT
            COUNT(*) AS total_predictions,
            COUNT(DISTINCT p.prediction_date) AS prediction_days,
            COUNT(o.id) AS evaluated,
            AVG(o.hit) * 100.0 AS accuracy_pct,
            AVG(o.actual_return) * 100.0 AS avg_return_pct,
            AVG(p.confidence) * 100.0 AS avg_confidence_pct,
            MIN(p.prediction_date) AS first_prediction_date,
            MAX(p.prediction_date) AS last_prediction_date,
            COUNT(DISTINCT p.ticker) AS unique_tickers
        FROM predictions p
        LEFT JOIN outcomes o ON p.id = o.prediction_id
        WHERE {where_clause}
        """,
        params,
    ).iloc[0]

    latest_prediction_date = summary["last_prediction_date"]
    latest_target_date = None
    latest_tickers: list[str] = []
    latest_rows = query_df(
        con,
        f"""
        SELECT p.ticker, p.target_date
        FROM predictions p
        WHERE {where_clause} AND p.prediction_date = ?
        ORDER BY p.ticker
        """,
        params + (latest_prediction_date,),
    )
    if not latest_rows.empty:
        latest_tickers = sorted({str(value) for value in latest_rows["ticker"].tolist()})
        target_dates = sorted({str(value) for value in latest_rows["target_date"].tolist() if value})
        if len(target_dates) == 1:
            latest_target_date = target_dates[0]
        elif len(target_dates) > 1:
            latest_target_date = f"{target_dates[0]} -> {target_dates[-1]}"

    daily = query_df(
        con,
        f"""
        SELECT
            p.target_date AS date,
            COUNT(*) AS picks,
            SUM(o.hit) AS hits,
            AVG(o.hit) * 100.0 AS accuracy_pct,
            AVG(o.actual_return) * 100.0 AS avg_return_pct,
            {tickers_csv_sql}
        FROM predictions p
        JOIN outcomes o ON p.id = o.prediction_id
        WHERE {where_clause}
        GROUP BY p.target_date
        ORDER BY p.target_date
        """,
        params,
    )
    series = daily["avg_return_pct"].tolist()[-60:] if not daily.empty else []
    spark_labels = daily["target_date"].astype(str).tolist()[-60:] if not daily.empty else []
    cumulative = []
    total = 0.0
    for value in series:
        total += float(value)
        cumulative.append(round(total, 4))

    recent_10 = build_window_metrics(con, entry, daily, market_dates[-10:])
    recent_30 = build_window_metrics(con, entry, daily, market_dates[-30:])
    recent_15 = build_window_metrics(con, entry, daily, market_dates[-15:])

    return {
        "version": str(entry["label"]),
        "role": str(entry["role"]),
        "pattern": str(entry["prefix"]),
        "exact_model_name": bool(entry.get("exact_model_name", False)),
        "pred_days": to_int(summary["prediction_days"]),
        "total_preds": to_int(summary["total_predictions"]),
        "evaluated": to_int(summary["evaluated"]),
        "accuracy_pct": to_float(summary["accuracy_pct"]),
        "avg_return_pct": to_float(summary["avg_return_pct"]),
        "avg_confidence_pct": to_float(summary["avg_confidence_pct"]),
        "first_date": summary["first_prediction_date"],
        "last_date": latest_prediction_date,
        "latest_target_date": latest_target_date,
        "latest_picks": len(latest_tickers),
        "latest_tickers": latest_tickers,
        "unique_tickers": to_int(summary["unique_tickers"]),
        "stale_market_days": market_staleness(latest_prediction_date, market_dates),
        "spark_avg_return_pct": series,
        "spark_cumulative_return_pct": cumulative,
        "spark_labels": spark_labels,
        "recent_10": recent_10,
        "recent_15": recent_15,
        "recent_30": recent_30,
    }


def build_league_snapshot(con: RuntimeDB, market_dates: list[str]) -> list[dict[str, Any]]:
    rows = [fetch_entry_summary(con, entry, market_dates) for entry in monitored_entries()]
    return sorted(
        rows,
        key=lambda item: (
            item["accuracy_pct"] if item["accuracy_pct"] is not None else float("-inf"),
            item["avg_return_pct"] if item["avg_return_pct"] is not None else float("-inf"),
            item["version"],
        ),
        reverse=True,
    )


def exact_model_daily(con: RuntimeDB, model_name: str) -> list[dict[str, Any]]:
    df = query_df(
        con,
        """
        SELECT
            p.target_date AS date,
            COUNT(*) AS picks,
            AVG(o.hit) * 100.0 AS accuracy_pct,
            AVG(o.actual_return) * 100.0 AS avg_return_pct
        FROM predictions p
        JOIN outcomes o ON p.id = o.prediction_id
        WHERE p.model_name = ?
        GROUP BY p.target_date
        ORDER BY p.target_date
        """,
        (model_name,),
    )
    return df.to_dict(orient="records")


def exact_model_accuracy(db: RuntimeDB, model_name: str) -> dict[str, Any]:
    payload = db.get_model_accuracy(model_name)
    payload["streak"] = db.get_streak(model_name)
    return payload


def exact_sector_accuracy(db: RuntimeDB, model_name: str, limit: int = 6) -> list[dict[str, Any]]:
    df = db.get_accuracy_by_sector(model_name)
    if df.empty:
        return []
    return df.head(limit).to_dict(orient="records")


def empty_model_results(model_name: str) -> dict[str, Any]:
    return {
        "model_name": model_name,
        "prediction_date": None,
        "target_dates": [],
        "results": [],
    }


def build_results_for_model_prediction_date(
    con: RuntimeDB,
    model_name: str,
    prediction_date: Any,
) -> dict[str, Any]:
    if not prediction_date:
        return empty_model_results(model_name)

    prediction_date_text = str(prediction_date)
    df = query_df(
        con,
        """
        SELECT ticker, direction, sector, confidence, score, target_date
        FROM predictions
        WHERE model_name = ? AND prediction_date = ?
        ORDER BY
            CASE WHEN confidence IS NULL THEN 1 ELSE 0 END,
            confidence DESC,
            CASE WHEN score IS NULL THEN 1 ELSE 0 END,
            score DESC,
            ticker
        """,
        (model_name, prediction_date_text),
    )

    target_dates = sorted({str(value) for value in df["target_date"].tolist() if value}) if not df.empty else []
    results: list[dict[str, Any]] = []
    for row in df.itertuples(index=False):
        confidence = to_float(row.confidence)
        score = to_float(row.score)
        results.append(
            {
                "ticker": str(row.ticker),
                "signal": str(row.direction or "-"),
                "sector": str(row.sector or "-"),
                "confidence": confidence,
                "score": score,
                "priority_score": round(confidence * 100.0, 2) if confidence is not None else score,
                "priority_expected_return": None,
                "risk_pct": None,
                "rsi": None,
                "note": "db fallback",
                "target_date": str(row.target_date) if row.target_date else None,
            }
        )

    return {
        "model_name": model_name,
        "prediction_date": prediction_date_text,
        "target_dates": target_dates,
        "results": results,
    }


def build_latest_results_for_model(con: RuntimeDB, model_name: str) -> dict[str, Any]:
    latest_prediction_date = query_df(
        con,
        """
        SELECT MAX(prediction_date) AS prediction_date
        FROM predictions
        WHERE model_name = ?
        """,
        (model_name,),
    )["prediction_date"].iloc[0]
    if not latest_prediction_date:
        return empty_model_results(model_name)
    return build_results_for_model_prediction_date(con, model_name, latest_prediction_date)


def resolve_regime_label_from_db(con: RuntimeDB, analyzed_date: str | None, version: int) -> str:
    if analyzed_date:
        df = query_df(
            con,
            """
            SELECT composite, trend_regime, vol_regime, credit_regime
            FROM regimes
            WHERE date <= ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (analyzed_date,),
        )
        if not df.empty:
            row = df.iloc[0]
            for field in ["composite", "trend_regime", "vol_regime", "credit_regime"]:
                value = row.get(field)
                if value:
                    return str(value).upper()

    fallback = query_df(
        con,
        """
        SELECT regime
        FROM predictions
        WHERE model_name LIKE ? AND regime IS NOT NULL
        ORDER BY prediction_date DESC
        LIMIT 1
        """,
        (f"INVERTIR_V{version}_%",),
    )
    if not fallback.empty and fallback.iloc[0]["regime"]:
        return str(fallback.iloc[0]["regime"]).upper()
    return "GLOBAL"


def build_run_snapshot_from_db(
    con: RuntimeDB,
    version: int,
    market_dates: list[str] | None = None,
) -> dict[str, Any] | None:
    snapshot_row = fetch_latest_model_run_snapshot(con, f"V{version}")
    if snapshot_row is not None:
        payload = dict(snapshot_row.get("snapshot") or {})
        if payload:
            analyzed_date = str(snapshot_row.get("analyzed_date") or payload.get("analyzed_date") or "")
            model_d = f"INVERTIR_V{version}_D_D10"
            model_e = f"INVERTIR_V{version}_E_D15"
            latest_d = build_results_for_model_prediction_date(con, model_d, analyzed_date) if analyzed_date else {"results": [], "target_dates": []}
            latest_e = build_results_for_model_prediction_date(con, model_e, analyzed_date) if analyzed_date else {"results": [], "target_dates": []}
            hydrated = dict(payload)
            hydrated["version"] = version
            hydrated["source"] = "snapshot_db"
            hydrated["analyzed_date"] = analyzed_date or payload.get("analyzed_date")
            hydrated["prediction_for"] = str(snapshot_row.get("prediction_for") or payload.get("prediction_for") or "")
            hydrated["freshness"] = payload.get("freshness") or snapshot_row.get("freshness")
            hydrated["regime_label"] = (
              payload.get("regime_label")
              or snapshot_row.get("regime_label")
              or resolve_regime_label_from_db(con, hydrated["analyzed_date"], version)
            )
            hydrated["breadth_pct"] = payload.get("breadth_pct")
            if latest_d["results"]:
                hydrated["results_d"] = merge_live_results_with_db(payload.get("results_d"), latest_d["results"])
            else:
                hydrated.setdefault("results_d", [])
            if latest_e["results"]:
                hydrated["results_e"] = merge_live_results_with_db(payload.get("results_e"), latest_e["results"])
            else:
                hydrated.setdefault("results_e", [])
            return hydrated

    model_d = f"INVERTIR_V{version}_D_D10"
    model_e = f"INVERTIR_V{version}_E_D15"
    latest_d_any = build_latest_results_for_model(con, model_d)
    latest_e_any = build_latest_results_for_model(con, model_e)
    if not latest_d_any["results"] and not latest_e_any["results"]:
        return None

    analyzed_candidates = [value for value in [latest_d_any["prediction_date"], latest_e_any["prediction_date"]] if value]
    analyzed_date = max(analyzed_candidates) if analyzed_candidates else None
    if not analyzed_date:
        return None

    # El snapshot publico debe representar un unico corte operativo. Si un
    # sleeve no emitio picks en la fecha mas reciente, se publica vacio en vez
    # de arrastrar picks historicos de otra rueda.
    latest_d = build_results_for_model_prediction_date(con, model_d, analyzed_date)
    latest_e = build_results_for_model_prediction_date(con, model_e, analyzed_date)
    prediction_for = next_operational_session(analyzed_date, market_dates or []) or collapse_target_dates(
        latest_d["target_dates"] + latest_e["target_dates"]
    )

    return {
        "version": version,
        "source": "prediction_db_fallback",
        "fallback_reason": "missing_postgres_run_snapshot",
        "analyzed_date": analyzed_date,
        "prediction_for": prediction_for,
        "regime_label": resolve_regime_label_from_db(con, analyzed_date, version),
        "breadth_pct": None,
        "memory_context": [],
        "freshness": "prediction_db_fallback",
        "results_d": latest_d["results"],
        "results_e": latest_e["results"],
    }


def merge_live_results_with_db(
    snapshot_rows: list[dict[str, Any]] | None,
    db_rows: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    snapshot_rows = snapshot_rows or []
    db_rows = db_rows or []
    if not db_rows:
        return [dict(row) for row in snapshot_rows]

    snapshot_by_ticker = {
        str(row.get("ticker")): dict(row)
        for row in snapshot_rows
        if row.get("ticker")
    }
    merged: list[dict[str, Any]] = []
    for db_row in db_rows:
        ticker = str(db_row.get("ticker") or "")
        base = dict(snapshot_by_ticker.get(ticker, {}))
        base["ticker"] = db_row.get("ticker")
        base["signal"] = base.get("signal") or db_row.get("signal")
        base["sector"] = base.get("sector") or db_row.get("sector")
        base["confidence"] = db_row.get("confidence")
        base["score"] = db_row.get("score")
        base["target_date"] = db_row.get("target_date")
        if base.get("priority_score") is None:
            base["priority_score"] = db_row.get("priority_score") or db_row.get("score")
        if base.get("note") in (None, "", "-"):
            base["note"] = "db synced" if ticker in snapshot_by_ticker else db_row.get("note") or "db fallback"
        merged.append(base)
    return merged


def load_run_snapshot(
    con: RuntimeDB,
    version: int | None,
    market_dates: list[str] | None = None,
) -> dict[str, Any] | None:
    if version is None:
        return None
    return build_run_snapshot_from_db(con, version, market_dates)


def build_active_snapshot(
    db: RuntimeDB,
    con: RuntimeDB,
    market_dates: list[str] | None = None,
) -> dict[str, Any]:
    operational = resolve_operational_scanner_context()
    active_version = operational.active_version
    reference_version = operational.reference_version
    resolved_market_dates = market_dates or load_market_dates(con)
    active_run = load_run_snapshot(con, active_version, resolved_market_dates)
    reference_run = load_run_snapshot(con, reference_version, resolved_market_dates)
    if active_run is not None and not active_run.get("regime_label"):
      active_run["regime_label"] = resolve_regime_label_from_db(con, active_run.get("analyzed_date"), active_version)
    if reference_run is not None and reference_version is not None and not reference_run.get("regime_label"):
      reference_run["regime_label"] = resolve_regime_label_from_db(
        con,
        reference_run.get("analyzed_date"),
        reference_version,
      )

    active_d = exact_model_accuracy(db, f"INVERTIR_V{active_version}_D_D10")
    active_e = exact_model_accuracy(db, f"INVERTIR_V{active_version}_E_D15")
    reference_d = exact_model_accuracy(db, f"INVERTIR_V{reference_version}_D_D10") if reference_version else None
    base_c5 = exact_model_accuracy(db, "INVERTIR_V11_C5_D4")

    return {
        "active_version": active_version,
        "reference_version": reference_version,
        "active_run": active_run,
        "reference_run": reference_run,
        "active_d": active_d,
        "active_e": active_e,
        "reference_d": reference_d,
        "base_c5": base_c5,
        "active_d_daily": exact_model_daily(con, f"INVERTIR_V{active_version}_D_D10"),
        "active_e_daily": exact_model_daily(con, f"INVERTIR_V{active_version}_E_D15"),
    }


def build_v12_v13_divergence(con: RuntimeDB) -> dict[str, Any]:
    df = query_df(
        con,
        """
        SELECT model_name, prediction_date, ticker
        FROM predictions
        WHERE model_name LIKE 'INVERTIR_V12_%' OR model_name LIKE 'INVERTIR_V13_%'
        """
    )
    grouped: dict[tuple[str, str], set[str]] = {}
    for row in df.itertuples(index=False):
        version = "12" if str(row.model_name).startswith("INVERTIR_V12_") else "13"
        grouped.setdefault((version, row.prediction_date), set()).add(str(row.ticker))

    dates_12 = {date for version, date in grouped if version == "12"}
    dates_13 = {date for version, date in grouped if version == "13"}
    common_dates = sorted(dates_12 & dates_13)

    changed_dates = 0
    recent_window = common_dates[-31:] if common_dates else []
    recent_changed = 0
    changed_samples: list[dict[str, Any]] = []
    for date_text in common_dates:
        v12 = grouped.get(("12", date_text), set())
        v13 = grouped.get(("13", date_text), set())
        if v12 != v13:
            changed_dates += 1
            changed_samples.append(
                {
                    "date": date_text,
                    "only_v13": sorted(v13 - v12),
                    "only_v12": sorted(v12 - v13),
                }
            )
    for date_text in recent_window:
        if grouped.get(("12", date_text), set()) != grouped.get(("13", date_text), set()):
            recent_changed += 1

    latest_common_date = common_dates[-1] if common_dates else None
    latest_only_v13: list[str] = []
    latest_only_v12: list[str] = []
    latest_common_equal = True
    if latest_common_date:
        latest_v12 = grouped.get(("12", latest_common_date), set())
        latest_v13 = grouped.get(("13", latest_common_date), set())
        latest_only_v13 = sorted(latest_v13 - latest_v12)
        latest_only_v12 = sorted(latest_v12 - latest_v13)
        latest_common_equal = not latest_only_v13 and not latest_only_v12

    return {
        "common_dates": len(common_dates),
        "changed_dates": changed_dates,
        "same_dates": len(common_dates) - changed_dates,
        "recent_common_dates": len(recent_window),
        "recent_changed_dates": recent_changed,
        "latest_common_date": latest_common_date,
        "latest_common_equal": latest_common_equal,
        "latest_only_v13": latest_only_v13,
        "latest_only_v12": latest_only_v12,
        "sample_changed_dates": list(reversed(changed_samples[-8:])),
    }


def build_overlap_matrix(
    con: RuntimeDB,
    scanner_labels: list[str] | None = None,
) -> dict[str, Any]:
    scanner_model_map = {
        "V11": "INVERTIR_V11_C5_D4",
        "V12": "INVERTIR_V12_D_D10",
        "V13": "INVERTIR_V13_D_D10",
    }
    labels: dict[str, str] = {}
    for label in scanner_labels or ["V13", "V11"]:
        model_name = scanner_model_map.get(label)
        if model_name:
            labels[label] = model_name
    if not labels:
        labels["V13"] = scanner_model_map["V13"]
    labels.update(
        {
            "ML_V97": "LEGACY_ML_V97_SURGE_D3",
            "ML_V39": "LEGACY_ML_V39_TOP_D1",
            "ML_V39FULL": "LEGACY_ML_V39FULL_TOP_D1",
            "ML_BRAIN_V11": "LEGACY_ML_BRAIN_V11_BUY_D5",
            "ML_BRAIN_V11_OPT": "LEGACY_ML_BRAIN_V11_OPT_BUY_D5",
            "ML_V37": "LEGACY_ML_V37_SURGE_D1",
        }
    )
    recent_dates = query_df(
        con,
        """
        SELECT DISTINCT prediction_date AS date
        FROM predictions
        ORDER BY prediction_date DESC
        LIMIT 31
        """
    )["date"].tolist()
    date_min = min(recent_dates) if recent_dates else "1900-01-01"
    placeholders = ",".join("?" for _ in labels)
    df = query_df(
        con,
        f"""
        SELECT model_name, prediction_date, ticker
        FROM predictions
        WHERE model_name IN ({placeholders}) AND prediction_date >= ?
        """,
        tuple(labels.values()) + (date_min,),
    )
    grouped: dict[tuple[str, str], set[str]] = {}
    for row in df.itertuples(index=False):
        grouped.setdefault((str(row.model_name), str(row.prediction_date)), set()).add(str(row.ticker))

    matrix: list[list[float | None]] = []
    common_days: list[list[int]] = []
    label_list = list(labels.keys())
    for left_label in label_list:
        left_model = labels[left_label]
        left_row: list[float | None] = []
        left_common: list[int] = []
        left_dates = {date for model_name, date in grouped if model_name == left_model}
        for right_label in label_list:
            right_model = labels[right_label]
            right_dates = {date for model_name, date in grouped if model_name == right_model}
            dates = sorted(left_dates & right_dates)
            scores: list[float] = []
            for date_text in dates:
                left_set = grouped.get((left_model, date_text), set())
                right_set = grouped.get((right_model, date_text), set())
                union = left_set | right_set
                if not union:
                    continue
                scores.append(len(left_set & right_set) / len(union))
            left_row.append(round(sum(scores) / len(scores), 3) if scores else None)
            left_common.append(len(scores))
        matrix.append(left_row)
        common_days.append(left_common)

    return {
        "labels": label_list,
        "matrix": matrix,
        "common_days": common_days,
    }


def build_sector_snapshot(db: RuntimeDB) -> dict[str, Any]:
    return {
        "v13_d": exact_sector_accuracy(db, "INVERTIR_V13_D_D10"),
        "ml_v97": exact_sector_accuracy(db, "LEGACY_ML_V97_SURGE_D3"),
        "ml_v39": exact_sector_accuracy(db, "LEGACY_ML_V39_TOP_D1"),
    }


def ranked_recent_rows(rows: list[dict[str, Any]], window_key: str) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        window = row.get(window_key) or {}
        copy_row = dict(row)
        copy_row["window"] = dict(window)
        scored.append(copy_row)

    ranked = sorted(
        scored,
        key=lambda item: (
            item["window"].get("accuracy_pct") if item["window"].get("accuracy_pct") is not None else float("-inf"),
            item["window"].get("avg_return_pct") if item["window"].get("avg_return_pct") is not None else float("-inf"),
            -1 * (item.get("stale_market_days") if item.get("stale_market_days") is not None else 999),
            item["window"].get("active_days", 0),
            item["version"],
        ),
        reverse=True,
    )
    for idx, row in enumerate(ranked, start=1):
        row["rank"] = idx
    return ranked


def build_focus_labels(
    by_equalized: list[dict[str, Any]],
    active_version: int,
    reference_version: int | None,
) -> list[str]:
    labels: list[str] = []

    def add(label: str | None) -> None:
        if label and label not in labels:
            labels.append(label)

    add(f"V{active_version}")
    if reference_version is not None:
        add(f"V{reference_version}")

    for row in by_equalized:
        add(str(row["version"]))
        if len(labels) >= 5:
            return labels

    return labels


def build_equalized_window_for_row(
    con: RuntimeDB,
    row: dict[str, Any],
    equalized_days: int,
) -> dict[str, Any]:
    if equalized_days <= 0:
        return empty_window_metrics([])
    entry = {
        "prefix": row["pattern"],
        "exact_model_name": row.get("exact_model_name", False),
    }
    where_clause, params = model_filter(entry, alias="p")
    tickers_csv_sql = aggregate_distinct_sql("p.ticker", "tickers_csv", con.backend.name)
    daily_df = query_df(
        con,
        f"""
        SELECT
            p.target_date AS date,
            COUNT(*) AS picks,
            SUM(o.hit) AS hits,
            AVG(o.hit) * 100.0 AS accuracy_pct,
            AVG(o.actual_return) * 100.0 AS avg_return_pct,
            {tickers_csv_sql}
        FROM predictions p
        JOIN outcomes o ON p.id = o.prediction_id
        WHERE {where_clause}
        GROUP BY p.target_date
        ORDER BY p.target_date
        """,
        params,
    )
    if daily_df.empty:
        return empty_window_metrics([])
    window_dates = daily_df["date"].tolist()[-equalized_days:]
    metrics = build_window_metrics(con, entry, daily_df, window_dates)
    metrics["equalized_days"] = equalized_days
    return metrics


def build_recent_competition_snapshot(
    con: RuntimeDB,
    rows: list[dict[str, Any]],
    active_version: int,
    reference_version: int | None,
) -> dict[str, Any]:
    by_30 = ranked_recent_rows(rows, "recent_30")
    by_10 = ranked_recent_rows(rows, "recent_10")
    active_days = [
        to_int(row.get("recent_30", {}).get("active_days"))
        for row in rows
        if to_int(row.get("recent_30", {}).get("active_days")) > 0
    ]
    equalized_days = min(active_days) if active_days else 0
    equalized_rows = []
    for row in rows:
        copy_row = dict(row)
        copy_row["equalized_recent"] = build_equalized_window_for_row(con, row, equalized_days)
        copy_row["window"] = dict(copy_row["equalized_recent"])
        equalized_rows.append(copy_row)
    by_equalized = ranked_recent_rows(equalized_rows, "equalized_recent")
    rank_30 = {str(row["version"]): row["rank"] for row in by_30}
    rank_10 = {str(row["version"]): row["rank"] for row in by_10}
    rank_equalized = {str(row["version"]): row["rank"] for row in by_equalized}
    focus_labels = build_focus_labels(by_equalized, active_version, reference_version)
    row_map = {str(row["version"]): row for row in equalized_rows}

    return {
        "league_30": by_30,
        "league_10": by_10,
        "equalized_days": equalized_days,
        "league_equalized": by_equalized,
        "focus_labels": focus_labels,
        "focus_models": [row_map[label] for label in focus_labels if label in row_map],
        "rank_30": rank_30,
        "rank_10": rank_10,
        "rank_equalized": rank_equalized,
    }


def build_dashboard_payload(
    pipeline_run_id: str | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    operational = resolve_operational_scanner_context()
    engine = create_db_engine(database_url=database_url) if database_url else None
    with (RuntimeDB(engine) if engine is not None else connect_runtime_db()) as db:
        con = db
        market_dates = load_market_dates(con)
        standardized_competition = build_standardized_competition_snapshot(
            con,
            market_dates,
            operational.active_version,
            operational.reference_version,
        )
        competition_rows = standardized_competition["rows"]
        payload = {
            "generated_at": now,
            "build": build_dashboard_metadata(db.backend.name, pipeline_run_id=pipeline_run_id),
            "operational_context": {
                "active_version": operational.active_version,
                "reference_version": operational.reference_version,
            },
            "integrity": build_integrity_snapshot(db, con, market_dates),
            "ingestion": build_ingestion_series(con),
            "active": build_active_snapshot(db, con, market_dates),
            "competition_policy": standardized_competition["policy"],
            "competition": competition_rows,
            "competition_recent": standardized_competition["recent"],
            "divergence": build_v12_v13_divergence(con),
            "overlap": build_overlap_matrix(
                con,
                standardized_competition["recent"].get("dashboard_scanner_labels"),
            ),
            "sectors": build_sector_snapshot(db),
        }
    return payload


def sparkline_svg(
    values: list[float],
    stroke: str,
    fill: str = "none",
    width: int = 240,
    height: int = 72,
    labels: list[str] | None = None,
    title: str | None = None,
    value_format: str = "pct",
    previewable: bool = False,
) -> str:
    if not values:
        return (
            f"<svg viewBox='0 0 {width} {height}' class='sparkline'>"
            f"<rect x='0' y='0' width='{width}' height='{height}' rx='12' fill='rgba(0,0,0,0.04)' />"
            "</svg>"
        )
    normalized_labels = list(labels or [])
    if len(normalized_labels) < len(values):
        normalized_labels.extend(f"Punto {idx}" for idx in range(len(normalized_labels) + 1, len(values) + 1))
    points: list[tuple[float, float]] = []
    lo = min(values)
    hi = max(values)
    span = hi - lo or 1.0
    for idx, value in enumerate(values):
        x = idx * (width - 8) / max(len(values) - 1, 1) + 4
        y = height - 8 - ((value - lo) / span) * (height - 16)
        points.append((x, y))
    line = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    area = " ".join([f"4,{height-4}"] + [f"{x:.2f},{y:.2f}" for x, y in points] + [f"{width-4},{height-4}"])
    baseline = height - 4
    values_json = safe(json.dumps([round(float(value), 6) for value in values], ensure_ascii=True))
    labels_json = safe(json.dumps(normalized_labels[: len(values)], ensure_ascii=True))
    return (
        f"<svg viewBox='0 0 {width} {height}' class='sparkline'"
        f" data-values='{values_json}'"
        f" data-labels='{labels_json}'"
        f" data-title='{safe(title or '')}'"
        f" data-format='{safe(value_format)}'"
        f" data-previewable='{'1' if previewable else '0'}'>"
        f"<polyline points='0,{baseline} {width},{baseline}' fill='none' stroke='rgba(0,0,0,0.08)' stroke-width='1' />"
        f"<polygon points='{area}' fill='{fill}' opacity='0.18' />"
        f"<polyline points='{line}' fill='none' stroke='{stroke}' stroke-width='3' stroke-linecap='round' stroke-linejoin='round' />"
        f"<circle cx='{points[-1][0]:.2f}' cy='{points[-1][1]:.2f}' r='3.5' fill='{stroke}' />"
        "</svg>"
    )


def role_badge(role: str) -> str:
    styles = {
        "activo": "badge badge-active",
        "referencia": "badge badge-reference",
        "base": "badge badge-base",
        "observado": "badge badge-observed",
        "legacy_ml": "badge badge-legacy",
    }
    return f"<span class='{styles.get(role, 'badge')}'>{safe(role)}</span>"


def freshness_badge(stale_market_days: int | None) -> str:
    if stale_market_days is None:
        return "<span class='badge badge-muted'>sin fecha</span>"
    if stale_market_days == 0:
        return "<span class='badge badge-fresh'>al dia</span>"
    if stale_market_days == 1:
        return "<span class='badge badge-warn'>1 rueda atras</span>"
    return f"<span class='badge badge-stale'>{stale_market_days} ruedas atras</span>"


def competition_freshness_date(row: dict[str, Any]) -> Any:
    return row.get("latest_snapshot_date") or row.get("last_date")


def competition_signal_date(row: dict[str, Any]) -> Any:
    return row.get("last_signal_date") or row.get("last_date")


def metric_card(title: str, value: str, subtitle: str, spark: str = "", tone: str = "neutral") -> str:
    return (
        f"<section class='metric-card tone-{tone}'>"
        f"<div class='metric-title'>{safe(title)}</div>"
        f"<div class='metric-value'>{safe(value)}</div>"
        f"<div class='metric-subtitle'>{safe(subtitle)}</div>"
        f"{spark}"
        "</section>"
    )


def render_latest_pick_rows(results: list[dict[str, Any]]) -> str:
    if not results:
        return "<tr><td colspan='8' class='muted center'>Sin picks en el snapshot mas reciente.</td></tr>"
    rows = []
    for item in results:
        rows.append(
            "<tr>"
            f"<td>{safe(item.get('ticker'))}</td>"
            f"<td>{safe(item.get('signal'))}</td>"
            f"<td>{safe(item.get('sector'))}</td>"
            f"<td>{fmt_ratio(item.get('priority_score') or item.get('score'), 1)}</td>"
            f"<td>{fmt_pct(item.get('priority_expected_return'), 2, signed=True)}</td>"
            f"<td>{fmt_pct(item.get('risk_pct'), 1)}</td>"
            f"<td>{fmt_ratio(item.get('rsi'), 1)}</td>"
            f"<td>{safe(item.get('note') or '-')}</td>"
            "</tr>"
        )
    return "".join(rows)


def render_competition_rows(rows: list[dict[str, Any]]) -> str:
    html_rows = []
    for row in rows:
        bar_width = max(0, min(100, int(round(to_float(row.get("accuracy_pct")) or 0))))
        spark_values = [float(value) for value in row.get("spark_cumulative_return_pct", []) if value is not None]
        spark = sparkline_svg(
            spark_values,
            "#0b7fab",
            "#0b7fab",
            width=160,
            height=46,
            labels=[str(label) for label in (row.get("spark_labels") or [])],
            title=f"{row['version']} | retorno acumulado",
            value_format="pct",
            previewable=True,
        )
        latest = ", ".join(row.get("latest_tickers", [])[:6]) or "-"
        html_rows.append(
            "<tr>"
            f"<td><strong>{safe(row['version'])}</strong><br>{role_badge(str(row['role']))}</td>"
            f"<td>{freshness_badge(row.get('stale_market_days'))}<br><span class='mini'>{fmt_date(competition_freshness_date(row))}</span></td>"
            f"<td>{fmt_int(row.get('evaluated'))}<br><span class='mini'>{fmt_int(row.get('pred_days'))} ruedas</span></td>"
            f"<td><div class='bar-track'><div class='bar-fill' style='width:{bar_width}%'></div></div><span class='mini'>{fmt_pct(row.get('accuracy_pct'))}</span></td>"
            f"<td>{fmt_pct(row.get('avg_return_pct'), 3, signed=True)}<br><span class='mini'>conf {fmt_pct(row.get('avg_confidence_pct'))}</span></td>"
            f"<td>{fmt_int(row.get('unique_tickers'))}<br><span class='mini'>{fmt_int(row.get('latest_picks'))} picks latest</span></td>"
            f"<td>{spark}</td>"
            f"<td class='tight'>{safe(latest)}</td>"
            "</tr>"
        )
    return "".join(html_rows)


def heat_color(value: float | None) -> str:
    if value is None:
        return "rgba(130, 130, 130, 0.14)"
    clamped = max(0.0, min(1.0, value))
    red = int(242 - clamped * 180)
    green = int(235 - clamped * 60)
    blue = int(224 - clamped * 130)
    return f"rgba({red}, {green}, {blue}, 0.95)"


def render_overlap_matrix(payload: dict[str, Any]) -> str:
    labels = payload["labels"]
    matrix = payload["matrix"]
    common_days = payload["common_days"]
    header = "".join(f"<th>{safe(label)}</th>" for label in labels)
    rows = []
    for idx, label in enumerate(labels):
        cells = [f"<th>{safe(label)}</th>"]
        for jdx, value in enumerate(matrix[idx]):
            title = f"Jaccard medio {fmt_ratio((value or 0) * 100, 1)} | dias comunes {common_days[idx][jdx]}"
            text = "-" if value is None else f"{value:.3f}"
            cells.append(
                f"<td style='background:{heat_color(value)}' title='{safe(title)}'>{safe(text)}</td>"
            )
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        "<table class='matrix-table'>"
        "<thead><tr><th></th>"
        f"{header}"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def render_sector_table(rows: list[dict[str, Any]], empty_text: str) -> str:
    if not rows:
        return f"<div class='panel-note'>{safe(empty_text)}</div>"
    body = []
    for row in rows:
        body.append(
            "<tr>"
            f"<td>{safe(row.get('sector'))}</td>"
            f"<td>{fmt_int(row.get('total'))}</td>"
            f"<td>{fmt_pct(row.get('accuracy_pct'))}</td>"
            f"<td>{fmt_pct(row.get('avg_return_pct'), 3, signed=True)}</td>"
            "</tr>"
        )
    return (
        "<table class='data-table compact'>"
        "<thead><tr><th>Sector</th><th>N</th><th>WR</th><th>Ret</th></tr></thead>"
        "<tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def render_model_strip(rows: list[dict[str, Any]]) -> str:
    cards = []
    for row in rows:
        cards.append(
            "<article class='model-strip-card'>"
            f"<div class='model-strip-head'><strong>{safe(row['version'])}</strong>{role_badge(str(row['role']))}</div>"
            f"<div class='model-strip-fresh'>{freshness_badge(row.get('stale_market_days'))}</div>"
            f"<div class='model-strip-metrics'>WR {fmt_pct(row.get('accuracy_pct'))} | Ret {fmt_pct(row.get('avg_return_pct'), 3, signed=True)}</div>"
            f"<div class='model-strip-picks'>{safe(', '.join(row.get('latest_tickers', [])[:8]) or '-')}</div>"
            "</article>"
        )
    return "".join(cards)


def render_chart_hover_css() -> str:
    return """
    .sparkline[data-values]{cursor:crosshair}
    .sparkline.is-previewable{cursor:zoom-in}
    .sparkline-preview-wrap{display:flex;align-items:center;justify-content:flex-start;min-width:230px}
    .league-spark-cell{min-width:230px;width:250px}
    .league-spark-cell .sparkline{margin-top:0}
    .chart-hover-tooltip{
      position:fixed;z-index:96;max-width:280px;padding:10px 12px;border-radius:14px;
      background:rgba(5,12,20,0.96);border:1px solid rgba(255,255,255,0.10);box-shadow:0 18px 40px rgba(0,0,0,0.35);
      color:#edf4fb;font-size:12px;line-height:1.45;pointer-events:none;opacity:0;transform:translateY(6px);
      transition:opacity .08s ease, transform .08s ease
    }
    .chart-hover-tooltip.show{opacity:1;transform:translateY(0)}
    .chart-hover-tooltip strong{display:block;margin-bottom:4px}
    .chart-hover-label{color:#8ea4b8;font-size:11px}
    .chart-hover-value{margin-top:6px;font-size:14px;font-weight:800;color:#ffffff}
    .chart-preview-panel{
      position:fixed;right:18px;bottom:18px;z-index:95;width:min(520px, calc(100vw - 28px));
      padding:14px 14px 12px 14px;border-radius:22px;background:linear-gradient(180deg, rgba(16,29,48,0.98) 0%, rgba(10,19,33,0.98) 100%);
      border:1px solid rgba(255,255,255,0.10);box-shadow:0 26px 65px rgba(0,0,0,0.40);
      opacity:0;transform:translateY(12px);pointer-events:none;transition:opacity .12s ease, transform .12s ease
    }
    .chart-preview-panel.show{opacity:1;transform:translateY(0)}
    .chart-preview-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-end;margin-bottom:10px}
    .chart-preview-title{font-size:12px;text-transform:uppercase;letter-spacing:0.12em;color:#8ea4b8;font-weight:800}
    .chart-preview-meta{font-size:18px;font-weight:800;color:#edf4fb;text-align:right}
    .chart-preview-canvas{border-radius:16px;padding:8px 10px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06)}
    .chart-preview-canvas svg{display:block;width:100%;height:auto;max-height:240px}
    @media (max-width: 900px){
      .chart-preview-panel{left:14px;right:14px;width:auto}
      .league-spark-cell{min-width:190px;width:210px}
    }
    """


def render_chart_interaction_script() -> str:
    return r"""
(function(){
  function parseList(raw){
    try {
      const data = JSON.parse(raw || "[]");
      return Array.isArray(data) ? data : [];
    } catch (_) {
      return [];
    }
  }
  function clamp(value, min, max){
    return Math.min(max, Math.max(min, value));
  }
  function ensureTooltip(){
    let tooltip = document.getElementById("chartHoverTooltip");
    if (!tooltip) {
      tooltip = document.createElement("div");
      tooltip.id = "chartHoverTooltip";
      tooltip.className = "chart-hover-tooltip";
      document.body.appendChild(tooltip);
    }
    return tooltip;
  }
  function ensurePreview(){
    let preview = document.getElementById("chartPreviewPanel");
    if (!preview) {
      preview = document.createElement("div");
      preview.id = "chartPreviewPanel";
      preview.className = "chart-preview-panel";
      preview.innerHTML =
        "<div class='chart-preview-head'>"
        + "<div class='chart-preview-title'></div>"
        + "<div class='chart-preview-meta'></div>"
        + "</div>"
        + "<div class='chart-preview-canvas'></div>";
      document.body.appendChild(preview);
    }
    return preview;
  }
  function formatValue(value, format){
    const num = Number(value);
    if (!Number.isFinite(num)) return "—";
    if (format === "int") return Math.round(num).toLocaleString("es-AR");
    if (format === "float") return num.toFixed(2);
    return (num >= 0 ? "+" : "") + num.toFixed(2) + "%";
  }
  function viewBoxSize(svg){
    const raw = (svg.getAttribute("viewBox") || "").trim().split(/\s+/).map(Number);
    if (raw.length === 4 && raw.every(Number.isFinite)) {
      return { width: raw[2], height: raw[3] };
    }
    return { width: 240, height: 72 };
  }
  function ensureMarker(svg){
    if (svg._sparkHoverMarker) return svg._sparkHoverMarker;
    const marker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    marker.setAttribute("r", "5");
    marker.setAttribute("fill", "#ffffff");
    marker.setAttribute("stroke", svg.dataset.markerStroke || "#21c7c4");
    marker.setAttribute("stroke-width", "2");
    marker.setAttribute("opacity", "0");
    marker.setAttribute("pointer-events", "none");
    svg.appendChild(marker);
    svg._sparkHoverMarker = marker;
    return marker;
  }
  function moveMarker(svg, values, index){
    const marker = ensureMarker(svg);
    const box = viewBoxSize(svg);
    const width = box.width;
    const height = box.height;
    const lo = Math.min.apply(null, values);
    const hi = Math.max.apply(null, values);
    const span = (hi - lo) || 1;
    const x = index * (width - 8) / Math.max(values.length - 1, 1) + 4;
    const y = height - 8 - ((values[index] - lo) / span) * (height - 16);
    marker.setAttribute("cx", x.toFixed(2));
    marker.setAttribute("cy", y.toFixed(2));
    marker.setAttribute("opacity", "1");
  }
  function hideMarker(svg){
    const marker = svg._sparkHoverMarker;
    if (marker) marker.setAttribute("opacity", "0");
  }
  function nearestIndex(svg, event, values){
    const rect = svg.getBoundingClientRect();
    const ratio = clamp((event.clientX - rect.left) / Math.max(rect.width, 1), 0, 1);
    return Math.round(ratio * Math.max(values.length - 1, 0));
  }
  function positionTooltip(tooltip, event){
    tooltip.style.left = Math.min(window.innerWidth - tooltip.offsetWidth - 16, event.clientX + 16) + "px";
    tooltip.style.top = Math.min(window.innerHeight - tooltip.offsetHeight - 16, event.clientY + 16) + "px";
  }
  function updatePreview(svg, label, valueText){
    if (svg.dataset.previewable !== "1") return;
    const preview = ensurePreview();
    preview.querySelector(".chart-preview-title").textContent = svg.dataset.title || "Preview";
    preview.querySelector(".chart-preview-meta").textContent = label + " · " + valueText;
    preview.querySelector(".chart-preview-canvas").innerHTML = svg.outerHTML;
    preview.classList.add("show");
    svg.classList.add("is-previewable");
  }
  function hidePreview(svg){
    if (svg) svg.classList.remove("is-previewable");
    const preview = document.getElementById("chartPreviewPanel");
    if (preview) preview.classList.remove("show");
  }
  function bindSpark(svg){
    if (svg.dataset.hoverBound === "1") return;
    svg.dataset.hoverBound = "1";
    const values = parseList(svg.dataset.values);
    const labels = parseList(svg.dataset.labels);
    if (!values.length) return;
    const tooltip = ensureTooltip();
    svg.dataset.markerStroke = svg.querySelector("polyline[stroke]")?.getAttribute("stroke") || "#21c7c4";
    function update(event){
      const idx = nearestIndex(svg, event, values);
      const label = String(labels[idx] || ("Punto " + (idx + 1)));
      const valueText = formatValue(values[idx], svg.dataset.format || "pct");
      tooltip.innerHTML =
        "<strong>" + (svg.dataset.title || "Serie") + "</strong>"
        + "<div class='chart-hover-label'>" + label + "</div>"
        + "<div class='chart-hover-value'>" + valueText + "</div>";
      tooltip.classList.add("show");
      positionTooltip(tooltip, event);
      moveMarker(svg, values.map(Number), idx);
      updatePreview(svg, label, valueText);
    }
    function leave(){
      tooltip.classList.remove("show");
      hideMarker(svg);
      hidePreview(svg);
    }
    svg.addEventListener("mouseenter", update);
    svg.addEventListener("mousemove", update);
    svg.addEventListener("mouseleave", leave);
  }
  function init(){
    document.querySelectorAll("svg.sparkline[data-values]").forEach(bindSpark);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
"""


def render_base_css() -> str:
    return """
    :root{
      --bg:#f4efe8;
      --panel:#fffaf2;
      --panel-strong:#f7efe0;
      --ink:#1e2428;
      --muted:#5f6a72;
      --line:#dbcdb9;
      --accent:#0b7fab;
      --gold:#b7852b;
      --rose:#b65b46;
      --mint:#3f7f61;
      --shadow:0 18px 40px rgba(72, 52, 22, 0.10);
      --radius:22px;
    }
    *{box-sizing:border-box}
    body{
      margin:0;
      font-family:"Aptos","Segoe UI",sans-serif;
      color:var(--ink);
      background:
        radial-gradient(circle at top right, rgba(11,127,171,0.10), transparent 24%),
        radial-gradient(circle at left 20%, rgba(183,133,43,0.12), transparent 22%),
        linear-gradient(180deg, #faf6ef 0%, var(--bg) 100%);
    }
    .page{width:min(1480px, calc(100vw - 40px));margin:28px auto 48px auto}
    .hero{display:grid;grid-template-columns:1.35fr 0.95fr;gap:22px;margin-bottom:22px}
    .hero-panel,.panel,.metric-card,.variant-card,.model-strip-card{
      background:var(--panel);border:1px solid rgba(110,90,50,0.14);border-radius:var(--radius);box-shadow:var(--shadow)
    }
    .hero-panel{padding:28px 30px}
    .eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:0.16em;color:var(--accent);font-weight:700}
    h1{font-family:"Georgia","Times New Roman",serif;font-size:48px;line-height:1.02;margin:10px 0 12px 0;letter-spacing:-0.03em}
    .hero-copy{font-size:17px;line-height:1.6;color:var(--muted);max-width:74ch}
    .hero-grid,.metric-grid{display:grid;gap:14px}
    .hero-grid{grid-template-columns:repeat(2,minmax(0,1fr));margin-top:20px}
    .metric-grid{grid-template-columns:repeat(4,minmax(0,1fr));margin-bottom:22px}
    .metric-card{padding:18px 18px 14px 18px;overflow:hidden;position:relative}
    .tone-accent{background:linear-gradient(180deg, #fafdff 0%, #eef8fc 100%)}
    .tone-gold{background:linear-gradient(180deg, #fffaf2 0%, #fbf0df 100%)}
    .tone-rose{background:linear-gradient(180deg, #fff9f7 0%, #f8ebe5 100%)}
    .tone-mint{background:linear-gradient(180deg, #fbfffc 0%, #edf6f0 100%)}
    .metric-title{font-size:12px;text-transform:uppercase;letter-spacing:0.14em;color:var(--muted);font-weight:700}
    .metric-value{font-size:34px;font-weight:800;letter-spacing:-0.03em;margin-top:10px}
    .metric-subtitle{font-size:13px;line-height:1.5;color:var(--muted);margin-top:6px}
    .sparkline{display:block;width:100%;height:auto;margin-top:14px}
    .panel{padding:22px 24px;margin-bottom:22px}
    .section-head{display:flex;justify-content:space-between;align-items:flex-end;gap:14px;margin-bottom:18px}
    .section-title{font-family:"Georgia","Times New Roman",serif;font-size:30px;letter-spacing:-0.03em;margin:0}
    .section-copy{color:var(--muted);font-size:14px;line-height:1.5;max-width:76ch}
    .two-col{display:grid;grid-template-columns:1.2fr 0.8fr;gap:18px}
    .three-col{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}
    .data-table{width:100%;border-collapse:collapse;font-size:14px}
    .data-table th,.data-table td{padding:12px 10px;border-top:1px solid rgba(80,70,40,0.12);text-align:left;vertical-align:top}
    .data-table thead th{border-top:none;font-size:12px;text-transform:uppercase;letter-spacing:0.12em;color:var(--muted)}
    .data-table.compact th,.data-table.compact td{padding:9px 8px}
    .mini{font-size:12px;color:var(--muted)}
    .muted{color:var(--muted)}
    .center{text-align:center}
    .tight{max-width:280px}
    .bar-track{width:100%;height:8px;border-radius:999px;background:rgba(11,127,171,0.12);overflow:hidden;margin-bottom:8px}
    .bar-fill{height:100%;border-radius:999px;background:linear-gradient(90deg, #0b7fab 0%, #2aa17e 100%)}
    .badge{display:inline-flex;align-items:center;padding:4px 9px;border-radius:999px;font-size:11px;text-transform:uppercase;letter-spacing:0.09em;font-weight:800;background:rgba(60,70,80,0.08);color:var(--muted)}
    .badge-active{background:#dff2fa;color:#0a678b}.badge-reference{background:#f2ebd6;color:#87611a}.badge-base{background:#ece7de;color:#5b564e}.badge-observed{background:#e7f1ea;color:#42725b}.badge-legacy{background:#efe5f5;color:#6b4c8e}.badge-fresh{background:#dff3e8;color:#2e6f51}.badge-warn{background:#fff0d8;color:#8f5e17}.badge-stale{background:#f7e3dc;color:#99513e}.badge-muted{background:#ece7e0;color:#6e655a}
    .note-list{margin:0;padding-left:18px;color:var(--muted);line-height:1.6}.note-list li{margin-bottom:8px}
    .panel-note{color:var(--muted);font-size:14px;line-height:1.6;padding:8px 0 2px 0}
    .matrix-table{width:100%;border-collapse:separate;border-spacing:8px;table-layout:fixed}
    .matrix-table th{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;text-align:center}
    .matrix-table td{text-align:center;padding:14px 8px;border-radius:14px;font-weight:800}
    .model-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}
    .model-strip-card{padding:16px;min-height:160px}
    .model-strip-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px}
    .model-strip-fresh{margin-bottom:12px}.model-strip-metrics{font-size:14px;font-weight:700;margin-bottom:12px}.model-strip-picks{color:var(--muted);font-size:13px;line-height:1.5}
    .variant-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px;margin-top:24px}
    .variant-card{padding:26px}.variant-card h3{margin:0 0 10px 0;font-family:"Georgia","Times New Roman",serif;font-size:28px}
    .variant-links a,.button-link{display:inline-flex;align-items:center;gap:10px;text-decoration:none;color:white;background:linear-gradient(135deg, #0b7fab 0%, #2b5364 100%);padding:12px 16px;border-radius:999px;font-weight:700;letter-spacing:0.02em;margin-right:10px;margin-top:8px}
    .inline-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
    .kpi-line{display:flex;justify-content:space-between;gap:12px;border-top:1px solid rgba(80,70,40,0.12);padding:10px 0;font-size:14px}.kpi-line:first-child{border-top:none;padding-top:0}
    .footer-note{margin-top:18px;color:var(--muted);font-size:13px;line-height:1.6}
    @media (max-width: 1180px){.hero,.two-col,.three-col,.metric-grid,.model-strip,.variant-grid,.inline-grid{grid-template-columns:1fr}.page{width:min(100vw - 24px, 1480px)}}
    """ + render_chart_hover_css()


def render_main_css() -> str:
    return """
    :root{
      --bg:#08111f;
      --bg-2:#0b1627;
      --sidebar:#0a1321;
      --panel:#101d30;
      --panel-2:#13253a;
      --panel-3:#0f1928;
      --ink:#edf4fb;
      --muted:#8ea4b8;
      --line:rgba(169,191,211,0.12);
      --cyan:#21c7c4;
      --cyan-2:#49dbc4;
      --gold:#f0c96f;
      --green:#58d39b;
      --rose:#ff7e86;
      --violet:#8f86ff;
      --shadow:0 24px 60px rgba(0,0,0,0.35);
      --radius:22px;
      --sidebar-width:280px;
      --layout-gap:18px;
      --grid-gap:14px;
    }
    *{box-sizing:border-box}
    body{
      margin:0;
      font-family:"Aptos","Segoe UI",sans-serif;
      color:var(--ink);
      background:
        radial-gradient(circle at top right, rgba(33,199,196,0.16), transparent 18%),
        radial-gradient(circle at left 12%, rgba(240,201,111,0.10), transparent 18%),
        linear-gradient(180deg, var(--bg-2) 0%, var(--bg) 100%);
    }
    .app-shell{display:grid;grid-template-columns:var(--sidebar-width) minmax(0,1fr);gap:12px;width:min(1680px, calc(100vw - 16px));margin:12px auto 20px auto;transition:grid-template-columns .22s ease}
    .sidebar{
      position:sticky;top:18px;height:calc(100vh - 36px);overflow:auto;
      background:linear-gradient(180deg, rgba(10,19,33,0.98) 0%, rgba(8,16,28,0.98) 100%);
      border:1px solid var(--line);border-radius:24px;box-shadow:var(--shadow);padding:16px 14px;transition:transform .22s ease, opacity .22s ease, width .22s ease, padding .22s ease, border .22s ease
    }
    .content{min-width:0}
    .topbar,.panel,.stat-card,.focus-card,.mini-card,.sidebar{
      background:linear-gradient(180deg, rgba(17,31,49,0.98) 0%, rgba(12,24,39,0.98) 100%);
      border:1px solid var(--line);
      box-shadow:var(--shadow)
    }
    .topbar,.panel,.stat-card,.focus-card,.mini-card{border-radius:var(--radius)}
    .topbar{padding:12px 14px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;gap:12px}
    .eyebrow,.sidebar-label,.section-label{font-size:11px;text-transform:uppercase;letter-spacing:0.16em;color:var(--cyan);font-weight:800}
    .brand{font-family:"Georgia","Times New Roman",serif;font-size:24px;line-height:1.02;letter-spacing:-0.03em}
    .brand span{display:block;font-family:"Aptos","Segoe UI",sans-serif;font-size:12px;letter-spacing:0.18em;text-transform:uppercase;color:var(--muted);margin-top:6px}
    .sidebar-section{margin-top:14px}
    .side-nav{display:flex;flex-direction:column;gap:8px;margin-top:12px}
    .nav-link,.side-button{
      display:flex;align-items:center;justify-content:space-between;gap:10px;text-decoration:none;
      padding:12px 14px;border-radius:16px;border:1px solid rgba(255,255,255,0.05);background:rgba(255,255,255,0.03);
      color:var(--ink);font-weight:700;font-size:14px
    }
    .nav-link.active{background:linear-gradient(135deg, rgba(33,199,196,0.20), rgba(73,219,196,0.14));border-color:rgba(33,199,196,0.20)}
    .side-button{justify-content:center}
    .drawer{margin-top:12px;border:1px solid rgba(255,255,255,0.06);border-radius:18px;background:rgba(255,255,255,0.03);overflow:hidden}
    .drawer summary{list-style:none;cursor:pointer;padding:13px 14px;font-weight:800;font-size:13px;color:var(--ink)}
    .drawer summary::-webkit-details-marker{display:none}
    .drawer-body{padding:0 14px 14px 14px;color:var(--muted);font-size:13px;line-height:1.65}
    .drawer-body .kpi-line{font-size:13px}
    h1{font-family:"Georgia","Times New Roman",serif;font-size:28px;line-height:1.04;margin:4px 0 8px 0;letter-spacing:-0.03em}
    h2,h3{font-family:"Georgia","Times New Roman",serif;letter-spacing:-0.03em;margin:0}
    .section-copy,.footer-note,.muted{color:var(--muted);line-height:1.6}
    .header-meta,.pill-row{display:flex;flex-wrap:wrap;gap:10px}
    .pill{display:inline-flex;align-items:center;padding:7px 10px;border-radius:999px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);font-size:11px;color:#d6e4ee}
    .toolbar{display:flex;flex-wrap:wrap;gap:10px;justify-content:flex-end}
    .button-link{
      display:inline-flex;align-items:center;text-decoration:none;color:#061119;
      background:linear-gradient(135deg, var(--cyan) 0%, var(--cyan-2) 100%);
      padding:8px 12px;border-radius:999px;font-weight:800;letter-spacing:0.01em;font-size:12px
    }
    .ghost-link{
      display:inline-flex;align-items:center;text-decoration:none;color:var(--ink);
      background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);
      padding:8px 12px;border-radius:999px;font-weight:700;font-size:12px
    }
    .kpi-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin-bottom:10px}
    .stat-card{padding:10px 12px;min-height:96px}
    .stat-label{font-size:12px;text-transform:uppercase;letter-spacing:0.14em;color:var(--muted);font-weight:700}
    .stat-value{font-size:21px;font-weight:800;letter-spacing:-0.03em;margin-top:6px;line-height:1.05}
    .stat-subtitle{font-size:11px;line-height:1.35;color:var(--muted);margin-top:4px}
    .accent-cyan{background:linear-gradient(180deg, rgba(35,201,200,0.17) 0%, rgba(16,37,49,0.98) 100%)}
    .accent-gold{background:linear-gradient(180deg, rgba(243,201,106,0.16) 0%, rgba(16,37,49,0.98) 100%)}
    .accent-green{background:linear-gradient(180deg, rgba(94,211,157,0.16) 0%, rgba(16,37,49,0.98) 100%)}
    .accent-rose{background:linear-gradient(180deg, rgba(255,125,125,0.15) 0%, rgba(16,37,49,0.98) 100%)}
    .section{margin-bottom:var(--layout-gap)}
    .panel{padding:14px 16px}
    .section-head,.panel-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px}
    .section-title{font-size:19px;line-height:1.1}
    .main-grid{display:grid;grid-template-columns:1.3fr 0.9fr;gap:12px;margin-bottom:12px}
    .prime-grid{display:grid;grid-template-columns:0.74fr 1.26fr;gap:12px;margin-bottom:12px}
    .secondary-grid{display:grid;grid-template-columns:1.05fr 1.05fr 0.9fr;gap:12px;margin-bottom:12px}
    .bottom-grid{display:grid;grid-template-columns:1.15fr 0.85fr;gap:12px;margin-bottom:12px}
    .stack{display:grid;gap:12px}
    .hero-chart{min-height:100%}
    .chart-wrap{padding:4px 0 0 0}
    .dense-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--grid-gap)}
    .focus-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
    .group-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
    .mini-card{padding:10px 11px;border-radius:16px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06)}
    .mini-title{font-size:10px;text-transform:uppercase;letter-spacing:0.12em;color:var(--muted);font-weight:700}
    .mini-value{font-size:16px;font-weight:800;margin-top:5px;line-height:1.15}
    .data-table{width:100%;border-collapse:collapse;font-size:12px}
    .data-table th,.data-table td{padding:8px 7px;border-top:1px solid rgba(255,255,255,0.07);text-align:left;vertical-align:top}
    .data-table thead th{border-top:none;font-size:10px;text-transform:uppercase;letter-spacing:0.11em;color:var(--muted)}
    .data-table.compact th,.data-table.compact td{padding:6px 6px}
    .leaderboard-table td:first-child,.leaderboard-table th:first-child{padding-left:0}
    .kpi-line{display:flex;justify-content:space-between;gap:10px;padding:5px 0;border-top:1px solid rgba(255,255,255,0.06);font-size:12px}
    .kpi-line:first-child{border-top:none;padding-top:0}
    .rank-chip{display:inline-flex;align-items:center;justify-content:center;min-width:28px;height:28px;border-radius:999px;background:linear-gradient(135deg, rgba(35,201,200,0.22), rgba(79,224,193,0.30));font-weight:800;font-size:12px}
    .subtle-box,.window-block{padding:9px 10px;border-radius:14px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06)}
    .window-title{font-size:12px;text-transform:uppercase;letter-spacing:0.12em;color:var(--muted);font-weight:700;margin-bottom:8px}
    .window-value{font-size:18px;font-weight:800}
    .window-caption,.mini{font-size:12px;color:var(--muted)}
    .focus-card{padding:16px;display:flex;flex-direction:column;gap:12px}
    .focus-head{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
    .focus-name{font-size:21px}
    .focus-meta{display:flex;flex-wrap:wrap;gap:8px}
    .model-card{padding:10px 11px;border-radius:18px;background:linear-gradient(180deg, rgba(18,31,48,0.98) 0%, rgba(12,23,37,0.98) 100%);border:1px solid rgba(255,255,255,0.07);box-shadow:var(--shadow)}
    .model-card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:10px}
    .model-card-title{font-size:17px;font-weight:800;letter-spacing:-0.02em}
    .model-card-chart{margin:2px 0 8px 0}
    .model-card-kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin-bottom:8px}
    .model-kpi{padding:7px 8px;border-radius:12px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06)}
    .model-kpi span{display:block;font-size:9px;text-transform:uppercase;letter-spacing:0.10em;color:var(--muted);font-weight:700}
    .model-kpi strong{display:block;font-size:13px;margin-top:4px;line-height:1.15}
    .card-details{margin-top:12px;border:1px solid rgba(255,255,255,0.06);border-radius:16px;background:rgba(255,255,255,0.03);overflow:hidden}
    .card-details summary{list-style:none;cursor:pointer;padding:12px 14px;font-weight:800;font-size:13px}
    .card-details summary::-webkit-details-marker{display:none}
    .card-details-body{padding:0 14px 14px 14px}
    .detail-picks{margin-top:8px;color:var(--muted);font-size:12px;line-height:1.45}
    .ticker-cloud{font-size:11px;line-height:1.55;color:#dbe7ed}
    .ticker-cloud code{background:rgba(255,255,255,0.06);padding:2px 5px;border-radius:999px;margin-right:4px;display:inline-block;margin-bottom:4px}
    .badge{display:inline-flex;align-items:center;padding:4px 9px;border-radius:999px;font-size:11px;text-transform:uppercase;letter-spacing:0.09em;font-weight:800;background:rgba(255,255,255,0.08);color:var(--muted)}
    .badge-active{background:rgba(35,201,200,0.18);color:#8df4f3}
    .badge-reference{background:rgba(243,201,106,0.18);color:#ffd979}
    .badge-base{background:rgba(255,255,255,0.10);color:#e6edf2}
    .badge-observed{background:rgba(94,211,157,0.18);color:#93f1c0}
    .badge-legacy{background:rgba(163,126,255,0.20);color:#d2bbff}
    .badge-fresh{background:rgba(94,211,157,0.18);color:#93f1c0}.badge-warn{background:rgba(243,201,106,0.18);color:#ffd979}.badge-stale{background:rgba(255,125,125,0.18);color:#ffb6b6}.badge-muted{background:rgba(255,255,255,0.09);color:#cbd8de}
    .heat-table{width:100%;border-collapse:separate;border-spacing:4px;table-layout:fixed}
    .heat-table th{font-size:10px;text-transform:uppercase;letter-spacing:0.10em;color:var(--muted);padding:0 2px 6px 2px}
    .heat-table td{padding:7px 4px;border-radius:10px;text-align:center;font-size:11px;font-weight:800;cursor:help}
    .heat-table .row-label{background:none;border:none;text-align:left;padding-left:0;font-size:11px;min-width:88px}
    .sparkline{display:block;width:100%;height:auto}
    .footer-note{margin-top:10px;font-size:12px}
    .compact-ranking-grid{display:grid;grid-template-columns:0.8fr 1.2fr;gap:10px;margin-bottom:10px}
    .champion-compact .chart-wrap{max-width:100%}
    .scanner-top-note{font-size:11px;color:var(--muted);margin-bottom:8px}
    .sidebar-toggle{
      display:inline-flex;align-items:center;justify-content:center;min-width:34px;height:34px;border:none;border-radius:12px;
      background:rgba(255,255,255,0.06);color:var(--ink);cursor:pointer;font-size:16px;font-weight:900
    }
    .floating-sidebar-toggle{
      position:fixed;top:12px;left:12px;z-index:62;display:none;align-items:center;justify-content:center;
      width:40px;height:40px;border:none;border-radius:14px;background:rgba(16,29,48,0.96);color:var(--ink);box-shadow:var(--shadow);cursor:pointer
    }
    body.sidebar-collapsed .floating-sidebar-toggle{display:flex}
    body.sidebar-collapsed .app-shell{grid-template-columns:0 minmax(0,1fr)}
    body.sidebar-collapsed .sidebar{transform:translateX(-110%);opacity:0;pointer-events:none;width:0;padding:0;border-color:transparent}
    .editable-block{position:relative;transition:outline-color .15s ease, box-shadow .15s ease, opacity .15s ease}
    .editable-text{transition:box-shadow .15s ease, background .15s ease}
    body.edit-mode .editable-text{box-shadow:inset 0 -1px 0 rgba(73,219,196,0.45);cursor:text}
    body.edit-mode [data-block-id]{outline:1px dashed rgba(73,219,196,0.28)}
    body.edit-mode [data-block-id]:hover{outline-color:rgba(73,219,196,0.68)}
    .selected-block{outline:2px solid rgba(73,219,196,0.95) !important;box-shadow:0 0 0 3px rgba(73,219,196,0.12), var(--shadow) !important}
    .dragging-block{opacity:.45}
    .block-handle{
      position:absolute;top:10px;right:10px;z-index:4;display:none;
      width:30px;height:30px;border-radius:999px;border:1px solid rgba(255,255,255,0.10);
      background:rgba(8,17,31,0.82);color:var(--muted);font-size:15px;font-weight:800;
      align-items:center;justify-content:center;cursor:grab;backdrop-filter:blur(8px)
    }
    body.edit-mode .block-handle{display:flex}
    body.edit-mode .editable-block{overflow:visible;min-height:unset}
    .editor-toggle{
      position:fixed;right:22px;bottom:22px;z-index:60;border:none;border-radius:999px;
      background:linear-gradient(135deg, var(--cyan) 0%, var(--cyan-2) 100%);
      color:#04121a;padding:13px 18px;font-weight:900;letter-spacing:.01em;box-shadow:var(--shadow);cursor:pointer
    }
    .builder-panel{
      position:fixed;top:18px;right:18px;bottom:18px;z-index:70;width:350px;max-width:calc(100vw - 20px);
      padding:18px;background:linear-gradient(180deg, rgba(12,24,39,0.99) 0%, rgba(8,16,28,0.99) 100%);
      border:1px solid var(--line);border-radius:26px;box-shadow:var(--shadow);overflow:auto;
      transform:translateX(calc(100% + 24px));transition:transform .22s ease
    }
    body.builder-open .builder-panel{transform:translateX(0)}
    .builder-head{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;margin-bottom:16px}
    .builder-head h3{font-size:24px}
    .builder-close{
      border:none;background:rgba(255,255,255,0.06);color:var(--ink);border-radius:999px;
      width:34px;height:34px;cursor:pointer;font-size:18px;font-weight:800
    }
    .builder-group{padding:14px;border-radius:18px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.07);margin-bottom:14px}
    .builder-group h4{margin:0 0 10px 0;font-size:15px;letter-spacing:.02em}
    .builder-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
    .builder-field{display:flex;flex-direction:column;gap:6px;margin-bottom:10px}
    .builder-field label{font-size:12px;text-transform:uppercase;letter-spacing:.10em;color:var(--muted);font-weight:800}
    .builder-field input,.builder-field select,.builder-field textarea{
      width:100%;border-radius:12px;border:1px solid rgba(255,255,255,0.08);background:rgba(255,255,255,0.04);
      color:var(--ink);padding:10px 11px;font:inherit
    }
    .builder-field input[type="color"]{padding:4px;height:42px}
    .builder-field input[type="range"]{padding:0}
    .builder-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
    .builder-actions button,.builder-actions label{
      display:flex;align-items:center;justify-content:center;border:none;border-radius:14px;padding:11px 12px;
      cursor:pointer;font-weight:800;background:rgba(255,255,255,0.06);color:var(--ink);text-align:center
    }
    .builder-actions .primary{background:linear-gradient(135deg, var(--cyan) 0%, var(--cyan-2) 100%);color:#04121a}
    .builder-note{font-size:12px;line-height:1.55;color:var(--muted)}
    .builder-status{font-size:11px;color:var(--cyan);font-weight:800;min-height:18px;margin-top:8px}
    .selected-block-name{font-size:18px;font-weight:800;margin-bottom:10px}
    .hidden-block{display:none !important}
    .heat-tooltip{
      position:fixed;z-index:80;max-width:340px;padding:10px 12px;border-radius:14px;
      background:rgba(5,12,20,0.96);border:1px solid rgba(255,255,255,0.10);box-shadow:var(--shadow);
      color:var(--ink);font-size:12px;line-height:1.45;pointer-events:none;opacity:0;transform:translateY(6px);transition:opacity .08s ease, transform .08s ease
    }
    .heat-tooltip.show{opacity:1;transform:translateY(0)}
    .heat-tooltip strong{display:block;margin-bottom:4px}
    .heat-tooltip .muted-line{color:var(--muted);font-size:11px}
    @media (max-width: 1480px){.group-grid,.secondary-grid,.bottom-grid{grid-template-columns:1fr 1fr}.kpi-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.prime-grid{grid-template-columns:1fr}.compact-ranking-grid{grid-template-columns:1fr}}
    @media (max-width: 1220px){.app-shell{grid-template-columns:1fr}.sidebar{position:relative;height:auto}.main-grid,.prime-grid,.secondary-grid,.bottom-grid,.dense-grid,.kpi-grid,.focus-grid,.group-grid,.builder-grid,.builder-actions,.compact-ranking-grid{grid-template-columns:1fr}.builder-panel{left:12px;right:12px;width:auto}}
    """ + render_chart_hover_css()


def latest_ticker_cloud(tickers: list[str], limit: int = 12) -> str:
    if not tickers:
        return "<span class='mini'>Sin picks recientes.</span>"
    parts = [f"<code>{safe(ticker)}</code>" for ticker in tickers[:limit]]
    if len(tickers) > limit:
        parts.append(f"<span class='mini'>+{len(tickers) - limit}</span>")
    return "".join(parts)


def recent_value_text(window: dict[str, Any]) -> str:
    if window.get("accuracy_pct") is None:
        return "sin datos"
    return f"{fmt_pct(window.get('accuracy_pct'))} | {fmt_pct(window.get('avg_return_pct'), 3, signed=True)}"


def tone_for_role(role: str) -> tuple[str, str]:
    if role == "activo":
        return "#23c9c8", "#23c9c8"
    if role == "referencia":
        return "#f3c96a", "#f3c96a"
    if role == "legacy_ml":
        return "#a989ff", "#a989ff"
    if role == "observado":
        return "#5ed39d", "#5ed39d"
    return "#7db8d6", "#7db8d6"


def render_recent_rank_rows(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        window = row.get("window") or {}
        body.append(
            "<tr>"
            f"<td><span class='rank-chip'>{fmt_int(row.get('rank'))}</span></td>"
            f"<td><strong>{safe(row['version'])}</strong><br>{role_badge(str(row['role']))}</td>"
            f"<td>{freshness_badge(row.get('stale_market_days'))}<br><span class='mini'>{fmt_date(competition_freshness_date(row))}</span></td>"
            f"<td>{fmt_int(window.get('active_days'))}/{fmt_int(window.get('window_days'))}<br><span class='mini'>{fmt_int(window.get('evaluated'))} picks</span></td>"
            f"<td>{fmt_pct(window.get('accuracy_pct'))}<br><span class='mini'>mejor {fmt_pct(window.get('best_day_return_pct'), 2, signed=True)}</span></td>"
            f"<td>{fmt_pct(window.get('avg_return_pct'), 3, signed=True)}<br><span class='mini'>peor {fmt_pct(window.get('worst_day_return_pct'), 2, signed=True)}</span></td>"
            f"<td>{fmt_pct(window.get('avg_return_right_pct'), 2, signed=True)}<br><span class='mini'>{fmt_pct(window.get('avg_return_wrong_pct'), 2, signed=True)}</span></td>"
            f"<td class='tight'>{safe(', '.join(row.get('latest_tickers', [])[:8]) or '-')}</td>"
            "</tr>"
        )
    return "".join(body)


def render_compact_rank_rows(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        window = row.get("window") or {}
        body.append(
            "<tr>"
            f"<td><span class='rank-chip'>{fmt_int(row.get('rank'))}</span></td>"
            f"<td><strong>{safe(row['version'])}</strong><br>{role_badge(str(row['role']))}</td>"
            f"<td>{fmt_pct(window.get('accuracy_pct'))}<br><span class='mini'>{fmt_pct(window.get('avg_return_pct'), 3, signed=True)}</span></td>"
            f"<td>{fmt_int(window.get('active_days'))}/{fmt_int(window.get('window_days'))}<br><span class='mini'>{fmt_int(window.get('evaluated'))} picks</span></td>"
            f"<td class='tight'>{safe(', '.join(row.get('latest_tickers', [])[:5]) or '-')}</td>"
            "</tr>"
        )
    return "".join(body)


def render_window_block(title: str, window: dict[str, Any]) -> str:
    return (
        "<div class='window-block'>"
        f"<div class='window-title'>{safe(title)}</div>"
        f"<div class='window-value'>{safe(recent_value_text(window))}</div>"
        f"<div class='window-caption'>{fmt_int(window.get('active_days'))}/{fmt_int(window.get('window_days'))} ruedas | "
        f"{fmt_int(window.get('evaluated'))} picks | peor {fmt_pct(window.get('worst_day_return_pct'), 2, signed=True)}</div>"
        "</div>"
    )


def render_focus_cards(rows: list[dict[str, Any]]) -> str:
    cards = []
    for row in rows:
        stroke, fill = tone_for_role(str(row["role"]))
        spark = sparkline_svg(
            [float(value) for value in row.get("recent_30", {}).get("spark_avg_return_pct", []) if value is not None],
            stroke,
            fill,
            width=320,
            height=90,
            labels=sparkline_labels_from_calendar(row.get("recent_30") or {}),
            title=f"{row['version']} | contexto 30 ruedas",
            value_format="pct",
        )
        cards.append(
            "<article class='focus-card'>"
            "<div class='focus-head'>"
            f"<div><div class='focus-name'>{safe(row['version'])}</div><div class='focus-meta'>{role_badge(str(row['role']))} {freshness_badge(row.get('stale_market_days'))}</div></div>"
            f"<div class='mini'>{fmt_date(competition_freshness_date(row))}</div>"
            "</div>"
            f"{render_window_block('Muestra igualada', row.get('equalized_recent') or {})}"
            f"{render_window_block('Contexto 30 ruedas', row.get('recent_30') or {})}"
            f"<div class='subtle-box'><div class='window-title'>Proximos activos</div><div class='ticker-cloud'>{latest_ticker_cloud(row.get('latest_tickers', []))}</div>"
            f"<div class='window-caption'>prediction_date {fmt_date(competition_signal_date(row))} -> target {fmt_date(row.get('latest_target_date'))} | universo {fmt_int(row.get('unique_tickers'))}</div></div>"
            f"{spark}"
            "</article>"
        )
    return "".join(cards)


def heat_color_for_return(value: float | None) -> str:
    if value is None:
        return "rgba(255,255,255,0.06)"
    if value >= 0:
        intensity = min(abs(value) / 5.0, 1.0)
        return f"rgba(94, 211, 157, {0.18 + intensity * 0.48:.3f})"
    intensity = min(abs(value) / 5.0, 1.0)
    return f"rgba(255, 122, 122, {0.18 + intensity * 0.48:.3f})"


def render_recent_heatmap(rows: list[dict[str, Any]], dates: list[str]) -> str:
    header = "".join(f"<th>{safe(date_text[5:])}</th>" for date_text in dates)
    body = []
    for row in rows:
        calendar_map = {
            str(item["date"]): item for item in (row.get("recent_15", {}).get("calendar") or [])
        }
        cells = [f"<th class='row-label'><strong>{safe(row['version'])}</strong><br><span class='mini'>{safe(row['role'])}</span></th>"]
        for date_text in dates:
            item = calendar_map.get(date_text, {})
            ret = to_float(item.get("avg_return_pct"))
            acc = to_float(item.get("accuracy_pct"))
            picks = to_int(item.get("picks"))
            tickers = item.get("tickers") or []
            text = "-" if ret is None else f"{ret:+.1f}"
            ticker_preview = ", ".join(tickers[:12]) if tickers else "Sin picks"
            title = (
                f"{row['version']} | {date_text}\n"
                f"ret {fmt_pct(ret, 2, signed=True)} | WR {fmt_pct(acc)} | picks {picks}\n"
                f"{ticker_preview}"
            )
            cells.append(
                f"<td class='heat-cell' style='background:{heat_color_for_return(ret)}' title='{safe(title)}' "
                f"data-preview='{safe(title)}'>{safe(text)}</td>"
            )
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        "<table class='heat-table'>"
        "<thead><tr><th></th>"
        f"{header}"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def render_full_league_rows(rows: list[dict[str, Any]]) -> str:
    body = []
    for row in rows:
        equalized = row.get("equalized_recent") or {}
        thirty = row.get("recent_30") or {}
        role = str(row.get("role") or "")
        stroke, fill = tone_for_role(role)
        series = equalized.get("spark_avg_return_pct") or thirty.get("spark_avg_return_pct") or []
        labels = sparkline_labels_from_calendar(equalized) or sparkline_labels_from_calendar(thirty)
        curve = sparkline_svg(
            cumulative_series(series),
            stroke,
            fill,
            width=236,
            height=72,
            labels=labels,
            title=f"{row['version']} | curva reciente",
            value_format="pct",
            previewable=True,
        )
        body.append(
            "<tr>"
            f"<td><strong>{safe(row['version'])}</strong><br>{role_badge(str(row['role']))}</td>"
            f"<td>{freshness_badge(row.get('stale_market_days'))}<br><span class='mini'>{fmt_date(competition_freshness_date(row))}</span></td>"
            f"<td>{fmt_pct(equalized.get('accuracy_pct'))}<br><span class='mini'>{fmt_pct(equalized.get('avg_return_pct'), 3, signed=True)}</span></td>"
            f"<td>{fmt_int(equalized.get('active_days'))}/{fmt_int(equalized.get('window_days'))}<br><span class='mini'>{fmt_int(equalized.get('evaluated'))} picks</span></td>"
            f"<td>{fmt_pct(thirty.get('accuracy_pct'))}<br><span class='mini'>{fmt_pct(thirty.get('avg_return_pct'), 3, signed=True)}</span></td>"
            f"<td>{fmt_int(thirty.get('active_days'))}/{fmt_int(thirty.get('window_days'))}<br><span class='mini'>{fmt_int(thirty.get('evaluated'))} picks</span></td>"
            f"<td>{fmt_int(row.get('unique_tickers'))}<br><span class='mini'>{fmt_int(row.get('latest_picks'))} ultimos</span></td>"
            f"<td class='tight'>{safe(', '.join(row.get('latest_tickers', [])[:10]) or '-')}</td>"
            f"<td class='league-spark-cell'>{curve}</td>"
            "</tr>"
        )
    return "".join(body)


def cumulative_series(values: list[Any]) -> list[float]:
    total = 0.0
    out: list[float] = []
    for value in values:
        total += to_float(value) or 0.0
        out.append(round(total, 4))
    return out


def latest_overlap_pct(row: dict[str, Any], champion_latest: set[str]) -> float | None:
    current = set(row.get("latest_tickers", []) or [])
    if not current or not champion_latest:
        return None
    union = current | champion_latest
    if not union:
        return None
    return round(len(current & champion_latest) * 100.0 / len(union), 1)


def render_group_model_cards(rows: list[dict[str, Any]], champion_latest: set[str]) -> str:
    cards = []
    for row in rows:
        eq = row.get("equalized_recent") or {}
        thirty = row.get("recent_30") or {}
        role = str(row.get("role") or "")
        stroke, fill = tone_for_role(role)
        series = eq.get("spark_avg_return_pct") or thirty.get("spark_avg_return_pct") or []
        curve = sparkline_svg(
            cumulative_series(series),
            stroke,
            fill,
            width=280,
            height=84,
            labels=sparkline_labels_from_calendar(eq) or sparkline_labels_from_calendar(thirty),
            title=f"{row['version']} | muestra visible",
            value_format="pct",
        )
        overlap = latest_overlap_pct(row, champion_latest)
        block_id = f"model-{dom_id(role)}-{dom_id(row['version'])}"
        cards.append(
            f"<article class='model-card editable-block' data-block-id='{safe(block_id)}' data-block-label='{safe(row['version'])}'>"
            "<div class='model-card-head'>"
            f"<div><div class='model-card-title'>{safe(row['version'])}</div><div class='focus-meta'>{role_badge(role)} {freshness_badge(row.get('stale_market_days'))}</div></div>"
            f"<div class='rank-chip'>{fmt_int(row.get('rank'))}</div>"
            "</div>"
            f"<div class='model-card-chart'>{curve}</div>"
            "<div class='model-card-kpis'>"
            f"<div class='model-kpi'><span>WR</span><strong>{fmt_pct(eq.get('accuracy_pct'))}</strong></div>"
            f"<div class='model-kpi'><span>Ret</span><strong>{fmt_pct(eq.get('avg_return_pct'), 3, signed=True)}</strong></div>"
            f"<div class='model-kpi'><span>Hits</span><strong>{fmt_int(eq.get('hits'))}/{fmt_int(eq.get('evaluated'))}</strong></div>"
            f"<div class='model-kpi'><span>Activos</span><strong>{fmt_int(row.get('latest_picks'))}</strong></div>"
            "</div>"
            f"<div class='ticker-cloud'>{latest_ticker_cloud(row.get('latest_tickers', []), limit=8)}</div>"
            "<details class='card-details'>"
            "<summary>Mas data</summary>"
            "<div class='card-details-body'>"
            f"<div class='kpi-line'><span>WR igualado</span><strong>{fmt_pct(eq.get('accuracy_pct'))}</strong></div>"
            f"<div class='kpi-line'><span>Ret igualado</span><strong>{fmt_pct(eq.get('avg_return_pct'), 3, signed=True)}</strong></div>"
            f"<div class='kpi-line'><span>Hits / Misses</span><strong>{fmt_int(eq.get('hits'))} / {fmt_int(eq.get('misses'))}</strong></div>"
            f"<div class='kpi-line'><span>Ganancia media aciertos</span><strong>{fmt_pct(eq.get('avg_return_right_pct'), 2, signed=True)}</strong></div>"
            f"<div class='kpi-line'><span>Perdida media errores</span><strong>{fmt_pct(eq.get('avg_return_wrong_pct'), 2, signed=True)}</strong></div>"
            f"<div class='kpi-line'><span>Rango muestra igualada</span><strong>{fmt_date(eq.get('start_date'))} -> {fmt_date(eq.get('end_date'))}</strong></div>"
            f"<div class='kpi-line'><span>Contexto 30 ruedas</span><strong>{fmt_pct(thirty.get('accuracy_pct'))} | {fmt_pct(thirty.get('avg_return_pct'), 3, signed=True)}</strong></div>"
            f"<div class='kpi-line'><span>Ultima fecha</span><strong>{fmt_date(competition_freshness_date(row))}</strong></div>"
            f"<div class='kpi-line'><span>Target de picks</span><strong>{fmt_date(row.get('latest_target_date'))}</strong></div>"
            f"<div class='kpi-line'><span>Universo total</span><strong>{fmt_int(row.get('unique_tickers'))}</strong></div>"
            f"<div class='kpi-line'><span>Overlap ultimo set vs champion</span><strong>{fmt_pct(overlap) if overlap is not None else '-'}</strong></div>"
            f"<div class='detail-picks'>{safe(', '.join(row.get('latest_tickers', [])) or 'Sin picks recientes')}</div>"
            "</div>"
            "</details>"
            "</article>"
        )
    return "".join(cards)


def render_builder_markup() -> str:
    return """
  <button class="editor-toggle" id="editorToggle" type="button">Personalizar</button>
  <button class="floating-sidebar-toggle" id="floatingSidebarToggle" type="button" aria-label="Mostrar menu">|||</button>
  <aside class="builder-panel" id="builderPanel" aria-hidden="true">
    <div class="builder-head">
      <div>
        <div class="sidebar-label">Editor visual</div>
        <h3>Personaliza el dashboard</h3>
      </div>
      <button class="builder-close" id="builderClose" type="button">×</button>
    </div>

    <div class="builder-group">
      <h4>Como usarlo</h4>
      <div class="builder-note">
        Abri el modo edicion y despues:
        <br>1. hace click en cualquier cuadro para seleccionarlo,
        <br>2. arrastralo para reordenarlo dentro de su zona,
        <br>3. usa el panel para cambiar ancho, alto minimo u ocultarlo,
        <br>4. hace doble click en titulos, menus o botones para editar el texto.
        <br><br>Las metricas y numeros siguen viniendo de la base real: este editor cambia presentacion, no resultados.
      </div>
    </div>

    <div class="builder-group">
      <h4>Tema</h4>
      <div class="builder-grid">
        <div class="builder-field"><label for="editorBg">Fondo</label><input id="editorBg" type="color"></div>
        <div class="builder-field"><label for="editorBg2">Fondo 2</label><input id="editorBg2" type="color"></div>
        <div class="builder-field"><label for="editorPanel">Panel</label><input id="editorPanel" type="color"></div>
        <div class="builder-field"><label for="editorInk">Texto</label><input id="editorInk" type="color"></div>
        <div class="builder-field"><label for="editorMuted">Texto muteado</label><input id="editorMuted" type="color"></div>
        <div class="builder-field"><label for="editorCyan">Acento</label><input id="editorCyan" type="color"></div>
        <div class="builder-field"><label for="editorGold">Dorado</label><input id="editorGold" type="color"></div>
        <div class="builder-field"><label for="editorGreen">Verde</label><input id="editorGreen" type="color"></div>
        <div class="builder-field"><label for="editorRose">Rojo</label><input id="editorRose" type="color"></div>
        <div class="builder-field"><label for="editorViolet">Violeta</label><input id="editorViolet" type="color"></div>
      </div>
      <div class="builder-field"><label for="editorRadius">Redondeo</label><input id="editorRadius" type="range" min="8" max="36" step="1"></div>
      <div class="builder-field"><label for="editorSidebarWidth">Ancho menu izquierdo</label><input id="editorSidebarWidth" type="range" min="220" max="420" step="2"></div>
      <div class="builder-field"><label for="editorGap">Separacion general</label><input id="editorGap" type="range" min="8" max="32" step="1"></div>
    </div>

    <div class="builder-group">
      <h4>Bloque seleccionado</h4>
      <div class="selected-block-name" id="selectedBlockName">Ningun bloque seleccionado</div>
      <div class="builder-field">
        <label for="blockSpan">Ancho del bloque</label>
        <select id="blockSpan">
          <option value="1">Normal</option>
          <option value="2">Doble</option>
          <option value="full">Completo</option>
        </select>
      </div>
      <div class="builder-field"><label for="blockHeight">Altura minima</label><input id="blockHeight" type="range" min="110" max="1100" step="10"></div>
      <div class="builder-field">
        <label for="blockHidden">Visibilidad</label>
        <select id="blockHidden">
          <option value="0">Visible</option>
          <option value="1">Oculto</option>
        </select>
      </div>
      <div class="builder-actions">
        <button id="blockMoveUp" type="button">Subir</button>
        <button id="blockMoveDown" type="button">Bajar</button>
      </div>
    </div>

    <div class="builder-group">
      <h4>Guardar cambios</h4>
      <div class="builder-note">Los cambios quedan guardados en este navegador para tu seguimiento diario.</div>
      <div class="builder-actions">
        <button class="primary" id="builderSave" type="button">Guardar</button>
        <button id="builderReset" type="button">Resetear</button>
        <button id="builderCloseAction" type="button">Cerrar editor</button>
        <button id="sidebarToggleFromEditor" type="button">Ocultar / mostrar menu</button>
      </div>
      <div class="builder-status" id="builderStatus"></div>
    </div>
  </aside>
    """


def render_builder_script() -> str:
    return """
(() => {
  const STORAGE_KEY = "titan-dashboard-builder-v1";
  const THEME_FIELDS = [
    { id: "editorBg", cssVar: "--bg", type: "color" },
    { id: "editorBg2", cssVar: "--bg-2", type: "color" },
    { id: "editorPanel", cssVar: "--panel", type: "color" },
    { id: "editorInk", cssVar: "--ink", type: "color" },
    { id: "editorMuted", cssVar: "--muted", type: "color" },
    { id: "editorCyan", cssVar: "--cyan", type: "color" },
    { id: "editorGold", cssVar: "--gold", type: "color" },
    { id: "editorGreen", cssVar: "--green", type: "color" },
    { id: "editorRose", cssVar: "--rose", type: "color" },
    { id: "editorViolet", cssVar: "--violet", type: "color" },
    { id: "editorRadius", cssVar: "--radius", type: "range", suffix: "px" },
    { id: "editorSidebarWidth", cssVar: "--sidebar-width", type: "range", suffix: "px" },
    { id: "editorGap", cssVar: "--layout-gap", type: "range", suffix: "px", also: [["--grid-gap", "px"]] },
  ];
  const TEXT_SELECTOR = [
    ".brand",
    ".brand span",
    ".sidebar-label",
    ".nav-link span:first-child",
    ".side-button",
    ".drawer summary",
    ".eyebrow",
    "header h1",
    ".toolbar a",
    ".stat-label",
    ".section-label",
    ".section-title",
    ".mini-title",
    ".window-title",
    ".card-details summary",
    ".editor-toggle",
  ].join(",");

  let state = loadState();
  let selectedBlockId = null;
  let dragState = null;
  let dragHandleBlockId = null;

  function qs(selector) {
    return document.querySelector(selector);
  }

  function qsa(selector) {
    return Array.from(document.querySelectorAll(selector));
  }

  function loadState() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      return {
        theme: parsed.theme || {},
        text: parsed.text || {},
        ui: parsed.ui || { sidebarCollapsed: false },
        layout: {
          containers: (parsed.layout && parsed.layout.containers) || {},
          blocks: (parsed.layout && parsed.layout.blocks) || {},
        },
      };
    } catch (error) {
      return { theme: {}, text: {}, ui: { sidebarCollapsed: false }, layout: { containers: {}, blocks: {} } };
    }
  }

  function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function setStatus(message) {
    const status = qs("#builderStatus");
    if (!status) return;
    status.textContent = message || "";
    if (message) {
      window.clearTimeout(setStatus._timer);
      setStatus._timer = window.setTimeout(() => {
        if (status.textContent === message) {
          status.textContent = "";
        }
      }, 1800);
    }
  }

  function currentCssValue(cssVar) {
    return getComputedStyle(document.documentElement).getPropertyValue(cssVar).trim();
  }

  function normalizeColor(value) {
    const color = (value || "").trim();
    if (color.startsWith("#")) return color;
    const probe = document.createElement("span");
    probe.style.color = color;
    document.body.appendChild(probe);
    const rgb = getComputedStyle(probe).color;
    probe.remove();
    const match = rgb.match(/\\d+/g);
    if (!match || match.length < 3) return "#ffffff";
    return "#" + match.slice(0, 3).map((part) => Number(part).toString(16).padStart(2, "0")).join("");
  }

  function syncThemeInputs() {
    THEME_FIELDS.forEach((field) => {
      const input = qs("#" + field.id);
      if (!input) return;
      const stored = state.theme[field.cssVar];
      const value = stored || currentCssValue(field.cssVar);
      if (field.type === "color") {
        input.value = normalizeColor(value);
      } else {
        input.value = parseInt(String(value || "").replace(/[^\\d.-]/g, ""), 10) || 0;
      }
    });
  }

  function applyTheme() {
    THEME_FIELDS.forEach((field) => {
      const raw = state.theme[field.cssVar];
      if (raw) {
        document.documentElement.style.setProperty(field.cssVar, raw);
        (field.also || []).forEach(([cssVar, suffix]) => {
          document.documentElement.style.setProperty(cssVar, suffix ? raw : raw);
        });
      }
    });
    syncThemeInputs();
  }

  function applyUi() {
    document.body.classList.toggle("sidebar-collapsed", !!(state.ui && state.ui.sidebarCollapsed));
    const toggle = qs("#sidebarToggle");
    const floating = qs("#floatingSidebarToggle");
    const label = state.ui && state.ui.sidebarCollapsed ? "Mostrar menu" : "Ocultar menu";
    [toggle, floating].forEach((button) => {
      if (!button) return;
      button.setAttribute("aria-label", label);
      button.textContent = "|||";
    });
  }

  function textRole(el) {
    const classes = Array.from(el.classList || []);
    const known = [
      "brand", "sidebar-label", "eyebrow", "stat-label", "section-label",
      "section-title", "mini-title", "window-title", "side-button",
      "button-link", "ghost-link", "editor-toggle"
    ];
    return classes.find((item) => known.includes(item)) || el.tagName.toLowerCase();
  }

  function assignTextTargets() {
    const counters = {};
    qsa(TEXT_SELECTOR).forEach((el) => {
      if (el.closest("#builderPanel")) return;
      const blockId = el.closest("[data-block-id]")?.dataset.blockId || "root";
      const base = blockId + "::" + textRole(el);
      counters[base] = (counters[base] || 0) + 1;
      const key = base + "::" + counters[base];
      el.dataset.editKey = key;
      el.classList.add("editable-text");
      el.setAttribute("spellcheck", "false");
      if (el.dataset.editorBound === "1") return;
      el.dataset.editorBound = "1";
      el.addEventListener("dblclick", (event) => {
        if (!document.body.classList.contains("edit-mode")) return;
        event.preventDefault();
        event.stopPropagation();
        el.contentEditable = "true";
        el.focus();
        document.execCommand?.("selectAll", false, null);
      });
      el.addEventListener("blur", () => {
        if (el.contentEditable !== "true") return;
        el.contentEditable = "false";
        state.text[key] = el.textContent || "";
        saveState();
      });
      el.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          el.blur();
        }
      });
    });
  }

  function applyTexts() {
    qsa("[data-edit-key]").forEach((el) => {
      const key = el.dataset.editKey;
      if (key in state.text) {
        el.textContent = state.text[key];
      }
    });
  }

  function ensureLayoutDefaults() {
    qsa("[data-container-id]").forEach((container) => {
      const containerId = container.dataset.containerId;
      const children = Array.from(container.children).filter((child) => child.dataset.blockId);
      if (!state.layout.containers[containerId]) {
        state.layout.containers[containerId] = children.map((child) => child.dataset.blockId);
      }
    });
    qsa("[data-block-id]").forEach((block) => {
      const blockId = block.dataset.blockId;
      if (!state.layout.blocks[blockId]) {
        state.layout.blocks[blockId] = {
          span: block.dataset.defaultSpan || "1",
          hidden: false,
          height: "",
        };
      }
    });
  }

  function blockSpanValue(span) {
    if (span === "2") return "span 2";
    if (span === "full") return "1 / -1";
    return "";
  }

  function applyLayout() {
    qsa("[data-container-id]").forEach((container) => {
      const containerId = container.dataset.containerId;
      const order = state.layout.containers[containerId] || [];
      order.forEach((blockId) => {
        const block = document.querySelector('[data-block-id="' + blockId + '"]');
        if (block && block.parentElement === container) {
          container.appendChild(block);
        }
      });
    });

    qsa("[data-block-id]").forEach((block) => {
      const blockId = block.dataset.blockId;
      const config = state.layout.blocks[blockId] || {};
      block.classList.toggle("hidden-block", !!config.hidden);
      block.style.gridColumn = blockSpanValue(config.span || "1");
      block.style.minHeight = config.height ? config.height + "px" : "";
      block.style.height = "";
    });
    refreshSelectedBlockPanel();
  }

  function getBlockName(block) {
    return (
      block.dataset.blockLabel ||
      block.querySelector(".section-title, .model-card-title, .mini-title, .stat-label, .sidebar-label, .section-label")?.textContent?.trim() ||
      block.dataset.blockId
    );
  }

  function selectBlock(blockId) {
    selectedBlockId = blockId;
    qsa("[data-block-id]").forEach((block) => {
      block.classList.toggle("selected-block", block.dataset.blockId === blockId);
    });
    refreshSelectedBlockPanel();
  }

  function refreshSelectedBlockPanel() {
    const nameEl = qs("#selectedBlockName");
    const spanEl = qs("#blockSpan");
    const heightEl = qs("#blockHeight");
    const hiddenEl = qs("#blockHidden");
    if (!selectedBlockId) {
      nameEl.textContent = "Ningun bloque seleccionado";
      spanEl.value = "1";
      heightEl.value = 220;
      hiddenEl.value = "0";
      return;
    }
    const block = document.querySelector('[data-block-id="' + selectedBlockId + '"]');
    const config = state.layout.blocks[selectedBlockId] || {};
    if (!block) return;
    nameEl.textContent = getBlockName(block);
    spanEl.value = config.span || "1";
    heightEl.value = config.height || Math.round(block.getBoundingClientRect().height) || 220;
    hiddenEl.value = config.hidden ? "1" : "0";
  }

  function saveContainerOrder(container) {
    const containerId = container.dataset.containerId;
    state.layout.containers[containerId] = Array.from(container.children)
      .filter((child) => child.dataset.blockId)
      .map((child) => child.dataset.blockId);
    saveState();
  }

  function closestDropReference(container, draggedId, clientX, clientY) {
    const siblings = Array.from(container.children).filter((child) => child.dataset.blockId && child.dataset.blockId !== draggedId);
    let best = null;
    siblings.forEach((child) => {
      const box = child.getBoundingClientRect();
      const cx = box.left + box.width / 2;
      const cy = box.top + box.height / 2;
      const score = Math.hypot(clientX - cx, clientY - cy);
      if (!best || score < best.score) {
        best = { child, box, score };
      }
    });
    if (!best) return null;
    return {
      child: best.child,
      after: clientY > best.box.top + best.box.height / 2,
    };
  }

  function bindBlocks() {
    qsa("[data-block-id]").forEach((block) => {
      block.classList.add("editable-block");
      if (!block.querySelector(":scope > .block-handle")) {
        const handle = document.createElement("button");
        handle.type = "button";
        handle.className = "block-handle";
        handle.textContent = "⋮⋮";
        handle.tabIndex = -1;
        handle.addEventListener("mousedown", () => {
          dragHandleBlockId = block.dataset.blockId;
        });
        block.appendChild(handle);
      }
      if (block.dataset.editorBound === "1") return;
      block.dataset.editorBound = "1";
      block.draggable = true;
      block.addEventListener("click", (event) => {
        if (!document.body.classList.contains("edit-mode")) return;
        if (event.target.closest("[contenteditable='true']")) return;
        if (event.target.closest(".block-handle") || event.target === block) {
          event.preventDefault();
        }
        event.stopPropagation();
        selectBlock(block.dataset.blockId);
      });
      block.addEventListener("dragstart", (event) => {
        if (!document.body.classList.contains("edit-mode")) {
          event.preventDefault();
          return;
        }
        if (dragHandleBlockId !== block.dataset.blockId) {
          event.preventDefault();
          return;
        }
        dragState = {
          blockId: block.dataset.blockId,
          containerId: block.parentElement?.dataset.containerId || "",
        };
        block.classList.add("dragging-block");
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", block.dataset.blockId);
      });
      block.addEventListener("dragend", () => {
        block.classList.remove("dragging-block");
        dragState = null;
        dragHandleBlockId = null;
      });
    });
  }

  function bindContainers() {
    qsa("[data-container-id]").forEach((container) => {
      if (container.dataset.editorDropBound === "1") return;
      container.dataset.editorDropBound = "1";
      container.addEventListener("dragover", (event) => {
        if (!document.body.classList.contains("edit-mode") || !dragState) return;
        if (dragState.containerId !== container.dataset.containerId) return;
        event.preventDefault();
      });
      container.addEventListener("drop", (event) => {
        if (!document.body.classList.contains("edit-mode") || !dragState) return;
        if (dragState.containerId !== container.dataset.containerId) return;
        event.preventDefault();
        const dragged = document.querySelector('[data-block-id="' + dragState.blockId + '"]');
        if (!dragged) return;
        const ref = closestDropReference(container, dragState.blockId, event.clientX, event.clientY);
        if (!ref) {
          container.appendChild(dragged);
        } else if (ref.after) {
          ref.child.after(dragged);
        } else {
          container.insertBefore(dragged, ref.child);
        }
        saveContainerOrder(container);
        applyLayout();
      });
    });
  }

  function bindResizeObserver() {
    return null;
  }

  function moveSelected(delta) {
    if (!selectedBlockId) return;
    const block = document.querySelector('[data-block-id="' + selectedBlockId + '"]');
    const container = block?.parentElement;
    if (!block || !container || !container.dataset.containerId) return;
    const siblings = Array.from(container.children).filter((child) => child.dataset.blockId);
    const index = siblings.indexOf(block);
    const next = index + delta;
    if (next < 0 || next >= siblings.length) return;
    if (delta < 0) {
      container.insertBefore(block, siblings[next]);
    } else {
      siblings[next].after(block);
    }
    saveContainerOrder(container);
    applyLayout();
    setStatus("Orden actualizado");
  }

  function bindControls() {
    qs("#editorToggle")?.addEventListener("click", () => {
      document.body.classList.add("builder-open", "edit-mode");
      setStatus("Modo edicion activo");
    });
    const toggleSidebar = () => {
      state.ui = state.ui || {};
      state.ui.sidebarCollapsed = !state.ui.sidebarCollapsed;
      saveState();
      applyUi();
      setStatus(state.ui.sidebarCollapsed ? "Menu oculto" : "Menu visible");
    };
    const closeEditor = () => {
      document.body.classList.remove("builder-open", "edit-mode");
      qsa("[contenteditable='true']").forEach((el) => {
        el.contentEditable = "false";
      });
      dragHandleBlockId = null;
    };
    qs("#builderClose")?.addEventListener("click", closeEditor);
    qs("#builderCloseAction")?.addEventListener("click", closeEditor);
    qs("#sidebarToggle")?.addEventListener("click", toggleSidebar);
    qs("#floatingSidebarToggle")?.addEventListener("click", toggleSidebar);
    qs("#sidebarToggleFromEditor")?.addEventListener("click", toggleSidebar);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeEditor();
    });
    document.addEventListener("mouseup", () => {
      dragHandleBlockId = null;
    });
    document.addEventListener("click", (event) => {
      if (!document.body.classList.contains("edit-mode")) return;
      const link = event.target.closest("a");
      if (link && !link.closest("#builderPanel")) {
        event.preventDefault();
      }
    }, true);

    THEME_FIELDS.forEach((field) => {
      const input = qs("#" + field.id);
      if (!input) return;
      input.addEventListener("input", () => {
        const value = field.type === "range" ? input.value + (field.suffix || "") : input.value;
        state.theme[field.cssVar] = value;
        if (field.also) {
          field.also.forEach(([cssVar, suffix]) => {
            state.theme[cssVar] = input.value + (suffix || "");
          });
        }
        saveState();
        applyTheme();
        setStatus("Tema actualizado");
      });
    });

    qs("#blockSpan")?.addEventListener("change", (event) => {
      if (!selectedBlockId) return;
      state.layout.blocks[selectedBlockId].span = event.target.value;
      saveState();
      applyLayout();
      setStatus("Bloque actualizado");
    });
    qs("#blockHeight")?.addEventListener("input", (event) => {
      if (!selectedBlockId) return;
      state.layout.blocks[selectedBlockId].height = Number(event.target.value);
      saveState();
      applyLayout();
      setStatus("Altura minima actualizada");
    });
    qs("#blockHidden")?.addEventListener("change", (event) => {
      if (!selectedBlockId) return;
      state.layout.blocks[selectedBlockId].hidden = event.target.value === "1";
      saveState();
      applyLayout();
      setStatus("Visibilidad actualizada");
    });
    qs("#blockMoveUp")?.addEventListener("click", () => moveSelected(-1));
    qs("#blockMoveDown")?.addEventListener("click", () => moveSelected(1));
    qs("#builderSave")?.addEventListener("click", () => {
      saveState();
      setStatus("Cambios guardados");
    });
    qs("#builderReset")?.addEventListener("click", () => {
      localStorage.removeItem(STORAGE_KEY);
      window.location.reload();
    });
  }

  function bindHeatmapPreview() {
    let tooltip = qs("#heatTooltip");
    if (!tooltip) {
      tooltip = document.createElement("div");
      tooltip.id = "heatTooltip";
      tooltip.className = "heat-tooltip";
      document.body.appendChild(tooltip);
    }
    const showTooltip = (event) => {
      const cell = event.currentTarget;
      const text = cell.dataset.preview || "";
      if (!text) return;
      const lines = text.split("\\n");
      const [head, meta, tickers] = lines;
      tooltip.innerHTML = "<strong>" + head + "</strong>"
        + "<div class='muted-line'>" + (meta || "") + "</div>"
        + "<div style='margin-top:6px'>" + (tickers || "") + "</div>";
      tooltip.classList.add("show");
      moveTooltip(event);
    };
    const moveTooltip = (event) => {
      const offsetX = 16;
      const offsetY = 16;
      tooltip.style.left = Math.min(window.innerWidth - tooltip.offsetWidth - 16, event.clientX + offsetX) + "px";
      tooltip.style.top = Math.min(window.innerHeight - tooltip.offsetHeight - 16, event.clientY + offsetY) + "px";
    };
    const hideTooltip = () => {
      tooltip.classList.remove("show");
    };
    qsa(".heat-cell").forEach((cell) => {
      if (cell.dataset.tooltipBound === "1") return;
      cell.dataset.tooltipBound = "1";
      cell.addEventListener("mouseenter", showTooltip);
      cell.addEventListener("mousemove", moveTooltip);
      cell.addEventListener("mouseleave", hideTooltip);
    });
  }

  function applyAll() {
    applyTheme();
    applyUi();
    applyTexts();
    applyLayout();
  }

  assignTextTargets();
  bindBlocks();
  bindContainers();
  ensureLayoutDefaults();
  applyAll();
  bindControls();
  bindHeatmapPreview();
  syncThemeInputs();
})();
    """


def dashboard_visible_league_rows(recent: dict[str, Any]) -> list[dict[str, Any]]:
    return list(recent.get("dashboard_league_equalized") or recent.get("league_equalized") or [])


def filter_dashboard_competition_rows(
    rows: list[dict[str, Any]],
    recent: dict[str, Any],
) -> list[dict[str, Any]]:
    scanner_labels = set(recent.get("dashboard_scanner_labels") or [])
    if not scanner_labels:
        return list(rows)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        role = str(row.get("role") or "")
        version = str(row.get("version") or "")
        if role == "legacy_ml" or version in scanner_labels:
            filtered.append(row)
    return filtered


def render_index(payload: dict[str, Any]) -> str:
    integrity = payload["integrity"]
    active = payload["active"]
    competition = payload["competition"]
    recent = payload["competition_recent"]
    divergence = payload["divergence"]
    active_run = active["active_run"] or {}
    live_results = active_run.get("results_d", []) + active_run.get("results_e", [])
    visible_league = dashboard_visible_league_rows(recent)
    row_map = {str(row["version"]): row for row in visible_league}
    champion_label = f"V{active['active_version']}"
    reference_label = f"V{active['reference_version']}" if active.get("reference_version") else None
    champion_family = row_map.get(champion_label, {})
    reference_family = row_map.get(reference_label, {}) if reference_label else {}
    league_equalized = visible_league[:5]
    league_all = visible_league
    historical_rows = [row for row in league_all if str(row.get("role")) != "legacy_ml"]
    legacy_rows = [row for row in league_all if str(row.get("role")) == "legacy_ml"]
    hidden_redundant_scanners = recent.get("hidden_redundant_scanners") or []
    base_family = row_map.get("V11", {})
    focus_models: list[dict[str, Any]] = []
    for candidate in [champion_family] + historical_rows[:3] + legacy_rows[:3]:
        if candidate and candidate not in focus_models:
            focus_models.append(candidate)
    equalized_days = recent.get("equalized_days", 0)
    leader_equalized = league_equalized[0] if league_equalized else {}
    historical_leader = historical_rows[0] if historical_rows else {}
    champion_rank_equalized = recent.get("rank_equalized", {}).get(champion_label)
    recent_dates = [item["date"] for item in (champion_family.get("recent_15", {}) or {}).get("calendar", [])]
    if not recent_dates and focus_models:
        recent_dates = [item["date"] for item in (focus_models[0].get("recent_15", {}) or {}).get("calendar", [])]
    champion_equalized = champion_family.get("equalized_recent") or {}
    champion_recent_30 = champion_family.get("recent_30") or {}
    reference_equalized = reference_family.get("equalized_recent") or {}
    base_equalized = base_family.get("equalized_recent") or {}
    leader_window = leader_equalized.get("window") or {}
    champion_latest = set(champion_family.get("latest_tickers", []) or [])
    champion_curve = cumulative_series(champion_recent_30.get("spark_avg_return_pct", []))
    leader_curve = cumulative_series(leader_window.get("spark_avg_return_pct", []))
    historical_leader_curve = cumulative_series((historical_leader.get("equalized_recent") or {}).get("spark_avg_return_pct", []))
    champion_curve_svg = sparkline_svg(
        champion_curve,
        "#21c7c4",
        "#21c7c4",
        width=420,
        height=94,
        labels=sparkline_labels_from_calendar(champion_recent_30),
        title=f"{champion_label} | curva 30 ruedas",
        value_format="pct",
    )
    leader_curve_svg = sparkline_svg(
        leader_curve,
        "#f0c96f",
        "#f0c96f",
        width=240,
        height=58,
        labels=sparkline_labels_from_calendar(leader_window),
        title=f"{leader_equalized.get('version') or 'Lider'} | curva visible",
        value_format="pct",
    )
    historical_leader_svg = sparkline_svg(
        historical_leader_curve,
        "#5ed39d",
        "#5ed39d",
        width=220,
        height=54,
        labels=sparkline_labels_from_calendar(historical_leader.get("equalized_recent") or {}),
        title=f"{historical_leader.get('version') or 'Scanner'} | curva visible",
        value_format="pct",
    )

    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Tablero Maquina Pensante</title>
  <style>{render_main_css()}</style>
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar editable-block" data-block-id="sidebar-shell" data-block-label="Menu lateral" data-lock-resize="true">
      <div class="brand">Titan<span>Machine Dashboard</span></div>

      <div class="sidebar-section">
        <div class="sidebar-label">Menu</div>
        <nav class="side-nav" data-container-id="sidebar-menu">
          <a class="nav-link editable-block active" data-block-id="nav-dashboard" data-block-label="Menu Dashboard" href="#overview"><span>Dashboard</span><span>{safe(champion_label)}</span></a>
          <a class="nav-link editable-block" data-block-id="nav-champion" data-block-label="Menu Champion" href="#champion"><span>Champion</span><span>{fmt_int(len(live_results))}</span></a>
          <a class="nav-link editable-block" data-block-id="nav-league" data-block-label="Menu Liga" href="#league"><span>Liga</span><span>{fmt_int(equalized_days)}</span></a>
          <a class="nav-link editable-block" data-block-id="nav-competition" data-block-label="Menu Competidores" href="#competition"><span>Competidores</span><span>{fmt_int(len(focus_models))}</span></a>
          <a class="nav-link editable-block" data-block-id="nav-heatmap" data-block-label="Menu Heatmap" href="#heatmap"><span>Heatmap</span><span>{fmt_int(len(recent_dates))}</span></a>
          <a class="nav-link editable-block" data-block-id="nav-data" data-block-label="Menu Data" href="#data"><span>Data</span><span>{fmt_int(integrity['outcome_models'])}</span></a>
        </nav>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-label">Vistas</div>
        <div class="side-nav" data-container-id="sidebar-views">
          <a class="side-button editable-block" data-block-id="view-executive" data-block-label="Boton Executive" href="{safe(EXECUTIVE_HTML.name)}">Executive</a>
          <a class="side-button editable-block" data-block-id="view-lab" data-block-label="Boton Lab" href="{safe(LAB_HTML.name)}">Lab</a>
        </div>
      </div>

      <details class="drawer editable-block" data-block-id="drawer-data" data-block-label="Panel Data">
        <summary>Data</summary>
        <div class="drawer-body">
          <div class="kpi-line"><span>Mercado</span><strong>{fmt_date(integrity["latest_market_date"])}</strong></div>
          <div class="kpi-line"><span>Predictions</span><strong>{fmt_int(integrity["predictions_count"])}</strong></div>
          <div class="kpi-line"><span>Outcomes</span><strong>{fmt_int(integrity["outcomes_count"])}</strong></div>
          <div class="kpi-line"><span>Regimes</span><strong>{fmt_int(integrity["regimes_count"])}</strong></div>
        </div>
      </details>

      <details class="drawer editable-block" data-block-id="drawer-configuracion" data-block-label="Panel Configuracion">
        <summary>Configuracion</summary>
        <div class="drawer-body">
          <div class="kpi-line"><span>Champion</span><strong>{safe(champion_label)}</strong></div>
          <div class="kpi-line"><span>Referencia</span><strong>{safe(reference_label or '-')}</strong></div>
          <div class="kpi-line"><span>Muestra igualada</span><strong>{fmt_int(equalized_days)} ruedas</strong></div>
          <div class="kpi-line"><span>Snapshot</span><strong>{safe(SNAPSHOT_PATH.name)}</strong></div>
        </div>
      </details>

      <details class="drawer editable-block" data-block-id="drawer-metodologia" data-block-label="Panel Metodologia">
        <summary>Metodologia</summary>
        <div class="drawer-body">
          La liga principal compara la misma cantidad de dias activos por familia para evitar rankings injustos.
          Los paneles de 30 ruedas quedan visibles solo como contexto complementario.
        </div>
      </details>

      <details class="drawer editable-block" data-block-id="drawer-validacion" data-block-label="Panel Validacion">
        <summary>Validacion</summary>
        <div class="drawer-body">
          <div class="kpi-line"><span>{safe(champion_label)} hits</span><strong>{fmt_int(champion_equalized.get('hits'))}/{fmt_int(champion_equalized.get('evaluated'))}</strong></div>
          <div class="kpi-line"><span>{safe(leader_equalized.get('version') or 'Lider')} hits</span><strong>{fmt_int(leader_window.get('hits'))}/{fmt_int(leader_window.get('evaluated'))}</strong></div>
          <div class="kpi-line"><span>Clones ocultos</span><strong>{fmt_int(len(hidden_redundant_scanners))}</strong></div>
          <div class="kpi-line"><span>Lectura</span><strong>Metricas desde outcomes</strong></div>
        </div>
      </details>
    </aside>

    <main class="content" data-container-id="main-root">
      <header class="topbar editable-block" data-block-id="header-overview" data-block-label="Cabecera principal" id="overview">
        <div>
          <div class="eyebrow">Dashboard operativo</div>
          <h1>Champion, liga y competencia diaria</h1>
          <div class="header-meta">
            <span class="pill">Generado {safe(payload["generated_at"])}</span>
            <span class="pill">Build {safe(build_status_label(payload))}</span>
            <span class="pill">Mercado {fmt_date(integrity["latest_market_date"])}</span>
            <span class="pill">Muestra igualada {fmt_int(equalized_days)} ruedas</span>
            <span class="pill">Cobertura 30/30</span>
          </div>
        </div>
        <div class="toolbar" data-container-id="topbar-actions">
          <button class="sidebar-toggle editable-block" data-block-id="toolbar-sidebar-toggle" data-block-label="Boton menu" id="sidebarToggle" type="button">|||</button>
          <a class="button-link editable-block" data-block-id="toolbar-league" data-block-label="Boton Ver liga" href="#league">Ver liga</a>
          <a class="ghost-link editable-block" data-block-id="toolbar-competition" data-block-label="Boton Competidores" href="#competition">Competidores</a>
          <a class="ghost-link editable-block" data-block-id="toolbar-data" data-block-label="Boton Data" href="#data">Data</a>
        </div>
      </header>

      <section class="kpi-grid editable-block" data-block-id="section-kpi-grid" data-block-label="Franja KPI" data-container-id="kpi-grid">
        <div class="stat-card accent-cyan editable-block" data-block-id="kpi-champion" data-block-label="KPI Champion"><div class="stat-label">Champion</div><div class="stat-value">{safe(champion_label)} | {fmt_pct(champion_equalized.get('accuracy_pct'))}</div><div class="stat-subtitle">ret {fmt_pct(champion_equalized.get('avg_return_pct'), 3, signed=True)} | rank #{fmt_int(champion_rank_equalized)}</div></div>
        <div class="stat-card accent-green editable-block" data-block-id="kpi-lider" data-block-label="KPI Lider actual"><div class="stat-label">Lider actual</div><div class="stat-value">{safe(leader_equalized.get('version') or '-')}</div><div class="stat-subtitle">{fmt_pct(leader_window.get('accuracy_pct'))} | {fmt_pct(leader_window.get('avg_return_pct'), 3, signed=True)}</div></div>
        <div class="stat-card accent-gold editable-block" data-block-id="kpi-picks" data-block-label="KPI Picks vivos"><div class="stat-label">Picks vivos</div><div class="stat-value">{fmt_int(len(live_results))} | {safe(active_run.get('regime_label', '-'))}</div><div class="stat-subtitle">breadth {fmt_pct(active_run.get('breadth_pct'), 1)} | target {fmt_date(active_run.get('prediction_for'))}</div></div>
        <div class="stat-card accent-rose editable-block" data-block-id="kpi-db" data-block-label="KPI DB viva"><div class="stat-label">DB viva</div><div class="stat-value">{fmt_int(integrity['outcomes_count'])}</div><div class="stat-subtitle">outcomes | pred {fmt_int(integrity['predictions_count'])}</div></div>
        <div class="stat-card editable-block" data-block-id="kpi-divergencia" data-block-label="KPI familias visibles"><div class="stat-label">Familias scanner</div><div class="stat-value">{fmt_int(len(historical_rows))}</div><div class="stat-subtitle">{fmt_int(len(hidden_redundant_scanners))} clones ocultos por redundancia</div></div>
        <div class="stat-card editable-block" data-block-id="kpi-integridad" data-block-label="KPI Integridad"><div class="stat-label">Integridad</div><div class="stat-value">{integrity['coverage_last_30']['predictions']['covered_days']}/{integrity['coverage_last_30']['predictions']['expected_days']}</div><div class="stat-subtitle">pred | out | regime alineados</div></div>
      </section>

      <section class="prime-grid" data-container-id="champion-league-grid" id="champion">
        <article class="panel hero-chart champion-compact editable-block" data-block-id="panel-champion-hero" data-block-label="Panel Champion">
          <div class="panel-head">
            <div>
              <div class="section-label">Champion activo</div>
              <h2 class="section-title">{safe(champion_label)} | resumen reciente</h2>
            </div>
            <div class="header-meta">
              {role_badge("activo")}
              {freshness_badge(champion_family.get("stale_market_days"))}
            </div>
          </div>
          <div class="chart-wrap">{champion_curve_svg}</div>
          <div class="dense-grid" data-container-id="champion-mini-grid">
            <div class="mini-card editable-block" data-block-id="mini-champion-equalized" data-block-label="Mini muestra igualada">
              <div class="mini-title">Muestra igualada</div>
              <div class="mini-value">{safe(recent_value_text(champion_equalized))}</div>
              <div class="kpi-line"><span>Hits</span><strong>{fmt_int(champion_equalized.get('hits'))}/{fmt_int(champion_equalized.get('evaluated'))}</strong></div>
              <div class="kpi-line"><span>Peor rueda</span><strong>{fmt_pct(champion_equalized.get('worst_day_return_pct'), 2, signed=True)}</strong></div>
            </div>
            <div class="mini-card editable-block" data-block-id="mini-champion-context" data-block-label="Mini contexto 30 ruedas">
              <div class="mini-title">Contexto 30 ruedas</div>
              <div class="mini-value">{safe(recent_value_text(champion_recent_30))}</div>
              <div class="kpi-line"><span>Universo</span><strong>{fmt_int(champion_family.get('unique_tickers'))}</strong></div>
              <div class="kpi-line"><span>Picks</span><strong>{fmt_int(champion_family.get('latest_picks'))}</strong></div>
            </div>
            <div class="mini-card editable-block" data-block-id="mini-champion-sleeve-d" data-block-label="Mini sleeve D">
              <div class="mini-title">Sleeve D_D10</div>
              <div class="mini-value">{fmt_pct(active['active_d'].get('accuracy_pct'))}</div>
              <div class="kpi-line"><span>Ret medio</span><strong>{fmt_pct(active['active_d'].get('avg_return_pct'), 3, signed=True)}</strong></div>
              <div class="kpi-line"><span>Racha</span><strong>{safe(active['active_d'].get('streak', {}).get('streak_type', '-'))} {fmt_int(active['active_d'].get('streak', {}).get('current_streak'))}</strong></div>
            </div>
            <div class="mini-card editable-block" data-block-id="mini-champion-sleeve-e" data-block-label="Mini sleeve E">
              <div class="mini-title">Sleeve E_D15</div>
              <div class="mini-value">{fmt_pct(active['active_e'].get('accuracy_pct'))}</div>
              <div class="kpi-line"><span>Ret medio</span><strong>{fmt_pct(active['active_e'].get('avg_return_pct'), 3, signed=True)}</strong></div>
              <div class="kpi-line"><span>Base V11</span><strong>{safe(recent_value_text(base_equalized))}</strong></div>
            </div>
          </div>
        </article>

        <article class="panel editable-block" data-block-id="section-historical-family" data-block-label="Scanners historicos" id="competition">
          <div class="panel-head">
            <div>
              <div class="section-label">Scanners historicos</div>
              <h2 class="section-title">Familia scanner en foco</h2>
            </div>
            <span class="pill">Muestra comun {fmt_int(equalized_days)} ruedas</span>
          </div>
          <div class="compact-ranking-grid">
            <div class="mini-card editable-block" data-block-id="panel-scanner-ranking" data-block-label="Ranking scanner">
              <div class="mini-title">Ranking scanner</div>
              <table class="data-table compact leaderboard-table">
                <thead><tr><th>#</th><th>Modelo</th><th>WR</th><th>Muestra</th><th>Picks</th></tr></thead>
                <tbody>{render_compact_rank_rows(historical_rows[:4])}</tbody>
              </table>
            </div>
            <div class="mini-card editable-block" data-block-id="panel-scanner-leader" data-block-label="Lider scanner">
              <div class="mini-title">Lider scanner</div>
              <div class="mini-value">{safe(historical_leader.get('version') or '-')} | {fmt_pct((historical_leader.get('window') or {}).get('accuracy_pct'))}</div>
              <div class="scanner-top-note">ret {fmt_pct((historical_leader.get('window') or {}).get('avg_return_pct'), 3, signed=True)} | rank global #{fmt_int(historical_leader.get('rank'))}</div>
              {historical_leader_svg}
              <div class="kpi-line"><span>Champion</span><strong>#{fmt_int(champion_rank_equalized)}</strong></div>
              <div class="kpi-line"><span>Picks actuales</span><strong>{safe(', '.join(champion_family.get('latest_tickers', [])[:4]) or '-')}</strong></div>
            </div>
          </div>
          <div class="group-grid" data-container-id="historical-group">{render_group_model_cards(historical_rows, champion_latest)}</div>
        </article>
      </section>

      <section class="secondary-grid" data-container-id="operations-grid" id="league">
        <article class="panel editable-block" data-block-id="panel-league-ranking" data-block-label="Panel ranking igualado">
          <div class="panel-head">
            <div>
              <div class="section-label">Liga principal</div>
              <h2 class="section-title">Ranking igualado total</h2>
            </div>
            <span class="pill">{fmt_int(equalized_days)} ruedas activas</span>
          </div>
          <table class="data-table compact leaderboard-table">
            <thead><tr><th>#</th><th>Modelo</th><th>WR</th><th>Muestra</th><th>Picks</th></tr></thead>
            <tbody>{render_compact_rank_rows(league_equalized)}</tbody>
          </table>
          <div class="footer-note">Lider {safe(leader_equalized.get('version') or '-')} | WR {fmt_pct(leader_window.get('accuracy_pct'))} | ret {fmt_pct(leader_window.get('avg_return_pct'), 3, signed=True)}</div>
          {leader_curve_svg}
        </article>

        <article class="panel editable-block" data-block-id="panel-live-picks" data-block-label="Panel prediccion viva">
          <div class="panel-head">
            <div>
              <div class="section-label">Prediccion viva</div>
              <h2 class="section-title">{safe(champion_label)} | activos actuales</h2>
            </div>
            <span class="pill">{fmt_date(active_run.get('prediction_for'))}</span>
          </div>
          <table class="data-table compact">
            <thead><tr><th>Ticker</th><th>Setup</th><th>Sector</th><th>Priority</th><th>Ret esp.</th><th>Risk</th></tr></thead>
            <tbody>{
              "".join(
                "<tr>"
                f"<td><strong>{safe(item.get('ticker'))}</strong></td>"
                f"<td>{safe(item.get('signal'))}</td>"
                f"<td>{safe(item.get('sector') or '-')}</td>"
                f"<td>{fmt_ratio(item.get('priority_score') or item.get('score'), 1)}</td>"
                f"<td>{fmt_pct(item.get('priority_expected_return'), 2, signed=True)}</td>"
                f"<td>{fmt_pct(item.get('risk_pct'), 1)}</td>"
                "</tr>"
                for item in live_results
              ) or "<tr><td colspan='6' class='muted'>Sin picks vivos en el snapshot mas reciente.</td></tr>"
            }</tbody>
          </table>
        </article>

        <article class="panel editable-block" data-block-id="panel-control" data-block-label="Panel control operativo">
          <div class="panel-head">
            <div>
              <div class="section-label">Control</div>
              <h2 class="section-title">Estado operativo</h2>
            </div>
          </div>
          <div class="dense-grid" data-container-id="control-mini-grid">
            <div class="mini-card editable-block" data-block-id="mini-control-continuidad" data-block-label="Mini continuidad">
              <div class="mini-title">Continuidad</div>
              <div class="mini-value">{integrity['coverage_last_30']['predictions']['covered_days']}/{integrity['coverage_last_30']['predictions']['expected_days']}</div>
              <div class="kpi-line"><span>Pred</span><strong>{integrity['coverage_last_30']['predictions']['covered_days']}</strong></div>
              <div class="kpi-line"><span>Out</span><strong>{integrity['coverage_last_30']['outcomes']['covered_days']}</strong></div>
            </div>
            <div class="mini-card editable-block" data-block-id="mini-control-snapshot" data-block-label="Mini snapshot">
              <div class="mini-title">Snapshot</div>
              <div class="mini-value">{safe(active_run.get('regime_label', '-'))}</div>
              <div class="kpi-line"><span>prediction_for</span><strong>{fmt_date(active_run.get('prediction_for'))}</strong></div>
              <div class="kpi-line"><span>Memoria</span><strong>{fmt_int(len(active_run.get('memory_context', [])))}</strong></div>
            </div>
            <div class="mini-card editable-block" data-block-id="mini-control-reference" data-block-label="Mini referencia">
              <div class="mini-title">Referencia {safe(reference_label or '-')}</div>
              <div class="mini-value">{safe(recent_value_text(reference_equalized))}</div>
              <div class="kpi-line"><span>Ultimos activos</span><strong>{fmt_int(reference_family.get('latest_picks'))}</strong></div>
              <div class="kpi-line"><span>Fecha</span><strong>{fmt_date(competition_freshness_date(reference_family))}</strong></div>
            </div>
            <div class="mini-card editable-block" data-block-id="mini-control-honestidad" data-block-label="Mini honestidad">
              <div class="mini-title">Honestidad</div>
              <div class="mini-value">{'igual hoy' if divergence.get('latest_common_equal') else 'hoy divergen'}</div>
              <div class="kpi-line"><span>Fecha comun</span><strong>{fmt_date(divergence.get('latest_common_date'))}</strong></div>
              <div class="kpi-line"><span>Cambios</span><strong>{fmt_int(divergence.get('changed_dates'))}</strong></div>
            </div>
          </div>
        </article>
      </section>

      <section class="bottom-grid">
      <section class="section panel editable-block" data-block-id="section-legacy-family" data-block-label="Legacy ML externos">
        <div class="section-head">
          <div>
            <div class="section-label">Legacy ML externos</div>
            <h2 class="section-title">Familia legacy ML</h2>
          </div>
        </div>
        <div class="group-grid" data-container-id="legacy-group">{render_group_model_cards(legacy_rows, champion_latest)}</div>
      </section>

      <section class="section panel editable-block" data-block-id="section-heatmap" data-block-label="Heatmap" id="heatmap">
        <div class="section-head">
          <div>
            <div class="section-label">Heatmap</div>
            <h2 class="section-title">Rendimiento por rueda</h2>
          </div>
        </div>
        {render_recent_heatmap(focus_models, recent_dates)}
      </section>
      </section>

      <section class="section panel editable-block" data-block-id="section-data-table" data-block-label="Liga completa" id="data">
        <div class="section-head">
          <div>
            <div class="section-label">Data</div>
            <h2 class="section-title">Liga completa monitoreada</h2>
          </div>
        </div>
        <table class="data-table">
          <thead><tr><th>Modelo</th><th>Frescura</th><th>Muestra igualada WR/Ret</th><th>Muestra igualada</th><th>30 ruedas WR/Ret</th><th>30 ruedas muestra</th><th>Universo</th><th>Proximos activos</th><th>Curva</th></tr></thead>
          <tbody>{render_full_league_rows(league_all)}</tbody>
        </table>
      </section>
    </main>
    {render_builder_markup()}
  </div>
  <script>{render_chart_interaction_script()}</script>
  <script>{render_builder_script()}</script>
</body>
</html>"""


def render_executive(payload: dict[str, Any]) -> str:
    integrity = payload["integrity"]
    active = payload["active"]
    recent = payload.get("competition_recent") or {}
    competition = filter_dashboard_competition_rows(payload["competition"], recent)
    divergence = payload["divergence"]
    ingestion = payload["ingestion"]
    active_run = active["active_run"] or {}
    executive_rows = competition[:8]
    latest_results = active_run.get("results_d", []) + active_run.get("results_e", [])
    hero_spark = sparkline_svg(
        [to_int(item["count"]) for item in ingestion["predictions"]],
        "#0b7fab",
        "#0b7fab",
        labels=sparkline_labels_from_series(ingestion["predictions"], fallback_prefix="Rueda"),
        title="Predictions | registros por rueda",
        value_format="int",
    )
    outcome_spark = sparkline_svg(
        [to_int(item["count"]) for item in ingestion["outcomes"]],
        "#b7852b",
        "#b7852b",
        labels=sparkline_labels_from_series(ingestion["outcomes"], fallback_prefix="Rueda"),
        title="Outcomes | registros por rueda",
        value_format="int",
    )
    regime_spark = sparkline_svg(
        [to_int(item["count"]) for item in ingestion["regimes"]],
        "#3f7f61",
        "#3f7f61",
        labels=sparkline_labels_from_series(ingestion["regimes"], fallback_prefix="Rueda"),
        title="Regimes | registros por rueda",
        value_format="int",
    )
    active_d = active["active_d"]
    active_e = active["active_e"]
    reference_d = active["reference_d"] or {}
    base_c5 = active["base_c5"]
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Executive Board | Maquina Pensante</title>
  <style>{render_base_css()}</style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="hero-panel">
        <div class="eyebrow">Executive Board</div>
        <h1>La maquina esta viva, midiendo y compitiendo todos los dias</h1>
        <div class="hero-copy">
          Predicciones, outcomes y regimens tuvieron cobertura completa en las ultimas 30 ruedas.
          El tablero distingue continuidad del champion, ortogonalidad legacy y salud de la
          memoria operativa sin ocultar donde todavia hay similitud entre versiones.
        </div>
        <div class="footer-note">Build {safe(build_status_label(payload))}</div>
        <div class="hero-grid">
          {metric_card("Mercado mas reciente", fmt_date(integrity["latest_market_date"]), "Cierre ya validado en la DB", tone="accent")}
          {metric_card("Predictions", fmt_int(integrity["predictions_count"]), "Registros operativos acumulados", hero_spark, tone="mint")}
          {metric_card("Outcomes", fmt_int(integrity["outcomes_count"]), "Predicciones ya contrastadas", outcome_spark, tone="gold")}
          {metric_card("Regimes", fmt_int(integrity["regimes_count"]), "Contexto macro diario persistido", regime_spark, tone="rose")}
        </div>
      </div>
      <div class="hero-panel">
        <div class="eyebrow">Scanner activo</div>
        <h2 class="section-title">Champion V{active['active_version']} | {safe(active_run.get('regime_label', '-'))}</h2>
        <div class="section-copy">
          Fecha analizada {safe(active_run.get('analyzed_date', '-'))} para operar {safe(active_run.get('prediction_for', '-'))}.
          Breadth {fmt_pct(active_run.get('breadth_pct'), 1)}. Snapshot fresco: {safe(active_run.get('freshness', '-'))}.
        </div>
        <div class="inline-grid" style="margin-top:18px">
          <div>
            <div class="kpi-line"><span>Picks actuales</span><strong>{fmt_int(len(latest_results))}</strong></div>
            <div class="kpi-line"><span>WR D_D10</span><strong>{fmt_pct(active_d.get('accuracy_pct'))}</strong></div>
            <div class="kpi-line"><span>Ret D_D10</span><strong>{fmt_pct(active_d.get('avg_return_pct'), 3, signed=True)}</strong></div>
            <div class="kpi-line"><span>Racha actual D</span><strong>{safe(active_d.get('streak', {}).get('streak_type', '-'))} {fmt_int(active_d.get('streak', {}).get('current_streak'))}</strong></div>
          </div>
          <div>
            <div class="kpi-line"><span>WR sleeve E</span><strong>{fmt_pct(active_e.get('accuracy_pct'))}</strong></div>
            <div class="kpi-line"><span>Ret sleeve E</span><strong>{fmt_pct(active_e.get('avg_return_pct'), 3, signed=True)}</strong></div>
            <div class="kpi-line"><span>V12 vs V13 en {safe(divergence.get('latest_common_date') or '-')}</span><strong>{'mismos picks' if divergence['latest_common_equal'] else 'hay diferencia'}</strong></div>
            <div class="kpi-line"><span>Memoria contexto</span><strong>{fmt_int(len(active_run.get('memory_context', [])))}</strong></div>
          </div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="section-head">
        <div>
          <h2 class="section-title">Aprendizaje diario real</h2>
          <div class="section-copy">
            Esta capa responde si la maquina esta registrando, contrastando y contextualizando o si solo esta repitiendo archivos.
          </div>
        </div>
      </div>
      <div class="metric-grid">
        {metric_card("Cobertura predicciones", f"{integrity['coverage_last_30']['predictions']['covered_days']}/{integrity['coverage_last_30']['predictions']['expected_days']}", "Ultimas 30 ruedas con nuevas predicciones", tone="accent")}
        {metric_card("Cobertura outcomes", f"{integrity['coverage_last_30']['outcomes']['covered_days']}/{integrity['coverage_last_30']['outcomes']['expected_days']}", "Ultimas 30 ruedas con outcomes medidos", tone="gold")}
        {metric_card("Cobertura regimens", f"{integrity['coverage_last_30']['regimes']['covered_days']}/{integrity['coverage_last_30']['regimes']['expected_days']}", "Ultimas 30 ruedas con contexto de mercado", tone="mint")}
        {metric_card("Modelos con outcomes", fmt_int(integrity['outcome_models']), "Modelos distintos ya contrastados en DB", tone="rose")}
      </div>
      <div class="two-col">
        <div class="panel" style="margin:0">
          <div class="section-head">
            <div>
              <h3 class="section-title" style="font-size:24px">Champion vs cadena operativa</h3>
              <div class="section-copy">El scanner activo hereda continuidad, pero no hay que confundir continuidad con clonacion total.</div>
            </div>
          </div>
          <div class="kpi-line"><span>V13 D_D10</span><strong>WR {fmt_pct(active_d.get('accuracy_pct'))} | Ret {fmt_pct(active_d.get('avg_return_pct'), 3, signed=True)} | N {fmt_int(active_d.get('total'))}</strong></div>
          <div class="kpi-line"><span>V12 D_D10</span><strong>WR {fmt_pct(reference_d.get('accuracy_pct'))} | Ret {fmt_pct(reference_d.get('avg_return_pct'), 3, signed=True)} | N {fmt_int(reference_d.get('total'))}</strong></div>
          <div class="kpi-line"><span>V11 C5_D4</span><strong>WR {fmt_pct(base_c5.get('accuracy_pct'))} | Ret {fmt_pct(base_c5.get('avg_return_pct'), 3, signed=True)} | N {fmt_int(base_c5.get('total'))}</strong></div>
          <div class="kpi-line"><span>Fechas comunes V12/V13</span><strong>{fmt_int(divergence['common_dates'])}</strong></div>
          <div class="kpi-line"><span>Fechas distintas historicas</span><strong>{fmt_int(divergence['changed_dates'])}</strong></div>
          <div class="kpi-line"><span>Ultimas 31 ruedas</span><strong>{'sin diferencia agregada' if divergence['recent_changed_dates'] == 0 else str(divergence['recent_changed_dates']) + ' con cambios'}</strong></div>
        </div>
        <div class="panel" style="margin:0">
          <div class="section-head"><div><h3 class="section-title" style="font-size:24px">Lectura honesta</h3></div></div>
          <ul class="note-list">
            <li>La maquina si aprende cada dia: predicciones, outcomes y regimens tuvieron continuidad 30/30 en la ultima ventana.</li>
            <li>V12 y V13 comparten la mayor parte del sleeve D: 1162 de 1203 fechas comunes fueron iguales en el agregado.</li>
            <li>Eso no invalida a V13: la diferencia estructural viene del sleeve E y de la continuidad del champion.</li>
            <li>La liga legacy si agrega ortogonalidad real frente al champion y por eso merece tablero propio.</li>
          </ul>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="section-head"><div><h2 class="section-title">Liga de modelos</h2><div class="section-copy">Ranking por accuracy y retorno medio en datos ya evaluados.</div></div></div>
      <table class="data-table">
        <thead><tr><th>Modelo</th><th>Frescura</th><th>Muestra</th><th>WR</th><th>Retorno</th><th>Universo</th><th>Curva</th><th>Ultimos picks</th></tr></thead>
        <tbody>{render_competition_rows(executive_rows)}</tbody>
      </table>
    </section>

    <section class="panel">
      <div class="section-head"><div><h2 class="section-title">Picks vivos del champion</h2><div class="section-copy">Snapshot del scanner activo mas reciente con score, retorno esperado proxy y riesgo.</div></div></div>
      <table class="data-table">
        <thead><tr><th>Ticker</th><th>Setup</th><th>Sector</th><th>Priority</th><th>Ret esp.</th><th>Risk</th><th>RSI</th><th>Nota</th></tr></thead>
        <tbody>{render_latest_pick_rows(latest_results)}</tbody>
      </table>
      <div class="footer-note">Memoria visible en el snapshot: {safe(" | ".join(active_run.get("memory_context", [])) or "-")}</div>
    </section>

    <section class="panel">
      <div class="section-head"><div><h2 class="section-title">Ortogonalidad entre cerebros</h2><div class="section-copy">Jaccard medio de picks por rueda en la ventana reciente.</div></div></div>
      {render_overlap_matrix(payload["overlap"])}
      <div class="footer-note">Clave de lectura: V12 y V13 aparecen practicamente iguales en la base D reciente, mientras que la familia legacy queda muy lejos del champion y por eso aporta informacion nueva.</div>
    </section>
  </main>
  <script>{render_chart_interaction_script()}</script>
</body>
</html>"""


def render_lab(payload: dict[str, Any]) -> str:
    integrity = payload["integrity"]
    recent = payload.get("competition_recent") or {}
    competition = filter_dashboard_competition_rows(payload["competition"], recent)
    active = payload["active"]
    sectors = payload["sectors"]
    divergence = payload["divergence"]
    active_run = active["active_run"] or {}
    highlighted = competition[:6]
    active_d_series = [to_float(item.get("avg_return_pct")) or 0.0 for item in active["active_d_daily"]][-90:]
    active_e_series = [to_float(item.get("avg_return_pct")) or 0.0 for item in active["active_e_daily"]][-90:]
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Research Lab Board | Maquina Pensante</title>
  <style>{render_base_css()}</style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <div class="hero-panel">
        <div class="eyebrow">Research Lab Board</div>
        <h1>Densidad tecnica para medir si la maquina esta pensando o solo replicando</h1>
        <div class="hero-copy">
          Esta vista cruza competencia, sectores, continuidad y overlap. Sirve para auditar si la
          DB esta viva, si el champion evoluciona con memoria y si los challengers legacy son de verdad
          modelos ortogonales o solo ruido con nombres nuevos.
        </div>
        <div class="footer-note">Build {safe(build_status_label(payload))}</div>
        <div class="metric-grid" style="margin-top:24px">
          {metric_card("Latest prediction", fmt_date(integrity['latest_prediction_date']), "Ultima fecha escrita en predictions", tone="accent")}
          {metric_card("Latest outcome", fmt_date(integrity['latest_outcome_date']), "Ultima fecha ya evaluada", tone="gold")}
          {metric_card("DB size", f"{fmt_ratio(integrity.get('db_size_mb'), 2)} MB", "Tamano actual de titan.db", tone="mint")}
          {metric_card("Prediction models", fmt_int(integrity['prediction_models']), "Modelos distintos con registros en DB", tone="rose")}
        </div>
      </div>
      <div class="hero-panel">
        <div class="eyebrow">Matriz de lectura</div>
        <h2 class="section-title">Hechos clave del sistema</h2>
        <div class="kpi-line"><span>Champion actual</span><strong>V{active['active_version']}</strong></div>
        <div class="kpi-line"><span>Referencia inmediata</span><strong>V{active['reference_version']}</strong></div>
        <div class="kpi-line"><span>Fechas iguales V12/V13</span><strong>{fmt_int(divergence['same_dates'])}</strong></div>
        <div class="kpi-line"><span>Fechas distintas V12/V13</span><strong>{fmt_int(divergence['changed_dates'])}</strong></div>
        <div class="kpi-line"><span>Sleeve E evaluado</span><strong>{fmt_int(active['active_e'].get('total'))} casos</strong></div>
        <div class="kpi-line"><span>Mercado del ultimo snapshot</span><strong>{safe(active_run.get('regime_label', '-'))} | breadth {fmt_pct(active_run.get('breadth_pct'), 1)}</strong></div>
        <div class="kpi-line"><span>Target operativo</span><strong>{fmt_date(active_run.get('prediction_for'))}</strong></div>
        <div class="footer-note">Un sistema honesto no oculta cuando dos versiones son muy parecidas. Lo muestra, y deja que la diversidad verdadera aparezca en las familias legacy o en sleeves nuevos.</div>
      </div>
    </section>

    <section class="panel">
      <div class="section-head"><div><h2 class="section-title">Competencia reciente y frescura</h2><div class="section-copy">Modelos con mejores estadisticos evaluados en la liga monitoreada.</div></div></div>
      <div class="model-strip">{render_model_strip(highlighted)}</div>
    </section>

    <section class="panel">
      <div class="section-head"><div><h2 class="section-title">Curvas de retorno medio por rueda</h2><div class="section-copy">Series de retorno promedio diario para los sleeves del champion.</div></div></div>
      <div class="two-col">
        <div class="panel" style="margin:0">
          <div class="section-head"><div><h3 class="section-title" style="font-size:24px">V13 D_D10</h3></div></div>
          {sparkline_svg(
              active_d_series,
              "#0b7fab",
              "#0b7fab",
              width=560,
              height=120,
              labels=sparkline_labels_from_series(active["active_d_daily"], fallback_prefix="Rueda"),
              title="V13 D_D10 | retorno medio por rueda",
              value_format="pct",
          )}
          <div class="kpi-line"><span>WR</span><strong>{fmt_pct(active['active_d'].get('accuracy_pct'))}</strong></div>
          <div class="kpi-line"><span>Ret medio</span><strong>{fmt_pct(active['active_d'].get('avg_return_pct'), 3, signed=True)}</strong></div>
          <div class="kpi-line"><span>Conf media</span><strong>{fmt_pct(active['active_d'].get('avg_confidence'))}</strong></div>
        </div>
        <div class="panel" style="margin:0">
          <div class="section-head"><div><h3 class="section-title" style="font-size:24px">V13 E_D15</h3></div></div>
          {sparkline_svg(
              active_e_series,
              "#b7852b",
              "#b7852b",
              width=560,
              height=120,
              labels=sparkline_labels_from_series(active["active_e_daily"], fallback_prefix="Rueda"),
              title="V13 E_D15 | retorno medio por rueda",
              value_format="pct",
          )}
          <div class="kpi-line"><span>WR</span><strong>{fmt_pct(active['active_e'].get('accuracy_pct'))}</strong></div>
          <div class="kpi-line"><span>Ret medio</span><strong>{fmt_pct(active['active_e'].get('avg_return_pct'), 3, signed=True)}</strong></div>
          <div class="kpi-line"><span>Conf media</span><strong>{fmt_pct(active['active_e'].get('avg_confidence'))}</strong></div>
        </div>
      </div>
    </section>

    <section class="panel">
      <div class="section-head"><div><h2 class="section-title">Overlap matrix</h2><div class="section-copy">Promedio de coincidencia por rueda en la ventana reciente.</div></div></div>
      {render_overlap_matrix(payload["overlap"])}
    </section>

    <section class="panel">
      <div class="section-head"><div><h2 class="section-title">Sectores fuertes</h2><div class="section-copy">Donde el champion y dos challengers destacados estan acertando mas segun la DB evaluada.</div></div></div>
      <div class="three-col">
        <div class="panel" style="margin:0"><div class="section-head"><div><h3 class="section-title" style="font-size:24px">V13 D_D10</h3></div></div>{render_sector_table(sectors["v13_d"], "Sin desagregado sectorial disponible.")}</div>
        <div class="panel" style="margin:0"><div class="section-head"><div><h3 class="section-title" style="font-size:24px">ML_V97</h3></div></div>{render_sector_table(sectors["ml_v97"], "Este modelo no trae sectores mapeados todavia.")}</div>
        <div class="panel" style="margin:0"><div class="section-head"><div><h3 class="section-title" style="font-size:24px">ML_V39</h3></div></div>{render_sector_table(sectors["ml_v39"], "Este modelo no trae sectores mapeados todavia.")}</div>
      </div>
    </section>

    <section class="panel">
      <div class="section-head"><div><h2 class="section-title">Diferencias reales entre V12 y V13</h2><div class="section-copy">Ejemplos historicos donde el agregado de V13 no fue igual al de V12.</div></div></div>
      <table class="data-table compact">
        <thead><tr><th>Fecha</th><th>Solo V13</th><th>Solo V12</th></tr></thead>
        <tbody>{
            "".join(
                "<tr>"
                f"<td>{safe(sample['date'])}</td>"
                f"<td>{safe(', '.join(sample['only_v13']) or '-')}</td>"
                f"<td>{safe(', '.join(sample['only_v12']) or '-')}</td>"
                "</tr>"
                for sample in divergence['sample_changed_dates']
            ) or "<tr><td colspan='3' class='center muted'>No hay cambios registrados.</td></tr>"
        }</tbody>
      </table>
    </section>
  </main>
  <script>{render_chart_interaction_script()}</script>
</body>
</html>"""


def write_outputs(payload: dict[str, Any], variant: str) -> list[Path]:
    ensure_dashboard_dir()
    SNAPSHOT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True, default=json_default) + "\n",
        encoding="utf-8",
    )

    written = [SNAPSHOT_PATH]
    INDEX_HTML.write_text(render_index(payload), encoding="utf-8")
    written.append(INDEX_HTML)

    if variant in {"all", "executive"}:
        EXECUTIVE_HTML.write_text(render_executive(payload), encoding="utf-8")
        written.append(EXECUTIVE_HTML)
    if variant in {"all", "lab"}:
        LAB_HTML.write_text(render_lab(payload), encoding="utf-8")
        written.append(LAB_HTML)
    written.extend(build_c1_pro_outputs())
    manifest = build_artifact_manifest(payload, written)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True, default=json_default) + "\n",
        encoding="utf-8",
    )
    written.append(MANIFEST_PATH)
    return written


def build_pipeline_run_metadata(payload: dict[str, Any], written: list[Path], variant: str) -> dict[str, Any]:
    active = payload.get("active") or {}
    active_run = active.get("active_run") or {}
    return {
        "generator": "analisis.generar_tablero_maquina_pensante",
        "variant": variant,
        "written_files": [path.name for path in written],
        "published_entrypoint": C1_PRO_BUNDLE_HTML.name,
        "local_c1_pro_path": str(C1_PRO_TEMPLATE_HTML.resolve()),
        "local_c1_pro_synced": os.getenv("GITHUB_ACTIONS") != "true",
        "active_version": payload.get("operational_context", {}).get("active_version"),
        "reference_version": payload.get("operational_context", {}).get("reference_version"),
        "active_run_source": active_run.get("source", "snapshot"),
        "active_run_freshness": active_run.get("freshness"),
    }


def generate_dashboard_bundle(variant: str = "all", database_url: str | None = None) -> dict[str, Any]:
    require_cloud_database_runtime(database_url or get_database_url())
    recorder = start_pipeline_run(
        "dashboard_build",
        database_url=database_url or get_database_url(),
    )
    try:
        payload = build_dashboard_payload(
            pipeline_run_id=recorder.run_id,
            database_url=database_url,
        )
        written = write_outputs(payload, variant)
        artifact_manifest = read_json(MANIFEST_PATH)
        recorder.finish(
            status="SUCCESS",
            run_date=payload.get("generated_at"),
            active_scanner_version=str(payload.get("operational_context", {}).get("active_version") or ""),
            db_backend=(payload.get("build") or {}).get("db_backend"),
            latest_prices_date=(payload.get("integrity") or {}).get("latest_market_date"),
            warnings_count=0,
            artifact_manifest=artifact_manifest,
            metadata_json=build_pipeline_run_metadata(payload, written, variant),
        )
        return {
            "payload": payload,
            "written": written,
            "artifact_manifest": artifact_manifest,
            "ledger": {
                "persisted": recorder.persisted,
                "run_id": recorder.run_id,
                "skipped_reason": recorder.skipped_reason,
                "error_message": recorder.error_message,
            },
        }
    except Exception as exc:
        recorder.finish(
            status="FAIL",
            run_date=datetime.now().isoformat(timespec="seconds"),
            error_message=f"{type(exc).__name__}: {exc}",
            metadata_json={"generator": "analisis.generar_tablero_maquina_pensante", "variant": variant},
        )
        raise


def main() -> int:
    args = parse_args()
    result = generate_dashboard_bundle(variant=args.variant)
    print("Tablero maquina pensante generado:")
    for path in result["written"]:
        print(f" - {path}")
    ledger = result["ledger"]
    if ledger["persisted"]:
        print(f" - pipeline_runs ledger: {ledger['run_id']} | SUCCESS")
    elif ledger["skipped_reason"]:
        print(f" - pipeline_runs ledger: skipped ({ledger['skipped_reason']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
