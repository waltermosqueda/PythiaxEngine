#!/usr/bin/env python3

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.aprendizaje_operativo_legacy_ml_base import LegacyMLConfig, main_for_config
from herramientas.competencia_topn_estandar import STANDARD_TOP_N


CONFIG = LegacyMLConfig(
    model_id="legacy_ml_brain_v9",
    label="ML_BRAIN_V9",
    model_prefix="LEGACY_ML_BRAIN_V9",
    source_path="ml_investigacion/ml_trading_v22.py",
    learning_file="herramientas/aprendizaje_operativo_legacy_ml_brain_v9.py",
    adapter_kind="brain_v9",
    signal_code="BUY",
    native_horizon=5,
    evaluation_mode="close_on_target",
    max_picks=STANDARD_TOP_N,
    min_rows=260,
    notes="ML Trading Brain v9.0 original (v20/v22). 62 features, Triple Barrier, Purged WF, IC weights. Direct module import with titan DB data.",
)


if __name__ == "__main__":
    raise SystemExit(main_for_config(CONFIG))
