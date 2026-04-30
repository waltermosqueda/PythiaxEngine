<#
.SYNOPSIS
    Ejecuta el pipeline completo localmente (identico a GitHub Actions CI).

.DESCRIPTION
    Pasos (replica exacta del workflow github-pages-publish.yml):
      1. Valida .env y DATABASE_URL
      2. Muestra a que DB esta apuntando (Supabase vs Docker local)
      3. alembic upgrade head
      4. auto_actualizar.py --force-pipeline --skip-dashboard-refresh
      5. generar_tablero_maquina_pensante.py --variant all
      6. Construye el site bundle en dist/local-preview/
      7. Levanta servidor HTTP local y abre el browser

.NOTES
    Ejecutar desde la raiz del proyecto:
      .\scripts\run_local.ps1
    
    Para parar el servidor HTTP: Ctrl+C en la ventana del servidor,
    o cerrar la ventana de PowerShell que queda en background.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step { param([string]$msg) Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok   { param([string]$msg) Write-Host "    [OK] $msg" -ForegroundColor Green }
function Write-Warn { param([string]$msg) Write-Host "    [!]  $msg" -ForegroundColor Yellow }
function Write-Fail { param([string]$msg) Write-Host "    [ERROR] $msg" -ForegroundColor Red }

$ROOT = Split-Path $PSScriptRoot -Parent
Push-Location $ROOT

try {

# ---------------------------------------------------------------------------
# PASO 0 - Validar .env y DATABASE_URL
# ---------------------------------------------------------------------------
Write-Step "Validando configuracion"

if (-not (Test-Path ".env")) {
    Write-Fail ".env no encontrado. Copiar .env.example como .env y configurar DATABASE_URL."
    exit 1
}

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

# Mostrar modo actual
if ($dbUrl -match "localhost:5433") {
    Write-Warn "Modo: POSTGRES DOCKER LOCAL (offline staging)"
    Write-Warn "Para usar Supabase, cambiar DATABASE_URL en .env a OPCION A."
} elseif ($dbUrl -match "supabase\.com|pooler\.supabase") {
    Write-Ok "Modo: SUPABASE CLOUD (identico a produccion)"
} else {
    Write-Ok "Modo: Postgres custom - $($dbUrl.Substring(0, [Math]::Min(50, $dbUrl.Length)))..."
}

# ---------------------------------------------------------------------------
# PASO 1 - alembic upgrade head
# ---------------------------------------------------------------------------
Write-Step "Aplicando migraciones de schema (alembic upgrade head)"

alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Fail "alembic upgrade head fallo. Verificar DATABASE_URL y conectividad."
    exit 1
}
Write-Ok "Schema actualizado"

# ---------------------------------------------------------------------------
# PASO 2 - Pipeline de datos (igual que CI)
# ---------------------------------------------------------------------------
Write-Step "Ejecutando pipeline de datos (auto_actualizar.py)"
Write-Warn "En primer uso puede tardar varios minutos. Runs siguientes son rapidos si los datos estan al dia."

python -u herramientas/auto_actualizar.py --force-pipeline --skip-dashboard-refresh
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Pipeline fallo. Revisar bitacora/auto_actualizar.log para detalle."
    exit 1
}
Write-Ok "Pipeline completado"

# ---------------------------------------------------------------------------
# PASO 3 - Generar dashboard
# ---------------------------------------------------------------------------
Write-Step "Generando bundle del dashboard (generar_tablero_maquina_pensante.py)"

python -u analisis/generar_tablero_maquina_pensante.py --variant all
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Generacion del dashboard fallo."
    exit 1
}
Write-Ok "Dashboard generado"

# ---------------------------------------------------------------------------
# PASO 4 - Construir site bundle
# ---------------------------------------------------------------------------
Write-Step "Construyendo site bundle -> dist/local-preview/"

$null = New-Item -ItemType Directory -Path "dist/local-preview" -Force
python -m infra.publish.dashboard_site `
    --source-dir dashboards/maquina_pensante `
    --output-dir dist/local-preview
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Construccion del site bundle fallo."
    exit 1
}
Write-Ok "Site bundle construido en dist/local-preview/"

# ---------------------------------------------------------------------------
# PASO 5 - Servidor HTTP local + browser
# ---------------------------------------------------------------------------
Write-Step "Levantando servidor HTTP en http://localhost:8080"

# Iniciar servidor en background
$serverJob = Start-Process `
    -FilePath "python" `
    -ArgumentList "-m http.server 8080 --directory dist/local-preview" `
    -PassThru `
    -WindowStyle Minimized

Start-Sleep -Seconds 2  # Dar tiempo al servidor de iniciar

Write-Ok "Servidor corriendo (PID $($serverJob.Id))"
Write-Host ""
Write-Host "  Abriendo: http://localhost:8080" -ForegroundColor White
Start-Process "http://localhost:8080"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  DASHBOARD LOCAL DISPONIBLE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  URL:     http://localhost:8080" -ForegroundColor White
Write-Host "  Archivos: dist/local-preview/" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Para detener el servidor HTTP, cerrar la ventana minimizada" -ForegroundColor Yellow
Write-Host "  o ejecutar: Stop-Process -Id $($serverJob.Id)" -ForegroundColor DarkGray
Write-Host ""

} finally {
    Pop-Location
}
