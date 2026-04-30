<#
.SYNOPSIS
    Actualiza la DB Docker local con datos frescos de yfinance.

.DESCRIPTION
    Corre el mismo pipeline que el CI en GitHub Actions pero apuntando al
    contenedor Postgres Docker local (puerto 5433).  No descarga nada desde
    Supabase ni consume egress: yfinance es la unica fuente de datos.

    Pensado para correr como tarea programada (ver abajo).

.NOTES
    Tarea sugerida: lunes a viernes a las 20:00 AR
      schtasks /query /tn TITAN_UpdateLocalStaging

    Para registrar la tarea:
      .\scripts\register_local_staging_task.ps1
#>

$ProjectDir = "C:\Users\wmx_7\OneDrive\Escritorio\Inversiones\PythiaxEngine"
$Python     = "C:\Users\wmx_7\AppData\Local\Programs\Python\Python314\python.exe"
$Container  = "pythiax_staging_postgres"
$DockerUrl  = "postgresql+psycopg://postgres:postgres_local@localhost:5433/pythiax"
$LogDir     = Join-Path $ProjectDir "logs"
$LogFile    = Join-Path $LogDir "update_local_staging.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Log {
    param([string]$Msg)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $Msg"
    Add-Content $LogFile $line
    Write-Host $line
}

Log "===== Inicio update_local_staging ====="

# --------------------------------------------------------------------------
# 1. Verificar Docker Desktop
# --------------------------------------------------------------------------
$dockerInfo = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Log "SKIP: Docker Desktop no esta corriendo. Abrir Docker Desktop y reintentar."
    exit 0   # exit 0 para que la tarea no aparezca como fallida en el scheduler
}

# --------------------------------------------------------------------------
# 2. Asegurar que el contenedor este corriendo
# --------------------------------------------------------------------------
$running = docker inspect $Container --format '{{.State.Running}}' 2>&1
if ($running -ne "true") {
    Log "Contenedor '$Container' detenido. Intentando iniciar..."
    docker start $Container 2>&1 | Out-Null
    Start-Sleep -Seconds 5
    $running = docker inspect $Container --format '{{.State.Running}}' 2>&1
    if ($running -ne "true") {
        Log "ERROR: No se pudo iniciar '$Container'. Correr: docker start $Container"
        exit 1
    }
    Log "Contenedor iniciado."
}

# --------------------------------------------------------------------------
# 3. Ejecutar pipeline apuntando a Docker (override sobre .env)
# --------------------------------------------------------------------------
$env:DATABASE_URL = $DockerUrl

Set-Location $ProjectDir
Log "Ejecutando pipeline contra Docker local ($DockerUrl)..."

& $Python herramientas/auto_actualizar.py 2>&1 | Tee-Object -Append -FilePath $LogFile

$exit = $LASTEXITCODE
Log "===== Fin update_local_staging  exit=$exit ====="
exit $exit
