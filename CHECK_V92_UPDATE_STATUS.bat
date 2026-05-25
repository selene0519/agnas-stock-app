@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PYEXE="
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"
if "%PYEXE%"=="" set "PYEXE=python"
%PYEXE% check_v92_update_status.py
