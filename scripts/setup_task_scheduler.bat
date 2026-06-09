@echo off
REM MONE 로컬 데이터 수집기 - Windows 작업 스케줄러 등록
REM 관리자 권한으로 실행 필요

SET REPO_ROOT=%~dp0..
SET PYTHON=python
SET SCRIPT=%REPO_ROOT%\scripts\local_data_collector.py

echo [MONE] 작업 스케줄러 등록 중...

REM 기존 작업 삭제
schtasks /delete /tn "MONE_Morning_Collect" /f >nul 2>&1
schtasks /delete /tn "MONE_Evening_Collect" /f >nul 2>&1

REM 장전 수집 (평일 07:30)
schtasks /create /tn "MONE_Morning_Collect" ^
  /tr "\"%PYTHON%\" \"%SCRIPT%\" --push --days 5" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI /st 07:30 ^
  /ru "%USERNAME%" ^
  /f
IF %ERRORLEVEL% EQU 0 (
  echo [OK] 장전 수집 등록 완료 (평일 07:30)
) ELSE (
  echo [ERROR] 장전 수집 등록 실패
)

REM 장후 수집 (평일 16:30)
schtasks /create /tn "MONE_Evening_Collect" ^
  /tr "\"%PYTHON%\" \"%SCRIPT%\" --push --days 5" ^
  /sc WEEKLY /d MON,TUE,WED,THU,FRI /st 16:30 ^
  /ru "%USERNAME%" ^
  /f
IF %ERRORLEVEL% EQU 0 (
  echo [OK] 장후 수집 등록 완료 (평일 16:30)
) ELSE (
  echo [ERROR] 장후 수집 등록 실패
)

echo.
echo 등록된 작업 확인:
schtasks /query /tn "MONE_Morning_Collect" /fo LIST 2>nul
schtasks /query /tn "MONE_Evening_Collect" /fo LIST 2>nul

echo.
echo [MONE] 등록 완료!
echo 수동 테스트: python "%SCRIPT%" --days 5
pause
