@echo off
cd /d %~dp0
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe run_v73_daily_update.py
) else (
  python run_v73_daily_update.py
)
pause
