#!/bin/bash
# Automation Ambassador Program – macOS Installer
# Run with: bash install.sh

set -e

REPO="https://github.com/Rajkumar9750/automation-ambassador-program.git"
DEST="$HOME/automation-ambassador-program"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   Automation Ambassador Program – Installer      ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── 1. Homebrew ─────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  echo "► Homebrew not found — installing..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  [[ -f /opt/homebrew/bin/brew ]] && eval "$(/opt/homebrew/bin/brew shellenv)"
  [[ -f /usr/local/bin/brew ]]    && eval "$(/usr/local/bin/brew shellenv)"
fi
eval "$(brew shellenv 2>/dev/null)" || true

# ── 2. Git ──────────────────────────────────────────────
if ! command -v git &>/dev/null; then
  echo "► Git not found — installing via Homebrew..."
  brew install git
else
  echo "✔ Git: $(git --version)"
fi

# ── 3. Python 3.11 ──────────────────────────────────────
# Force python@3.11 — newer versions (3.12+) break pandas and other dependencies
if ! brew list python@3.11 &>/dev/null; then
  echo "► Installing Python 3.11 via Homebrew..."
  brew install python@3.11
fi
brew link --overwrite python@3.11 2>/dev/null || true
# Prepend python@3.11 to PATH so it takes priority over any system Python
export PATH="/opt/homebrew/opt/python@3.11/bin:/usr/local/opt/python@3.11/bin:$PATH"
echo "✔ Python: $(python3.11 --version 2>/dev/null || python3 --version)"

# ── 2. Clone or update ──────────────────────────────────
echo ""
if [ -d "$DEST/.git" ]; then
  echo "► Folder already exists — pulling latest changes..."
  cd "$DEST" && git pull
elif [ -d "$DEST" ]; then
  echo "► Incomplete folder found — removing and cloning fresh..."
  rm -rf "$DEST"
  git clone "$REPO" "$DEST"
  cd "$DEST"
else
  echo "► Cloning repository to $DEST..."
  git clone "$REPO" "$DEST"
  cd "$DEST"
fi

# ── 3. Setup ────────────────────────────────────────────
echo ""
echo "► Running setup..."
bash setup.sh

# ── 4. Launch ───────────────────────────────────────────
echo ""
echo "► Launching Monitor..."
bash "Launch Monitor.command"
