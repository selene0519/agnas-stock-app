@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist logs mkdir logs
set "LOG=logs\v84_daily_update.log"
echo [INFO] Running MONE v84 daily update... > "%LOG%"

set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if "%PYEXE%"=="" set "PYEXE=python"

echo [INFO] Python: %PYEXE% >> "%LOG%"
%PYEXE% -c "import pandas, streamlit" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [WARN] Missing required packages. Installing from requirements.txt... >> "%LOG%"
  if exist requirements.txt (
    %PYEXE% -m pip install -r requirements.txt >> "%LOG%" 2>&1
  ) else (
    %PYEXE% -m pip install streamlit pandas numpy requests python-dotenv >> "%LOG%" 2>&1
  )
)

%PYEXE% run_v84_daily_update.py >> "%LOG%" 2>&1
set "ERR=%ERRORLEVEL%"
type "%LOG%"
if not "%ERR%"=="0" (
  echo.
  echo [ERROR] MONE v84 update failed. See %LOG%
  pause
  exit /b %ERR%
)
echo [OK] MONE v84 daily update complete.
pause
