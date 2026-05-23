#!/usr/bin/env python3
"""Render dashboard to staging file using fixed renderer + local snapshot."""
import json
import sys
from pathlib import Path

repo = Path("C:/repos/PythiaxEngine")
sys.path.insert(0, str(repo))

from herramientas.refrescar_datos_dashboard import render_dashboard_html

snap_path = repo / "dashboards/maquina_pensante/tablero_maquina_pensante_snapshot.json"
staging_path = repo / "analisis/_staging_h7t3b.html"

if not snap_path.exists():
    print(f"ERROR: snapshot not found at {snap_path}")
    sys.exit(1)

if not staging_path.exists():
    print(f"ERROR: staging template not found at {staging_path}")
    sys.exit(1)

snap = json.loads(snap_path.read_text(encoding="utf-8"))
html = staging_path.read_text(encoding="utf-8")

print(f"Snapshot: {snap.get('generated_at')}")
print(f"Rendering to: {staging_path}")

rendered = render_dashboard_html(html, snap, verbose=True)
staging_path.write_text(rendered, encoding="utf-8")

print(f"\nDone. Staging file updated: {staging_path}")
