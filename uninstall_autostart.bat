@echo off
setlocal
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS_PATH=%STARTUP_DIR%\stock_app_auto_accumulator.vbs"
if exist "%VBS_PATH%" del "%VBS_PATH%"
echo.
echo [완료] Windows 시작 자동 실행 등록을 해제했습니다.
echo 이미 실행 중인 자동누적 창/프로세스는 직접 닫거나 Ctrl+C로 종료하세요.
echo.
pause
