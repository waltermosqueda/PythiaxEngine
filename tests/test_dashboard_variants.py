from __future__ import annotations

import analisis.generar_tablero_maquina_pensante as dashboard


def test_render_lab_includes_active_prediction_target() -> None:
    payload = {
        "integrity": {
            "latest_prediction_date": "2026-04-23",
            "latest_outcome_date": "2026-04-23",
            "db_size_mb": None,
            "prediction_models": 37,
        },
        "competition": [
            {
                "version": "V13",
                "role": "activo",
                "stale_market_days": 0,
                "accuracy_pct": 55.53,
                "avg_return_pct": 1.7075,
                "latest_tickers": ["INTC", "MU"],
            }
        ],
        "active": {
            "active_version": 13,
            "reference_version": 12,
            "active_run": {
                "regime_label": "PELIGRO",
                "breadth_pct": 52.3,
                "prediction_for": "2026-04-24",
            },
            "active_e": {
                "total": 25,
                "accuracy_pct": 64.0,
                "avg_return_pct": 4.5863,
                "avg_confidence": 23.85,
            },
            "active_d": {
                "accuracy_pct": 55.53,
                "avg_return_pct": 1.7075,
                "avg_confidence": 69.67,
            },
            "active_d_daily": [{"avg_return_pct": 1.0}, {"avg_return_pct": -0.5}],
            "active_e_daily": [{"avg_return_pct": 0.2}, {"avg_return_pct": 0.1}],
        },
        "sectors": {"v13_d": [], "ml_v97": [], "ml_v39": []},
        "divergence": {"same_dates": 10, "changed_dates": 2, "sample_changed_dates": []},
        "overlap": {
            "labels": ["V13", "V12"],
            "matrix": [[1.0, 0.95], [0.95, 1.0]],
            "common_days": [[30, 30], [30, 30]],
        },
        "build": {"build_source": "local", "db_backend": "postgresql", "pipeline_run_id": "run-1"},
    }

    html = dashboard.render_lab(payload)

    assert "Target operativo" in html
    assert "2026-04-24" in html
