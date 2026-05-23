@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v44 - Environment Check
echo [CHECK] app.py
if exist "app.py" (echo OK) else (echo MISSING)
echo [CHECK] Python
py --version
python --version
echo [CHECK] git
git --version
echo [CHECK] streamlit
if exist ".venv\Scripts\python.exe" ".venv\Scripts\python.exe" -m streamlit --version
pause
