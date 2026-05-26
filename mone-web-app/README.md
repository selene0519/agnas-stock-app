# MONE Web App v1.6

Next.js + FastAPI 기반의 MONE 웹앱입니다. v1.6에서는 앱 밖에서 수집한 `data/market/ohlcv/*_daily.csv` 과거 OHLCV 데이터를 백테스트 엔진에 연결했습니다. 기존 Streamlit `app.py`와 기존 `reports/`, `data/history/`, `predictions.csv`, watchlist/candidate 파일은 임의로 덮어쓰지 않고, 백테스트는 읽기 전용 데이터 기반으로 계산합니다.

## 1. 실행 방법

Backend는 사용 가능한 포트를 기준으로 실행합니다. 현재 로컬에서는 8050 사용을 권장합니다.

```powershell
cd C:\Users\minbo\OneDrive\문서\GitHub\agnas-stock-app\mone-web-app\backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8050 --reload
```

Frontend:

```powershell
cd C:\Users\minbo\OneDrive\문서\GitHub\agnas-stock-app\mone-web-app\frontend
@'
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8050
'@ | Set-Content .\.env.local -Encoding UTF8
npm install
npm run dev
```

- Frontend: http://localhost:3000
- Backend health: http://127.0.0.1:8050/health
- Backend docs: http://127.0.0.1:8050/docs

## 2. 폴더 구조

```text
mone-web-app/
  backend/
    app/
      main.py
      services/data_loader.py
      services/quotes.py
      services/advanced.py
      services/user_data.py
    cache/              # runtime quote/token cache, git ignored
    backups/            # write 작업 백업, git ignored
    requirements.txt
  frontend/
    .env.example
    src/app/
    src/components/
    src/lib/
    package.json
  README.md
```

## 3. Backend API 목록

- `GET /health`
- `GET /api/status/files`
- `GET /api/status/env`
- `GET /api/market/summary?market=kr|us`
- `GET /api/symbols?market=kr|us`
- `GET /api/symbols/{symbol}?market=kr|us`
- `GET /api/candidates?market=kr|us&type=action|pullback|flow|risk`
- `GET /api/positions?market=kr|us`
- `GET /api/watchlist?market=kr|us`
- `POST /api/watchlist`
- `DELETE /api/watchlist/{symbol}?market=kr|us`
- `GET /api/holdings?market=kr|us`
- `POST /api/holdings`
- `PATCH /api/holdings/{symbol}`
- `DELETE /api/holdings/{symbol}?market=kr|us`
- `GET /api/news?market=kr|us`
- `GET /api/predictions?market=kr|us`
- `GET /api/reports/premarket?market=kr|us`
- `GET /api/reports/intraday?market=kr|us`
- `GET /api/reports/closing?market=kr|us`
- `GET /api/reports/files`
- `GET /api/reports/preview?path=reports/...csv`
- `GET /api/history/predictions`
- `GET /api/history/outcomes`
- `POST /api/quotes/refresh?market=kr|us|all&symbols=005930,NVDA&max_symbols=80`
- `GET /api/advanced/backtest?market=kr|us`
- `GET /api/advanced/scanner?market=kr|us`
- `POST /api/advanced/calculator/kelly`
- `POST /api/advanced/calculator/var`
- `POST /api/advanced/calculator/risk-reward`
- `POST /api/advanced/monte-carlo`
- `GET /api/advanced/correlation?market=kr|us`

## 4. v1.6 OHLCV 백테스트 연결

백테스트는 이제 `data/market/ohlcv/` 아래의 일봉 CSV를 직접 읽습니다.

예시 파일:

```text
data/market/ohlcv/kr_005930_daily.csv
data/market/ohlcv/kr_000660_daily.csv
data/market/ohlcv/us_NVDA_daily.csv
data/market/ohlcv/us_AAPL_daily.csv
```

백테스트 화면에서 표시하는 주요 진단값:

- 전체 `predictions.csv` rows
- 현재 시장 필터 rows
- OHLCV 파일 수
- 30일 이상 OHLCV 보유 종목 수
- 예측+OHLCV 매칭 종목 수
- OHLCV 부족 종목 수
- 컬럼/파싱 오류 수
- 전체 거래 신호 수

구현된 전략:

- 20일 고점 돌파
- MA10 > MA20 추세
- RSI 저점 반등
- 20일선 눌림목

성과 지표:

- 평균 거래 수익률
- 승률
- MDD
- Sharpe
- 거래 수
- 최근 백테스트 신호

데이터가 부족하면 임의 샘플 계산을 만들지 않고, 부족한 이유를 화면에 표시합니다.

## 5. 현재가 새로고침

- 국장: KIS 국내주식 현재가 API를 사용합니다.
- 미장: KIS 해외주식 현재가 API를 먼저 사용하고, 실패하면 Finnhub quote API로 보조 조회합니다.
- 성공한 현재가만 cache에 저장합니다.
- 실패 종목은 기존 reports/data 값 또는 기존 cache 값을 fallback으로 유지합니다.
- API 키는 backend `.env` 또는 실행 환경 변수에서만 읽고 frontend로 전달하지 않습니다.

필요한 backend 환경 변수:

```powershell
KIS_APP_KEY=...
KIS_APP_SECRET=...
KIS_IS_MOCK=false
FINNHUB_API_KEY=...
```

## 6. Frontend 화면 목록

사이드바에는 대분류만 표시하고, 각 대분류 화면 상단에서 소분류를 pill button으로 선택합니다.

- 시장 홈: 요약, 오늘 체크, 운영 대시보드
- 운용 리포트: 장전 리포트, 장중 체크, 장마감 검증, 리포트 센터
- 종목 탐색: 선택 종목, 관심종목, 후보군, 매수 후보, 매수금지 / 주의
- 보유·리스크: 보유 관리, 손절·목표가, 평가손익, 포지션 계산
- 차트·기술분석: 차트 보기, 기술지표, 지지·저항, 예측선 / 주문선
- 뉴스·기업분석: 뉴스 요약, 공시, 기업분석, 종목 내러티브
- 예측·검증: 확률 예측, 예측 기록, 결과 검증, 실패 복기, 자동 보정
- 고급 분석: 백테스트, 스캐너, 계산기, 몬테카를로, 상관관계 / 히트맵
- 관리: 데이터 점검, API 상태, 자동화 상태, 로그 / 백업

## 7. 검증 결과

- `python -m compileall mone-web-app/backend/app`: 성공
- `npm run build`: 성공
- `GET /api/advanced/backtest?market=kr`: OHLCV 기반 응답 구조 확인
- `GET /api/advanced/backtest?market=us`: OHLCV 기반 응답 구조 확인
- 백테스트 화면에 `OHLCV 파일`, `30일 이상 종목`, `예측+가격 매칭`, `전체 예측 rows` 표시
- `data/market/ohlcv` 파일이 있으면 `DATA_SHORT` 대신 실제 전략별 결과 계산
- 자동매매/주문 기능 추가 없음

## 8. 기존 파일 보호 확인

이번 작업은 `mone-web-app/` 폴더 안에서만 진행했습니다.

- 기존 `app.py`: 수정하지 않음
- 기존 `reports/`: 수정/삭제/이동하지 않음
- 기존 `data/history/`: 수정/삭제/이동하지 않음
- 기존 `watchlist_*.csv`: 직접 수정하지 않음. 단, 앱의 관심종목 저장 기능을 사용하면 백업 후 `watchlist_*_growth.csv`만 수정 가능
- 기존 `candidate_universe_*.csv`: 수정하지 않음
- 기존 `predictions.csv`: 수정하지 않음
- 기존 `.github/workflows/`: 수정하지 않음
