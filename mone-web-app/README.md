# MONE Web App v2.1

Next.js + FastAPI 기반의 MONE 웹앱입니다. v2.1은 기존 v2.0 정리 방향을 유지하면서 남은 대분류를 추가 정리했습니다. 일반 사용자 화면은 매일 확인할 내용 중심으로 줄이고, 예측 기록/결과 검증/실패 복기/자동 보정은 관리 영역으로 이동했습니다.

## 1. 실행 방법

Backend는 8050 포트를 권장합니다.

```powershell
cd "C:\Users\minbo\OneDrive\문서\GitHub\agnas-stock-app\mone-web-app\backend"
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8050 --reload
```

Frontend:

```powershell
cd "C:\Users\minbo\OneDrive\문서\GitHub\agnas-stock-app\mone-web-app\frontend"
@'
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8050
'@ | Set-Content .\.env.local -Encoding UTF8
npm install
npm run dev
```

- Frontend: http://localhost:3000
- Backend health: http://127.0.0.1:8050/health
- Backend docs: http://127.0.0.1:8050/docs

## 2. v2.1 수정 내용

### 차트·기술분석

- 대분류 이름은 `차트·기술분석`으로 유지했습니다.
- 실제 캔들/거래량/이동평균선/RSI/MACD/볼린저밴드가 들어올 수 있도록 이름은 유지하되, 현재 중복되는 소분류는 제거했습니다.
- 소분류는 `차트 보기`만 남겼습니다.
- `기술지표`, `지지·저항`, `예측선 / 주문선`은 별도 탭에서 제거했습니다.
- 차트 위에 종목 선택 드롭다운을 배치했습니다.
- 차트 아래의 긴 가격 기준 표는 제거하고, 선택 종목의 현재가/기준가/손절가/목표가/1일·3일·5일 예상가/상태를 요약 카드로 표시합니다.

### 뉴스·기업분석

- `뉴스 요약`, `공시`, `기업분석`만 유지했습니다.
- `종목 내러티브`는 제거했습니다.
- 뉴스 요약은 시장 뉴스만 반복되지 않도록 개별/공시·이슈/반도체/2차전지/시장 순으로 다양화해 표시합니다.
- 공시 데이터가 없을 때는 뉴스를 대신 표시하지 않고 공시 데이터 없음 안내만 보여줍니다.

### 예측·검증 / 관리

- 일반 사용자용 `예측·검증`에는 `확률 예측`만 남겼습니다.
- 확률 예측표는 1일/3일/5일 확률과 예상가를 함께 표시합니다.
- `예측 기록`, `결과 검증`, `실패 복기`, `자동 보정`은 `관리` 영역으로 이동했습니다.
- 향후 관리자 로그인/관리자 모드가 붙으면 `관리` 대분류는 로그인 후에만 표시하도록 확장할 수 있습니다.

### 운용 리포트 / 종목 탐색 / 보유·리스크 유지

v2.0에서 확정한 정리 방향을 유지합니다.

- 시장 홈은 요약 화면 하나로 유지합니다.
- 운용 리포트는 장전 리포트, 장중 체크, 장마감 검증만 유지합니다.
- 장중 체크는 `기준가와 거리`, `구간`, `장중 판단` 중심으로 표시합니다.
- 종목 탐색은 `종목 검색 / 관심`, `오늘 매수 검토`, `매수금지 / 주의` 3개로 유지합니다.
- 후보군은 별도 탭이 아니라 종목 검색 범위에 포함합니다.
- 보유·리스크는 `보유 현황` 하나로 통합합니다.

## 3. 기존 기능 유지

- v1.6 OHLCV 백테스트 연결 유지
- v1.5 watchlist/holdings 백업 후 쓰기 구조 유지
- v1.4 고급 분석 유지
- v1.3 현재가 새로고침 유지
- v1.2 운용 리포트 유지
- v1.1 네비게이션/alias fallback 유지

## 4. 검증 결과

- `python -m compileall mone-web-app/backend/app`: 성공
- `npm run build`: 성공

## 5. 기존 파일 보호 확인

이번 작업은 `mone-web-app/` 폴더 안에서만 진행합니다.

- 기존 `app.py`: 수정하지 않음
- 기존 `reports/`: 수정/삭제/이동하지 않음
- 기존 `data/`, `data/history/`: 수정/삭제/이동하지 않음
- 기존 `watchlist_*.csv`: 수정/삭제/이동하지 않음
- 기존 `candidate_universe_*.csv`: 수정/삭제/이동하지 않음
- 기존 `predictions.csv`: 수정/삭제/이동하지 않음
- 기존 `.github/workflows/`: 수정하지 않음
