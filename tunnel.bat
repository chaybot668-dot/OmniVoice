@echo off
chcp 65001 >nul
cd /d %~dp0
rem Mo duong ham de Claude tren cloud goi OmniVoice tren may nay (chi doc giong, co ma bi mat)
where ngrok >nul 2>nul || winget install -e --id Ngrok.Ngrok --accept-source-agreements --accept-package-agreements
set "PATH=%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
if not exist agent\ngrok_domain.txt (
  echo Dan ten mien tinh ngrok cua Sep ^(vd: abc-xyz.ngrok-free.app^):
  set /p D=
  call echo %%D%%> agent\ngrok_domain.txt
  echo Dan authtoken ngrok ^(dashboard.ngrok.com/get-started/your-authtoken^):
  set /p T=
  call ngrok config add-authtoken %%T%%
)
set /p DOMAIN=<agent\ngrok_domain.txt
.venv\Scripts\python.exe -c "import json,secrets;p='agent/config.json';c=json.load(open(p,encoding='utf-8'));c.setdefault('remote_token',secrets.token_urlsafe(24));json.dump(c,open(p,'w',encoding='utf-8'),indent=2,ensure_ascii=False);print('MA BI MAT (dan vao o Claude hoi):',c['remote_token'])"
echo Duong ham: https://%DOMAIN%  ^(de cua so nay mo^)
ngrok http --url=%DOMAIN% 8765
pause
