#!/bin/bash
# Automation Ambassador Program – macOS Installer
# Run with: bash install.sh

REPO="https://github.com/Rajkumar9750/automation-ambassador-program.git"
DEST="$HOME/automation-ambassador-program"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   Automation Ambassador Program – Installer      ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Helper: find python3.11 in known locations ───────────
_find_py311() {
  for p in \
    "$HOME/.pyenv/versions/3.11.9/bin/python3.11" \
    "/opt/homebrew/opt/python@3.11/bin/python3.11" \
    "/usr/local/opt/python@3.11/bin/python3.11" \
    "$(command -v python3.11 2>/dev/null)"; do
    [[ -x "$p" ]] && echo "$p" && return 0
  done
  return 1
}

# ── 1. Git ───────────────────────────────────────────────
if ! command -v git &>/dev/null; then
  echo "► Git not found — trying Xcode Command Line Tools..."
  xcode-select --install 2>/dev/null || true
  sleep 5
fi
command -v git &>/dev/null && echo "✔ Git: $(git --version)" || {
  echo "✖ Git still not found. Please install Xcode Command Line Tools and re-run."
  exit 1
}

# ── 2. Python 3.11 ───────────────────────────────────────
PYTHON311=$(_find_py311 || true)

if [[ -z "$PYTHON311" ]]; then
  # Try Homebrew first (admin users)
  if command -v brew &>/dev/null || {
       /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" 2>/dev/null
       [[ -f /opt/homebrew/bin/brew ]] && eval "$(/opt/homebrew/bin/brew shellenv)"
       [[ -f /usr/local/bin/brew ]]    && eval "$(/usr/local/bin/brew shellenv)"
       command -v brew &>/dev/null
     }; then
    eval "$(brew shellenv 2>/dev/null)" || true
    echo "► Installing Python 3.11 via Homebrew..."
    brew install python@3.11 2>/dev/null || true
    brew link --overwrite python@3.11 2>/dev/null || true
    export PATH="/opt/homebrew/opt/python@3.11/bin:/usr/local/opt/python@3.11/bin:$PATH"
    PYTHON311=$(_find_py311 || true)
  fi
fi

if [[ -z "$PYTHON311" ]]; then
  # No admin rights — fall back to pyenv (installs in ~/.pyenv, no sudo needed)
  echo "► Homebrew unavailable (no admin rights) — installing Python 3.11 via pyenv..."
  export PYENV_ROOT="$HOME/.pyenv"
  export PATH="$PYENV_ROOT/bin:$PATH"
  if ! command -v pyenv &>/dev/null; then
    curl -fsSL https://pyenv.run | bash
    export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init --path 2>/dev/null)" || true
    eval "$(pyenv init - 2>/dev/null)"      || true
  fi
  eval "$(pyenv init --path 2>/dev/null)" || true
  eval "$(pyenv init - 2>/dev/null)"      || true
  pyenv install -s 3.11.9
  pyenv global 3.11.9
  PYTHON311=$(_find_py311 || true)
fi

if [[ -z "$PYTHON311" ]]; then
  echo "✖ Could not install Python 3.11. Please contact your IT administrator."
  exit 1
fi

echo "✔ Python: $($PYTHON311 --version)"
export PATH="$(dirname "$PYTHON311"):$PATH"

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
