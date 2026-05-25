@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist logs mkdir logs
set "LOG=logs\v92_daily_update.log"
echo [INFO] Running MONE v92 stable update... > "%LOG%"

set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if "%PYEXE%"=="" set "PYEXE=python"

echo [INFO] Python: %PYEXE% >> "%LOG%"
echo [INFO] This updater does NOT install packages. It only runs the update. >> "%LOG%"
%PYEXE% -u run_v92_daily_update.py >> "%LOG%" 2>&1
set "ERR=%ERRORLEVEL%"
type "%LOG%"
if not "%ERR%"=="0" (
  echo.
  echo [ERROR] MONE v92 update failed. See %LOG%
  exit /b %ERR%
)
echo [OK] MONE v92 daily update complete.
exit /b 0
