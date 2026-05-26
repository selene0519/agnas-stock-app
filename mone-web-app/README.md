# MONE Web App v1.3

Next.js + FastAPI 기반의 MONE 웹앱입니다. v1.3에서는 `POST /api/quotes/refresh`를 실제 현재가 새로고침으로 연결했습니다. 현재가는 백엔드에서만 KIS/Finnhub API 키를 사용해 조회하고, 결과는 `mone-web-app/backend/cache/quotes_cache.json`에 저장됩니다. 기존 Streamlit `app.py`와 기존 `reports/`, `data/`, `predictions.csv`, watchlist/candidate 파일은 수정하지 않고 읽기 전용으로 유지합니다.

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

## 4. 현재가 새로고침

- 국장: KIS 국내주식 현재가 API를 사용합니다.
- 미장: KIS 해외주식 현재가 API를 먼저 사용하고, 실패하면 Finnhub quote API로 보조 조회합니다.
- 성공한 현재가만 cache에 저장합니다.
- 실패 종목은 기존 reports/data 값 또는 기존 cache 값을 fallback으로 유지합니다.
- API 키는 backend `.env` 또는 실행 환경 변수에서만 읽고 frontend로 전달하지 않습니다.
- 자동매매/주문 기능은 구현하지 않았습니다.

필요한 backend 환경 변수:

```powershell
KIS_APP_KEY=...
KIS_APP_SECRET=...
KIS_IS_MOCK=false
FINNHUB_API_KEY=...
```

## 5. Frontend 네비게이션 구조

사이드바에는 대분류만 표시하고, 각 대분류 화면 상단에서 소분류를 pill button으로 선택합니다. 상단 바의 `현재가 새로고침` 버튼을 누르면 현재 선택한 시장의 현재가를 갱신한 뒤 시장 요약, 종목, 보유, 리포트 데이터를 다시 조회합니다.

- 시장 홈: 요약, 오늘 체크, 운영 대시보드
- 운용 리포트: 장전 리포트, 장중 체크, 장마감 검증, 리포트 센터
- 종목 탐색: 선택 종목, 관심종목, 후보군, 매수 후보, 매수금지 / 주의
- 보유·리스크: 보유 관리, 손절·목표가, 평가손익, 포지션 계산
- 차트·기술분석: 차트 보기, 기술지표, 지지·저항, 예측선 / 주문선
- 뉴스·기업분석: 뉴스 요약, 공시, 기업분석, 종목 내러티브
- 예측·검증: 확률 예측, 예측 기록, 결과 검증, 실패 복기, 자동 보정
- 고급 분석: 백테스트, 스캐너, 계산기, 몬테카를로, 상관관계 / 히트맵
- 관리: 데이터 점검, API 상태, 자동화 상태, 로그 / 백업

## 6. 검증 결과

- `python -m compileall mone-web-app\backend\app`: 성공
- `npm run build`: 성공
- `/health`: OK
- `POST /api/quotes/refresh?market=kr&symbols=005930&max_symbols=1`: JSON 응답, 삼성전자 KIS 현재가 수신
- `POST /api/quotes/refresh?market=us&symbols=NVDA&max_symbols=1`: JSON 응답, NVDA KIS 해외 현재가 수신
- 삼성전자: 현재가 `300,500원`, 기준시각 `2026-05-26 13:51:37 KST`, 출처 `KIS 현재가`
- NVDA: 현재가 `$215.33`, 기준시각 `2026-05-26 13:51:10 KST`, 출처 `KIS 해외 현재가 · NAS`
- API 키 missing 시: `NO_REFRESH` JSON 응답, 앱 예외 없음, 기존 fallback 유지
- 보유종목 수익률 표시: 유지

## 7. 기존 파일 보호 확인

이번 작업은 `mone-web-app/` 폴더 안에서만 진행했습니다.

- 기존 `app.py`: 수정하지 않음
- 기존 `reports/`: 수정/삭제/이동하지 않음
- 기존 `data/`, `data/history/`: 수정/삭제/이동하지 않음
- 기존 `watchlist_*.csv`: 수정/삭제/이동하지 않음
- 기존 `candidate_universe_*.csv`: 수정/삭제/이동하지 않음
- 기존 `predictions.csv`: 수정/삭제/이동하지 않음
- 기존 `.github/workflows/`: 수정하지 않음
