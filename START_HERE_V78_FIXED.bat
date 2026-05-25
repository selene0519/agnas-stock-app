@echo off
setlocal
cd /d "%~dp0"
echo [INFO] Starting MONE v78 app with optional GitHub sync...
if exist "sync_latest_from_github.bat" call sync_latest_from_github.bat
call run_v78_daily_update.bat
call START_APP_NO_SYNC_V78_FIXED.bat
