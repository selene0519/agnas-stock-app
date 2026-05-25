@echo off
setlocal
cd /d "%~dp0"
echo [INFO] Running MONE v80 daily update...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run_v80_daily_update.py
) else (
  python run_v80_daily_update.py
)
if %ERRORLEVEL% NEQ 0 (
  echo [ERROR] MONE v80 daily update failed.
  pause
  exit /b %ERRORLEVEL%
)
echo [OK] MONE v80 daily update complete.
pause
