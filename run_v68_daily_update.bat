@echo off
setlocal
chcp 65001 >nul
echo [INFO] Running MONE v68 news/finance/market update...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run_v68_daily_update.py
) else (
  py run_v68_daily_update.py
)
pause
