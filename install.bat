@echo off
chcp 65001 >nul
cd /d %~dp0
echo === Cai dat OmniVoice Agent (Windows + NVIDIA) ===
where python >nul 2>nul || (echo Chua co Python 3.10-3.12. Tai tai python.org, tick "Add to PATH". & pause & exit /b 1)
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
python -m pip install -U pip
pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128 || goto :err
pip install -e . imageio-ffmpeg || goto :err
python -c "import torch;print('GPU:',torch.cuda.is_available(),torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
if not exist agent\config.json copy agent\config.example.json agent\config.json >nul
where claude >nul 2>nul || echo [!] Chua co Claude Code: cai Node.js roi chay  npm i -g @anthropic-ai/claude-code  va dang nhap bang lenh  claude
echo.
echo Xong. Sua agent\config.json (duong dan manstory), bo giong mau vao voices\default.wav + default.txt
echo Chay app: start.bat
pause & exit /b 0
:err
echo Cai dat loi. Chup man hinh gui Claude. & pause & exit /b 1
