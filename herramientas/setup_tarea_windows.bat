@echo off
:: ============================================================
::  TITAN - Registrar pipeline diario V11 en Windows
::  Ubicacion: herramientas/setup_tarea_windows.bat
::  Ejecutar una sola vez como Administrador
:: ============================================================

echo.
echo  Registrando tareas en Windows Task Scheduler...
echo.

:: Obtener el path de Python
for /f "delims=" %%i in ('where python') do set PYTHON_EXE=%%i

if "%PYTHON_EXE%"=="" (
    echo  [ERROR] Python no encontrado en el PATH.
    echo  Instala Python o agrega su directorio al PATH del sistema.
    pause
    exit /b 1
)

set SCRIPT_PATH=%~dp0auto_actualizar.py
set DAILY_TASK=TITAN_AutoActualizar_Diario
set LOGON_TASK=TITAN_AutoActualizar_Logon
set LEGACY_TASK=TITAN_AutoActualizar
set DAILY_TIME=19:15

echo  Python encontrado: %PYTHON_EXE%
echo  Script: %SCRIPT_PATH%
echo.

:: Limpiar tareas previas
schtasks /delete /tn "%LEGACY_TASK%" /f >nul 2>&1
schtasks /delete /tn "%DAILY_TASK%" /f >nul 2>&1
schtasks /delete /tn "%LOGON_TASK%" /f >nul 2>&1

:: Tarea 1: corrida diaria despues del cierre del mercado.
schtasks /create ^
  /tn "%DAILY_TASK%" ^
  /tr "\"%PYTHON_EXE%\" \"%SCRIPT_PATH%\"" ^
  /sc DAILY ^
  /st %DAILY_TIME% ^
  /ru "%USERNAME%" ^
  /f

set DAILY_STATUS=%ERRORLEVEL%

:: Tarea 2: backup al iniciar sesion.
schtasks /create ^
  /tn "%LOGON_TASK%" ^
  /tr "\"%PYTHON_EXE%\" \"%SCRIPT_PATH%\"" ^
  /sc ONLOGON ^
  /ru "%USERNAME%" ^
  /delay 0002:00 ^
  /f

set LOGON_STATUS=%ERRORLEVEL%

if %DAILY_STATUS% EQU 0 if %LOGON_STATUS% EQU 0 (
    echo.
    echo  ============================================================
    echo   Tareas registradas correctamente.
    echo.
    echo   Diario : %DAILY_TASK% a las %DAILY_TIME%
    echo   Backup : %LOGON_TASK% al iniciar sesion
    echo   Script : herramientas\auto_actualizar.py
    echo.
echo   El script ejecutara el flujo diario:
echo   actualizar_datos -> aprendizaje_operativo_v11 -> scanner V11 -> resumen
echo   Log: bitacora\auto_actualizar.log
    echo  ============================================================
) else if %DAILY_STATUS% EQU 0 (
    echo.
    echo  ============================================================
    echo   Tarea diaria registrada correctamente.
    echo.
    echo   Diario : %DAILY_TASK% a las %DAILY_TIME%
    echo   Script : herramientas\auto_actualizar.py
    echo.
    echo   Aviso: no se pudo crear el backup ONLOGON en este contexto.
echo   El pipeline diario queda operativo igual.
echo   Log: bitacora\auto_actualizar.log
    echo  ============================================================
) else (
    echo.
    echo  [ERROR] No se pudo registrar la tarea diaria principal.
    echo  Revisa permisos de Task Scheduler y ejecuta este .bat como Administrador.
)

echo.
pause
