@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist logs mkdir logs
set "LOG=logs\v91_app_start.log"
echo [INFO] Starting MONE v91 app without GitHub sync... > "%LOG%"

set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if "%PYEXE%"=="" set "PYEXE=python"

echo [INFO] Python: %PYEXE% >> "%LOG%"
%PYEXE% -c "import streamlit, pandas" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [WARN] Missing required packages. Installing... >> "%LOG%"
  if exist requirements.txt (
    %PYEXE% -m pip install -r requirements.txt >> "%LOG%" 2>&1
  ) else (
    %PYEXE% -m pip install streamlit pandas numpy requests python-dotenv >> "%LOG%" 2>&1
  )
)

echo [INFO] Launching Streamlit... >> "%LOG%"
%PYEXE% -m streamlit run app.py
