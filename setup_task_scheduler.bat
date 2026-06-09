@echo off
echo Configurazione Task Scheduler Windows...
echo.

for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)"') do set PYTHON_PATH=%%i
set SCRIPT_PATH=%~dp0scraper.py

echo Python: %PYTHON_PATH%
echo Script: %SCRIPT_PATH%
echo.

schtasks /create /tn "JobScraperFrontaliero" ^
  /tr "\"%PYTHON_PATH%\" \"%SCRIPT_PATH%\"" ^
  /sc daily /st 08:00 ^
  /f

if %ERRORLEVEL% == 0 (
    echo.
    echo [OK] Task creato! Lo script girera ogni mattina alle 08:00.
    echo.
    echo Per rimuoverlo: schtasks /delete /tn "JobScraperFrontaliero"
) else (
    echo.
    echo [ERRORE] Creazione fallita. Prova a eseguire come Amministratore.
)
echo.
pause
