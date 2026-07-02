#!/bin/bash
# Automation Ambassador Program – One-time setup
# Run this once on a new machine before launching the monitor.

set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
PYTHON=python3

check_python() {
  if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.9+ from https://www.python.org"; exit 1
  fi
  echo "  Python: $(python3 --version)"
}

make_venv() {
  local name="$1" venv_path="$2" req="$3"
  echo ""
  echo "[$name]"
  if [ -f "$venv_path/bin/python3" ]; then
    echo "  venv already exists, updating..."
  else
    echo "  Creating venv..."
    python3 -m venv "$venv_path"
  fi
  echo "  Installing dependencies..."
  "$venv_path/bin/pip" install --quiet --upgrade pip
  "$venv_path/bin/pip" install --quiet -r "$req"
  echo "  Done."
}

echo "╔══════════════════════════════════════════════════╗"
echo "║   Automation Ambassador Program – Setup          ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
check_python

make_venv "Monitor"              "$BASE/venv"                            "$BASE/requirements.txt"
make_venv "Dashboard Factory"    "$BASE/01_Dashboard_Factory/venv"       "$BASE/01_Dashboard_Factory/requirements.txt"
make_venv "Dashboard Factory QA" "$BASE/02_Dashboard_Factory_QA/.venv"   "$BASE/02_Dashboard_Factory_QA/requirements.txt"
make_venv "Jira Tracker"         "$BASE/03_Jira_Tracker/venv"            "$BASE/03_Jira_Tracker/requirements.txt"

# Make all launch scripts executable
chmod +x "$BASE/Launch Monitor.command" 2>/dev/null || true
chmod +x "$BASE/01_Dashboard_Factory/start.sh" 2>/dev/null || true
chmod +x "$BASE/02_Dashboard_Factory_QA/start.sh" 2>/dev/null || true
chmod +x "$BASE/03_Jira_Tracker/start.sh" 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   Setup complete! Double-click:                  ║"
echo "║   'Launch Monitor.command' to get started.       ║"
echo "╚══════════════════════════════════════════════════╝"
