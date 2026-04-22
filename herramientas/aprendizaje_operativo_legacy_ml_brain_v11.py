#!/usr/bin/env python3

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.aprendizaje_operativo_legacy_ml_base import LegacyMLConfig, main_for_config
from herramientas.competencia_topn_estandar import STANDARD_TOP_N


CONFIG = LegacyMLConfig(
    model_id="legacy_ml_brain_v11",
    label="ML_BRAIN_V11",
    model_prefix="LEGACY_ML_BRAIN_V11",
    source_path=r"c:\Users\wmx_7\OneDrive\Escritorio\Inversiones\Machine Winners\ml_trading_brain_v11.py",
    learning_file="herramientas/aprendizaje_operativo_legacy_ml_brain_v11.py",
    adapter_kind="brain_v11",
    signal_code="BUY",
    native_horizon=5,
    evaluation_mode="close_on_target",
    max_picks=STANDARD_TOP_N,
    min_rows=220,
    notes="Filtro BUY por consenso >= 60%.",
)


if __name__ == "__main__":
    raise SystemExit(main_for_config(CONFIG))
