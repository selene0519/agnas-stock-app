@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v45 - Start Without Sync

echo ============================================================
echo  ARCFLOW/NEXORA v45 - Start Without GitHub Sync
echo ============================================================
echo.

if not exist "app.py" (
  echo [ERROR] app.py was not found in this folder.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] .venv not found. Creating .venv...
  py -m venv .venv
)

set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
"%PY%" -m pip install streamlit

echo [START] Launching app without sync...
"%PY%" -m streamlit run app.py
pause
