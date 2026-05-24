@echo off
setlocal
chcp 65001 >nul
echo [INFO] Running MONE v70 news/finance/market update...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run_v70_daily_update.py
) else (
  py run_v70_daily_update.py
)
pause
