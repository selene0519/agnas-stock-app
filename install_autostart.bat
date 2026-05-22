@echo off
setlocal
cd /d %~dp0
set "APP_DIR=%CD%"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS_PATH=%STARTUP_DIR%\stock_app_auto_accumulator.vbs"
if not exist "%STARTUP_DIR%" mkdir "%STARTUP_DIR%"
(
  echo Set WshShell = CreateObject("WScript.Shell"^)
  echo appDir = "%APP_DIR%"
  echo WshShell.Run Chr(34^) ^& appDir ^& "\start_auto_accumulator_background.bat" ^& Chr(34^), 0, False
) > "%VBS_PATH%"
echo.
echo [완료] Windows 시작 시 자동누적이 실행되도록 등록했습니다.
echo 등록 위치: %VBS_PATH%
echo.
echo 지금 바로 백그라운드 자동누적도 시작하려면 아래 파일을 한 번 실행하세요.
echo start_auto_accumulator.bat
pause
