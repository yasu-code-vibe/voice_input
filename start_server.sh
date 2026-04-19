#!/bin/bash
export PYTHONUTF8=1
export DB_HOST=127.0.0.1
export DB_PORT=3306
export DB_NAME=voice_input
export DB_USER=voice_input
export DB_PASSWORD=voice_input_pass
# macOS では AirPlay が 5000 番を使用するため 5010 番を使用
export HTTP_PORT=5010
export HTTPS_PORT=5011
cd "$(dirname "$0")"
SCRIPT_DIR="$(dirname "$0")"
if [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
    "$SCRIPT_DIR/.venv/bin/python3" server.py >> server.log 2>&1
else
    python3 server.py >> server.log 2>&1
fi
