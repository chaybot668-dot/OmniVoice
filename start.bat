@echo off
chcp 65001 >nul
cd /d %~dp0
call .venv\Scripts\activate
set PYTHONUTF8=1
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
start "" http://127.0.0.1:8765
python agent\tts_server.py
pause
