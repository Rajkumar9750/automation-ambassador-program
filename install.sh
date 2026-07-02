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

# ── 1. Git ──────────────────────────────────────────────
if ! command -v git &>/dev/null; then
  echo "► Git not found — installing..."
  if command -v brew &>/dev/null; then
    brew install git
  else
    echo "  Installing Homebrew first..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    [[ -f /opt/homebrew/bin/brew ]] && eval "$(/opt/homebrew/bin/brew shellenv)"
    brew install git
  fi
else
  echo "✔ Git: $(git --version)"
fi

# ── 2. Clone or update ──────────────────────────────────
echo ""
if [ -d "$DEST/.git" ]; then
  echo "► Folder already exists — pulling latest changes..."
  cd "$DEST" && git pull
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
