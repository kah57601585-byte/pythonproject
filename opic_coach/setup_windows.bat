@echo off
chcp 65001 >nul
REM 처음 한 번만 실행: 가상환경을 만들고 필요한 패키지를 설치합니다.
cd /d "%~dp0"
py -m venv .venv || python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo 설치 완료! .env 파일을 메모장으로 열어 ANTHROPIC_API_KEY 를 넣은 뒤 run_windows.bat 을 실행하세요.
pause
