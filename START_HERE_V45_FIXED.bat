@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v45 - Repair, Sync and Start

echo ============================================================
echo  ARCFLOW/NEXORA v45 - Repair, Sync and Start
echo ============================================================
echo.
echo [INFO] Current folder: %CD%
echo.

if not exist "app.py" (
  echo [ERROR] app.py was not found in this folder.
  echo [HELP] Move this BAT file into the folder that contains app.py and requirements.txt.
  pause
  exit /b 1
)

if not exist "requirements.txt" (
  echo [ERROR] requirements.txt was not found in this folder.
  pause
  exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYLAUNCH=py"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PYLAUNCH=python"
  ) else (
    echo [ERROR] Python was not found.
    pause
    exit /b 1
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating .venv...
  %PYLAUNCH% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create .venv.
    pause
    exit /b 1
  )
)

set "PY=.venv\Scripts\python.exe"

echo [INFO] Installing/updating requirements...
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] requirements installation failed.
  pause
  exit /b 1
)

echo [INFO] Checking Streamlit...
"%PY%" -m streamlit --version
if errorlevel 1 (
  "%PY%" -m pip install streamlit
)

echo [INFO] Syncing from GitHub if possible...
where git >nul 2>nul
if %errorlevel%==0 (
  if exist ".git" (
    git pull --rebase --autostash
    if errorlevel 1 echo [WARN] git pull failed. App will still start with local files.
  ) else (
    echo [INFO] This folder is not a git repository. Skipping sync.
  )
) else (
  echo [WARN] git command was not found. Skipping sync.
)

echo [INFO] Running v45 daily update once...
"%PY%" run_v45_daily_update.py
if errorlevel 1 echo [WARN] v45 daily update failed. App will still start.

echo.
echo [START] Launching Streamlit app...
"%PY%" -m streamlit run app.py

echo.
echo [INFO] App process ended.
pause
