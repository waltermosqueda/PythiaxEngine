from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any, Iterable

from infra.db.runtime import RuntimeDB


def _coerce_date_text(value: date | datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text[:10] if text else None


def serialize_snapshot_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, default=str)


def deserialize_snapshot_payload(payload_text: str | None) -> dict[str, Any]:
    if not payload_text:
        return {}
    try:
        loaded = json.loads(payload_text)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def fetch_model_run_snapshots(
    con: RuntimeDB,
    *,
    model_keys: Iterable[str] | None = None,
    analyzed_date_from: str | None = None,
    analyzed_date_to: str | None = None,
    include_snapshot_json: bool = True,
) -> list[dict[str, Any]]:
    _extra_col = "\n            snapshot_json," if include_snapshot_json else ""
    query = f"""
        SELECT
            model_key,
            model_name,
            model_version,
            role,
            analyzed_date,
            prediction_for,
            freshness,
            regime_label,
            breadth_pct,
            signal_count,{_extra_col}
            created_at
        FROM model_run_snapshots
        WHERE 1 = 1
    """
    params: list[Any] = []
    keys = [str(item) for item in (model_keys or []) if str(item).strip()]
    if keys:
        placeholders = ", ".join("?" for _ in keys)
        query += f" AND model_key IN ({placeholders})"
        params.extend(keys)
    if analyzed_date_from:
        query += " AND analyzed_date >= ?"
        params.append(analyzed_date_from)
    if analyzed_date_to:
        query += " AND analyzed_date <= ?"
        params.append(analyzed_date_to)
    query += " ORDER BY analyzed_date, model_key"

    rows: list[dict[str, Any]] = []
    for raw_row in con.execute(query, tuple(params)).fetchall():
        row = dict(raw_row._mapping)
        row["analyzed_date"] = _coerce_date_text(row.get("analyzed_date"))
        row["prediction_for"] = _coerce_date_text(row.get("prediction_for"))
        if include_snapshot_json:
            row["snapshot"] = deserialize_snapshot_payload(row.get("snapshot_json"))
        rows.append(row)
    return rows


def fetch_latest_model_run_snapshot(con: RuntimeDB, model_key: str) -> dict[str, Any] | None:
    rows = fetch_model_run_snapshots(con, model_keys=[model_key])
    return rows[-1] if rows else None


def fetch_model_run_snapshot(con: RuntimeDB, model_key: str, analyzed_date: str) -> dict[str, Any] | None:
    rows = fetch_model_run_snapshots(
        con,
        model_keys=[model_key],
        analyzed_date_from=analyzed_date,
        analyzed_date_to=analyzed_date,
    )
    return rows[0] if rows else None
