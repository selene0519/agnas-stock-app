@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo [INFO] Installing/repairing MONE v76 dependencies...
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install streamlit pandas numpy plotly requests beautifulsoup4 python-dotenv yfinance finance-datareader pykrx
echo.
echo [INFO] Done. Run START_APP_NO_SYNC_V76_FIXED.bat
pause
