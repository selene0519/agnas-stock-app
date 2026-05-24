@echo off
cd /d %~dp0
echo [INFO] Starting MONE v73 with GitHub sync...
if exist sync_latest_from_github.bat call sync_latest_from_github.bat
call run_v73_daily_update.bat
call START_APP_NO_SYNC_V73_FIXED.bat
