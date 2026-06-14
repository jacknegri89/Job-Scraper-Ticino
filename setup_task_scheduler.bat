@echo off
setlocal enabledelayedexpansion

echo Configuring Windows Task Scheduler...
echo.

for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)"') do set PYTHON_PATH=%%i
set SCRIPT_PATH=%~dp0main.py

if not defined PYTHON_PATH (
    echo [ERROR] Python was not found. Make sure Python is installed and available in PATH.
    pause
    exit /b 1
)

echo Python: !PYTHON_PATH!
echo Script: !SCRIPT_PATH!
echo.

schtasks /create /tn "JobScraperFrontaliero" ^
  /tr "\"!PYTHON_PATH!\" \"!SCRIPT_PATH!\"" ^
  /sc daily /st 08:00 ^
  /f

if !ERRORLEVEL! == 0 (
    echo.
    echo [OK] Task created. The scraper will run every morning at 08:00.
    echo.
    echo To remove it: schtasks /delete /tn "JobScraperFrontaliero"
) else (
    echo.
    echo [ERROR] Task creation failed. Try running this file as Administrator.
)
echo.
pause
