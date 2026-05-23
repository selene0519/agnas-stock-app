@echo off
setlocal
chcp 65001 >nul
title MONE V66 - Start No Sync
echo [INFO] Starting MONE V66 without GitHub sync...
if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating .venv...
  py -m venv .venv
)
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py --runner v66
.\.venv\Scripts\python.exe -m streamlit run app.py
pause
