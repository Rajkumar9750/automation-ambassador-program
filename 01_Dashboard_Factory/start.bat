@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" python -m venv venv
venv\Scripts\pip install -r requirements.txt -q
echo Starting Dashboard Factory on http://localhost:8080
venv\Scripts\uvicorn app:app --host 0.0.0.0 --port 8080 --reload
