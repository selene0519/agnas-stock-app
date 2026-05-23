@echo off
setlocal
chcp 65001 >nul
echo [CHECK] folder: %CD%
echo [CHECK] app.py
if exist app.py (echo OK) else (echo MISSING)
echo [CHECK] git
git --version
echo [CHECK] Python
py --version
python --version
echo [CHECK] .venv streamlit
if exist .venv\Scripts\python.exe .venv\Scripts\python.exe -m streamlit --version
pause
