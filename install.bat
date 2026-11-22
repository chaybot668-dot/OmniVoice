@echo off
chcp 65001 >nul
cd /d %~dp0
echo === Cai dat OmniVoice Agent (Windows + NVIDIA) ===
rem Dung uv de tu tai Python 3.11 rieng (Python 3.14 tren may qua moi, PyTorch chua ho tro)
where uv >nul 2>nul || powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
if not exist .venv uv venv --python 3.11 .venv || goto :err
call .venv\Scripts\activate
uv pip install torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --extra-index-url https://download.pytorch.org/whl/cu128 --index-strategy unsafe-best-match || goto :err
uv pip install -e . imageio-ffmpeg || goto :err
python -c "import torch;print('GPU:',torch.cuda.is_available(),torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
if not exist agent\config.json copy agent\config.example.json agent\config.json >nul
where claude >nul 2>nul || powershell -ExecutionPolicy Bypass -c "irm https://claude.ai/install.ps1 | iex"
echo.
echo Xong. Mo cua so moi, go  claude  de dang nhap 1 lan. Roi chay start.bat
pause & exit /b 0
:err
echo Cai dat loi. Chup man hinh gui Claude. & pause & exit /b 1
