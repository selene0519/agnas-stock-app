@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v50 - Start Without Sync
if not exist ".venv\Scripts\python.exe" py -m venv .venv
set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
"%PY%" run_v50_daily_update.py
"%PY%" -m streamlit run app.py
pause
