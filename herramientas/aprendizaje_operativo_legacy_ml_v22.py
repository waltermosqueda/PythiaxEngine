#!/usr/bin/env python3

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.aprendizaje_operativo_legacy_ml_base import LegacyMLConfig, main_for_config


CONFIG = LegacyMLConfig(
    model_id="legacy_ml_v22",
    label="ML_V22",
    model_prefix="LEGACY_ML_V22",
    source_path=r"c:\Users\wmx_7\OneDrive\Escritorio\Inversiones\Machine Winners\ml_trading_v22.py",
    learning_file="herramientas/aprendizaje_operativo_legacy_ml_v22.py",
    adapter_kind="v22",
    signal_code="BUY",
    native_horizon=5,
    evaluation_mode="close_on_target",
    max_picks=10,
    min_rows=260,
    notes="Proxy operativa D5 para el stacked ensemble de triple barrier.",
)


if __name__ == "__main__":
    raise SystemExit(main_for_config(CONFIG))
