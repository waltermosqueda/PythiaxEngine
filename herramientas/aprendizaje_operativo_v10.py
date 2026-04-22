#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.aprendizaje_operativo_observado_base import ObservedScannerConfig, main_for_config


CONFIG = ObservedScannerConfig(
    version=10,
    scanner_module="SCANNER.invertir_v10",
    scanner_file="SCANNER/invertir_v10.py",
    learning_file="herramientas/aprendizaje_operativo_v10.py",
    crash_signal_attr="signal_c4_crash_rebound",
    crash_signal_code="C4",
    crash_display_label="C4",
    crash_horizons=(1, 4, 7),
)


if __name__ == "__main__":
    raise SystemExit(main_for_config(CONFIG))
