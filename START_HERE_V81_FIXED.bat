@echo off
setlocal
cd /d "%~dp0"
echo [INFO] Starting MONE v81 app with optional GitHub sync...
if exist "sync_latest_from_github.bat" call sync_latest_from_github.bat
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m streamlit run app.py
) else (
  python -m streamlit run app.py
)
pause
