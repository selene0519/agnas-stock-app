# MONE Web App v1.2

Next.js + FastAPI 기반의 MONE 웹앱입니다. v1.2에서는 기존 v1.1 네비게이션 구조를 유지하면서 `운용 리포트` 영역의 장전 리포트, 장중 체크, 장마감 검증, 리포트 센터를 실제 CSV/JSON 기반 화면으로 강화했습니다. 기존 Streamlit `app.py`와 기존 `reports/`, `data/`, `predictions.csv`, watchlist/candidate 파일은 수정하지 않고 읽기 전용으로 사용합니다.

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
- `POST /api/quotes/refresh`

## 4. Frontend 네비게이션 구조

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

## 5. v1.2 운용 리포트 화면

- 장전 리포트: `today_summary`, `action_cards`, `pullback_cards`, `risk_cards`, `future_probability`, `predictions.csv`를 조합해 현재가, 기준시각, 출처, 예상 시초가/종가, 기준가, 손절가, 목표가, 손익비, 다음 행동, 리스크 상태, 데이터 상태를 표시합니다.
- 장중 체크: `symbol_snapshot`, `position_cards`, `risk_cards`, `news_summary`를 조합해 기준가 대비 괴리율, 손절가 이탈 여부, 목표가 도달 여부, 보유 위험, 뉴스/리스크 상태, 장중 판단을 표시합니다.
- 장마감 검증: `prediction_history`, `outcome_history`, `predictions.csv`를 조합해 최근 예측, 결과일, 방향/범위 적중, 주문 기준가, 손절/익절, 실패 사유, 전체 적중률을 표시합니다.
- 리포트 센터: `reports/` 폴더의 latest, v92, v93, operational, portfolio, backtest 관련 파일 목록과 row/column count, 수정시각, 파일 크기, CSV 미리보기, fallback 상태를 표시합니다.

## 6. 검증 결과

- `python -m compileall mone-web-app\backend\app`: 성공
- `npm run build`: 성공
- `/health`: OK
- 장전 리포트: 21 rows
- 장중 체크: 34 rows
- 장마감 검증: 80 rows
- 리포트 센터: 129 files
- 국장/미장 시장 전환: 정상
- 현재가 기준시각/출처 표시: 유지
- 보유종목 수익률 표시: 유지
- 삼성전자: 현재가 `299,500원`, 기준시각 `05-26 10:12 KST`, 출처 `KIS 현재가 · 05-26 10:12 KST`
- 두산테스나: 평균단가 `178,200원`, 현재가 `169,000원`, 수익률 `-5.16%`
- 심텍: 평균단가 `98,200원`, 현재가 `132,400원`, 수익률 `+34.83%`

## 7. 기존 app.py를 건드리지 않았는지 확인 결과

이번 작업은 `mone-web-app/` 폴더 안에서만 진행했습니다.

- 기존 `app.py`: 수정하지 않음
- 기존 `reports/`: 수정/삭제/이동하지 않음
- 기존 `data/`, `data/history/`: 수정/삭제/이동하지 않음
- 기존 `watchlist_*.csv`: 수정/삭제/이동하지 않음
- 기존 `candidate_universe_*.csv`: 수정/삭제/이동하지 않음
- 기존 `predictions.csv`: 수정/삭제/이동하지 않음
- 기존 `.github/workflows/`: 수정하지 않음
