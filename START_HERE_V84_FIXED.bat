@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo [INFO] Starting MONE v84 with update first...
call run_v84_daily_update.bat
call START_APP_NO_SYNC_V84_FIXED.bat
