@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File setup_env.ps1
echo.
echo Done. Start RouteDL from the desktop shortcut or RouteDL.bat
pause
