#!/usr/bin/env python3
"""Extract key values from snapshot for staging header update."""
import json, sys
sys.path.insert(0, 'C:/repos/PythiaxEngine')
from pathlib import Path
from herramientas.refrescar_datos_dashboard import (
    _dashboard_league, _build_c1pro_hero_row, _render_kpi_strip, latest_market_date
)

snap = json.loads(Path('C:/repos/PythiaxEngine/dashboards/maquina_pensante/tablero_maquina_pensante_snapshot.json').read_text(encoding='utf-8'))

league = _dashboard_league(snap)
print('League length:', len(league))
for m in league[:5]:
    eq = m.get('equalized_recent') or m.get('window') or {}
    print(f"  rank={m.get('rank')} {m.get('version')} wr={eq.get('accuracy_pct')} ret={eq.get('avg_return_pct')}")

active = snap.get('active') or {}
run = (active.get('active_run')) or {}
champion_ver = f"V{active.get('active_version', '13')}"
print('champion_ver:', champion_ver)
print('latest_market:', latest_market_date(snap))
print('generated_at:', snap.get('generated_at'))

# regime from competition_recent
comp_recent = snap.get('competition_recent') or []
if comp_recent:
    regime_entry = sorted(comp_recent, key=lambda x: x.get('date') or '', reverse=True)
    print('Latest comp_recent date:', regime_entry[0].get('date') if regime_entry else None)

# Ver la primera entrada de competition para extraer WR del rank1
comp = snap.get('competition') or []
if comp:
    # Sort by accuracy_pct to find champion
    ranked = sorted(comp, key=lambda x: x.get('accuracy_pct') or 0, reverse=True)
    champ = ranked[0]
    print(f"Best by accuracy: {champ.get('version')} wr={champ.get('accuracy_pct'):.1f}% ret={champ.get('avg_return_pct')}")

# Try to build kpi strip
try:
    kpi_html = _build_kpi_strip(snap)
    # Extract WR value from HTML
    import re
    m = re.search(r'WR ([\d.]+)%', kpi_html)
    if m:
        print('KPI champion WR from renderer:', m.group(1))
    m2 = re.search(r'breadth ([\d.]+)%', kpi_html)
    if m2:
        print('KPI breadth from renderer:', m2.group(1))
    m3 = re.search(r'regime-(seguro|peligro|cautela)', kpi_html)
    if m3:
        print('KPI regime from renderer:', m3.group(1))
    # Show first 500 chars
    print('KPI HTML preview:', kpi_html[:500])
except Exception as e:
    print('_build_kpi_strip error:', e)
