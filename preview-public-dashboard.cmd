@echo off
setlocal
cd /d "%~dp0"

echo Building the public bundle...
call npm --prefix public-ui run build || goto :failed

echo Publishing the current source into the public store...
powershell -NoProfile -ExecutionPolicy Bypass -File ".\ops\publish-public.ps1" || goto :failed

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8380/'"
echo.
echo Preview running on http://127.0.0.1:8380/ -- this machine only, nothing is exposed.
echo Close this window to stop it.
python -m app.public.server --public-db data/boustrategy.public.db --port 8380

echo.
echo Preview stopped. Press any key to close.
pause >nul
exit /b 0

:failed
echo.
echo Preview could not start. See the output above.
pause >nul
exit /b 1
