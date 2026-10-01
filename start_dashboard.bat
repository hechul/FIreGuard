@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [FireGuard] 가상환경이 없습니다. 최초 설치를 진행합니다.
  call setup_and_run.bat
  exit /b %errorlevel%
)

start "FireGuard Server" /min ".venv\Scripts\python.exe" "app.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:5000/"
exit /b 0
