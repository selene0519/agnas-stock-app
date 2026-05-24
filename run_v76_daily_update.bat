@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo [INFO] Running MONE v76 HOTFIX daily update...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" ".\run_v76_daily_update.py"
) else (
  python ".\run_v76_daily_update.py"
)
echo.
echo [CHECK] v76 report files:
dir ".\reports\v76_*" /b 2>nul
echo.
echo Press any key to continue . . .
pause >nul
