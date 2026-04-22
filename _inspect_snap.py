import json
snap = json.loads(open('C:/Users/wmx_7/OneDrive/Escritorio/Inversiones/Claude/dashboards/maquina_pensante/tablero_maquina_pensante_snapshot.json', encoding='utf-8').read())
cr = snap.get('competition_recent', {})
league = cr.get('league_equalized', [])
row = league[0]
print('Snapshot top-level:', list(snap.keys()))
print()
for k in ('recent_10', 'recent_15', 'recent_30', 'equalized_recent', 'window'):
    w = row.get(k, {})
    cal = w.get('calendar') or []
    print(f'  {k}: window_days={w.get("window_days")}, active_days={w.get("active_days")}, cal_len={len(cal)}')
    if cal:
        print(f'    First: {cal[0].get("date")} | Last: {cal[-1].get("date")}')
print()
# Check window (full history) calendar
full_cal = (row.get('window') or {}).get('calendar') or []
print(f'Full window calendar entries: {len(full_cal)}')
# Check all league rows - which has most calendar entries
for r in league:
    cal60 = (r.get('window') or {}).get('calendar') or []
    print(f"  {r.get('version')}: window cal_len={len(cal60)}, window_days={r.get('window',{}).get('window_days')}")
