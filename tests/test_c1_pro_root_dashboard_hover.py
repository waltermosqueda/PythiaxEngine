from __future__ import annotations

from herramientas.dashboard_paths import C1_PRO_TEMPLATE_HTML
import herramientas.refrescar_datos_dashboard as refresher


def test_root_preview_template_has_chart_hover_and_preview_containers() -> None:
    html = C1_PRO_TEMPLATE_HTML.read_text(encoding="utf-8")

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


def test_heatmap_variant_a_marks_fresh_zero_signal_days_explicitly() -> None:
    focus = [
        {
            "version": "ML_V94",
            "role": "legacy_ml",
            "latest_snapshot_date": "2026-04-28",
            "recent_30": {
                "calendar": [
                    {"date": "2026-04-27", "avg_return_pct": 1.4, "accuracy_pct": 50.0, "picks": 2, "tickers": ["NVDA", "AAPL"]},
                ]
            },
        }
    ]

    html = refresher._build_variant_a(focus, ["2026-04-27", "2026-04-28"], [])

    assert "0p" in html
    assert "snapshot fresco sin señal" in html
    assert "sin señal" in html


def test_heatmap_variant_a_marks_stale_snapshot_gaps_explicitly() -> None:
    focus = [
        {
            "version": "ML_V94",
            "role": "legacy_ml",
            "latest_snapshot_date": "2026-04-27",
            "recent_30": {
                "calendar": [
                    {"date": "2026-04-27", "avg_return_pct": 1.4, "accuracy_pct": 50.0, "picks": 2, "tickers": ["NVDA", "AAPL"]},
                ]
            },
        }
    ]

    html = refresher._build_variant_a(focus, ["2026-04-27", "2026-04-28"], [])

    assert "sin snapshot fresco para esta rueda" in html
    assert "hm-stale-gap" in html


def test_build_liga_table_uses_provisional_window_data_when_aggregates_are_missing() -> None:
    snap = {
        "competition_recent": {
            "dashboard_league_equalized": [
                {
                    "version": "ML_V94",
                    "role": "legacy_ml",
                    "stale_market_days": 1,
                    "latest_tickers": [],
                    "latest_picks": 0,
                    "window": {
                        "accuracy_pct": None,
                        "avg_return_pct": None,
                        "equalized_days": 39,
                        "active_days": 0,
                        "evaluated": 0,
                        "calendar": [
                            {"date": "2026-04-22", "avg_return_pct": 0.6, "tickers": ["NVDA", "AAPL"]},
                            {"date": "2026-04-23", "avg_return_pct": -0.4, "tickers": ["AAPL"]},
                        ],
                    },
                    "recent_30": {
                        "accuracy_pct": None,
                        "avg_return_pct": None,
                        "active_days": 0,
                        "window_days": 30,
                        "evaluated": 0,
                        "calendar": [
                            {"date": "2026-04-22", "avg_return_pct": 0.6, "tickers": ["NVDA", "AAPL"]},
                            {"date": "2026-04-23", "avg_return_pct": -0.4, "tickers": ["AAPL"]},
                        ],
                    },
                    "recent_60": {
                        "calendar": [
                            {"date": "2026-04-22", "avg_return_pct": 0.6, "tickers": ["NVDA", "AAPL"]},
                        ],
                    },
                    "recent_90": {
                        "calendar": [
                            {"date": "2026-04-22", "avg_return_pct": 0.6, "tickers": ["NVDA", "AAPL"]},
                        ],
                    },
                }
            ]
        }
    }

    html = refresher.build_liga_table(snap)

    assert ">PROV<" in html
    assert "picks prov" in html
    assert "NVDA" in html
    assert "AAPL" in html
    assert "data-spark-vals='[0.6, 0.2]'" in html


def test_render_legacy_grid_uses_calendar_fallback_for_cards() -> None:
    snap = {
        "competition_recent": {
            "dashboard_league_equalized": [
                {
                    "version": "ML_V94",
                    "role": "legacy_ml",
                    "rank": 4,
                    "stale_market_days": 1,
                    "latest_tickers": [],
                    "latest_picks": 0,
                    "unique_tickers": 2,
                    "equalized_recent": {
                        "accuracy_pct": None,
                        "avg_return_pct": None,
                        "active_days": 0,
                        "window_days": 39,
                        "evaluated": 0,
                        "calendar": [
                            {"date": "2026-04-22", "avg_return_pct": 0.6, "tickers": ["NVDA", "AAPL"]},
                        ],
                    },
                    "recent_30": {
                        "accuracy_pct": None,
                        "avg_return_pct": None,
                        "active_days": 0,
                        "window_days": 30,
                        "evaluated": 0,
                        "calendar": [
                            {"date": "2026-04-22", "avg_return_pct": 0.6, "tickers": ["NVDA", "AAPL"]},
                            {"date": "2026-04-23", "avg_return_pct": -0.4, "tickers": ["AAPL"]},
                        ],
                    },
                }
            ]
        }
    }

    html = refresher._render_legacy_grid(snap)

    assert "PROV" in html
    assert "prov 2" in html
    assert "NVDA" in html
    assert "AAPL" in html
    assert "data-values='[0.6, 0.2]'" in html


def test_heatmap_variant_a_uses_tickers_when_picks_field_is_missing() -> None:
    focus = [
        {
            "version": "ML_V94",
            "role": "legacy_ml",
            "latest_snapshot_date": "2026-04-27",
            "recent_30": {
                "calendar": [
                    {"date": "2026-04-27", "avg_return_pct": 1.4, "accuracy_pct": 50.0, "tickers": ["NVDA", "AAPL"]},
                ]
            },
        }
    ]

    html = refresher._build_variant_a(focus, ["2026-04-27"], [])

    assert "2p" in html
    assert "NVDA, AAPL" in html


def test_build_liga_table_hides_models_without_visible_recent_activity() -> None:
    snap = {
        "competition_recent": {
            "dashboard_league_equalized": [
                {
                    "version": "V13",
                    "role": "active",
                    "stale_market_days": 0,
                    "latest_tickers": ["MU"],
                    "latest_picks": 1,
                    "window": {
                        "accuracy_pct": 66.67,
                        "avg_return_pct": 6.0,
                        "equalized_days": 42,
                        "active_days": 31,
                        "evaluated": 60,
                    },
                    "recent_30": {
                        "accuracy_pct": 73.0,
                        "avg_return_pct": 8.29,
                        "window_days": 30,
                        "evaluated": 44,
                        "spark_avg_return_pct": [1.0, 2.0],
                        "calendar": [
                            {"date": "2026-04-28", "avg_return_pct": 1.0, "tickers": ["MU"]},
                            {"date": "2026-04-29", "avg_return_pct": 2.0, "tickers": ["MU"]},
                        ],
                    },
                },
                {
                    "version": "ML_V94",
                    "role": "legacy_ml",
                    "stale_market_days": None,
                    "latest_tickers": [],
                    "latest_picks": 0,
                    "window": {
                        "accuracy_pct": None,
                        "avg_return_pct": None,
                        "equalized_days": 42,
                        "active_days": 0,
                        "evaluated": 0,
                    },
                    "recent_30": {"window_days": 30, "evaluated": 0, "calendar": []},
                    "recent_60": {"calendar": []},
                    "recent_90": {"calendar": []},
                },
            ]
        }
    }

    html = refresher.build_liga_table(snap)

    assert "V13" in html
    assert "ML_V94" not in html


def test_render_overlap_table_hides_models_without_visible_activity() -> None:
    snap = {
        "competition_recent": {
            "dashboard_league_equalized": [
                {
                    "version": "V13",
                    "role": "active",
                    "latest_tickers": ["MU"],
                    "latest_picks": 1,
                    "recent_30": {
                        "window_days": 30,
                        "evaluated": 1,
                        "calendar": [{"date": "2026-04-29", "avg_return_pct": 2.0, "tickers": ["MU"]}],
                    },
                },
                {
                    "version": "ML_V94",
                    "role": "legacy_ml",
                    "latest_tickers": [],
                    "latest_picks": 0,
                    "recent_30": {"window_days": 30, "evaluated": 0, "calendar": []},
                },
            ]
        },
        "overlap": {
            "labels": ["V13", "ML_V94"],
            "matrix": [[1.0, None], [None, None]],
        },
    }

    html = refresher._render_overlap_table_content(snap)

    assert "V13" in html
    assert "ML_V94" not in html
