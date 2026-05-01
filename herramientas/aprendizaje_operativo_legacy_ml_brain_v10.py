#!/usr/bin/env python3
"""
ML_BRAIN_V10 — Adapter para ml_trading_v23.py (Ultra-Fast Edition)

Misma interfaz que ML_BRAIN_V9 (brain_v9 adapter kind) pero apunta al v23:
  · HistGradientBoosting en lugar de GradientBoosting  → 30-50x más rápido
  · RF/ET con 80 árboles (vs 400)                      → 5x más rápido
  · Triple Barrier vectorizado con numpy broadcasting   → 100x más rápido
  · Features calculadas en paralelo por ticker (joblib) → 8x más rápido
  · 3 folds WF en lugar de 4                           → 25% menos entrenamiento
  · Sin MLP (lento, IC similar a LR)

Rendimiento esperado: ~4-6 min totales (vs ~45 min del v22/brain_v9)
Picks: lógica idéntica (mismas 62 features, mismas labels Triple Barrier,
       mismo umbral 0.018, mismo horizonte 5d, mismo universo ACTIVOS)
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.aprendizaje_operativo_legacy_ml_base import LegacyMLConfig, main_for_config
from herramientas.competencia_topn_estandar import STANDARD_TOP_N


CONFIG = LegacyMLConfig(
    model_id="legacy_ml_brain_v10",
    label="ML_BRAIN_V10",
    model_prefix="LEGACY_ML_BRAIN_V10",
    source_path="ml_investigacion/ml_trading_v23.py",
    learning_file="herramientas/aprendizaje_operativo_legacy_ml_brain_v10.py",
    adapter_kind="brain_v9",   # Reutiliza _run_v22() — compatible con TradingEngine v23
    signal_code="BUY",
    native_horizon=5,
    evaluation_mode="close_on_target",
    max_picks=STANDARD_TOP_N,
    min_rows=260,
    notes=(
        "ML Trading Brain v10.0 Ultra-Fast. "
        "62 features idénticas al v22, Triple Barrier vectorizado numpy, "
        "HistGradientBoosting (30-50x vs GBC), RF/ET 80 árboles, "
        "features paralelas joblib, 3-fold WF. "
        "Misma interfaz TradingEngine que v22/brain_v9."
    ),
)


if __name__ == "__main__":
    raise SystemExit(main_for_config(CONFIG))
