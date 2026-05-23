@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v51 - Start Fast

echo ============================================================
echo  ARCFLOW/NEXORA v51 - Start Fast With Sync
echo ============================================================
echo [INFO] Current folder: %CD%
if not exist "app.py" (
  echo [ERROR] app.py was not found. Put this BAT in the app folder.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating .venv...
  py -m venv .venv
)
set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
where git >nul 2>nul
if %errorlevel%==0 (
  if exist ".git" (
    echo [INFO] Pulling latest data/code from GitHub...
    git pull --rebase --autostash
  ) else (
    echo [INFO] This folder is not a git repository. Skipping git pull.
  )
) else (
  echo [WARN] git command not found. Skipping git pull.
)
echo [INFO] Precomputing v51 light reports...
"%PY%" run_v51_daily_update.py
echo [START] Opening Streamlit...
"%PY%" -m streamlit run app.py
pause
