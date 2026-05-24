@echo off
cd /d %~dp0
echo [INFO] Starting MONE v74 with GitHub sync...
call sync_latest_from_github.bat
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe run_v74_daily_update.py
  .venv\Scripts\python.exe -m streamlit run app.py
) else (
  python run_v74_daily_update.py
  python -m streamlit run app.py
)
pause
