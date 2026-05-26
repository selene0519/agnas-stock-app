# MONE Web App v1

Next.js + FastAPI 기반의 MONE 웹앱 v1입니다. 기존 Streamlit `app.py`와 기존 `reports/`, `data/`, `predictions.csv`, watchlist/candidate 파일은 수정하지 않고 읽기 전용으로 사용합니다.

## 1. 실행 방법

Backend:

```powershell
cd C:\Users\minbo\OneDrive\문서\GitHub\agnas-stock-app\mone-web-app\backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Frontend:

```powershell
cd C:\Users\minbo\OneDrive\문서\GitHub\agnas-stock-app\mone-web-app\frontend
npm install
npm run dev
```

Open:

- Frontend: http://localhost:3000
- Backend health: http://127.0.0.1:8000/health
- Backend docs: http://127.0.0.1:8000/docs

## 2. 폴더 구조

```text
mone-web-app/
  backend/
    app/
      main.py
      services/data_loader.py
    requirements.txt
  frontend/
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
- `GET /api/history/predictions`
- `GET /api/history/outcomes`
- `POST /api/quotes/refresh`

## 4. Frontend 화면 목록

실제 구현:

- 시장 홈
- 선택 종목
- 관심종목 / 후보군
- 매수 후보
- 매수금지 / 주의
- 보유 관리
- 손절·목표가
- 차트 보기
- 뉴스·공시·기업분석
- 확률 예측
- 리포트 센터
- 데이터 점검
- API / 자동화 상태

준비 중 화면:

- 장전 리포트
- 장중 체크
- 장마감 검증
- 백테스트
- 스캐너
- 계산기
- 몬테카를로
- 상관관계 / 히트맵

## 5. 검증 결과

Backend `TestClient` 검증:

- `/health`: OK
- 국장 선택종목: 64개
- 미장 선택종목: 61개
- 국장 보유종목: 2개
- 미장 보유종목: 11개
- 국장 뉴스: 20개
- 미장 뉴스: 20개
- `prediction_history`: 1051 rows
- `outcome_history`: 50 rows
- 필수 파일 누락: 0개
- 모든 요구 API endpoint: HTTP 200
- `POST /api/quotes/refresh`: READY

Frontend 검증:

- `npm run build`: 성공
- 차트 보기 메뉴: 좌측 사이드바에 고정 표시
- 현재가 표시: 가격기준시각과 가격출처 함께 표시
- API 상태: OK/MISSING 배지 표시

## 6. 아직 준비 중인 기능

- 실시간 quote refresh 실제 연결
- 장전 리포트 상세 화면
- 장중 체크 상세 workflow
- 장마감 검증 자동 반영
- 백테스트 상세 리포트
- 스캐너/계산기/몬테카를로/상관관계 고급 화면
- watchlist/holdings 쓰기 기능

## 7. 기존 app.py를 건드리지 않았는지 확인 결과

이번 작업은 `mone-web-app/` 폴더 안에만 새 파일을 추가했습니다.

- 기존 `app.py`: 수정하지 않음
- 기존 `reports/`: 수정/삭제/이동하지 않음
- 기존 `data/`, `data/history/`: 수정/삭제/이동하지 않음
- 기존 `watchlist_*.csv`: 수정/삭제/이동하지 않음
- 기존 `candidate_universe_*.csv`: 수정/삭제/이동하지 않음
- 기존 `predictions.csv`: 수정/삭제/이동하지 않음
- 기존 `.github/workflows/`: 수정하지 않음
