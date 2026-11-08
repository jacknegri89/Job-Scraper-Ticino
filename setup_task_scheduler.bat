@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "TASK_NAME=JobScraper"
set "LEGACY_TASK_NAME=JobScraperFrontaliero"
set "RUN_FILE=%~dp0run_scheduled.bat"
set "PROJECT_PYTHON=%~dp0.venv\Scripts\python.exe"

echo Configuring Windows Task Scheduler...
echo.

if not exist "%PROJECT_PYTHON%" (
    echo [ERROR] The local environment was not found: %PROJECT_PYTHON%
    echo Create it first, as described in the Installation section of the README:
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -r requirements.txt
    echo     .venv\Scripts\python -m playwright install chromium
    pause
    exit /b 1
)

echo Python: %PROJECT_PYTHON%
echo Task:   %RUN_FILE%
echo.

rem A task created by an earlier version used the same job under another name; replace it.
schtasks /query /tn "%LEGACY_TASK_NAME%" >nul 2>&1
if not errorlevel 1 (
    schtasks /delete /tn "%LEGACY_TASK_NAME%" /f >nul 2>&1
    echo Removed the task "%LEGACY_TASK_NAME%" from an earlier version.
)

schtasks /create /tn "%TASK_NAME%" /tr "\"%RUN_FILE%\"" /sc daily /st 08:00 /f

if errorlevel 1 (
    echo.
    echo [ERROR] Task creation failed. Try running this file as Administrator.
    pause
    exit /b 1
)

echo.
echo [OK] Task "%TASK_NAME%" created. It runs every morning at 08:00 and writes to scraper.log.
echo Task Scheduler shows the exit code: 0 success, 1 failure, 2 partial, 3 another search was running.
echo To remove it: schtasks /delete /tn "%TASK_NAME%"
echo.
pause
