@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo 먼저 setup_windows.bat을 실행해 주세요.
    pause
    exit /b 1
)
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
".venv\Scripts\python.exe" -m desktop_buddy %*
if errorlevel 1 (
    echo.
    echo 실행 중 오류가 생겼습니다. 위 내용과 데이터 폴더의 logs\app.log를 확인하세요.
    pause
    exit /b 1
)
exit /b 0
