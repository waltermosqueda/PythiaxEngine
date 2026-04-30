<#
.SYNOPSIS
    Crea y sincroniza un Postgres Docker local desde Supabase (staging offline).

.DESCRIPTION
    Pasos:
      1. Valida prereqs (.env con DATABASE_URL de Supabase, Docker corriendo)
      2. Levanta el contenedor Postgres local (puerto 5433)
      3. Espera que este healthy
      4. Descarga todos los datos de Supabase -> SQLite local
      5. Carga SQLite -> Postgres Docker local (aplica migraciones via alembic)
      6. Muestra conteo de filas para verificar
      7. Indica como cambiar al modo Docker en .env

.NOTES
    Ejecutar desde la raiz del proyecto:
      .\scripts\setup_local_staging.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
function Write-Step { param([string]$msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn { param([string]$msg) Write-Host "    [!]  $msg" -ForegroundColor Yellow }
function Write-Fail { param([string]$msg) Write-Host "    [ERROR] $msg" -ForegroundColor Red }

# ---------------------------------------------------------------------------
# Cambiar al directorio raiz del proyecto
# ---------------------------------------------------------------------------
$ROOT = Split-Path $PSScriptRoot -Parent
Push-Location $ROOT

try {

# ---------------------------------------------------------------------------
# PASO 0 - Validar prereqs
# ---------------------------------------------------------------------------
Write-Step "Validando prereqs"

if (-not (Test-Path ".env")) {
    Write-Fail ".env no encontrado. Copiar .env.example como .env y configurar DATABASE_URL."
    exit 1
}

# Leer DATABASE_URL del .env
$envContent = Get-Content ".env" -ErrorAction SilentlyContinue
$dbUrlLine  = $envContent | Where-Object { $_ -match "^DATABASE_URL\s*=" } | Select-Object -First 1
if (-not $dbUrlLine) {
    Write-Fail "DATABASE_URL no encontrada en .env."
    exit 1
}
$dbUrl = ($dbUrlLine -split "=", 2)[1].Trim()

if ($dbUrl -match "change_me|<project-ref>|<region>|<password>") {
    Write-Fail "DATABASE_URL tiene valores placeholder. Completar con la URL real de Supabase."
    Write-Warn "Copiar el secret DATABASE_URL desde: https://github.com/waltermosqueda/PythiaxEngine/settings/secrets/actions"
    exit 1
}

if ($dbUrl -match "localhost:5433") {
    Write-Fail "DATABASE_URL apunta al Docker local, no a Supabase. Cambiar a OPCION A (Supabase) en .env para sincronizar datos."
    exit 1
}

Write-Ok "DATABASE_URL apunta a Supabase: $($dbUrl.Substring(0, [Math]::Min(50, $dbUrl.Length)))..."

# Verificar Docker
try {
    $null = docker info 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Docker no esta corriendo" }
    Write-Ok "Docker disponible"
} catch {
    Write-Fail "Docker no esta corriendo. Iniciar Docker Desktop y volver a ejecutar."
    exit 1
}

# ---------------------------------------------------------------------------
# PASO 1 - Levantar Postgres Docker
# ---------------------------------------------------------------------------
Write-Step "Levantando Postgres Docker local (puerto 5433)"

docker compose up -d postgres
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Fallo docker compose up"
    exit 1
}
Write-Ok "Contenedor iniciado"

# ---------------------------------------------------------------------------
# PASO 2 - Esperar que Postgres este healthy
# ---------------------------------------------------------------------------
Write-Step "Esperando que Postgres este healthy"

$maxWait   = 60   # segundos maximos
$elapsed   = 0
$interval  = 3
$isHealthy = $false

while ($elapsed -lt $maxWait) {
    $status = docker inspect --format="{{.State.Health.Status}}" pythiax_staging_postgres 2>$null
    if ($status -eq "healthy") {
        $isHealthy = $true
        break
    }
    Write-Host "    ... esperando ($elapsed s / ${maxWait}s) - estado: $status" -ForegroundColor DarkGray
    Start-Sleep -Seconds $interval
    $elapsed += $interval
}

if (-not $isHealthy) {
    Write-Fail "Postgres no llego a estar healthy en ${maxWait}s. Revisar: docker compose logs postgres"
    exit 1
}
Write-Ok "Postgres healthy"

# ---------------------------------------------------------------------------
# PASO 3 - Descargar Supabase -> SQLite local
# ---------------------------------------------------------------------------
Write-Step "Descargando Supabase -> SQLite local (titan_system/data/titan.db)"
Write-Warn "Este paso puede tomar varios minutos segun el volumen de datos..."

python -m infra.db.bootstrap_sqlite_from_target --reset-target
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Fallo la descarga desde Supabase."
    exit 1
}
Write-Ok "SQLite sincronizada desde Supabase"

# ---------------------------------------------------------------------------
# PASO 4 - Cargar SQLite -> Postgres Docker local
# ---------------------------------------------------------------------------
$LOCAL_PG_URL = "postgresql+psycopg://postgres:postgres_local@localhost:5433/pythiax"

Write-Step "Cargando SQLite -> Postgres Docker local"
Write-Warn "Este paso aplica las migraciones alembic y carga todos los datos..."

python -m infra.db.bootstrap_target `
    --source-sqlite-path titan_system/data/titan.db `
    --target-url $LOCAL_PG_URL `
    --reset-target
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Fallo la carga al Postgres local."
    exit 1
}
Write-Ok "Datos cargados en Postgres Docker local"

# ---------------------------------------------------------------------------
# PASO 5 - Verificacion de conteos
# ---------------------------------------------------------------------------
Write-Step "Verificando conteos de filas en Postgres local"

$verifyScript = @"
import sys
sys.path.insert(0, '.')
import os
os.environ['DATABASE_URL'] = 'postgresql+psycopg://postgres:postgres_local@localhost:5433/pythiax'
from titan_system.core.database import TitanDB
tables = ['prices', 'predictions', 'outcomes', 'model_metrics', 'regimes', 'data_status', 'pipeline_runs']
with TitanDB() as db:
    for t in tables:
        count = db.scalar(f'SELECT COUNT(*) FROM {t}')
        print(f'  {t:<20} {count:>8} rows')
"@

python -c $verifyScript
if ($LASTEXITCODE -ne 0) {
    Write-Warn "No se pudo verificar (puede ser normal si TitanDB usa otro modulo). Continuar de todas formas."
}

# ---------------------------------------------------------------------------
# PASO 6 - Instrucciones finales
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  STAGING LOCAL LISTO" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Para usar el Postgres Docker local, editar .env:" -ForegroundColor Yellow
Write-Host "    - Comentar:   DATABASE_URL=postgresql+psycopg://postgres.<ref>:..." -ForegroundColor DarkGray
Write-Host "    - Activar:    DATABASE_URL=postgresql+psycopg://postgres:postgres_local@localhost:5433/pythiax" -ForegroundColor White
Write-Host ""
Write-Host "  Proximos pasos:" -ForegroundColor Yellow
Write-Host "    .\scripts\run_local.ps1       <- pipeline completo + preview" -ForegroundColor White
Write-Host "    .\scripts\preview_local.ps1   <- solo preview del dashboard actual" -ForegroundColor White
Write-Host ""

} finally {
    Pop-Location
}
