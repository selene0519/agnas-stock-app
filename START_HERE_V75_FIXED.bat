@echo off
cd /d "%~dp0"
echo [INFO] Starting MONE v75 app with GitHub sync...
call sync_latest_from_github.bat
call run_v75_daily_update.bat
call START_APP_NO_SYNC_V75_FIXED.bat
