@echo off
setlocal
chcp 65001 >nul
title MONE V67 - Start
echo [INFO] Starting MONE V67...
echo [INFO] GitHub sync skipped.
if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating .venv...
  py -m venv .venv
)
echo [INFO] Installing requirements if needed...
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
echo [INFO] Updating MONE v67 reports...
.\.venv\Scripts\python.exe app.py --runner v67
echo [START] Launching MONE...
.\.venv\Scripts\python.exe -m streamlit run app.py
pause
