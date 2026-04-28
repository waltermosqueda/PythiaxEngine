#!/usr/bin/env python3

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.aprendizaje_operativo_legacy_ml_base import LegacyMLConfig, main_for_config
from herramientas.competencia_topn_estandar import STANDARD_TOP_N


CONFIG = LegacyMLConfig(
    model_id="legacy_ml_v39",
    label="ML_V39",
    model_prefix="LEGACY_ML_V39",
    source_path="titan_system/models/strategies.py",
    learning_file="herramientas/aprendizaje_operativo_legacy_ml_v39.py",
    adapter_kind="v39",
    signal_code="TOP",
    native_horizon=1,
    evaluation_mode="close_on_target",
    max_picks=STANDARD_TOP_N,
    min_rows=120,
    notes="Cross-sectional top decile D1.",
)


if __name__ == "__main__":
    raise SystemExit(main_for_config(CONFIG))
