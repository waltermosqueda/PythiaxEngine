#!/usr/bin/env python3
"""
Estandarizacion auditada de la liga de modelos.

Regla central:
  - comparar por activo predicho por rueda (prediction_date), no por filas crudas
  - recortar cada modelo a un top N fijo usando el ranking real del snapshot
  - para scanners con multiples horizontes por activo, tomar la fila operativa de
    mayor horizonte (la mas cercana al hold nativo del sleeve)
"""

from __future__ import annotations

import re
from typing import Any

from herramientas.competencia_modelos import monitored_entries
from infra.db.model_run_snapshots import fetch_model_run_snapshots
from infra.db.runtime import RuntimeDB
HORIZON_RE = re.compile(r"_D(\d+)$")

STANDARD_TOP_N = 2
STANDARD_SCOPE = "asset_per_prediction_day"
STANDARD_SELECTION = "db_snapshot_rank_then_max_native_horizon_with_prediction_fallback"
REDUNDANCY_MIN_COMMON_DAYS = 5
REDUNDANCY_SAME_DAY_PCT = 85.0
REDUNDANCY_AGG_JACCARD = 0.9


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _row_to_dict(raw_row: Any) -> dict[str, Any]:
    mapping = getattr(raw_row, "_mapping", None)
    if mapping is not None:
        return dict(mapping)
    return dict(raw_row)


def _empty_window_metrics(window_dates: list[str]) -> dict[str, Any]:
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
        "avg_confidence_pct": None,
        "positive_days": 0,
        "negative_days": 0,
        "best_day_return_pct": None,
        "best_day_date": None,
        "worst_day_return_pct": None,
        "worst_day_date": None,
        "spark_avg_return_pct": [],
        "calendar": [],
    }


def _market_staleness(
    latest_model_date: str | None,
    market_dates: list[str],
    latest_target_date: str | None = None,
) -> int | None:
    # If model has an active prediction covering the current market period it is not stale.
    # This handles D1/D3/D7 models that predict on day N for day N+k: their effective
    # "last active date" is the target date, not the prediction date.
    if market_dates and latest_target_date and latest_target_date >= market_dates[-1]:
        return 0
    if not latest_model_date or latest_model_date not in market_dates:
        return None
    return max(0, len(market_dates) - 1 - market_dates.index(latest_model_date))


def _rank_rows(rows: list[dict[str, Any]], window_key: str) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for row in rows:
        copy_row = dict(row)
        copy_row["window"] = dict(row.get(window_key) or {})
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


def _build_focus_labels(
    rows_equalized: list[dict[str, Any]],
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

    for row in rows_equalized:
        add(str(row["version"]))
        if len(labels) >= 5:
            return labels

    return labels


def _is_scanner_label(label: str) -> bool:
    return label.startswith("V") and label[1:].isdigit()


def _state_similarity(
    left_state: dict[str, Any],
    right_state: dict[str, Any],
    window_dates: list[str],
) -> dict[str, Any]:
    common_dates = sorted(set(left_state["all_dates"]) & set(right_state["all_dates"]) & set(window_dates))
    same_days = 0
    total_intersection = 0
    total_union = 0

    for date_text in common_dates:
        left_tickers = set((left_state["day_records"].get(date_text) or {}).get("tickers") or [])
        right_tickers = set((right_state["day_records"].get(date_text) or {}).get("tickers") or [])
        if left_tickers == right_tickers:
            same_days += 1
        union = left_tickers | right_tickers
        total_intersection += len(left_tickers & right_tickers)
        total_union += len(union)

    same_pct = (same_days * 100.0 / len(common_dates)) if common_dates else None
    agg_jaccard = (total_intersection / total_union) if total_union else None
    return {
        "common_dates": len(common_dates),
        "same_days": same_days,
        "same_pct": round(same_pct, 1) if same_pct is not None else None,
        "agg_jaccard": round(agg_jaccard, 3) if agg_jaccard is not None else None,
    }


def _build_dashboard_scanner_visibility(
    rows_equalized: list[dict[str, Any]],
    state_map: dict[str, dict[str, Any]],
    active_version: int,
    window_dates: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    scanner_rows = [row for row in rows_equalized if _is_scanner_label(str(row.get("version") or ""))]
    row_map = {str(row["version"]): row for row in scanner_rows}
    visible_labels: list[str] = []
    hidden_rows: list[dict[str, Any]] = []

    def add_visible(label: str | None) -> None:
        if label and label in row_map and label not in visible_labels:
            visible_labels.append(label)

    add_visible(f"V{active_version}")
    add_visible("V11")

    for row in scanner_rows:
        label = str(row["version"])
        if label in visible_labels:
            continue

        version_number = int(label[1:]) if _is_scanner_label(label) else None
        if version_number is not None and version_number < 11:
            hidden_rows.append(
                {
                    "version": label,
                    "role": row.get("role"),
                    "hidden_for_dashboard": True,
                    "anchor_version": "V11" if "V11" in row_map else (visible_labels[0] if visible_labels else None),
                    "reason": "pre_v11_reference",
                }
            )
            continue

        hidden_reason: dict[str, Any] | None = None
        for anchor_label in visible_labels:
            similarity = _state_similarity(state_map[label], state_map[anchor_label], window_dates)
            if (
                similarity["common_dates"] >= REDUNDANCY_MIN_COMMON_DAYS
                and similarity["same_pct"] is not None
                and similarity["same_pct"] >= REDUNDANCY_SAME_DAY_PCT
                and similarity["agg_jaccard"] is not None
                and similarity["agg_jaccard"] >= REDUNDANCY_AGG_JACCARD
            ):
                hidden_reason = {
                    "version": label,
                    "role": row.get("role"),
                    "hidden_for_dashboard": True,
                    "anchor_version": anchor_label,
                    "reason": "redundant_recent_behavior",
                    **similarity,
                }
                break

        if hidden_reason is not None:
            hidden_rows.append(hidden_reason)
            continue

        visible_labels.append(label)

    return visible_labels, hidden_rows


def load_entry_snapshots(con: RuntimeDB, entry: dict[str, Any], market_dates: list[str] | None = None) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for row in load_entry_snapshot_rows(con, entry, market_dates=market_dates):
        analyzed_date = str(row.get("analyzed_date") or "")
        payload = row.get("snapshot") or {}
        if analyzed_date and isinstance(payload, dict):
            snapshots[analyzed_date] = payload
    return snapshots


def load_entry_snapshot_rows(con: RuntimeDB, entry: dict[str, Any], market_dates: list[str] | None = None) -> list[dict[str, Any]]:
    cutoff = market_dates[-120] if market_dates and len(market_dates) > 120 else None
    return fetch_model_run_snapshots(con, model_keys=[str(entry["label"])], analyzed_date_from=cutoff)


def extract_ranked_snapshot_picks(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []

    for item in snapshot.get("picks") or []:
        if isinstance(item, dict) and item.get("ticker"):
            raw.append(dict(item))

    for key, value in snapshot.items():
        if not key.startswith("results_") or not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict) and item.get("ticker"):
                enriched = dict(item)
                enriched["_source"] = key
                raw.append(enriched)

    def sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
        rank = item.get("rank")
        rank_key = rank if isinstance(rank, int) else 10**9
        priority_score = item.get("priority_score")
        confidence = item.get("confidence")
        score = item.get("score")
        return (
            rank_key,
            -float(priority_score if priority_score is not None else -1e18),
            -float(confidence if confidence is not None else -1e18),
            -float(score if score is not None else -1e18),
            str(item.get("ticker")),
        )

    deduped: dict[str, dict[str, Any]] = {}
    for item in sorted(raw, key=sort_key):
        ticker = str(item["ticker"])
        if ticker not in deduped:
            deduped[ticker] = item
    return list(deduped.values())


def _build_db_fallback_ranked_picks(
    row_map: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}

    for (prediction_date, ticker), row in row_map.items():
        grouped.setdefault(str(prediction_date), []).append(
            {
                "ticker": str(ticker),
                "confidence": row.get("confidence"),
                "score": row.get("score"),
                "priority_score": row.get("confidence") if row.get("confidence") is not None else row.get("score"),
                "target_date": row.get("target_date"),
                "model_name": row.get("model_name"),
                "horizon": row.get("horizon", 0),
                "_source": "prediction_db_fallback",
            }
        )

    ranked_by_date: dict[str, list[dict[str, Any]]] = {}
    for date_text, raw_items in grouped.items():
        ranked_items = sorted(
            raw_items,
            key=lambda item: (
                -float(item["priority_score"] if item["priority_score"] is not None else -1e18),
                -float(item["confidence"] if item["confidence"] is not None else -1e18),
                -float(item["score"] if item["score"] is not None else -1e18),
                -int(item.get("horizon") or 0),
                str(item.get("ticker")),
            ),
        )
        enriched: list[dict[str, Any]] = []
        for rank, item in enumerate(ranked_items, start=1):
            copy_item = dict(item)
            copy_item["rank"] = rank
            enriched.append(copy_item)
        ranked_by_date[date_text] = enriched

    return ranked_by_date


def _build_ranked_picks_by_date(
    snapshots: dict[str, dict[str, Any]],
    row_map: dict[tuple[str, str], dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str], str]:
    ranked_by_date: dict[str, list[dict[str, Any]]] = {}
    source_by_date: dict[str, str] = {}

    for date_text, snapshot in snapshots.items():
        ranked_snapshot = extract_ranked_snapshot_picks(snapshot)
        if not ranked_snapshot:
            continue
        ranked_by_date[date_text] = ranked_snapshot
        source_by_date[date_text] = "snapshot_db"

    fallback_by_date = _build_db_fallback_ranked_picks(row_map)
    for date_text, ranked_fallback in fallback_by_date.items():
        if date_text in ranked_by_date:
            continue
        ranked_by_date[date_text] = ranked_fallback
        source_by_date[date_text] = "prediction_db_fallback"

    source_modes = set(source_by_date.values())
    if not source_modes:
        selection_source = "none"
    elif source_modes == {"snapshot_db"}:
        selection_source = "snapshot_db"
    elif source_modes == {"prediction_db_fallback"}:
        selection_source = "prediction_db_fallback"
    else:
        selection_source = "mixed"

    return ranked_by_date, source_by_date, selection_source


def _load_operational_row_map(
    con: RuntimeDB,
    entry: dict[str, Any],
    market_dates: list[str] | None = None,
) -> dict[tuple[str, str], dict[str, Any]]:
    prefix = str(entry["prefix"])
    exact = bool(entry.get("exact_model_name", False))
    cutoff = market_dates[-120] if market_dates and len(market_dates) > 120 else None
    params: tuple[Any, ...]
    # MTM (mark-to-market) provisional return for open/pending picks:
    # computed as (latest_close - entry_close) / entry_close
    # only filled when o.actual_return IS NULL (no resolved outcome yet)
    if exact:
        sql = """
            SELECT
                p.model_name,
                p.ticker,
                p.prediction_date,
                p.target_date,
                p.confidence,
                p.score,
                o.actual_return,
                o.hit,
                CASE WHEN o.actual_return IS NULL AND lp.mx >= p.prediction_date
                    THEN (p_latest.close - p_entry.close) / NULLIF(p_entry.close, 0)
                    ELSE NULL END AS mtm_return,
                p_entry.close AS entry_close,
                p_entry.date  AS entry_date,
                p_latest.close AS latest_close,
                lp.mx          AS latest_price_date
            FROM predictions p
            LEFT JOIN outcomes o ON o.prediction_id = p.id
            LEFT JOIN prices p_entry
                ON p_entry.ticker = p.ticker
                AND p_entry.date = (
                    SELECT MAX(pr2.date) FROM prices pr2
                    WHERE pr2.ticker = p.ticker AND pr2.date < p.prediction_date
                )
            LEFT JOIN (SELECT ticker, MAX(date) AS mx FROM prices GROUP BY ticker) lp
                ON lp.ticker = p.ticker
            LEFT JOIN prices p_latest
                ON p_latest.ticker = p.ticker AND p_latest.date = lp.mx
            WHERE p.model_name = ?
        """
        params = (prefix,)
    else:
        sql = """
            SELECT
                p.model_name,
                p.ticker,
                p.prediction_date,
                p.target_date,
                p.confidence,
                p.score,
                o.actual_return,
                o.hit,
                CASE WHEN o.actual_return IS NULL AND lp.mx >= p.prediction_date
                    THEN (p_latest.close - p_entry.close) / NULLIF(p_entry.close, 0)
                    ELSE NULL END AS mtm_return,
                p_entry.close AS entry_close,
                p_entry.date  AS entry_date,
                p_latest.close AS latest_close,
                lp.mx          AS latest_price_date
            FROM predictions p
            LEFT JOIN outcomes o ON o.prediction_id = p.id
            LEFT JOIN prices p_entry
                ON p_entry.ticker = p.ticker
                AND p_entry.date = (
                    SELECT MAX(pr2.date) FROM prices pr2
                    WHERE pr2.ticker = p.ticker AND pr2.date < p.prediction_date
                )
            LEFT JOIN (SELECT ticker, MAX(date) AS mx FROM prices GROUP BY ticker) lp
                ON lp.ticker = p.ticker
            LEFT JOIN prices p_latest
                ON p_latest.ticker = p.ticker AND p_latest.date = lp.mx
            WHERE p.model_name LIKE ?
        """
        params = (f"{prefix}_%",)

    if cutoff is not None:
        sql += " AND p.prediction_date >= ?"
        params = (*params, cutoff)

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for raw_row in con.execute(sql, params).fetchall():
        row = _row_to_dict(raw_row)
        match = HORIZON_RE.search(str(row["model_name"]))
        row["horizon"] = int(match.group(1)) if match else 0
        key = (str(row["prediction_date"]), str(row["ticker"]))
        prev = grouped.get(key)
        if prev is None:
            grouped[key] = row
            continue
        if row["horizon"] > prev["horizon"]:
            grouped[key] = row
            continue
        if row["horizon"] == prev["horizon"] and (_to_float(row["score"]) or -1e18) > (_to_float(prev["score"]) or -1e18):
            grouped[key] = row
    return grouped


def _build_day_records(
    ranked_picks_by_date: dict[str, list[dict[str, Any]]],
    source_by_date: dict[str, str],
    row_map: dict[tuple[str, str], dict[str, Any]],
    top_n: int,
) -> tuple[dict[str, dict[str, Any]], list[str], list[str], list[str]]:
    day_records: dict[str, dict[str, Any]] = {}
    active_evaluated_dates: list[str] = []
    all_dates = sorted(ranked_picks_by_date)
    all_tickers: set[str] = set()
    all_confidences: list[float] = []

    for date_text in all_dates:
        ranked_picks = ranked_picks_by_date[date_text][:top_n]
        tickers = [str(item["ticker"]) for item in ranked_picks]
        for ticker in tickers:
            all_tickers.add(ticker)

        evaluated_assets: list[dict[str, Any]] = []
        mtm_assets: list[dict[str, Any]] = []  # provisional mark-to-market for pending picks
        confidences: list[float] = []
        pending = False
        target_dates: list[str] = []

        for item in ranked_picks:
            key = (date_text, str(item["ticker"]))
            row = row_map.get(key)
            if row is None:
                pending = True
                continue

            confidence = _to_float(row.get("confidence"))
            if confidence is None:
                confidence = _to_float(item.get("confidence"))
            if confidence is not None:
                confidences.append(confidence)
                all_confidences.append(confidence)

            if row.get("target_date"):
                target_dates.append(str(row["target_date"]))

            if row.get("actual_return") is None or row.get("hit") is None:
                pending = True
                # Collect MTM (mark-to-market) provisional return if available
                mtm = _to_float(row.get("mtm_return"))
                if mtm is not None:
                    mtm_assets.append({
                        "ticker": str(item["ticker"]),
                        "mtm_return": mtm,
                        "confidence": confidence,
                        "target_date": str(row.get("target_date") or ""),
                        "entry_close": _to_float(row.get("entry_close")),
                        "entry_date": str(row.get("entry_date") or ""),
                        "latest_close": _to_float(row.get("latest_close")),
                        "latest_price_date": str(row.get("latest_price_date") or ""),
                    })
                continue

            evaluated_assets.append(
                {
                    "ticker": str(item["ticker"]),
                    "actual_return": float(row["actual_return"]),
                    "hit": int(row["hit"]),
                    "confidence": confidence,
                    "target_date": str(row["target_date"]),
                }
            )

        accuracy_pct = None
        avg_return_pct = None
        is_provisional = False
        avg_confidence_pct = (sum(confidences) / len(confidences) * 100.0) if confidences else None
        if ranked_picks and not pending and evaluated_assets:
            accuracy_pct = sum(asset["hit"] for asset in evaluated_assets) * 100.0 / len(evaluated_assets)
            avg_return_pct = sum(asset["actual_return"] for asset in evaluated_assets) * 100.0 / len(evaluated_assets)
            active_evaluated_dates.append(date_text)
        elif ranked_picks and pending and mtm_assets:
            # Show provisional MTM return for days where all/some picks are still open
            avg_return_pct = sum(a["mtm_return"] for a in mtm_assets) * 100.0 / len(mtm_assets)
            is_provisional = True

        day_records[date_text] = {
            "date": date_text,
            "picks": len(ranked_picks),
            "tickers": tickers,
            "pending": bool(ranked_picks) and pending,
            "accuracy_pct": accuracy_pct,
            "avg_return_pct": avg_return_pct,
            "is_provisional": is_provisional,  # True = MTM estimate, no final outcome yet
            "selection_source": source_by_date.get(date_text, "unknown"),
            "avg_confidence_pct": avg_confidence_pct,
            "evaluated_assets": evaluated_assets,
            "mtm_assets": mtm_assets,
            "latest_target_date": max(target_dates) if target_dates else None,
        }

    return day_records, all_dates, active_evaluated_dates, sorted(all_tickers)


def build_window_metrics_from_records(
    day_records: dict[str, dict[str, Any]],
    window_dates: list[str],
) -> dict[str, Any]:
    base = _empty_window_metrics(window_dates)
    if not window_dates:
        return base

    # Build a forwarding map: target_date → record from previous prediction_date.
    # This lets D1 picks (made on day T, targeting day T+1) show under T+1 in the
    # calendar when T+1 has no direct picks of its own. Only forward when the record
    # has avg_return_pct (provisional MTM) and latest_target_date matches the next
    # window_date exactly.
    _forward_map: dict[str, dict[str, Any]] = {}
    window_dates_set = set(window_dates)
    for d, rec in day_records.items():
        tgt = rec.get("latest_target_date")
        if (
            tgt
            and tgt != d  # target is a different (later) date
            and tgt in window_dates_set
            and rec.get("avg_return_pct") is not None  # has provisional data
            and not day_records.get(tgt, {}).get("picks")  # target day has no own picks
        ):
            # Only forward if we don't already have a better candidate
            existing = _forward_map.get(tgt)
            if existing is None or str(d) > str(existing.get("date", "")):
                _forward_map[tgt] = rec

    calendar: list[dict[str, Any]] = []
    spark: list[float] = []
    active_records: list[dict[str, Any]] = []
    evaluated_assets: list[dict[str, Any]] = []

    for date_text in window_dates:
        record = day_records.get(date_text)
        if record is None or not record.get("picks"):
            # No direct record — try forwarded D1 record from previous day
            fwd = _forward_map.get(date_text) if (record is None or not record.get("picks")) else None
            if fwd is not None:
                # Show forwarded record under this target_date
                calendar.append(
                    {
                        "date": date_text,
                        "picks": _to_int(fwd.get("picks")),
                        "accuracy_pct": _to_float(fwd.get("accuracy_pct")),
                        "avg_return_pct": _to_float(fwd.get("avg_return_pct")),
                        "is_provisional": bool(fwd.get("is_provisional", False)),
                        "tickers": list(fwd.get("tickers") or []),
                        "evaluated_assets": list(fwd.get("evaluated_assets") or []),
                        "mtm_assets": list(fwd.get("mtm_assets") or []),
                        "latest_target_date": fwd.get("latest_target_date"),
                        "forwarded_from": str(fwd.get("date", "")),  
                    }
                )
                spark.append(_to_float(fwd.get("avg_return_pct")) or 0.0)
                if fwd.get("accuracy_pct") is not None and fwd.get("avg_return_pct") is not None:
                    active_records.append(fwd)
                    evaluated_assets.extend(fwd.get("evaluated_assets") or [])
            else:
                calendar.append(
                    {
                        "date": date_text,
                        "picks": 0,
                        "accuracy_pct": None,
                        "avg_return_pct": None,
                        "tickers": [],
                    }
                )
                spark.append(0.0)
            continue

        calendar.append(
            {
                "date": date_text,
                "picks": _to_int(record.get("picks")),
                "accuracy_pct": _to_float(record.get("accuracy_pct")),
                "avg_return_pct": _to_float(record.get("avg_return_pct")),
                "is_provisional": bool(record.get("is_provisional", False)),
                "tickers": list(record.get("tickers") or []),
                # context for tooltip: per-ticker entry/exit detail
                "evaluated_assets": list(record.get("evaluated_assets") or []),
                "mtm_assets": list(record.get("mtm_assets") or []),
                "latest_target_date": record.get("latest_target_date"),
            }
        )
        spark.append(_to_float(record.get("avg_return_pct")) or 0.0)

        if record.get("picks") and record.get("accuracy_pct") is not None and record.get("avg_return_pct") is not None:
            active_records.append(record)
            evaluated_assets.extend(record.get("evaluated_assets") or [])

    if not active_records or not evaluated_assets:
        base["spark_avg_return_pct"] = spark
        base["calendar"] = calendar
        return base

    returns = [_to_float(record["avg_return_pct"]) or 0.0 for record in active_records]
    hits = sum(int(asset["hit"]) for asset in evaluated_assets)
    right_returns = [float(asset["actual_return"]) * 100.0 for asset in evaluated_assets if int(asset["hit"]) == 1]
    wrong_returns = [float(asset["actual_return"]) * 100.0 for asset in evaluated_assets if int(asset["hit"]) == 0]
    confidence_values = [
        float(asset["confidence"]) * 100.0
        for asset in evaluated_assets
        if asset.get("confidence") is not None
    ]
    best_idx = max(range(len(active_records)), key=lambda idx: _to_float(active_records[idx]["avg_return_pct"]) or float("-inf"))
    worst_idx = min(range(len(active_records)), key=lambda idx: _to_float(active_records[idx]["avg_return_pct"]) or float("inf"))

    return {
        "window_days": len(window_dates),
        "start_date": window_dates[0],
        "end_date": window_dates[-1],
        "active_days": len(active_records),
        "coverage_pct": round(len(active_records) * 100.0 / max(len(window_dates), 1), 1),
        "evaluated": len(evaluated_assets),
        "hits": hits,
        "misses": max(0, len(evaluated_assets) - hits),
        "accuracy_pct": hits * 100.0 / len(evaluated_assets),
        "avg_return_pct": sum(float(asset["actual_return"]) for asset in evaluated_assets) * 100.0 / len(evaluated_assets),
        "avg_return_right_pct": sum(right_returns) / len(right_returns) if right_returns else None,
        "avg_return_wrong_pct": sum(wrong_returns) / len(wrong_returns) if wrong_returns else None,
        "avg_picks_per_day": round(len(evaluated_assets) / max(len(active_records), 1), 2),
        "avg_confidence_pct": sum(confidence_values) / len(confidence_values) if confidence_values else None,
        "positive_days": sum(1 for value in returns if value > 0),
        "negative_days": sum(1 for value in returns if value < 0),
        "best_day_return_pct": _to_float(active_records[best_idx]["avg_return_pct"]),
        "best_day_date": str(active_records[best_idx]["date"]),
        "worst_day_return_pct": _to_float(active_records[worst_idx]["avg_return_pct"]),
        "worst_day_date": str(active_records[worst_idx]["date"]),
        "spark_avg_return_pct": spark,
        "calendar": calendar,
    }


def _build_entry_state(
    con: RuntimeDB,
    entry: dict[str, Any],
    market_dates: list[str],
    top_n: int,
) -> dict[str, Any]:
    snapshot_rows = load_entry_snapshot_rows(con, entry, market_dates=market_dates)
    snapshots = load_entry_snapshots(con, entry, market_dates=market_dates)
    row_map = _load_operational_row_map(con, entry, market_dates=market_dates)
    ranked_picks_by_date, source_by_date, selection_source = _build_ranked_picks_by_date(
        snapshots,
        row_map,
    )
    day_records, all_dates, active_evaluated_dates, unique_tickers = _build_day_records(
        ranked_picks_by_date,
        source_by_date,
        row_map,
        top_n,
    )

    total_evaluated_assets: list[dict[str, Any]] = []
    for date_text in active_evaluated_dates:
        total_evaluated_assets.extend(day_records[date_text]["evaluated_assets"])

    total_hits = sum(int(asset["hit"]) for asset in total_evaluated_assets)
    total_confidences = [
        float(asset["confidence"]) * 100.0
        for asset in total_evaluated_assets
        if asset.get("confidence") is not None
    ]
    latest_snapshot_row = snapshot_rows[-1] if snapshot_rows else None
    latest_snapshot_date = str(latest_snapshot_row.get("analyzed_date")) if latest_snapshot_row else None
    latest_snapshot_payload = (
        latest_snapshot_row.get("snapshot") if latest_snapshot_row and isinstance(latest_snapshot_row.get("snapshot"), dict) else {}
    )
    latest_snapshot_ranked = extract_ranked_snapshot_picks(latest_snapshot_payload)[:top_n]
    latest_snapshot_tickers = [
        str(item.get("ticker"))
        for item in latest_snapshot_ranked
        if item.get("ticker")
    ]
    latest_snapshot_target_dates = sorted(
        {
            str(item.get("target_date"))
            for item in latest_snapshot_ranked
            if item.get("target_date")
        }
    )
    latest_date = all_dates[-1] if all_dates else None
    latest_record = day_records.get(latest_date or "", {})
    _latest_target_date: str | None = (
        latest_snapshot_target_dates[-1]
        if latest_snapshot_target_dates
        else latest_record.get("latest_target_date")
    )
    spark_series = [
        _to_float(day_records[date_text].get("avg_return_pct")) or 0.0
        for date_text in active_evaluated_dates[-60:]
    ]
    cumulative: list[float] = []
    running = 0.0
    for value in spark_series:
        running += value
        cumulative.append(round(running, 4))
    spark_labels = active_evaluated_dates[-60:]

    state = {
        "entry": entry,
        "snapshots": snapshots,
        "day_records": day_records,
        "all_dates": all_dates,
        "active_evaluated_dates": active_evaluated_dates,
        "row": {
            "version": str(entry["label"]),
            "role": str(entry["role"]),
            "pattern": str(entry["prefix"]),
            "exact_model_name": bool(entry.get("exact_model_name", False)),
            "selection_source": selection_source,
            "snapshot_days": len(snapshot_rows),
            "db_fallback_days": sum(1 for source in source_by_date.values() if source == "prediction_db_fallback"),
            "pred_days": len(all_dates),
            "total_preds": sum(_to_int(day_records[date_text]["picks"]) for date_text in all_dates),
            "evaluated": len(total_evaluated_assets),
            "accuracy_pct": (total_hits * 100.0 / len(total_evaluated_assets)) if total_evaluated_assets else None,
            "avg_return_pct": (
                sum(float(asset["actual_return"]) for asset in total_evaluated_assets) * 100.0 / len(total_evaluated_assets)
            ) if total_evaluated_assets else None,
            "avg_confidence_pct": (sum(total_confidences) / len(total_confidences)) if total_confidences else None,
            "first_date": all_dates[0] if all_dates else None,
            "last_date": latest_snapshot_date or latest_date,
            "last_signal_date": latest_date,
            "latest_snapshot_date": latest_snapshot_date,
            "latest_prediction_for": latest_snapshot_row.get("prediction_for") if latest_snapshot_row else None,
            "latest_target_date": (
                latest_snapshot_target_dates[-1]
                if latest_snapshot_target_dates
                else latest_record.get("latest_target_date")
            ),
            "latest_picks": len(latest_snapshot_tickers) if latest_snapshot_row else _to_int(latest_record.get("picks")),
            "latest_tickers": latest_snapshot_tickers if latest_snapshot_row else list(latest_record.get("tickers") or []),
            "unique_tickers": len(unique_tickers),
            "latest_snapshot_signal_count": int(latest_snapshot_row.get("signal_count") or 0) if latest_snapshot_row else 0,
            "snapshot_stale_market_days": _market_staleness(latest_snapshot_date, market_dates),
            "stale_market_days": _market_staleness(latest_snapshot_date or latest_date, market_dates, _latest_target_date),
            "spark_avg_return_pct": spark_series,
            "spark_cumulative_return_pct": cumulative,
            "spark_labels": spark_labels,
            "recent_10": build_window_metrics_from_records(day_records, market_dates[-10:]),
            "recent_15": build_window_metrics_from_records(day_records, market_dates[-15:]),
            "recent_30": build_window_metrics_from_records(day_records, market_dates[-30:]),
            "recent_60": build_window_metrics_from_records(day_records, market_dates[-60:]),
            "recent_90": build_window_metrics_from_records(day_records, market_dates[-90:]),
        },
    }
    return state


def build_standardized_competition_snapshot(
    con: RuntimeDB,
    market_dates: list[str],
    active_version: int,
    reference_version: int | None,
    top_n: int = STANDARD_TOP_N,
) -> dict[str, Any]:
    states = [_build_entry_state(con, entry, market_dates, top_n=top_n) for entry in monitored_entries()]
    rows = [dict(state["row"]) for state in states]
    rows_sorted = sorted(
        rows,
        key=lambda item: (
            item["accuracy_pct"] if item["accuracy_pct"] is not None else float("-inf"),
            item["avg_return_pct"] if item["avg_return_pct"] is not None else float("-inf"),
            item["version"],
        ),
        reverse=True,
    )

    by_30 = _rank_rows(rows_sorted, "recent_30")
    by_10 = _rank_rows(rows_sorted, "recent_10")

    # ── Período de competencia justo ────────────────────────────────────────────
    # En vez de "mínimo de días activos en ventana 30d" (que colapsa a 6 días por
    # los modelos con señales muy selectivas como V11), usamos un período de
    # calendario fijo: desde que arrancó el primer modelo ML (competition_start)
    # hasta el último día de mercado disponible.
    # Esto da ~36 días de historia para TODOS los modelos — suficiente para
    # significancia estadística (n ≥ 30 picks para la mayoría) y completamente
    # equitativo porque ningún modelo existía antes de esa fecha.
    # Si un modelo no tuvo picks en algún día del período, ese día simplemente
    # no aporta datos, igual que en recent_30.
    competition_start = "2026-03-02"  # fecha de inicio del primer modelo ML
    competition_dates = [d for d in market_dates if d >= competition_start]
    competition_days = len(competition_dates)  # nro de ruedas de mercado desde inicio

    equalized_rows: list[dict[str, Any]] = []
    state_map = {str(state["row"]["version"]): state for state in states}
    for row in rows_sorted:
        version = str(row["version"])
        state = state_map[version]
        equalized_recent = build_window_metrics_from_records(state["day_records"], competition_dates)
        equalized_recent["equalized_days"] = competition_days
        equalized_recent["competition_start"] = competition_start
        row_copy = dict(row)
        row_copy["equalized_recent"] = equalized_recent
        row_copy["window"] = dict(equalized_recent)
        equalized_rows.append(row_copy)

    by_equalized = _rank_rows(equalized_rows, "equalized_recent")
    rank_30 = {str(row["version"]): row["rank"] for row in by_30}
    rank_10 = {str(row["version"]): row["rank"] for row in by_10}
    rank_equalized = {str(row["version"]): row["rank"] for row in by_equalized}
    focus_labels = _build_focus_labels(by_equalized, active_version, reference_version)
    row_map = {str(row["version"]): row for row in equalized_rows}
    dashboard_scanner_labels, hidden_redundant_scanners = _build_dashboard_scanner_visibility(
        by_equalized,
        state_map,
        active_version,
        competition_dates,
    )
    dashboard_scanner_label_set = set(dashboard_scanner_labels)
    dashboard_league_equalized = [
        row
        for row in by_equalized
        if str(row.get("role") or "") == "legacy_ml" or str(row.get("version") or "") in dashboard_scanner_label_set
    ]

    return {
        "policy": {
            "top_n": top_n,
            "scope": STANDARD_SCOPE,
            "selection": STANDARD_SELECTION,
            "notes": (
                "Se comparan activos por prediction_date usando el ranking del snapshot persistido en Postgres; "
                "si falta snapshot diario, se usa fallback desde predictions ordenado por confidence/score. "
                "Si un scanner guarda varios horizontes para el mismo activo, se usa el de mayor horizonte."
            ),
        },
        "rows": rows_sorted,
        "recent": {
            "league_30": by_30,
            "league_10": by_10,
            "equalized_days": competition_days,
            "competition_start": competition_start,
            "league_equalized": by_equalized,
            "dashboard_league_equalized": dashboard_league_equalized,
            "dashboard_scanner_labels": dashboard_scanner_labels,
            "hidden_redundant_scanners": hidden_redundant_scanners,
            "focus_labels": focus_labels,
            "focus_models": [row_map[label] for label in focus_labels if label in row_map],
            "rank_30": rank_30,
            "rank_10": rank_10,
            "rank_equalized": rank_equalized,
        },
    }


def _eligible_common_dates(states: list[dict[str, Any]], start_date: str | None = None) -> list[str]:
    date_sets = []
    for state in states:
        dates = set(state["all_dates"])
        if start_date is not None:
            dates = {date_text for date_text in dates if date_text >= start_date}
        date_sets.append(dates)
    if not date_sets:
        return []

    common_dates = sorted(set.intersection(*date_sets))
    eligible: list[str] = []
    for date_text in common_dates:
        fully_evaluated = True
        for state in states:
            record = state["day_records"].get(date_text) or {}
            if record.get("pending"):
                fully_evaluated = False
                break
        if fully_evaluated:
            eligible.append(date_text)
    return eligible


def summarize_topn_study(
    con: RuntimeDB,
    labels: list[str],
    market_dates: list[str],
    top_ns: tuple[int, ...] = (1, 2, 3, 4),
    start_date: str | None = None,
) -> dict[str, Any]:
    entries = [entry for entry in monitored_entries() if str(entry["label"]) in labels]
    summary: dict[str, Any] = {
        "labels": labels,
        "start_date": start_date,
        "results": [],
    }

    for top_n in top_ns:
        states = [_build_entry_state(con, entry, market_dates, top_n=top_n) for entry in entries]
        eligible_dates = _eligible_common_dates(states, start_date=start_date)
        if not eligible_dates:
            summary["results"].append(
                {
                    "top_n": top_n,
                    "eligible_days": 0,
                    "start_date": None,
                    "end_date": None,
                    "mean_model_accuracy_pct": None,
                    "mean_model_return_pct": None,
                    "mean_model_day_return_pct": None,
                    "mean_picks_active_day": None,
                    "leaderboard": [],
                }
            )
            continue

        leaderboard: list[dict[str, Any]] = []
        accuracy_values: list[float] = []
        return_values: list[float] = []
        day_return_values: list[float] = []
        picks_values: list[float] = []

        for state in states:
            asset_rows: list[dict[str, Any]] = []
            day_returns: list[float] = []
            active_days = 0
            for date_text in eligible_dates:
                record = state["day_records"].get(date_text) or {}
                if record.get("picks") and record.get("accuracy_pct") is not None:
                    active_days += 1
                    day_returns.append(float(record["avg_return_pct"]))
                    asset_rows.extend(record.get("evaluated_assets") or [])

            accuracy_pct = None
            avg_return_pct = None
            avg_day_return_pct = None
            if asset_rows:
                accuracy_pct = sum(int(item["hit"]) for item in asset_rows) * 100.0 / len(asset_rows)
                avg_return_pct = sum(float(item["actual_return"]) for item in asset_rows) * 100.0 / len(asset_rows)
                avg_day_return_pct = sum(day_returns) / len(day_returns) if day_returns else None
                accuracy_values.append(accuracy_pct)
                return_values.append(avg_return_pct)
            if avg_day_return_pct is not None:
                day_return_values.append(avg_day_return_pct)
            picks_values.append(len(asset_rows) / max(active_days, 1) if active_days else 0.0)

            leaderboard.append(
                {
                    "version": str(state["row"]["version"]),
                    "role": str(state["row"]["role"]),
                    "active_days": active_days,
                    "asset_picks": len(asset_rows),
                    "accuracy_pct": accuracy_pct,
                    "avg_return_pct": avg_return_pct,
                    "avg_day_return_pct": avg_day_return_pct,
                    "avg_picks_active_day": len(asset_rows) / max(active_days, 1) if active_days else 0.0,
                }
            )

        leaderboard = sorted(
            leaderboard,
            key=lambda item: (
                item["accuracy_pct"] if item["accuracy_pct"] is not None else float("-inf"),
                item["avg_return_pct"] if item["avg_return_pct"] is not None else float("-inf"),
                item["version"],
            ),
            reverse=True,
        )

        summary["results"].append(
            {
                "top_n": top_n,
                "eligible_days": len(eligible_dates),
                "start_date": eligible_dates[0],
                "end_date": eligible_dates[-1],
                "mean_model_accuracy_pct": sum(accuracy_values) / len(accuracy_values) if accuracy_values else None,
                "mean_model_return_pct": sum(return_values) / len(return_values) if return_values else None,
                "mean_model_day_return_pct": sum(day_return_values) / len(day_return_values) if day_return_values else None,
                "mean_picks_active_day": sum(picks_values) / len(picks_values) if picks_values else None,
                "leaderboard": leaderboard,
            }
        )

    return summary


def load_market_dates(con: RuntimeDB) -> list[str]:
    rows = con.execute(
        """
        SELECT DISTINCT date
        FROM prices
        WHERE ticker = 'SPY'
        ORDER BY date
        """
    ).fetchall()
    return [str(row[0]) for row in rows]
