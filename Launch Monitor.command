#!/bin/bash
# Automation Ambassador Program – Launch Monitor
# Double-click this file in Finder to start.

set -e
cd "$(dirname "$0")"
PORT=9000

# Remove macOS quarantine from the whole folder (one-time, silent)
xattr -rd com.apple.quarantine . 2>/dev/null || true
# Ensure all scripts are executable
chmod +x setup.sh 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║     Automation Ambassador Program Monitor        ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Run setup if monitor venv or any tool venv is missing
if [ ! -f "venv/bin/python3" ] || \
   [ ! -f "01_Dashboard_Factory/venv/bin/python3" ] || \
   [ ! -f "02_Dashboard_Factory_QA/.venv/bin/python3" ] || \
   [ ! -f "03_Timesheet_Tool/venv/bin/python3" ]; then
  echo "First run (or missing venv) — running setup..."
  bash setup.sh
  echo ""
fi

echo "  Dashboard Factory    → http://localhost:8080"
echo "  Dashboard Factory QA → http://localhost:5555"
echo "  Timesheet Tool       → http://localhost:5000"
echo "  Monitor              → http://localhost:${PORT}"
echo ""
echo "Press Ctrl+C to stop."
echo ""

# Free the port if something is already using it
EXISTING=$(lsof -t -i TCP:${PORT} -s TCP:LISTEN 2>/dev/null || true)
if [ -n "$EXISTING" ]; then
  echo "  Port ${PORT} in use — stopping existing process..."
  echo "$EXISTING" | xargs kill -9 2>/dev/null || true
  sleep 1
fi

(sleep 2 && open "http://localhost:${PORT}") &
venv/bin/uvicorn monitor:app --host 127.0.0.1 --port "$PORT" --reload \
  --reload-exclude "*/venv/*" --reload-exclude "*/.venv/*"
