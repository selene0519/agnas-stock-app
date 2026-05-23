@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v43 - Environment Check

echo ============================================================
echo  ARCFLOW/NEXORA v43 - Environment Check
echo ============================================================
echo.
echo [INFO] Current folder: %CD%
echo.

echo [CHECK] app.py
if exist "app.py" (echo OK: app.py found) else (echo MISSING: app.py not found)

echo.
echo [CHECK] requirements.txt
if exist "requirements.txt" (echo OK: requirements.txt found) else (echo MISSING: requirements.txt not found)

echo.
echo [CHECK] Python launcher
py --version
python --version

echo.
echo [CHECK] git
git --version

echo.
echo [CHECK] .venv Python
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" --version
  ".venv\Scripts\python.exe" -m streamlit --version
) else (
  echo MISSING: .venv\Scripts\python.exe not found
)

echo.
pause
