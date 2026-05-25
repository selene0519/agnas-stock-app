@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist logs mkdir logs
set "LOG=logs\v92_app_start.log"
echo [INFO] Starting MONE app without GitHub sync... > "%LOG%"

set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if "%PYEXE%"=="" set "PYEXE=python"

echo [INFO] Python: %PYEXE% >> "%LOG%"
%PYEXE% -c "import streamlit, pandas" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] streamlit/pandas missing. Run INSTALL_REQUIREMENTS_ONCE_V92.bat once. >> "%LOG%"
  type "%LOG%"
  exit /b 1
)

echo [INFO] Launching Streamlit... >> "%LOG%"
type "%LOG%"
%PYEXE% -m streamlit run app.py
