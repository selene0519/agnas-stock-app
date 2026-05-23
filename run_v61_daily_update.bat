@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v61 - Update Reports
if not exist ".venv\Scripts\python.exe" (
  py -m venv .venv
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" run_v61_daily_update.py
pause
