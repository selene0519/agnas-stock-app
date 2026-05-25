@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo [INFO] MONE v91 one-click repair/update/start
if not exist logs mkdir logs
set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if "%PYEXE%"=="" set "PYEXE=python"
%PYEXE% -m pip install --upgrade pip
if exist requirements.txt (
  %PYEXE% -m pip install -r requirements.txt
) else (
  %PYEXE% -m pip install streamlit pandas numpy requests python-dotenv
)
call run_v91_daily_update.bat
call START_APP_NO_SYNC_V91_FIXED.bat
