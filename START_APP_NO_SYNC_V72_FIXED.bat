@echo off
setlocal
chcp 65001 >nul
title MONE v72 - Start without sync

if not exist "app.py" (
  echo [ERROR] app.py was not found. Run this in the app folder.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating .venv...
  py -m venv .venv
)

set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install -r requirements.txt
"%PY%" -m pip install python-dotenv

echo [INFO] Starting MONE v72 app without GitHub sync...
"%PY%" -m streamlit run app.py
pause
