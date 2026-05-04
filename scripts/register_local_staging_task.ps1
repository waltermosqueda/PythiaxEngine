<#
.SYNOPSIS
    Registra la tarea programada TITAN_UpdateLocalStaging en Windows.

.DESCRIPTION
    Crea una tarea que corre update_local_staging.ps1 de lunes a viernes
    a las 20:00 (hora Argentina / sin DST).

    Ejecutar UNA SOLA VEZ desde la raiz del proyecto:
      .\scripts\register_local_staging_task.ps1

    Para ver el estado de la tarea despues:
      Get-ScheduledTask -TaskName TITAN_UpdateLocalStaging
#>

$TaskName   = "TITAN_UpdateLocalStaging"
$ScriptPath = "C:\repos\PythiaxEngine\scripts\update_local_staging.ps1"

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptPath`""

$Trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At "20:00"

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 90) `
    -RunOnlyIfNetworkAvailable `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName    $TaskName `
    -Action      $Action `
    -Trigger     $Trigger `
    -Settings    $Settings `
    -RunLevel    Limited `
    -Description "Actualiza DB Docker local con datos yfinance — PythiaxEngine (lun-vie 20:00 AR)" `
    -Force

Write-Host ""
Write-Host "[OK] Tarea '$TaskName' registrada." -ForegroundColor Green
Write-Host "     Corre: lunes a viernes a las 20:00 AR"
Write-Host "     Log:   C:\repos\PythiaxEngine\logs\update_local_staging.log"
Write-Host ""
Write-Host "Para ejecutar manualmente ahora:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
