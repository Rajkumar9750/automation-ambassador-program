@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" python -m venv venv
venv\Scripts\pip install -r requirements.txt -q
echo Starting Jira Tracker on http://localhost:8082
venv\Scripts\uvicorn jira_tracker:app --host 0.0.0.0 --port 8082 --reload
