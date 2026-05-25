@echo off
setlocal
cd /d "%~dp0"
echo [INFO] Running MONE v82 daily update...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run_v82_daily_update.py
) else (
  python run_v82_daily_update.py
)
echo [OK] MONE v82 daily update complete.
pause
