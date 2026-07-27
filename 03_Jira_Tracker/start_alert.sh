#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -d "venv" ]; then
    source venv/bin/activate
fi

python jira_alert.py
