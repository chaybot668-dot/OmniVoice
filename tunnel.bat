@echo off
chcp 65001 >nul
cd /d %~dp0
rem Mo duong ham de Claude tren cloud goi OmniVoice tren may nay (chi doc giong, co ma bi mat)
set "NG=%~dp0agent\bin\ngrok.exe"
if not exist "%NG%" (
  echo Dang tai ngrok...
  if not exist agent\bin mkdir agent\bin
  powershell -NoProfile -c "Invoke-WebRequest https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip -OutFile agent\bin\ngrok.zip; Expand-Archive -Force agent\bin\ngrok.zip agent\bin; Remove-Item agent\bin\ngrok.zip"
)
if not exist "%NG%" (echo Tai ngrok loi. Chup man hinh gui Claude. & pause & exit /b 1)
if not exist agent\ngrok_domain.txt (
  set /p D=Dan ten mien ngrok ^(vd abc.ngrok-free.dev^): 
  call echo %%D%%> agent\ngrok_domain.txt
)
if not exist agent\ngrok_ok.txt (
  set /p T=Dan authtoken ngrok ^(dashboard.ngrok.com/get-started/your-authtoken^): 
  call "%NG%" config add-authtoken %%T%% && echo ok> agent\ngrok_ok.txt
)
set /p DOMAIN=<agent\ngrok_domain.txt
.venv\Scripts\python.exe -c "import json,secrets;p='agent/config.json';c=json.load(open(p,encoding='utf-8'));c.setdefault('remote_token',secrets.token_urlsafe(24));json.dump(c,open(p,'w',encoding='utf-8'),indent=2,ensure_ascii=False);print('MA BI MAT (dan vao o Claude hoi):',c['remote_token'])"
echo Duong ham: https://%DOMAIN%  ^(de cua so nay mo^)
"%NG%" http --url=%DOMAIN% 8765
pause
