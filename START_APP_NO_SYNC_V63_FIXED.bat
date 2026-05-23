@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v63 - Start No Sync

echo ============================================================
echo  ARCFLOW/NEXORA v63 - Start Without GitHub Sync
echo ============================================================
echo [INFO] Current folder: %CD%

if not exist "app.py" (
  echo [ERROR] app.py not found. Put this BAT in the app folder.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating .venv...
  py -m venv .venv
)
set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
"%PY%" run_v63_daily_update.py
"%PY%" -m streamlit run app.py
pause
