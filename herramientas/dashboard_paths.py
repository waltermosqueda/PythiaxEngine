from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_DIR = ROOT / "dashboards" / "maquina_pensante"

SNAPSHOT_PATH = DASHBOARD_DIR / "tablero_maquina_pensante_snapshot.json"
INDEX_HTML = DASHBOARD_DIR / "tablero_maquina_pensante.html"
EXECUTIVE_HTML = DASHBOARD_DIR / "tablero_maquina_pensante_executive.html"
LAB_HTML = DASHBOARD_DIR / "tablero_maquina_pensante_lab.html"
AURORA_PRO_HTML = ROOT / "analisis" / "preview_c1_pro.html"
AURORA_PRO_BACKUP = DASHBOARD_DIR / "dashboard_operativo_aurora_pro.html"
LEGACY_AURORA_PREVIEW = ROOT / "analisis" / "preview_c1_pro.html"


def ensure_dashboard_dir() -> Path:
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    return DASHBOARD_DIR
