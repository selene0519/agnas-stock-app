@echo off
cd /d "%~dp0"
echo [INFO] Running MONE v75 complete Donhyun+QuantAI update...
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe run_v75_daily_update.py
) else (
  python run_v75_daily_update.py
)
echo.
echo Press any key to continue . . .
pause >nul
