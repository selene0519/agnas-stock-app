@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v60 - Start

echo ============================================================
echo  ARCFLOW/NEXORA v60 - Stable Start
echo ============================================================
echo [INFO] Current folder: %CD%

if not exist "app.py" (
  echo [ERROR] app.py not found. Put this BAT in the app folder.
  pause
  exit /b 1
)
if not exist "requirements.txt" (
  echo [ERROR] requirements.txt not found.
  pause
  exit /b 1
)

where git >nul 2>nul
if %errorlevel%==0 (
  if exist ".git" (
    echo [INFO] Pulling latest GitHub changes...
    git pull --rebase --autostash
    if errorlevel 1 echo [WARN] Git pull failed. Starting with local files.
  ) else (
    echo [INFO] This folder is not a git repository. Sync skipped.
  )
) else (
  echo [WARN] git command not found. Sync skipped.
)

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating .venv...
  py -m venv .venv
)
set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt

echo [INFO] Creating fast v60 reports...
"%PY%" run_v60_daily_update.py

echo [START] Launching Streamlit app...
"%PY%" -m streamlit run app.py
pause
