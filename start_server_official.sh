#!/bin/bash
export PYTHONUTF8=1
export OFFICIAL_MODE=1
export DB_HOST=127.0.0.1
export DB_PORT=3306
export DB_NAME=voice_input
export DB_USER=voice_input
export DB_PASSWORD=voice_input_pass
cd "$(dirname "$0")"
python3 server.py >> server.log 2>&1
