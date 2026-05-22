@echo off
cd /d "%~dp0"
echo [NEXORA] checking cloud auto-accumulation readiness...
python -m core.cloud_readiness_engine
pause
