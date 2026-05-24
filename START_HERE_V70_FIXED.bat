@echo off
setlocal
chcp 65001 >nul
title MONE v70 - Start

echo ============================================================
echo  MONE v70 - Start with optional Git sync
echo ============================================================
echo [INFO] Current folder: %CD%

if not exist "app.py" (
  echo [ERROR] app.py was not found. Run this in the app folder.
  pause
  exit /b 1
)

where git >nul 2>nul
if %errorlevel%==0 (
  if exist ".git" (
    echo [INFO] Pulling latest GitHub changes...
    git pull --rebase --autostash
  ) else (
    echo [INFO] This is not a git repository. Skipping git pull.
  )
) else (
  echo [WARN] git was not found. Skipping sync.
)

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating .venv...
  py -m venv .venv
)

set "PY=.venv\Scripts\python.exe"
echo [INFO] Installing/updating requirements...
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
"%PY%" -m pip install python-dotenv

echo [INFO] Starting MONE app...
"%PY%" -m streamlit run app.py
pause
