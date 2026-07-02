#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -f "venv/bin/python3" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

venv/bin/pip install -r requirements.txt -q

echo "Starting Jira Tracker on http://localhost:8082"
venv/bin/uvicorn jira_tracker:app --host 0.0.0.0 --port 8082 --reload
