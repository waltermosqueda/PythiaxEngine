from __future__ import annotations

from herramientas.dashboard_paths import AURORA_PRO_HTML
import herramientas.refrescar_datos_dashboard as refresher


def test_root_preview_template_has_chart_hover_and_preview_containers() -> None:
    html = AURORA_PRO_HTML.read_text(encoding="utf-8")

    assert 'id="chartHoverTooltip"' in html
    assert 'id="chartPreviewPanel"' in html
    assert "__bindC1DashboardSparkAll" in html
    assert "function buildLigaSpark(vals,labels,color,w,h,title,format,previewable)" in html


def test_build_liga_table_exposes_curve_column_and_hover_labels() -> None:
    snap = {
        "competition_recent": {
            "dashboard_league_equalized": [
                {
                    "version": "V13",
                    "role": "active",
                    "stale_market_days": 0,
                    "latest_tickers": ["LMT", "IREN"],
                    "window": {
                        "accuracy_pct": 68.5,
                        "avg_return_pct": 7.158,
                        "equalized_days": 39,
                        "active_days": 39,
                        "evaluated": 54,
                        "best_day_return_pct": 14.2,
                        "worst_day_return_pct": -7.3,
                    },
                    "equalized_recent": {
                        "accuracy_pct": 68.5,
                        "avg_return_pct": 7.158,
                        "equalized_days": 39,
                        "active_days": 39,
                        "evaluated": 54,
                    },
                    "recent_30": {
                        "accuracy_pct": 75.68,
                        "avg_return_pct": 9.865,
                        "active_days": 30,
                        "window_days": 30,
                        "evaluated": 37,
                        "spark_avg_return_pct": [1.2, -0.4, 2.1],
                        "calendar": [
                            {"date": "2026-04-22", "avg_return_pct": 1.2, "tickers": ["LMT"]},
                            {"date": "2026-04-23", "avg_return_pct": -0.4, "tickers": ["IREN"]},
                            {"date": "2026-04-24", "avg_return_pct": 2.1, "tickers": ["LMT", "IREN"]},
                        ],
                    },
                    "recent_60": {
                        "accuracy_pct": 66.0,
                        "avg_return_pct": 8.2,
                        "evaluated": 60,
                    },
                    "recent_90": {
                        "accuracy_pct": 63.0,
                        "avg_return_pct": 7.4,
                        "evaluated": 88,
                    },
                }
            ]
        }
    }

    html = refresher.build_liga_table(snap)

    assert "<th>Curva</th>" in html
    assert "league-spark-cell" in html
    assert "data-spark-labels=" in html
    assert "data-previewable='1'" in html
    assert "V13 | curva reciente" in html
