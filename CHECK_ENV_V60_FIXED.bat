@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v60 - Environment Check

echo [CHECK] Current folder: %CD%
echo.
echo [CHECK] app.py
if exist "app.py" (echo OK) else (echo MISSING)
echo [CHECK] .env
if exist ".env" (echo OK - local .env exists) else (echo MISSING - local API keys may not be detected)
echo [CHECK] git
git --version
echo [CHECK] Python
py --version
if exist ".venv\Scripts\python.exe" ".venv\Scripts\python.exe" -m streamlit --version
pause
