@echo off
setlocal
chcp 65001 >nul
echo [INFO] Running MONE v72 visible guard/quant update...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run_v72_daily_update.py
) else (
  py run_v72_daily_update.py
)
pause
