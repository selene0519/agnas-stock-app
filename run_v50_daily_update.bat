@echo off
setlocal
chcp 65001 >nul
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)
"%PY%" run_v50_daily_update.py
pause
