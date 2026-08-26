@echo off
setlocal
cd /d "%~dp0"

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8378/operate'"
python -m app.dashboard.server

echo.
echo BouStrategy stopped. Press any key to close.
pause >nul
