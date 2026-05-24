@echo off
setlocal
chcp 65001 >nul
echo [INFO] Running MONE v69 news/finance/API update...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run_v69_daily_update.py
) else (
  py run_v69_daily_update.py
)
pause
