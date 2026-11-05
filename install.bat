@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -c "import sys" >nul 2>&1
if errorlevel 1 (
  echo Python not found. Installing Python 3.12 via winget...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo Close this window and run install.bat again.
  pause
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File setup_env.ps1
echo.
echo Done. Start RouteDL.bat
pause
