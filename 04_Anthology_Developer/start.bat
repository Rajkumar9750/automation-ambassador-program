@echo off
cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv
)

echo Installing dependencies...
venv\Scripts\pip install -r requirements.txt -q

echo.
echo  Anthology Developer  -  http://localhost:8083
echo.

venv\Scripts\uvicorn app:app --host 0.0.0.0 --port 8083 --reload
pause
