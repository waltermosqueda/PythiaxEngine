<#
.SYNOPSIS
    Regenera el dashboard desde la DB actual y abre una preview local.

.DESCRIPTION
    NO ejecuta el pipeline de datos. Solo regenera el HTML/JSON del dashboard
    a partir de lo que ya hay en la DB configurada en .env, construye el site
    bundle y lo sirve en http://localhost:8080.

    Util para iterar rapido sobre cambios de visualizacion o para revisar
    el estado actual sin tocar datos.

.NOTES
    Ejecutar desde la raiz del proyecto:
      .\scripts\preview_local.ps1
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
# PASO 0 - Validar .env
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
    Write-Fail "DATABASE_URL tiene valores placeholder. Completar con la URL real en .env."
    exit 1
}

if ($dbUrl -match "localhost:5433") {
    Write-Warn "Modo: POSTGRES DOCKER LOCAL - asegurarse de que el contenedor este corriendo."
    Write-Warn "Iniciar si es necesario: docker compose up -d postgres"
} elseif ($dbUrl -match "supabase\.com|pooler\.supabase") {
    Write-Ok "Modo: SUPABASE CLOUD"
} else {
    Write-Ok "Modo: Postgres - $($dbUrl.Substring(0, [Math]::Min(50, $dbUrl.Length)))..."
}

# ---------------------------------------------------------------------------
# PASO 1 - Regenerar dashboard
# ---------------------------------------------------------------------------
Write-Step "Regenerando dashboard desde DB actual"

python -u analisis/generar_tablero_maquina_pensante.py --variant all
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Generacion del dashboard fallo."
    exit 1
}
Write-Ok "Dashboard generado"

# ---------------------------------------------------------------------------
# PASO 2 - Construir site bundle
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
Write-Ok "Site bundle construido"

# ---------------------------------------------------------------------------
# PASO 3 - Servidor HTTP + browser
# ---------------------------------------------------------------------------
Write-Step "Levantando servidor HTTP en http://localhost:8080"

$serverJob = Start-Process `
    -FilePath "python" `
    -ArgumentList "-m http.server 8080 --directory dist/local-preview" `
    -PassThru `
    -WindowStyle Minimized

Start-Sleep -Seconds 2

Write-Ok "Servidor corriendo (PID $($serverJob.Id))"
Start-Process "http://localhost:8080"

Write-Host ""
Write-Host "  Dashboard disponible en: http://localhost:8080" -ForegroundColor White
Write-Host "  Para detener: Stop-Process -Id $($serverJob.Id)" -ForegroundColor DarkGray
Write-Host ""

} finally {
    Pop-Location
}
