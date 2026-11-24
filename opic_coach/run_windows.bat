@echo off
chcp 65001 >nul
REM 서버 실행: 이 창을 켜두는 동안 휴대폰에서 접속할 수 있어요.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo OPIc Coach 서버를 시작합니다. 종료하려면 Ctrl+C
python -m uvicorn server:app --host 0.0.0.0 --port 8000
pause
