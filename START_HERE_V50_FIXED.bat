@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v50 - Start With Sync

echo ============================================================
echo  ARCFLOW/NEXORA v50 - Start With GitHub Sync
echo ============================================================
echo [INFO] Current folder: %CD%
echo.

if not exist "app.py" (
  echo [ERROR] app.py was not found. Put this file in the app folder.
  pause
  exit /b 1
)
if not exist "requirements.txt" (
  echo [ERROR] requirements.txt was not found. This is not the correct app folder.
  pause
  exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (set "PYLAUNCH=py") else (set "PYLAUNCH=python")

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

echo [INFO] Installing/checking dependencies...
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] requirements install failed.
  pause
  exit /b 1
)

echo [INFO] Syncing latest data/code from GitHub if available...
where git >nul 2>nul
if %errorlevel%==0 (
  if exist ".git" (
    git pull --rebase --autostash
    if errorlevel 1 echo [WARN] git pull failed. Starting app with local files.
  ) else (
    echo [INFO] This folder is not a git repository. Skipping sync.
  )
) else (
  echo [WARN] git command was not found. Skipping sync.
)

echo [INFO] Running v50 update once...
"%PY%" run_v50_daily_update.py

echo [START] Launching Streamlit app...
"%PY%" -m streamlit run app.py
pause
