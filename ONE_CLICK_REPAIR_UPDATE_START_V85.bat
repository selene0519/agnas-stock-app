@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo [INFO] MONE v85 one-click repair/update/start
set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if "%PYEXE%"=="" set "PYEXE=python"
%PYEXE% -m pip install --upgrade pip
if exist requirements.txt (
  %PYEXE% -m pip install -r requirements.txt
) else (
  %PYEXE% -m pip install streamlit pandas numpy requests python-dotenv
)
call run_v85_daily_update.bat
call START_APP_NO_SYNC_V85_FIXED.bat
