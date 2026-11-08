@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "%~dp0main.py" --panel
    exit /b 0
)
echo Local environment not found. Follow the Installation section of the README.
pause
exit /b 1
