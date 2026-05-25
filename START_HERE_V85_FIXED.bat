@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo [INFO] MONE v85 start with optional Git sync
if exist sync_latest_from_github.bat (
  call sync_latest_from_github.bat
)
call run_v85_daily_update.bat
call START_APP_NO_SYNC_V85_FIXED.bat
