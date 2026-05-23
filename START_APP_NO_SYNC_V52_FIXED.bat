@echo off
setlocal
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" py -m venv .venv
".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" run_v52_daily_update.py
".venv\Scripts\python.exe" -m streamlit run app.py
pause
