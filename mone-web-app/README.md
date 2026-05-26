# MONE Web App v1.4

Next.js + FastAPI 기반의 MONE 웹앱입니다. v1.4에서는 고급 분석 영역의 백테스트, 스캐너, 계산기, 몬테카를로, 상관관계/히트맵을 실제 데이터 화면으로 연결했습니다. 기존 Streamlit `app.py`와 기존 `reports/`, `data/`, `predictions.csv`, watchlist/candidate 파일은 수정하지 않고 읽기 전용으로 유지합니다.

## 1. 실행 방법

Backend는 8010 포트를 기준으로 실행합니다.

```powershell
cd C:\Users\minbo\OneDrive\문서\GitHub\agnas-stock-app\mone-web-app\backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
```

Frontend:

```powershell
cd C:\Users\minbo\OneDrive\문서\GitHub\agnas-stock-app\mone-web-app\frontend
npm install
npm run dev
```

Frontend API 주소 예시:

```powershell
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8010
```

- Frontend: http://localhost:3000
- Backend health: http://127.0.0.1:8010/health
- Backend docs: http://127.0.0.1:8010/docs

## 2. 폴더 구조

```text
mone-web-app/
  backend/
    app/
      main.py
      services/data_loader.py
      services/quotes.py
      services/advanced.py
    cache/              # runtime quote/token cache, git ignored
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

## 4. Frontend 화면 목록

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

## 5. v1.4 고급 분석

- 백테스트: `reports/backtest_*`, `reports/v92_quant_backtest_*`, `data/history`, `predictions.csv`를 읽어 전략별 수익률, 승률, MDD, Sharpe, 거래 수, 최근 결과를 표시합니다. 데이터가 부족하면 부족 사유를 표시합니다.
- 스캐너: `candidate_universe_*`, `watchlist_*_growth.csv`, v92 action/pullback/flow/risk 카드를 조합해 전체, BUY, 주의, 눌림목, 수급, 저평가, 보유 제외 필터를 제공합니다.
- 계산기: Kelly 포지션 사이징, VaR/CVaR, 위험조정수익률, 손익비, 포지션 수량 계산 결과만 표시합니다.
- 몬테카를로: 입력값 기반 GBM 시뮬레이션으로 P5/P50/P95, 상승확률, 예상 최종가, VaR/CVaR와 Recharts 라인 차트를 표시합니다.
- 상관관계/히트맵: `data/market/benchmark_daily.csv`를 우선 사용해 수익률 상관관계 히트맵과 페어별 해석을 표시합니다. 데이터가 부족하면 `상관관계 계산 데이터 부족`을 표시합니다.
- 자동매매/주문 기능은 구현하지 않았습니다.

## 6. 현재가 새로고침

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

## 7. 검증 결과

- `python -m compileall mone-web-app\backend\app`: 성공
- `npm run build`: 성공
- `/health`: OK
- `GET /api/advanced/backtest?market=kr`: `DATA_SHORT`, 4 strategies 표시
- `GET /api/advanced/scanner?market=kr`: 119 rows 표시
- `GET /api/advanced/scanner?market=us`: 128 rows 표시
- `GET /api/advanced/correlation?market=kr|us`: OK, 벤치마크 일간 수익률 기준
- `POST /api/advanced/calculator/kelly`: Half Kelly 계산 응답
- `POST /api/advanced/calculator/var`: VaR/CVaR 계산 응답
- `POST /api/advanced/calculator/risk-reward`: 손익비 계산 응답
- `POST /api/advanced/monte-carlo`: 61개 차트 포인트, P5/P50/P95 계산 응답
- 고급 분석 > 백테스트 화면 표시 확인
- 고급 분석 > 스캐너 화면 표시 확인
- 고급 분석 > 계산기 화면 표시 확인
- 고급 분석 > 몬테카를로 화면 표시 확인
- 고급 분석 > 상관관계/히트맵 화면 표시 확인
- 자동매매/주문 기능 추가 없음

## 8. 아직 준비 중인 기능

- 관심종목 편입 버튼은 v1.4에서 비활성 상태입니다.
- 계산기 입력값 UI는 기본값 기반 실행으로 제공하며, 상세 사용자 입력 폼은 후속 버전에서 확장합니다.
- 백테스트는 기존 파일에 충분한 OHLC/거래 결과가 부족하면 샘플 계산을 만들지 않고 데이터 부족 사유를 표시합니다.

## 9. 기존 파일 보호 확인

이번 작업은 `mone-web-app/` 폴더 안에서만 진행했습니다.

- 기존 `app.py`: 수정하지 않음
- 기존 `reports/`: 수정/삭제/이동하지 않음
- 기존 `data/`, `data/history/`: 수정/삭제/이동하지 않음
- 기존 `watchlist_*.csv`: 수정/삭제/이동하지 않음
- 기존 `candidate_universe_*.csv`: 수정/삭제/이동하지 않음
- 기존 `predictions.csv`: 수정/삭제/이동하지 않음
- 기존 `.github/workflows/`: 수정하지 않음
