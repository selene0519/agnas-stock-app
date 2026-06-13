@echo off
chcp 65001 >nul
echo [MONE] 토요일 미장 종가 수집 태스크를 추가합니다...

schtasks /create ^
  /tn "MONE_US_Saturday_Collect" ^
  /tr "\"C:\Users\minbo\AppData\Local\Programs\Python\Python312\python.exe\" \"C:\dev\agnas-stock-app\scripts\local_data_collector.py\" --market us --push --days 5" ^
  /sc WEEKLY ^
  /d SAT ^
  /st 06:30 ^
  /sd 2026-06-13 ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

if %ERRORLEVEL% == 0 (
    echo.
    echo [완료] MONE_US_Saturday_Collect 태스크가 추가되었습니다.
    echo   - 실행 시각: 매주 토요일 오전 06:30
    echo   - 역할: 금요일 미국 장 마감 후 종가 데이터 수집 및 GitHub push
) else (
    echo.
    echo [오류] 태스크 추가에 실패했습니다.
    echo 관리자 권한으로 실행해보세요: 이 파일에 우클릭 - 관리자 권한으로 실행
)

echo.
pause
