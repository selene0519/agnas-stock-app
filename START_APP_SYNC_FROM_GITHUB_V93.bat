@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [MONE] Fetch/Pull latest reports from GitHub...
git pull --ff-only
if errorlevel 1 (
  echo.
  echo [WARN] git pull failed. Resolve GitHub Desktop conflicts first, then run again.
  pause
  exit /b 1
)
echo.
echo [MONE] Start Streamlit app...
if exist .venv\Scripts\streamlit.exe (
  .venv\Scripts\streamlit.exe run app.py
) else (
  streamlit run app.py
)
