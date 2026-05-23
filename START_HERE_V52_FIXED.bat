@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v52 - Start

echo ============================================================
echo  ARCFLOW/NEXORA v52 - Start with GitHub Sync
echo ============================================================
echo [INFO] Current folder: %CD%

if not exist "app.py" (
  echo [ERROR] app.py was not found in this folder.
  pause
  exit /b 1
)
if not exist "requirements.txt" (
  echo [ERROR] requirements.txt was not found in this folder.
  pause
  exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (set "PYLAUNCH=py") else (set "PYLAUNCH=python")
if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating .venv...
  %PYLAUNCH% -m venv .venv
)
set "PY=.venv\Scripts\python.exe"

"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt

where git >nul 2>nul
if %errorlevel%==0 (
  if exist ".git" (
    echo [INFO] Pulling latest GitHub data/code...
    git pull --rebase --autostash
    if errorlevel 1 echo [WARN] git pull failed. Continuing with local files.
  ) else (
    echo [WARN] This folder is not a git repository. Skipping pull.
  )
) else (
  echo [WARN] git command was not found. Skipping GitHub sync.
)

echo [INFO] Running v52 light update...
"%PY%" run_v52_daily_update.py

echo [START] Launching Streamlit app...
"%PY%" -m streamlit run app.py
pause
