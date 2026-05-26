# MONE Web App

> v3.0: 첫 화면 보수/균형/공격 3모드 비교 카드, 선택 모드별 후보, 종목 상세 패널 확장(종목뉴스·공시/IR·EPS·주요재무·연간/분기실적·ESG·리서치 자리), 기본 API 포트 8050 정리, 버전 표기 정리.

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


## v3.0 데이터 산출 업그레이드

- 확률/예상가가 비어 있을 때 현재가, OHLCV, 신뢰도, 기준가와 거리로 단기/스윙/중기 값을 임시 산출합니다.
- 장전 리포트의 예상 시초가/예상 종가가 비어 있으면 OHLCV 갭 평균과 최근 수익률로 보강합니다.
- 차트 보기에서 OHLCV CSV를 감지해 종가, MA5, MA20, 볼린저밴드, RSI, MACD 계산값을 표시합니다.
- 자동화 상태 화면은 GitHub Actions API를 조회합니다. private repo는 `.env`에 `MONE_GITHUB_TOKEN` 또는 `GITHUB_TOKEN`이 필요합니다.
- 후보 카드에 예상 매수가 기준 손실/이익 계산을 표시합니다. 자동주문 기능은 없습니다.

## v3.0 virtual operation upgrade

- Added portfolio-level virtual operation summary endpoint: `GET /api/virtual/portfolio?market=kr|us&mode=conservative|balanced|aggressive`.
- Recommendation/virtual operation modes now support conservative, balanced, and aggressive operation assumptions.
- Virtual preview rows include execution possibility so a recommended stock is not treated as automatically bought.
- Probability screen includes account-level virtual operation cards: max positions, per-position capital, expected max loss, expected target profit, and cash left after integer share sizing.
- Stock detail card now shows prediction line and virtual operation line together.

Virtual operation is for simulation and calibration only. It does not place orders.

## v3.0 데이터 연결/공시 수집/차트 QA 업데이트

- `POST /api/disclosures/refresh?market=kr|us|all&days=30` 추가
  - 국장: DART 공시 목록 수집 후 `data/disclosures/disclosures_kr.csv` 생성
  - 미장: Finnhub filings API 기반 SEC filing 수집 후 `data/disclosures/disclosures_us.csv` 생성
- 공시 탭에서 공시 CSV가 없을 때 수집 버튼으로 수집을 시도할 수 있습니다.
- 기업분석 로더를 보강했습니다.
  - company_integrated, company, financial, fundamental, flow 계열 CSV를 최신 파일 우선으로 병합합니다.
  - EPS, PER, PBR, ROE, 매출, 영업이익, 순이익, 연간실적, 분기실적, ESG, 리서치 필드를 화면에 연결합니다.
- 첫 화면 뉴스는 시장·섹터·수급 뉴스 중심으로 우선 표시하고, 개별 종목 뉴스는 종목 상세 패널에서 우선 확인하도록 정리했습니다.
- 차트 화면은 OHLCV 기반 MA5/MA20/MA60, 볼린저밴드, RSI, MACD, 거래량 계산 상태를 함께 표시합니다.


## v3.0 기록 저장 / 자동 보정 준비

이번 버전은 미장/국장 자동 업데이트가 돌 때 예측값과 가상 운용 값을 바로 기록할 수 있도록 아래 기능을 추가합니다.

- `data/history/virtual_operation_history.csv`에 보수/균형/공격 가상 운용 스냅샷 저장
- `data/history/prediction_snapshot_history.csv`에 예측 스냅샷 저장
- 기존 `predictions.csv`, `prediction_history.csv`, `outcome_history.csv`를 활용한 backfill 지원
- `data/history/virtual_operation_evaluation.csv`에 outcome 매칭 평가 저장
- `data/history/auto_correction_summary.csv`에 모드별/스윙군별 보정 요약 저장

### 즉시 기록 생성

```powershell
cd "C:\Users\minbo\OneDrive\문서\GitHub\agnas-stock-app\mone-web-app\backend"
python .\record_operation_history.py --market all --modes all --source manual --backfill-existing
```

### API

- `POST /api/history/snapshot?market=all&modes=all&source=manual&backfill_existing=true`
- `POST /api/history/backfill?market=all&modes=all`
- `POST /api/history/evaluate`
- `GET /api/history/files`
- `GET /api/history/virtual-operations`
- `GET /api/history/prediction-snapshots`
- `GET /api/history/auto-correction`

### GitHub Actions 자동 기록 연결

`mone-auto-accumulator.yml`의 cloud update step 이후에 아래 실행을 추가하면 스케줄 실행 때마다 기록이 쌓입니다.

```yaml
      - name: Record virtual operation history
        run: |
          python mone-web-app/backend/record_operation_history.py --market all --modes all --source github-actions --backfill-existing
```
