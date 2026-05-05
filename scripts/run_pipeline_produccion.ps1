<#
.SYNOPSIS
    Ejecuta el pipeline diario contra la base de datos de produccion (Supabase).

.DESCRIPTION
    Lee la URL de Supabase desde la linea comentada en .env (OPCION A) y la
    establece como DATABASE_URL antes de correr herramientas/auto_actualizar.py.
    Esto hace que resolve_setting() use el env var en lugar del .env local
    (que apunta a Docker).

    Tarea programada: TITAN_AutoActualizar_Diario - lunes a viernes 19:15
#>

$ProjectDir = "C:\repos\PythiaxEngine"
$Python     = "C:\Users\wmx_7\AppData\Local\Programs\Python\Python314\python.exe"
$LogDir     = Join-Path $ProjectDir "logs"
$LogFile    = Join-Path $LogDir "pipeline_run.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Msg"
    Add-Content $LogFile $line
    Write-Host $line
}

Log "===== Inicio pipeline produccion ====="

# --------------------------------------------------------------------------
# Extraer DATABASE_URL de Supabase desde la linea comentada en .env
# --------------------------------------------------------------------------
$EnvFile = Join-Path $ProjectDir ".env"
$SupabaseLine = Get-Content $EnvFile |
    Where-Object { $_ -match "^#\s*DATABASE_URL=.*supabase" } |
    Select-Object -First 1

if (-not $SupabaseLine) {
    Log "ERROR: No se encontro la URL de Supabase comentada en .env"
    Log "       Verificar que existe la linea: # DATABASE_URL=postgresql+psycopg://...supabase..."
    exit 1
}

$SupabaseUrl = ($SupabaseLine -replace "^#\s*DATABASE_URL=", "").Trim()
$env:DATABASE_URL = $SupabaseUrl

Log "Database: Supabase (produccion)"

# --------------------------------------------------------------------------
# Ejecutar pipeline
# --------------------------------------------------------------------------
Set-Location $ProjectDir

& $Python herramientas/auto_actualizar.py 2>&1 | Tee-Object -Append -FilePath $LogFile

$exit = $LASTEXITCODE
Log "===== Fin pipeline produccion  exit=$exit ====="

# --------------------------------------------------------------------------
# Health check del dashboard (post-pipeline)
# --------------------------------------------------------------------------
Log "Ejecutando health check del dashboard..."
$HealthScript = Join-Path $ProjectDir "scripts\check_dashboard_health.py"
$HealthLog    = Join-Path $LogDir "dashboard_health.log"
& $Python $HealthScript 2>&1 | Tee-Object -Append -FilePath $HealthLog
if ($LASTEXITCODE -ne 0) {
    Log "ALERTA: Dashboard health check detecto problemas. Ver $HealthLog"
} else {
    Log "Dashboard health check: OK"
}

# --------------------------------------------------------------------------
# Recolector de errores graves (alimenta logs/errores_criticos.json)
# --------------------------------------------------------------------------
Log "Recolectando errores criticos del pipeline..."
$CollectorScript = Join-Path $ProjectDir "scripts\collect_pipeline_errors.py"
& $Python $CollectorScript 2>&1 | ForEach-Object { Log $_ }

exit $exit
