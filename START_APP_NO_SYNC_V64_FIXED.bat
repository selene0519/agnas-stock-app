@echo off
setlocal
chcp 65001 >nul
title ARCFLOW/NEXORA v64 - No Sync
if not exist .venv\Scripts\python.exe py -m venv .venv
set PY=.venv\Scripts\python.exe
%PY% -m pip install -r requirements.txt
%PY% -m streamlit run app.py
pause
