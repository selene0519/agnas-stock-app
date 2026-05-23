@echo off
setlocal
chcp 65001 >nul
title MONE V66 - Start
echo [INFO] Starting MONE V66 with optional GitHub sync...
if exist ".git" (
  where git >nul 2>nul
  if %errorlevel%==0 (
    echo [INFO] Syncing latest data/code from GitHub...
    git pull --rebase --autostash
  ) else (
    echo [WARN] git command was not found. Skipping sync.
  )
) else (
  echo [INFO] This folder is not a git repository. Skipping sync.
)
if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating .venv...
  py -m venv .venv
)
echo [INFO] Installing requirements if needed...
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
echo [INFO] Updating MONE v66 reports...
.\.venv\Scripts\python.exe app.py --runner v66
echo [START] Launching MONE...
.\.venv\Scripts\python.exe -m streamlit run app.py
pause
