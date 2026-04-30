from __future__ import annotations

import analisis.generar_tablero_maquina_pensante as dashboard


def test_sparkline_svg_exposes_hover_metadata() -> None:
    html = dashboard.sparkline_svg(
        [1.25, -0.5, 2.0],
        "#21c7c4",
        "#21c7c4",
        labels=["2026-04-22", "2026-04-23", "2026-04-24"],
        title="Serie demo",
        value_format="pct",
        previewable=True,
    )

    assert "data-values=" in html
    assert "data-labels=" in html
    assert "data-title='Serie demo'" in html
    assert "data-format='pct'" in html
    assert "data-previewable='1'" in html


def test_render_full_league_rows_includes_preview_spark_column() -> None:
    row = {
        "version": "V13",
        "role": "activo",
        "stale_market_days": 0,
        "last_date": "2026-04-24",
        "unique_tickers": 10,
        "latest_picks": 2,
        "latest_tickers": ["LMT", "IREN"],
        "equalized_recent": {
            "accuracy_pct": 68.5,
            "avg_return_pct": 7.15,
            "active_days": 28,
            "window_days": 39,
            "evaluated": 54,
            "spark_avg_return_pct": [1.0, -0.5, 2.0],
            "calendar": [
                {"date": "2026-04-22"},
                {"date": "2026-04-23"},
                {"date": "2026-04-24"},
            ],
        },
        "recent_30": {
            "accuracy_pct": 75.6,
            "avg_return_pct": 9.86,
            "active_days": 19,
            "window_days": 30,
            "evaluated": 37,
            "calendar": [
                {"date": "2026-04-22"},
                {"date": "2026-04-23"},
                {"date": "2026-04-24"},
            ],
        },
    }

    html = dashboard.render_full_league_rows([row])

    assert "league-spark-cell" in html
    assert "data-previewable='1'" in html
    assert "V13 | curva reciente" in html


def test_render_competition_rows_preserves_series_labels() -> None:
    row = {
        "version": "V11",
        "role": "scanner",
        "stale_market_days": 0,
        "last_date": "2026-04-24",
        "evaluated": 44,
        "pred_days": 20,
        "accuracy_pct": 61.2,
        "avg_return_pct": 4.25,
        "avg_confidence_pct": 58.0,
        "spark_cumulative_return_pct": [0.5, 1.25, 1.75],
        "spark_labels": ["2026-04-22", "2026-04-23", "2026-04-24"],
        "latest_tickers": ["LMT", "IREN"],
    }

    html = dashboard.render_competition_rows([row])

    assert "data-labels='[" in html
    assert "&quot;2026-04-22&quot;" in html
    assert "&quot;2026-04-24&quot;" in html
    assert "V11 | retorno acumulado" in html


def test_recent_value_text_uses_provisional_summary_when_accuracy_is_missing() -> None:
    window = {
        "window_days": 30,
        "calendar": [
            {"date": "2026-04-22", "picks": 2, "avg_return_pct": 1.5},
            {"date": "2026-04-23", "picks": 1, "avg_return_pct": -0.5},
        ],
    }

    assert dashboard.recent_value_text(window) == "PROV | +0.500%"


def test_render_full_league_rows_shows_provisional_activity_for_legacy_windows() -> None:
    row = {
        "version": "ML_V94",
        "role": "legacy_ml",
        "stale_market_days": 1,
        "last_date": "2026-04-24",
        "unique_tickers": 4,
        "latest_picks": 2,
        "latest_tickers": ["NVDA", "AAPL"],
        "equalized_recent": {
            "accuracy_pct": None,
            "avg_return_pct": None,
            "active_days": 0,
            "window_days": 39,
            "evaluated": 0,
            "calendar": [
                {"date": "2026-04-22", "picks": 2, "avg_return_pct": 1.2},
                {"date": "2026-04-23", "picks": 1, "avg_return_pct": -0.4},
            ],
            "spark_avg_return_pct": [1.2, -0.4],
        },
        "recent_30": {
            "accuracy_pct": None,
            "avg_return_pct": None,
            "active_days": 0,
            "window_days": 30,
            "evaluated": 0,
            "calendar": [
                {"date": "2026-04-22", "picks": 2, "avg_return_pct": 1.2},
                {"date": "2026-04-23", "picks": 1, "avg_return_pct": -0.4},
            ],
        },
    }

    html = dashboard.render_full_league_rows([row])

    assert "PROV" in html
    assert "picks prov" in html


def test_coverage_triplet_text_reports_real_prediction_gap() -> None:
    integrity = {
        "coverage_last_30": {
            "predictions": {"covered_days": 29, "expected_days": 30, "missing": ["2026-03-18"]},
            "outcomes": {"covered_days": 30, "expected_days": 30, "missing": []},
            "regimes": {"covered_days": 30, "expected_days": 30, "missing": []},
        }
    }

    text = dashboard.coverage_triplet_text(integrity)

    assert "pred 29/30" in text
    assert "falta 2026-03-18" in text
    assert "out 30/30" in text
    assert "reg 30/30" in text
