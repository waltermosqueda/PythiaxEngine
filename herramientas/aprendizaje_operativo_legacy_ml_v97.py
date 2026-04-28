#!/usr/bin/env python3

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.aprendizaje_operativo_legacy_ml_base import LegacyMLConfig, main_for_config
from herramientas.competencia_topn_estandar import STANDARD_TOP_N


CONFIG = LegacyMLConfig(
    model_id="legacy_ml_v97",
    label="ML_V97",
    model_prefix="LEGACY_ML_V97",
    source_path="titan_system/models/strategies.py",
    learning_file="herramientas/aprendizaje_operativo_legacy_ml_v97.py",
    adapter_kind="v97",
    signal_code="SURGE",
    native_horizon=3,
    evaluation_mode="window_max_close",
    max_picks=STANDARD_TOP_N,
    min_rows=220,
    notes="Evaluacion por mejor close de la ventana T+1..T+3.",
)


if __name__ == "__main__":
    raise SystemExit(main_for_config(CONFIG))
