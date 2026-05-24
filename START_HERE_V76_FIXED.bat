@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo [INFO] Starting MONE v76...
echo [INFO] Updating reports first...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" ".\run_v76_daily_update.py"
  ".venv\Scripts\python.exe" -m streamlit run app.py
) else (
  python ".\run_v76_daily_update.py"
  python -m streamlit run app.py
)
pause
