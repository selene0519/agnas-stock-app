@echo off
setlocal
cd /d "%~dp0"
call run_v77_daily_update.bat
call START_APP_NO_SYNC_V77_FIXED.bat
