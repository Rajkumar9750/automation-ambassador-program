@echo off
cd /d "%~dp0"
title Automation Ambassador Program Monitor
set PORT=9000

echo.
echo +==================================================+
echo ^|     Automation Ambassador Program Monitor        ^|
echo +==================================================+
echo.

:: Run setup if venv not yet created
if not exist "venv\Scripts\python.exe" (
    echo First run - running setup...
    call setup.bat
    echo.
)

echo   Dashboard Factory    -^> http://localhost:8080
echo   Dashboard Factory QA -^> http://localhost:5555
echo   Jira Tracker         -^> http://localhost:8082
echo   Monitor              -^> http://localhost:%PORT%
echo.
echo Press Ctrl+C to stop.
echo.

:: Open browser after 2 seconds
start /b cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:%PORT%"

venv\Scripts\uvicorn monitor:app --host 0.0.0.0 --port %PORT% --reload
