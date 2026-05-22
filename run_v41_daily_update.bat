@echo off
cd /d "%~dp0"
echo [v41] Updating intraday, operational, risk, and v40 reports...
python run_intraday_refresh.py
python app.py --runner final_metrics
python app.py --runner v37
python app.py --runner v40
set AUTO_ACCUMULATOR_ONCE=1
python run_auto_accumulator.py
echo.
echo [v41] Done. Press any key to close.
pause > nul
