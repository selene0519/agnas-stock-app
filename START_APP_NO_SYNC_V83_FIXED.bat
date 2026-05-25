@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist logs mkdir logs
set "LOG=logs\v83_start_app.log"
echo [INFO] Starting MONE v83 app... > "%LOG%"
set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if "%PYEXE%"=="" set "PYEXE=python"
%PYEXE% -m streamlit run app.py >> "%LOG%" 2>&1
if errorlevel 1 (
  type "%LOG%"
  echo.
  echo [ERROR] App start failed. See %LOG%
  pause
  exit /b 1
)
