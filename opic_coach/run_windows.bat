@echo off
chcp 65001 >nul
REM 서버 실행: 이 창을 켜두는 동안 휴대폰과 PC에서 접속할 수 있어요.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo 먼저 setup_windows.bat 을 실행해 주세요.
  pause
  exit /b 1
)
REM 예전 서버가 8000번 포트를 잡고 있으면 새 코드가 반영되지 않으니 먼저 종료합니다.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
  echo 이미 실행 중인 예전 서버를 종료합니다: PID %%p
  taskkill /F /PID %%p >nul 2>&1
)
echo OPIc Coach 서버를 시작합니다. 종료하려면 이 창을 닫거나 Ctrl+C
echo PC 브라우저: http://localhost:8000
.venv\Scripts\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8000
pause
