@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [MONE] v93 local/cloud-compatible update start...
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe scripts\mone_github_auto_update.py
) else (
  python scripts\mone_github_auto_update.py
)
echo.
echo [OK] MONE v93 update complete.
pause
