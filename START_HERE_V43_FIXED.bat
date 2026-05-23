@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v43 - Repair and Start

echo ============================================================
echo  ARCFLOW/NEXORA v43 - Repair and Start
echo ============================================================
echo.
echo [INFO] This file must be in the same folder as app.py
echo [INFO] Current folder: %CD%
echo.

if not exist "app.py" (
  echo [ERROR] app.py was not found in this folder.
  echo [HELP] Move this BAT file into the folder that contains app.py and requirements.txt.
  echo.
  pause
  exit /b 1
)

if not exist "requirements.txt" (
  echo [ERROR] requirements.txt was not found in this folder.
  echo [HELP] This is not the correct app folder.
  echo.
  pause
  exit /b 1
)

echo [STEP 1] Checking Python...
where py >nul 2>nul
if %errorlevel%==0 (
  set "PYLAUNCH=py"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PYLAUNCH=python"
  ) else (
    echo [ERROR] Python was not found.
    echo [HELP] Install Python, then run this file again.
    pause
    exit /b 1
  )
)

echo [STEP 2] Recreating virtual environment if needed...
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

echo [STEP 3] Upgrading pip...
"%PY%" -m pip install --upgrade pip
if errorlevel 1 (
  echo [WARN] pip upgrade failed. Continuing...
)

echo [STEP 4] Installing requirements...
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] requirements installation failed.
  echo [HELP] Copy the red error lines and send them to ChatGPT.
  pause
  exit /b 1
)

echo [STEP 5] Checking Streamlit...
"%PY%" -m streamlit --version
if errorlevel 1 (
  echo [INFO] Streamlit missing. Installing streamlit...
  "%PY%" -m pip install streamlit
  if errorlevel 1 (
    echo [ERROR] Streamlit installation failed.
    pause
    exit /b 1
  )
)

echo [STEP 6] Optional GitHub sync...
where git >nul 2>nul
if %errorlevel%==0 (
  if exist ".git" (
    echo [INFO] git found. Pulling latest changes...
    git pull --rebase --autostash
    if errorlevel 1 (
      echo [WARN] git pull failed. App will still start with local files.
    )
  ) else (
    echo [INFO] This folder is not a git repository. Skipping sync.
  )
) else (
  echo [WARN] git command was not found. Skipping GitHub sync.
)

echo.
echo [START] Launching Streamlit app...
echo [INFO] If a browser does not open, copy the Local URL shown below.
echo.
"%PY%" -m streamlit run app.py

echo.
echo [INFO] App process ended.
pause
