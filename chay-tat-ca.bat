@echo off
cd /d %~dp0
rem Mo ca OmniVoice va duong ham ngrok, moi cai mot cua so
start "ngrok - DUNG TAT" cmd /k tunnel.bat
start "OmniVoice - DUNG TAT" cmd /k start.bat
