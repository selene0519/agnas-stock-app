MONE v93 GitHub Actions 자동 업데이트 패치
================================================

목적
- 국장/미장 예측·리포트·prediction_history 누적을 GitHub 서버에서 자동 실행합니다.
- 작업스케줄러 시간에 맞춰 노트북을 켜둘 필요를 없애는 구조입니다.
- 노트북은 앱을 보고 싶을 때만 켜고, START_APP_SYNC_FROM_GITHUB_V93.bat로 Pull 후 실행하면 됩니다.

포함 파일
- .github/workflows/mone-auto-accumulator.yml
- scripts/mone_github_auto_update.py
- run_v93_daily_update.bat
- CHECK_V93_UPDATE_STATUS.bat
- START_APP_SYNC_FROM_GITHUB_V93.bat

사용 방법
1. 이 압축의 내용을 agnas-stock-app 폴더에 덮어씁니다.
2. .env는 절대 GitHub에 올리지 않습니다.
3. GitHub 저장소 Settings > Secrets and variables > Actions > New repository secret에 API 키를 넣습니다.
   권장 secret 이름:
   - DART_API_KEY
   - FINNHUB_API_KEY
   - GNEWS_API_KEY
   - SEC_USER_AGENT
   - KIS_APP_KEY
   - KIS_APP_SECRET
   - KIS_ACCOUNT 또는 KIS_CANO / KIS_ACNT_PRDT_CD
4. GitHub Desktop에서 변경 파일을 확인하고 commit/push 합니다.
5. GitHub Actions 탭에서 MONE Auto Accumulator를 Run workflow로 수동 실행해 첫 테스트를 합니다.
6. 초록 체크로 끝나고 reports/data/history에 변경 commit이 생기면 성공입니다.

노트북을 켤 필요가 있나?
- 데이터 업데이트/예측 누적 목적이라면 필요 없습니다. GitHub Actions가 서버에서 실행합니다.
- 앱을 직접 볼 때만 노트북을 켜면 됩니다.
- 앱 보기 전에는 START_APP_SYNC_FROM_GITHUB_V93.bat를 실행하면 최신 GitHub 결과를 pull하고 앱을 켭니다.

주의
- GitHub Actions 예약 실행 시간은 UTC 기준이며, 부하에 따라 몇 분 지연될 수 있습니다.
- 이 패치는 v93 파일을 만들고, 기존 화면 호환을 위해 v92 alias 파일도 같이 생성합니다.
- .github/workflows를 지우면 자동 업데이트가 중단됩니다.
- .env 또는 API 키가 담긴 파일은 commit하지 마세요.
