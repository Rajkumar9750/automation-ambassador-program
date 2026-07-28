#!/usr/bin/env bash
cd "$(dirname "$0")"
echo "Git Manager → http://localhost:9100"
python3 -m uvicorn git_manager:app --host 127.0.0.1 --port 9100 --reload
