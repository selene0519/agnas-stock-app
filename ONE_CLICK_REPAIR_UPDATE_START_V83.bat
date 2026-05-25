@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo [INFO] MONE v83 repair/update/start
if not exist .venv (
  echo [INFO] Creating .venv...
  python -m venv .venv
)
if exist ".venv\Scripts\python.exe" (
  set "PYEXE=.venv\Scripts\python.exe"
) else (
  set "PYEXE=python"
)
%PYEXE% -m pip install --upgrade pip
if exist requirements.txt (
  %PYEXE% -m pip install -r requirements.txt
) else (
  %PYEXE% -m pip install streamlit pandas numpy requests python-dotenv
)
call run_v83_daily_update.bat
call START_APP_NO_SYNC_V83_FIXED.bat
