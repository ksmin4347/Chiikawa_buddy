@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto install
where py >nul 2>nul
if errorlevel 1 goto python_fallback
py -3 -c "import sys; assert sys.version_info >= (3, 12)" >nul 2>nul
if errorlevel 1 goto missing_python
py -3 -m venv .venv
if errorlevel 1 goto failed
goto install
:python_fallback
where python >nul 2>nul
if errorlevel 1 goto missing_python
python -c "import sys; assert sys.version_info >= (3, 12)" >nul 2>nul
if errorlevel 1 goto missing_python
python -m venv .venv
if errorlevel 1 goto failed
:install
".venv\Scripts\python.exe" -c "import sys; assert sys.version_info >= (3, 12)"
if errorlevel 1 goto missing_python
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt
if errorlevel 1 goto failed
echo.
echo 준비가 끝났습니다. run_windows.bat을 더블클릭해 주세요.
pause
exit /b 0
:missing_python
echo Python 3.12 이상을 먼저 설치해 주세요. 개발 환경 준비에만 필요합니다.
echo Python이 없는 PC에서는 배포 폴더의 DesktopBuddy.exe를 사용하세요.
echo 설치 안내: https://www.python.org/downloads/windows/
goto failed
:failed
echo.
echo 준비하지 못했습니다. 위 오류 내용을 확인해 주세요.
pause
exit /b 1
