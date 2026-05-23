@echo off
setlocal
cd /d "%~dp0"
echo [INFO] Starting ARCFLOW/NEXORA app with GitHub sync...
call "%~dp0sync_latest_from_github.bat"
echo [INFO] Python: .venv\Scripts\python.exe
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m streamlit run app.py
) else (
  python -m streamlit run app.py
)
