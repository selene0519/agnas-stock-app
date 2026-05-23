@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v61 - Start No Sync

echo ============================================================
echo  ARCFLOW/NEXORA v61 - Start No Sync
echo ============================================================
echo [INFO] Current folder: %CD%

if not exist "app.py" (
  echo [ERROR] app.py not found. Put this BAT in the app folder.
  pause
  exit /b 1
)
if not exist "requirements.txt" (
  echo [ERROR] requirements.txt not found.
  pause
  exit /b 1
)

echo [INFO] GitHub sync skipped by no-sync launcher.

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating .venv...
  py -m venv .venv
)
set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt

echo [INFO] Creating fast v61 reports...
"%PY%" run_v61_daily_update.py

echo [START] Launching Streamlit app...
"%PY%" -m streamlit run app.py
pause
