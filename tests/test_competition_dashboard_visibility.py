from __future__ import annotations

import herramientas.competencia_topn_estandar as standardized
from herramientas.competencia_topn_estandar import _build_dashboard_scanner_visibility


def _state(*entries: tuple[str, list[str]]) -> dict[str, object]:
    day_records = {
        date_text: {"tickers": tickers}
        for date_text, tickers in entries
    }
    return {
        "all_dates": [date_text for date_text, _ in entries],
        "day_records": day_records,
    }


def test_dashboard_visibility_hides_recent_clones_and_keeps_active_plus_base() -> None:
    window_dates = [
        "2026-03-02",
        "2026-03-03",
        "2026-03-04",
        "2026-03-05",
        "2026-03-06",
    ]
    rows = [
        {"version": "V11", "role": "base", "rank": 1},
        {"version": "V9", "role": "observado", "rank": 2},
        {"version": "V12", "role": "referencia", "rank": 3},
        {"version": "V13", "role": "activo", "rank": 4},
    ]
    state_map = {
        "V13": _state(
            ("2026-03-02", ["AAPL", "NVDA"]),
            ("2026-03-03", ["AMD", "MU"]),
            ("2026-03-04", ["LMT"]),
            ("2026-03-05", ["TSM", "ASML"]),
            ("2026-03-06", ["META"]),
        ),
        "V12": _state(
            ("2026-03-02", ["AAPL", "NVDA"]),
            ("2026-03-03", ["AMD", "MU"]),
            ("2026-03-04", ["LMT"]),
            ("2026-03-05", ["TSM", "ASML"]),
            ("2026-03-06", ["META"]),
        ),
        "V11": _state(
            ("2026-03-02", ["XOM"]),
            ("2026-03-03", ["CVX"]),
            ("2026-03-04", ["OXY"]),
            ("2026-03-05", ["BP"]),
            ("2026-03-06", ["SHEL"]),
        ),
        "V9": _state(
            ("2026-03-02", ["XOM"]),
            ("2026-03-03", ["CVX"]),
            ("2026-03-04", ["OXY"]),
            ("2026-03-05", ["BP"]),
            ("2026-03-06", ["SHEL"]),
        ),
    }

    visible, hidden = _build_dashboard_scanner_visibility(rows, state_map, 13, window_dates)

    assert visible == ["V13", "V11"]
    assert {row["version"] for row in hidden} == {"V12", "V9"}
    assert next(row for row in hidden if row["version"] == "V12")["anchor_version"] == "V13"
    assert next(row for row in hidden if row["version"] == "V9")["anchor_version"] == "V11"


def test_dashboard_visibility_keeps_distinct_scanner_family() -> None:
    window_dates = [
        "2026-03-02",
        "2026-03-03",
        "2026-03-04",
        "2026-03-05",
        "2026-03-06",
    ]
    rows = [
        {"version": "V11", "role": "base", "rank": 1},
        {"version": "V14", "role": "observado", "rank": 2},
        {"version": "V13", "role": "activo", "rank": 3},
    ]
    state_map = {
        "V13": _state(
            ("2026-03-02", ["AAPL", "NVDA"]),
            ("2026-03-03", ["AMD", "MU"]),
            ("2026-03-04", ["LMT"]),
            ("2026-03-05", ["TSM", "ASML"]),
            ("2026-03-06", ["META"]),
        ),
        "V11": _state(
            ("2026-03-02", ["XOM"]),
            ("2026-03-03", ["CVX"]),
            ("2026-03-04", ["OXY"]),
            ("2026-03-05", ["BP"]),
            ("2026-03-06", ["SHEL"]),
        ),
        "V14": _state(
            ("2026-03-02", ["GLD"]),
            ("2026-03-03", ["SLV"]),
            ("2026-03-04", ["GDX"]),
            ("2026-03-05", ["NEM"]),
            ("2026-03-06", ["AEM"]),
        ),
    }

    visible, hidden = _build_dashboard_scanner_visibility(rows, state_map, 13, window_dates)

    assert visible == ["V13", "V11", "V14"]
    assert hidden == []


def test_build_entry_state_carries_spark_labels(monkeypatch) -> None:
    entry = {"label": "V11", "role": "base", "prefix": "V11"}
    active_dates = ["2026-04-22", "2026-04-23", "2026-04-24"]
    day_records = {
        "2026-04-22": {
            "picks": 2,
            "avg_return_pct": 1.1,
            "evaluated_assets": [{"hit": 1, "actual_return": 0.02, "confidence": 0.7}],
            "tickers": ["LMT"],
            "latest_target_date": "2026-04-23",
        },
        "2026-04-23": {
            "picks": 1,
            "avg_return_pct": -0.4,
            "evaluated_assets": [{"hit": 0, "actual_return": -0.01, "confidence": 0.6}],
            "tickers": ["IREN"],
            "latest_target_date": "2026-04-24",
        },
        "2026-04-24": {
            "picks": 3,
            "avg_return_pct": 2.3,
            "evaluated_assets": [{"hit": 1, "actual_return": 0.03, "confidence": 0.8}],
            "tickers": ["NVDA"],
            "latest_target_date": "2026-04-27",
        },
    }

    monkeypatch.setattr(standardized, "load_entry_snapshots", lambda con, entry: [])
    monkeypatch.setattr(standardized, "load_entry_snapshot_rows", lambda con, entry: [])
    monkeypatch.setattr(standardized, "_load_operational_row_map", lambda con, entry: {})
    monkeypatch.setattr(
        standardized,
        "_build_ranked_picks_by_date",
        lambda snapshots, row_map: ({}, {date_text: "snapshot" for date_text in active_dates}, "snapshot"),
    )
    monkeypatch.setattr(
        standardized,
        "_build_day_records",
        lambda ranked_picks_by_date, source_by_date, row_map, top_n: (day_records, active_dates, active_dates, {"LMT", "IREN", "NVDA"}),
    )
    monkeypatch.setattr(standardized, "_market_staleness", lambda latest_date, market_dates, latest_target_date=None: 0)
    monkeypatch.setattr(standardized, "build_window_metrics_from_records", lambda records, window_dates: {})

    state = standardized._build_entry_state(None, entry, active_dates, top_n=2)

    assert state["row"]["spark_labels"] == active_dates
    assert state["row"]["spark_cumulative_return_pct"] == [1.1, 0.7, 3.0]
