@echo off
chcp 65001 >nul
REM 최신 버전으로 업데이트: GitHub에서 코드를 받고, 예전 서버를 끄고, 패키지를 설치합니다.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_windows.ps1"
if errorlevel 1 goto failed
echo.
echo 이제 run_windows.bat 을 실행하세요.
pause
exit /b 0
:failed
echo.
echo 위의 빨간 메시지를 확인해 주세요.
pause
exit /b 1
