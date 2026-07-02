#!/bin/bash
set -e
cd "$(dirname "$0")"

# Create venv if it doesn't exist
if [ ! -f "venv/bin/python3" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

venv/bin/pip install -r requirements.txt -q

# Set your Anthropic API key here
export ANTHROPIC_API_KEY="your-api-key-here"

echo "Starting Dashboard Factory on http://localhost:8080"
venv/bin/uvicorn app:app --host 0.0.0.0 --port 8080 --reload
