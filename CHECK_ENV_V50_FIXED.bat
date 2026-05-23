@echo off
setlocal
chcp 65001 >nul
echo [CHECK] Current folder: %CD%
echo.
if exist app.py (echo OK app.py) else (echo MISSING app.py)
if exist requirements.txt (echo OK requirements.txt) else (echo MISSING requirements.txt)
echo.
python --version
py --version
git --version
echo.
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" --version
  ".venv\Scripts\python.exe" -m streamlit --version
) else (
  echo MISSING .venv\Scripts\python.exe
)
pause
