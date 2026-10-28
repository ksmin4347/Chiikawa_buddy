@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo 먼저 setup_windows.bat을 실행해 주세요.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pytest -q
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m PyInstaller --noconfirm DesktopBuddy.spec
if errorlevel 1 goto failed
echo.
echo 생성 완료: dist\DesktopBuddy\DesktopBuddy.exe
echo DesktopBuddy 폴더 전체를 함께 복사하세요. EXE만 옮기면 실행되지 않습니다.
pause
exit /b 0
:failed
echo 빌드하지 못했습니다. 위 오류 내용을 확인해 주세요.
pause
exit /b 1
