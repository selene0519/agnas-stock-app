@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [NEXORA] 장중 데이터 갱신을 시작합니다.
python run_intraday_refresh.py
echo.
echo 완료되었습니다. 창을 닫아도 됩니다.
pause
