@echo off
setlocal
chcp 65001 >nul
echo [INFO] Running MONE v71 guard/quant UI update...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run_v71_daily_update.py
) else (
  py run_v71_daily_update.py
)
pause
