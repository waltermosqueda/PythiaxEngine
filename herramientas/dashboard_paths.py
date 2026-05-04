from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT / "dashboards" / "maquina_pensante"

SNAPSHOT_PATH = DASHBOARD_DIR / "tablero_maquina_pensante_snapshot.json"
INDEX_HTML = DASHBOARD_DIR / "tablero_maquina_pensante.html"
EXECUTIVE_HTML = DASHBOARD_DIR / "tablero_maquina_pensante_executive.html"
LAB_HTML = DASHBOARD_DIR / "tablero_maquina_pensante_lab.html"
MANIFEST_PATH = DASHBOARD_DIR / "tablero_maquina_pensante_artifact_manifest.json"
C1_PRO_BUNDLE_HTML = DASHBOARD_DIR / "preview_c1_pro.html"
C1_PRO_TEMPLATE_HTML = ROOT / "analisis" / "preview_c1_pro.html"
C1_PRO_TEMPLATE_BACKUP_HTML = DASHBOARD_DIR / "dashboard_operativo_c1_pro.html"


def ensure_dashboard_dir() -> Path:
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    return DASHBOARD_DIR


def dashboard_relative_href(output_path: Path, target_path: Path) -> str:
    output_parent = output_path.resolve().parent
    target = target_path.resolve()
    return os.path.relpath(target, output_parent).replace("\\", "/")

