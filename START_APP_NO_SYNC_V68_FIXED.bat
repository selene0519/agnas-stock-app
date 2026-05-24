@echo off
setlocal
chcp 65001 >nul
title MONE v68 - Start No Sync

echo [INFO] Starting MONE v68 without Git sync...
if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
)
set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install -r requirements.txt
"%PY%" -m pip install python-dotenv
"%PY%" -m streamlit run app.py
pause
