@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/4] Python 확인...
where py >nul 2>&1
if %errorlevel%==0 (
  set PY=py
) else (
  set PY=python
)

%PY% --version || goto :python_error

echo [2/4] 가상환경 생성...
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
if errorlevel 1 goto :fail

echo [3/4] 패키지 설치...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [4/4] FireGuard 실행...
start "FireGuard Server" /min ".venv\Scripts\python.exe" "app.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:5000/"
exit /b 0

:python_error
echo Python을 찾을 수 없습니다. Python 3.10~3.13 설치 후 다시 실행하세요.
pause
exit /b 1

:fail
echo 설치 중 오류가 발생했습니다.
pause
exit /b 1
