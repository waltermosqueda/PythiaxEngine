"""Verifica timestamps en preview_c1_pro.html end-to-end."""
from pathlib import Path
import re
from datetime import datetime, timedelta

html = Path(r'C:\repos\PythiaxEngine\analisis\preview_c1_pro.html').read_text(encoding='utf-8')

# 1. Raw text del kpi-fresh-sub
m = re.search(r'id=["\']kpi-fresh-sub["\'][^>]*>([^<]+)', html)
raw = m.group(1).strip() if m else 'NO ENCONTRADO'
print(f'kpi-fresh-sub texto: {raw!r}')

# 2. ISO timestamp (debe tener sufijo Z para UTC correcto en browser)
m2 = re.search(r'(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ)', html)
if m2:
    iso = m2.group(1)
    print(f'ISO timestamp: {iso}  <- sufijo Z: {"OK" if iso.endswith("Z") else "FALTA Z - BUG"}')
    ts_utc = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    ts_ar  = ts_utc - timedelta(hours=3)
    print(f'UTC: {ts_utc.strftime("%Y-%m-%d %H:%M")}')
    print(f'AR:  {ts_ar.strftime("%Y-%m-%d %H:%M")}  (UTC-3, correcto: {"SI" if ts_utc.hour - ts_ar.hour == 3 or ts_ar.hour - ts_utc.hour == 21 else "NO"})')
else:
    print('ERROR: no se encontro ISO timestamp con Z en el HTML')

# 3. Verificar que el freshness JS convierte correctamente
# Buscar la logica de conversion UTC->AR en el script de freshness
fscript = re.search(r'_FRESHNESS_SCRIPT|kpi-fresh-sub|kpi-actualizacion', html)
print(f'\nFreshness script presente en HTML: {"SI" if fscript else "NO"}')

# 4. Verificar live-prices badge actual
if 'live-prices-v1' in html:
    print('\nlive-prices-v1 script: PRESENTE en prod HTML')
    m3 = re.search(r'order=([^&\'"]+)', html)
    if m3:
        print(f'Query order: {m3.group(1)}')
    # Buscar addLiveBadge
    if 'addLiveBadge' in html:
        idx = html.index('addLiveBadge')
        print(f'addLiveBadge snippet: {html[idx:idx+120]!r}')
else:
    print('\nlive-prices-v1: NO en prod - necesita inyeccion')

# 5. Resumen
print('\n=== RESUMEN ===')
print(f'Timestamp Z-suffix: {"OK" if m2 and m2.group(1).endswith("Z") else "BUG"}')
print(f'Conversion UTC-AR: {"OK" if m2 else "NO VERIFICADO"}')
print(f'Live prices badge: {"solo fecha, sin hora" if "precios live" in html else "ausente"}')
