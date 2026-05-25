# MONE v85 적용 가이드

## 적용 순서

1. 이 ZIP을 GitHub 앱 폴더에 덮어씁니다.
2. PowerShell에서 아래를 실행합니다.

```powershell
.\run_v85_daily_update.bat
```

3. 앱을 실행합니다.

```powershell
.\START_APP_NO_SYNC_V85_FIXED.bat
```

4. 실행/의존성 문제가 있으면 아래를 사용합니다.

```powershell
.\ONE_CLICK_REPAIR_UPDATE_START_V85.bat
```

## 확인 명령어

```powershell
dir .\reports\v85_*

Import-Csv .\reports\v85_today_summary_kr.csv |
Select-Object 카드,건수,TOP,구분 |
Format-Table -Auto

Import-Csv .\reports\v85_symbol_snapshot_kr.csv |
Select-Object 종목코드,종목명,현재가,기준가,손절가,목표가,호가,수급점수 |
Format-Table -Auto

Import-Csv .\reports\v85_future_probability_kr.csv |
Select-Object 종목코드,종목명,분류,1일상승확률,3일상승확률,5일상승확률,근거1,데이터충분도 |
Format-Table -Auto
```

## v85 핵심

- 첫 화면 5개 카드 고정
- 일반 화면 카드 중심 정리
- 관리자 모드에 원본/진단/퀀트 도구 이동
- 선택 종목 fallback 강화
- 뉴스·기업분석·내러티브 통합
- 확률 예측 카드에 근거/데이터충분도 표시
- outcome_history.csv 스켈레톤 생성으로 결과 추적 준비

## 주의

- `.env`는 절대 업로드하지 않습니다.
- 기존 `data`, `reports`, `.env`는 이 ZIP에 포함하지 않습니다.
- `prediction_history.csv`는 append 방식으로 누적되며 덮어쓰지 않도록 구성했습니다.
