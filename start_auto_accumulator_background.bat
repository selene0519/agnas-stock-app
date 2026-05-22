@echo off
cd /d %~dp0
if not exist logs mkdir logs
if not exist reports mkdir reports
if not exist backups mkdir backups
set AUTO_ACCUMULATOR_INTERVAL_MIN=15
python run_auto_accumulator.py >> logs\auto_accumulator_console.log 2>&1
