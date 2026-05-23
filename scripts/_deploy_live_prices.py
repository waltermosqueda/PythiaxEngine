"""Deploy live prices: copia staging -> prod y ejecuta git add/commit/push."""
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(r'C:\repos\PythiaxEngine')
STAGING = REPO / 'analisis' / '_staging_prod_preview.html'
PROD = REPO / 'analisis' / 'preview_c1_pro.html'

# 1. Verificar staging existe
if not STAGING.exists():
    print('ERROR: staging no existe'); sys.exit(1)

staging_size = STAGING.stat().st_size
print(f'Staging: {staging_size:,} bytes')

# 2. Verificar que el script live-prices-v1 esta en el staging
content = STAGING.read_text(encoding='utf-8')
if 'live-prices-v1' not in content:
    print('ERROR: live-prices-v1 no encontrado en staging'); sys.exit(1)
if 'order=date.desc' not in content:
    print('ERROR: bug de query no corregido (falta order=date.desc)'); sys.exit(1)
print('Verificaciones OK: script presente, query correcto')

# 3. Copiar staging -> prod
shutil.copy2(str(STAGING), str(PROD))
prod_size = PROD.stat().st_size
print(f'Prod copiado: {prod_size:,} bytes')

# 4. Git add
result = subprocess.run(
    ['git', 'add',
     'analisis/preview_c1_pro.html',
     'scripts/_inject_live_prices.py',
     'scripts/_validate_live_prices.py'],
    cwd=str(REPO), capture_output=True, text=True
)
if result.returncode != 0:
    print('ERROR git add:', result.stderr); sys.exit(1)
print('git add OK')

# 5. Git commit
result = subprocess.run(
    ['git', 'commit', '-m',
     'feat: live prices JS via Supabase anon REST — updates on page load, hourly intraday data'],
    cwd=str(REPO), capture_output=True, text=True
)
if result.returncode != 0:
    print('ERROR git commit:', result.stderr)
    print(result.stdout)
    sys.exit(1)
print('git commit OK')
print(result.stdout.strip())

# 6. Git push
result = subprocess.run(
    ['git', 'push'],
    cwd=str(REPO), capture_output=True, text=True
)
if result.returncode != 0:
    print('ERROR git push:', result.stderr); sys.exit(1)
print('git push OK')
print(result.stderr.strip() or result.stdout.strip())

print('\nDEPLOY COMPLETO')
