# v61 GNEWS + Current Price Fix

## 핵심 수정
- 뉴스 키 표시는 `GNEWS_API_KEY` 기준으로 통일했습니다. `NEWS_API_KEY`는 필수 키가 아닙니다.
- `run_v60_daily_update.py`, `run_v61_daily_update.py`, GitHub cloud accumulator에서 뉴스 수집과 현재가 fallback을 기본 실행하도록 변경했습니다.
- 데이터 연결 점검 화면에서 `NEWS_API_KEY` 항목을 숨기고 `GNEWS_API_KEY` 중심으로 안내합니다.
- 현재가가 비는 경우 `reports/intraday_realtime_snapshot.csv`, 보유/관심/예측 파일, yfinance/FinanceDataReader fallback 순서로 보강합니다.

## 사용
- 로컬 실행: `START_HERE_V61_FIXED.bat`
- 수동 갱신: `run_v61_daily_update.bat`
- GitHub 업로드용 safe zip을 반영하면 Actions도 v61 기준으로 실행됩니다.
