@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v64 - Start
echo [INFO] Starting ARCFLOW/NEXORA v64...
if not exist app.py (echo [ERROR] app.py not found.& pause& exit /b 1)
if not exist .venv\Scripts\python.exe (
  echo [INFO] Creating .venv...
  py -m venv .venv
)
set PY=.venv\Scripts\python.exe
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
where git >nul 2>nul
if %errorlevel%==0 (
  if exist .git (
    echo [INFO] Pulling latest GitHub data/code...
    git pull --rebase --autostash
  ) else (
    echo [INFO] This is not a git repository. Skipping git pull.
  )
) else (
  echo [WARN] git not found. Skipping sync.
)
%PY% -m streamlit run app.py
pause
