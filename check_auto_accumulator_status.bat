@echo off
cd /d %~dp0
if not exist logs mkdir logs
if not exist reports mkdir reports
if not exist backups mkdir backups
set AUTO_ACCUMULATOR_ONCE=1
python run_auto_accumulator.py
pause
