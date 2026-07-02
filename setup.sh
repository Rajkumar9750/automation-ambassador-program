#!/bin/bash
# Automation Ambassador Program – One-time setup
# Run this once on a new machine before launching the monitor.

set -e
BASE="$(cd "$(dirname "$0")" && pwd)"
REQUIRED_MAJOR=3
REQUIRED_MINOR=9

echo "╔══════════════════════════════════════════════════╗"
echo "║   Automation Ambassador Program – Setup          ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ---------------------------------------------------------------------------
# 1. Ensure Python 3.9+ is available
# ---------------------------------------------------------------------------

python_ok() {
  local py="$1"
  command -v "$py" &>/dev/null || return 1
  local ver; ver=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null) || return 1
  local major="${ver%%.*}"; local minor="${ver##*.}"
  # Accept 3.9, 3.10, 3.11 only — 3.12+ breaks pandas and other dependencies
  [[ "$major" -eq 3 && "$minor" -ge 9 && "$minor" -le 11 ]]
}

find_python() {
  # Check all known locations including pyenv (no-admin fallback)
  for p in \
    "$HOME/.pyenv/versions/3.11.9/bin/python3.11" \
    "/opt/homebrew/opt/python@3.11/bin/python3.11" \
    "/usr/local/opt/python@3.11/bin/python3.11"; do
    [[ -x "$p" ]] && python_ok "$p" && echo "$p" && return 0
  done
  for py in python3.11 python3.10 python3.9; do
    python_ok "$py" && echo "$py" && return 0
  done
  return 1
}

install_python_macos() {
  echo "  Python $REQUIRED_MAJOR.$REQUIRED_MINOR+ not found. Attempting auto-install..."
  echo ""

  # Try Homebrew
  if command -v brew &>/dev/null; then
    echo "  Homebrew found — installing Python 3.11..."
    brew install python@3.11
    brew link --overwrite python@3.11 2>/dev/null || true
    return 0
  fi

  # Try to install Homebrew first
  echo "  Homebrew not found — installing Homebrew first..."
  echo "  (You may be prompted for your Mac password)"
  echo ""
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  # Add brew to PATH for Apple Silicon
  if [[ -f /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  fi

  if command -v brew &>/dev/null; then
    echo ""
    echo "  Installing Python 3.11 via Homebrew..."
    brew install python@3.11
    brew link --overwrite python@3.11 2>/dev/null || true
    return 0
  fi

  echo ""
  echo "  ╔══════════════════════════════════════════════════╗"
  echo "  ║  Auto-install failed.                            ║"
  echo "  ║  Please install Python 3.9+ manually:           ║"
  echo "  ║  https://www.python.org/downloads/              ║"
  echo "  ╚══════════════════════════════════════════════════╝"
  exit 1
}

PYTHON=$(find_python || true)
if [[ -z "$PYTHON" ]]; then
  install_python_macos
  PYTHON=$(find_python || true)
  if [[ -z "$PYTHON" ]]; then
    echo "ERROR: Python install succeeded but python3 still not found."
    echo "Close this window, open a new Terminal, and run setup.sh again."
    exit 1
  fi
fi

echo "  Python: $($PYTHON --version)"
echo ""

# ---------------------------------------------------------------------------
# 2. Create / update virtual environments
# ---------------------------------------------------------------------------

make_venv() {
  local name="$1" venv_path="$2" req="$3"
  echo "[$name]"
  if [ -f "$venv_path/bin/python3" ]; then
    echo "  venv already exists, updating..."
  else
    echo "  Creating venv..."
    "$PYTHON" -m venv "$venv_path"
  fi
  echo "  Installing dependencies..."
  "$venv_path/bin/pip" install --quiet --upgrade pip
  "$venv_path/bin/pip" install --quiet -r "$req"
  echo "  Done."
  echo ""
}

make_venv "Monitor"              "$BASE/venv"                            "$BASE/requirements.txt"
make_venv "Dashboard Factory"    "$BASE/01_Dashboard_Factory/venv"       "$BASE/01_Dashboard_Factory/requirements.txt"
make_venv "Dashboard Factory QA" "$BASE/02_Dashboard_Factory_QA/.venv"   "$BASE/02_Dashboard_Factory_QA/requirements.txt"
make_venv "Jira Tracker"         "$BASE/03_Jira_Tracker/venv"            "$BASE/03_Jira_Tracker/requirements.txt"

# Make all launch scripts executable
chmod +x "$BASE/Launch Monitor.command" 2>/dev/null || true
chmod +x "$BASE/01_Dashboard_Factory/start.sh" 2>/dev/null || true
chmod +x "$BASE/02_Dashboard_Factory_QA/start.sh" 2>/dev/null || true
chmod +x "$BASE/03_Jira_Tracker/start.sh" 2>/dev/null || true

echo "╔══════════════════════════════════════════════════╗"
echo "║   Setup complete!                                ║"
echo "║   Double-click 'Launch Monitor.command' to go.  ║"
echo "╚══════════════════════════════════════════════════╝"
