@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set OFFICIAL_MODE=1
set DB_HOST=127.0.0.1
set DB_PORT=3306
set DB_NAME=voice_input
set DB_USER=voice_input
set DB_PASSWORD=voice_input_pass
cd /d d:\workspace_git\voice_input
python server.py >> server.log 2>&1
