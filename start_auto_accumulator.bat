@echo off
cd /d %~dp0
if not exist logs mkdir logs
if not exist reports mkdir reports
if not exist backups mkdir backups
set AUTO_ACCUMULATOR_INTERVAL_MIN=15
echo [Stock App] 자동누적을 시작합니다.
echo 창을 닫으면 자동누적이 멈춥니다. 멈추려면 Ctrl+C 를 누르세요.
echo 로그: logs\auto_accumulator.log
echo 상태: reports\auto_accumulator_status.json
python run_auto_accumulator.py
pause
