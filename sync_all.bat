@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\dev\agnas-stock-app\scripts\sync_all.ps1"
exit /b %ERRORLEVEL%
