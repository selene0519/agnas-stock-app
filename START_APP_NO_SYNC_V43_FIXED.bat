@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v43 - Start Without Sync

echo ============================================================
echo  ARCFLOW/NEXORA v43 - Start Without GitHub Sync
echo ============================================================
echo.
echo [INFO] Current folder: %CD%
echo.

if not exist "app.py" (
  echo [ERROR] app.py was not found in this folder.
  echo [HELP] Put this BAT file in the same folder as app.py.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] .venv not found. Creating .venv...
  py -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create .venv. Try installing Python.
    pause
    exit /b 1
  )
)

set "PY=.venv\Scripts\python.exe"

echo [INFO] Installing Streamlit if missing...
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
"%PY%" -m pip install streamlit

echo.
echo [START] Launching app without sync...
"%PY%" -m streamlit run app.py

echo.
pause
