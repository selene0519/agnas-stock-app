@echo off
setlocal
chcp 65001 >nul
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run_v52_daily_update.py
) else (
  python run_v52_daily_update.py
)
pause
