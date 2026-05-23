# stock_app FINAL v30 자동누적 안정화 패치

기준 파일: stock_app_FINAL_v29_from_v24_streamlit.zip

## v30 반영 내용

1. Windows 자동 시작 등록/해제 파일 추가
   - install_autostart.bat
   - uninstall_autostart.bat
   - start_auto_accumulator_background.bat
   - check_auto_accumulator_status.bat

2. 자동누적 상태 저장 강화
   - reports/auto_accumulator_status.json
   - 마지막 실행 시간, 마지막 성공 시간, 다음 실행 예상 시간, 반복 횟수, 데이터 파일별 row 수 저장

3. 자동누적 로그 저장
   - logs/auto_accumulator.log
   - logs/auto_accumulator_console.log

4. 일일 백업 기초 추가
   - backups/YYYY-MM-DD/
   - portfolio_daily_nav.csv, benchmark_daily.csv, news_cache.csv, backtest_beta_summary 등 주요 파일 백업

5. Streamlit 첫 화면에 자동누적 상태판 추가
   - 자동누적 상태
   - 마지막 실행/성공 시간
   - 다음 실행 예상 시간
   - 핵심 데이터 누적 row 수
   - 로그/상태/백업 경로

## 사용 방법

### 처음 한 번만 자동 시작 등록

PowerShell 또는 CMD에서 앱 폴더로 이동 후:

    .\install_autostart.bat

이후 Windows 로그인 시 자동누적이 백그라운드로 실행됩니다.

### 지금 바로 수동 실행

    .\start_auto_accumulator.bat

### 자동 시작 해제

    .\uninstall_autostart.bat

### 상태 1회 점검

    .\check_auto_accumulator_status.bat

## 주의

노트북이 완전히 꺼져 있으면 로컬 자동누적은 실행되지 않습니다.
노트북 전원이 켜져 있고 Windows에 로그인되어 있으면 자동 시작 등록으로 자동누적이 실행됩니다.
