# V44 Update Notes - 실전 복기·오차보정 강화

## 핵심 변경

1. 오늘 행동판 추가
   - 일반모드 `오늘 실행 → 오늘 행동판`
   - 후보·위험·복기 결과를 합쳐 초보자가 바로 볼 수 있는 행동 카드로 정리

2. 실전 복기·오차보정 추가
   - `퀀트 → 실전 복기·오차보정`
   - 앱이 추천한 후보를 `data/learning/recommendation_log.csv`에 누적 기록
   - 1/3/5/20거래일 수익률, 목표가/손절가 도달 여부 추적

3. 조건별 성과 기록
   - 시장/전략/키워드별 승률, 평균수익률, 실패율 계산
   - `reports/v44_condition_performance.csv` 저장

4. 보정 제안 자동 생성
   - 실패가 많은 조건을 찾아 감점/관망 권고 문구 생성
   - `reports/v44_calibration_summary.json` 저장

5. 자동 실행 연결
   - `run_cloud_accumulator.py`에 v44 업데이트 포함
   - GitHub Actions가 돌 때 v44 리포트도 같이 갱신

## 생성 파일

- `core/v44_learning_calibration_engine.py`
- `run_v44_daily_update.py`
- `run_v44_daily_update.bat`
- `START_HERE_V44_FIXED.bat`
- `START_APP_NO_SYNC_V44_FIXED.bat`
- `CHECK_ENV_V44_FIXED.bat`

## 사용법

로컬 실행:

```powershell
.\START_HERE_V44_FIXED.bat
```

v44 리포트만 갱신:

```powershell
.un_v44_daily_update.bat
```

## 주의

- 이 기능은 자동매매가 아닙니다.
- 추천 기록과 결과를 추적해 매수 기준을 보정하는 분석 기능입니다.
- 가격 히스토리가 없거나 yfinance가 실패하면 일부 결과는 `가격데이터 없음`으로 표시됩니다.
