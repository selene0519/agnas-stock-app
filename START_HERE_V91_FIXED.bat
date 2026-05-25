@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if exist sync_latest_from_github.bat (
  call sync_latest_from_github.bat
)
call run_v91_daily_update.bat
call START_APP_NO_SYNC_V91_FIXED.bat
