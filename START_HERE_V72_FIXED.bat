@echo off
setlocal
chcp 65001 >nul
title MONE v72 - Start with GitHub sync

echo [INFO] Starting MONE v72 app with GitHub sync...
if exist "sync_latest_from_github.bat" call sync_latest_from_github.bat
if exist "run_v72_daily_update.bat" call run_v72_daily_update.bat
call START_APP_NO_SYNC_V72_FIXED.bat
