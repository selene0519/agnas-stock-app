@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo [INFO] Starting MONE v76 without Git sync...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m streamlit run app.py
) else (
  python -m streamlit run app.py
)
pause
