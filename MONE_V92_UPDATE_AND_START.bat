@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo [INFO] MONE v92 stable update and start
call run_v92_daily_update.bat
if errorlevel 1 (
  echo [WARN] Update failed. Starting app with last normal reports instead.
)
call START_APP_NO_SYNC_V92_FIXED.bat
