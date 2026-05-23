from __future__ import annotations

from typing import Final

MARK_HM_S: Final = "<!-- DATA:heatmap-start -->"
MARK_HM_E: Final = "<!-- DATA:heatmap-end -->"
MARK_CSS_S: Final = "<!-- DATA:heatmap-css-start -->"
MARK_CSS_E: Final = "<!-- DATA:heatmap-css-end -->"
MARK_LIGA_S: Final = "<!-- DATA:liga-table-start -->"
MARK_LIGA_E: Final = "<!-- DATA:liga-table-end -->"
MARK_HERO_S: Final = "<!-- DATA:hero-row-start -->"
MARK_HERO_E: Final = "<!-- DATA:hero-row-end -->"
MARK_PRED_S: Final = "<!-- DATA:pred-viva-start -->"
MARK_PRED_E: Final = "<!-- DATA:pred-viva-end -->"

REQUIRED_MARKER_PAIRS: Final = (
    ("heatmap-css", MARK_CSS_S, MARK_CSS_E),
    ("heatmap", MARK_HM_S, MARK_HM_E),
    ("hero-row", MARK_HERO_S, MARK_HERO_E),
    ("liga-table", MARK_LIGA_S, MARK_LIGA_E),
)

OPTIONAL_MARKER_PAIRS: Final = (
    ("pred-viva-legacy", MARK_PRED_S, MARK_PRED_E),
)

LIGA_STATIC_META: Final[dict[str, dict[str, str]]] = {
    "V11": {"sharpe": "3.39", "mdd": "-37.9%", "signal": "A + C5 (cap operativa)", "universe": "197 activos", "prev": "MRNA OXY UAL BABA"},
    "V9": {"sharpe": "1.89", "mdd": "-38.2%", "signal": "A + C (path quality)", "universe": "197 activos", "prev": "SPCE VIST BABA COTY"},
    "V8": {"sharpe": "1.75", "mdd": "-39.1%", "signal": "A + C (candidato)", "universe": "197 activos", "prev": "SPCE VIST COTY"},
    "V10": {"sharpe": "2.91", "mdd": "-36.5%", "signal": "A + C4 (rebound capture)", "universe": "197 activos", "prev": "BABA COTY UAL"},
    "V12": {"sharpe": "1.36", "mdd": "-39.9%", "signal": "A + C5 + D (3 sleeves)", "universe": "197 activos", "prev": "MRNA OXY UAL EQNR"},
    "V13": {"sharpe": "1.62", "mdd": "-37.0%", "signal": "A + C5 + D + E_HW (4 sleeves)", "universe": "197 activos", "prev": "MRNA OXY UAL EQNR"},
    "ML_V97": {"sharpe": "2.14", "mdd": "-28.4%", "signal": "ML legacy v97 (ensemble)", "universe": "260 activos", "prev": "ASML GOLD META HMY"},
    "ML_BRAIN_V11_OPT": {"sharpe": "1.92", "mdd": "-31.2%", "signal": "ML BRAIN_V11 optimizado", "universe": "260 activos", "prev": "AMZN VIST BABA"},
    "ML_BRAIN_V11": {"sharpe": "1.38", "mdd": "-42.1%", "signal": "ML BRAIN_V11 base", "universe": "260 activos", "prev": "AMZN NVDA TSLA"},
    "ML_V37": {"sharpe": "1.44", "mdd": "-35.8%", "signal": "ML v37 (7 features)", "universe": "260 activos", "prev": "INTC ORCL BABA"},
    "ML_V39": {"sharpe": "1.22", "mdd": "-44.5%", "signal": "ML v39 base", "universe": "260 activos", "prev": "NVDA TSLA AMZN"},
    "ML_V39FULL": {"sharpe": "-0.39", "mdd": "-58.2%", "signal": "ML v39 full features", "universe": "260 activos", "prev": "TSLA NVDA AMZN"},
}


def liga_static_meta(version: str) -> dict[str, str]:
    return dict(LIGA_STATIC_META.get(version, {}))
