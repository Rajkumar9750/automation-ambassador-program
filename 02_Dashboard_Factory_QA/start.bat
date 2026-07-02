@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -q
echo Starting Dashboard Factory QA on http://localhost:5555
.venv\Scripts\python "Tableau QA Compliance \app.py"
