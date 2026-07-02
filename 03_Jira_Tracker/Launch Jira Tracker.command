#!/bin/bash
cd "$(dirname "$0")"

# Install rumps if missing
venv/bin/pip install rumps -q 2>/dev/null

echo "Starting Jira Tracker menu bar app..."
exec venv/bin/python3 launcher.py
