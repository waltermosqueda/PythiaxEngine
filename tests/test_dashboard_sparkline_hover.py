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
