# MONE v78 업데이트 요약

## 핵심 수정

1. 첫 화면 5개 카드 구조 유지
   - 오늘 우선 확인
   - 눌림목 진입 후보
   - 수급 급증 후보
   - 실적·저평가 후보
   - 매수금지·주의

2. 예측 기록 누적 오류 수정
   - KR 저장 후 US 저장 과정에서 prediction_history.csv가 덮어써지는 문제를 방지
   - KR/US 기록을 합친 뒤 한 번만 append 저장
   - 중복 기준: date + market + category + symbol

3. 국장 수급 복구
   - 파일명만 믿지 않고 CSV 내부의 market/시장/symbol/종목코드를 기준으로 KR/US 분리
   - intraday_flow_snapshot-Kang.csv, intraday_realtime_snapshot-Kang.csv, intraday_orderbook_snapshot-Kang.csv 등 자동 탐색
   - 외국인·기관 수급값이 부족하면 거래량·거래대금 fallback으로 후보 표시

4. UI/UX 정리
   - 일반모드: 카드형 요약, 뉴스 3줄 요약, 후보 카드 중심
   - 관리자모드: API/파일 rows/수급 원본 진단 분리

## 실행 순서

```powershell
.\run_v78_daily_update.bat
.\START_APP_NO_SYNC_V78_FIXED.bat
```

## 확인 명령

```powershell
Import-Csv .\reports\v78_today_summary_kr.csv | Select-Object 카드,건수,TOP,구분
Import-Csv .\reports\v78_flow_clean_kr.csv | Select-Object 종목코드,종목명,시장,수급기준,수급점수
Import-Csv .\data\history\prediction_history.csv | Group-Object market,category | Select-Object Name,Count
```
