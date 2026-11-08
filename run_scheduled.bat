@echo off
rem Runs one background search. Task Scheduler starts this file.
rem It uses the Python of the local virtual environment (.venv), writes everything to
rem scraper.log and passes the exit code of the search to Task Scheduler:
rem   0 success, 1 failure, 2 partial (some sources were not read), 3 another search was running.
cd /d "%~dp0"
set "PROJECT_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PROJECT_PYTHON%" (
    echo [%date% %time%] .venv not found: follow the Installation section of the README. >> scraper.log
    exit /b 1
)
echo [%date% %time%] Scheduled search started >> scraper.log
"%PROJECT_PYTHON%" "%~dp0main.py" --background --headless --project-dir >> scraper.log 2>&1
set "SEARCH_EXIT_CODE=%ERRORLEVEL%"
echo [%date% %time%] Scheduled search finished with exit code %SEARCH_EXIT_CODE% >> scraper.log
exit /b %SEARCH_EXIT_CODE%
