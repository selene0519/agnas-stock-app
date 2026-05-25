@echo off
setlocal
cd /d "%~dp0"
echo [INFO] Starting MONE v80 app without GitHub sync...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m streamlit run app.py
) else (
  python -m streamlit run app.py
)
pause
