#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.aprendizaje_operativo_observado_base import ObservedScannerConfig, main_for_config


CONFIG = ObservedScannerConfig(
    version=8,
    scanner_module="SCANNER.invertir_v8",
    scanner_file="SCANNER/invertir_v8.py",
    learning_file="herramientas/aprendizaje_operativo_v8.py",
    crash_signal_attr="signal_c2_crash_volume_oversold",
    crash_signal_code="C2",
    crash_display_label="C2",
    crash_horizons=(1, 7),
)


if __name__ == "__main__":
    raise SystemExit(main_for_config(CONFIG))
