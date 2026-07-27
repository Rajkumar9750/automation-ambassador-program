#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -f "venv/bin/python3" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

echo "Installing dependencies..."
venv/bin/pip install -r requirements.txt -q

# Load API key from .env if it exists
if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs)
fi

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║   Anthology Developer  →  localhost:8083 ║"
echo "╚══════════════════════════════════════════╝"
echo ""

venv/bin/uvicorn app:app --host 0.0.0.0 --port 8083 --reload
