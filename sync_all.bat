@echo off
cd /d "C:\dev\agnas-stock-app"
set PYTHON=C:\Users\minbo\AppData\Local\Programs\Python\Python312\python.exe

echo [%date% %time%] KIS 1번 계좌 동기화...
%PYTHON% scripts\sync_kis_holdings.py --upload --backend-url https://agnas-stock-app.onrender.com
if errorlevel 1 echo [ERROR] KIS 1번 실패

timeout /t 5 /nobreak > nul

echo [%date% %time%] KIS 2번 계좌 동기화...
%PYTHON% scripts\sync_kis_holdings.py --prefix KIS_2 --upload --backend-url https://agnas-stock-app.onrender.com
if errorlevel 1 echo [ERROR] KIS 2번 실패

timeout /t 5 /nobreak > nul

echo [%date% %time%] Toss 동기화...
%PYTHON% scripts\sync_toss_holdings.py --upload --backend-url https://agnas-stock-app.onrender.com
if errorlevel 1 echo [ERROR] Toss 실패

echo [%date% %time%] 완료.
