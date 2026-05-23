@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA V65 - No Sync
if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
)
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py --runner v65
.\.venv\Scripts\python.exe -m streamlit run app.py
pause
