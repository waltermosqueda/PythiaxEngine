#!/usr/bin/env python3
"""
WRAPPER LEGACY DEL GESTOR V11
=============================

Compatibilidad hacia atras para comandos viejos:
  python herramientas/gestor_posiciones_v10.py

El gestor canonico ahora vive en:
  python herramientas/gestor_posiciones_v11.py
"""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from herramientas.gestor_posiciones_v11 import main


if __name__ == "__main__":
    main()
