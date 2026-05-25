@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo [INFO] Starting MONE v83 with optional GitHub sync...
if exist "sync_latest_from_github.bat" call sync_latest_from_github.bat
call run_v83_daily_update.bat
call START_APP_NO_SYNC_V83_FIXED.bat
