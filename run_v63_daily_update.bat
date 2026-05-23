@echo off
setlocal
chcp 65001 >nul
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
%PY% run_v63_daily_update.py
pause
