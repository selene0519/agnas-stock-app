@echo off
setlocal
cd /d "%~dp0"
echo [INFO] Starting MONE v79 app with optional GitHub sync...
if exist "sync_latest_from_github.bat" call sync_latest_from_github.bat
call run_v79_daily_update.bat
call START_APP_NO_SYNC_V79_FIXED.bat
