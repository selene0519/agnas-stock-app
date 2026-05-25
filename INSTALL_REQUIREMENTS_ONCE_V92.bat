@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not exist logs mkdir logs
set "LOG=logs\v92_install_once.log"
set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if "%PYEXE%"=="" set "PYEXE=python"
echo [INFO] Installing requirements once with %PYEXE% > "%LOG%"
if exist requirements.txt (
  %PYEXE% -m pip install --disable-pip-version-check --no-input -r requirements.txt >> "%LOG%" 2>&1
) else (
  %PYEXE% -m pip install --disable-pip-version-check --no-input streamlit pandas numpy requests python-dotenv >> "%LOG%" 2>&1
)
type "%LOG%"
echo [OK] Install step finished. You usually do not need to run this again.
