#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -f ".venv/bin/python3" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

.venv/bin/pip install -r requirements.txt -q

echo "Starting Dashboard Factory QA on http://localhost:5555"
.venv/bin/python3 "Tableau QA Compliance /app.py"
