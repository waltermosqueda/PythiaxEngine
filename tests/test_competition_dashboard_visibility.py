from __future__ import annotations

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
