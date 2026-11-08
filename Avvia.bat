@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py" --panel
    exit /b 0
)
echo Ambiente locale non trovato. Segui la sezione Installazione del README.
pause
