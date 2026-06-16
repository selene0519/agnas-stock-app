# MONE 프로젝트 - Claude Code 컨텍스트

## 프로젝트 정체성
MONE은 국장·미장 주식 데이터를 자동 수집하고, 보수/균형/공격 × 단기/스윙/중기
3×3 전략 매트릭스로 매수 후보를 제안하며, 가상운용 검증과 자기개선 루프까지
갖춘 투자 의사결정 보조 앱이다.

---

## 기술 스택

- 백엔드: Python FastAPI (포트 8050)
- 프론트엔드: Next.js + TypeScript + Tailwind CSS (포트 3001)
- 데이터: KIS API (한국투자증권), DART, GNews, Finnhub
- 자동화: GitHub Actions
- 데이터 저장: CSV 파일 기반 (PostgreSQL 미전환)

---

## 핵심 파일 경로

### 백엔드
```
mone-web-app/backend/app/main.py                          ← API 엔드포인트
mone-web-app/backend/app/engine/quant_scanner.py          ← 퀀트 scoring 엔진 (v2)
mone-web-app/backend/app/engine/mone_v65_api_stabilizer.py ← 추천 API 핵심
mone-web-app/backend/app/services/final_engine.py         ← 최종 추천 계산
mone-web-app/backend/app/services/data_loader.py          ← 데이터 로딩
mone-web-app/backend/app/services/quotes.py               ← KIS 현재가 수집
```

### 프론트엔드
```
mone-web-app/frontend/components/pages/HomePage.tsx       ← 3×3 매트릭스 (v2)
mone-web-app/frontend/components/pages/StocksPage.tsx     ← 종목 탐색
mone-web-app/frontend/components/pages/HoldingsPage.tsx   ← 보유 리스크
mone-web-app/frontend/components/pages/ChartPage.tsx      ← 차트
mone-web-app/frontend/lib/api.ts                          ← API 클라이언트
```

### 데이터
```
data/market/ohlcv/kr_{symbol}_daily.csv    ← KR OHLCV (100종목, 매일 갱신)
data/stockapp/kis_current_price_kr.csv     ← KIS 현재가
reports/mone_v36_final_recommendations_kr_{mode}_{horizon}.csv  ← 추천 파일 (18개)
holdings_kr.csv / holdings_us.csv         ← 보유종목 원장
watchlist_kr.csv / watchlist_us.csv       ← 관심종목
```

---

## 현재 상태 (2026-06-04 기준)

### 완료된 것
- V2 Scoring 패치 (quant_scanner.py, mone_v65_api_stabilizer.py, HomePage.tsx)
- OHLCV fallback: 현재가 없으면 OHLCV 최신 close 자동 사용
- 진입가 괴리 15% 초과 시 현재가 기준 자동 재산출
- 전략별 가중치 기반 finalScore 계산, EV(기댓값) 계산 및 표시
- lightweight-charts v4.2.3 다운그레이드 (v5 API 제거 대응)
- holdings_kr/us.csv stopPrice/targetPrice 컬럼 추가
- ATR 기반 진입 계획 UI (ChartPage.tsx)
- 3주 예측 히스토리 + 정확도 통계 패널
- GitHub Secrets KIS 키 설정 완료 (priority 1)
- Actions cron 스케줄 추가 (priority 2)
- 이격도 수렴 신호 추가 (priority 3)
- 기관 순매수 신호 연결 (priority 4)
- **v10.2 누락 API 엔드포인트 28개 일괄 구현 (2026-06-04)**
  - holdings-edit, watchlist-edit (GET/POST)
  - predictions/table, virtual/ledger, virtual/validation
  - validation/dashboard, risk/sector-exposure, risk/benchmark
  - risk/correlation, risk/near-alerts, chart/index/{symbol}
  - portfolio/nav, home/summary (3×3 matrix + 마켓 레짐)
  - sectors, watchlist/groups, watchlist/set-group, watchlist/scored
  - disclosure-calendar, journal (CRUD), health/github, data/audit
  - position/size, kis/token/status
  - final/recommendations-ev-filtered (EV 양수 필터, priority 5)
  - home/summary 내 마켓 레짐 감지 KOSPI/SPY 20일선 기반 (priority 9)

### 미완료 / 이슈
- KIS 현재가: 부분 수집 중 (API 호출 제한 있음)
- 재무 데이터 CSV 매핑 불완전
- 뉴스 감성 분석 미연결 (priority 6)
- 앙상블 모델 5개 (데이터 500건 이상 후, priority 10)

---

## Scoring 로직 (V2)

### 7개 세부 점수 (0~100)
```
upsideScore     상승 여력 (모멘텀 + 이격도)
riskScore       리스크 안정성 (MDD + RSI + ATR)
momentumScore   추세/거래량
entryScore      진입가 접근성 (20일선 이격도)
rrScore         손익비
qualityScore    기업 안정성 (MDD + 60일선 대리)
newsRiskPenalty 뉴스 리스크 감점 (RSI 과열 대리)
```

### 전략별 가중치
```python
conservative: riskScore×0.35 + entryScore×0.20 + rrScore×0.15 + momentumScore×0.15 + qualityScore×0.10 - newsRisk×0.05
balanced:     upsideScore×0.25 + riskScore×0.25 + rrScore×0.20 + momentumScore×0.15 + entryScore×0.10 - newsRisk×0.05
aggressive:   upsideScore×0.35 + momentumScore×0.25 + rrScore×0.15 + entryScore×0.10 + riskScore×0.10 - newsRisk×0.05
```

### 기간별 Price Band
```
short: 손절 -2.5~-5%,  목표 +4~+8%,   최소RR 1.5
swing: 손절 -5~-8%,   목표 +8~+18%,  최소RR 1.8
mid:   손절 -7~-12%,  목표 +15~+30%, 최소RR 2.0
```

---

## API 엔드포인트 주요 목록

```
GET  /health
GET  /api/final/recommendations?market=kr&mode=balanced&horizon=swing
GET  /api/final/portfolio-risk?market=kr&mode=balanced&horizon=swing
GET  /api/chart/{symbol}?market=kr
GET  /api/holdings?market=kr
POST /api/holdings
PATCH /api/holdings/{symbol}
DELETE /api/holdings/{symbol}
GET  /api/watchlist?market=kr
POST /api/watchlist
POST /api/quotes/refresh?market=kr&max_symbols=100
GET  /api/news?market=kr
GET  /api/disclosures?market=kr
GET  /api/advanced/backtest?market=kr
POST /api/advanced/calculator/kelly
POST /api/advanced/monte-carlo
```

---

## 데이터 상태 체계

```
NORMAL        정상 (현재가 live)
PARTIAL       OHLCV close 사용 중
PRICE_PENDING 현재가 수집 대기
DATA_PENDING  OHLCV 30일 미만
STALE         오래된 데이터
FALLBACK      대체 파일 사용
CAUTION       과열/조건 미달 (매수 보류)
```

---

## 추천 카드 응답 구조

```json
{
  "symbol": "058470",
  "name": "리노공업",
  "market": "kr",
  "mode": "balanced",
  "horizon": "swing",
  "currentPrice": 97300,
  "entry": 102165,
  "stop": 95524,
  "target": 115446,
  "probability": 43.7,
  "finalScore": 43.7,
  "riskScore": 50.5,
  "upsideScore": 27.0,
  "momentumScore": 31.7,
  "entryScore": 50.0,
  "rrScore": 47.8,
  "qualityScore": 60.0,
  "expectedValue": 2.02,
  "rrActual": 2.0,
  "evGrade": "양호",
  "strategyTags": ["VOLUME_BREAKOUT"],
  "dataStatus": "PARTIAL",
  "tradeBlockStatus": "OK"
}
```

---

## 전략 태그

```
PULLBACK_BUY     눌림목 매수 (20일선 이격 -2~+5%, RSI<80)
BREAKOUT         52주 신고가 돌파
MOMENTUM         모멘텀 강세 (5일 >3%, 20일 >8%)
LOW_RISK_STABLE  안정형 (MDD>-12%, 60일선 이격>-8%)
VOLUME_BREAKOUT  거래대금 증가
CAUTION          RSI≥80, EV음수, 데이터부족
```

---

## 환경변수 (.env 위치: 레포 루트)

```
KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO
KIS_CANO (앞 8자리), KIS_ACNT_PRDT_CD (뒤 2자리)
KIS_IS_MOCK (false=실전, true=모의)
DART_API_KEY, GNEWS_API_KEY, FINNHUB_API_KEY
SEC_USER_AGENT (이메일)
GITHUB_TOKEN
```

---

## 주의사항

1. **lru_cache**: quant_scanner.py, mone_v65_api_stabilizer.py 수정 후 백엔드 재시작 필수
2. **holdings_kr.csv**: 보유종목 원장, 직접 수정됨. 수정 전 백업
3. **추천 파일**: reports/mone_v36_final_recommendations_*.csv는 GitHub Actions 실행 시만 갱신
4. **V2 패치 확인**: GET /api/final/recommendations 응답에 finalScore, expectedValue 필드 있어야 정상

---

## 다음 작업 우선순위

```
완료: 1.KIS 키 설정 2.Actions 스케줄 3.이격도 수렴 신호 4.기관 순매수
완료: 5.EV 음수 필터 (/api/final/recommendations-ev-filtered)
완료: 7.StocksPage 빠른 스크리닝 프리셋 + 그룹 필터
완료: 8.ATR 기반 진입 계획 UI (ChartPage.tsx)
완료: 9.마켓 레짐 감지 (/api/home/summary 내 KOSPI/SPY 20일선)
완료: 11.마켓 레짐 배너 (HomePage 상단)
완료: 12.감성 뱃지 (HomePage TodayEntryCard·WatchCard, StocksPage 종목카드)
완료: 28개 누락 API 엔드포인트 (v10.2)

다음:
6. 뉴스 감성 분석 (Claude API — ANTHROPIC_API_KEY Render 등록 후 자동 전환)
10. 앙상블 모델 5개 (데이터 500건 이상 후)
```

---

## 개발 로드맵 요약

```
Phase 1 (즉시):   KIS 키 설정, Actions 스케줄
Phase 2 (1~2개월): 재무제표 표준화, 뉴스 감성, 스크리너 고도화
Phase 3 (2~3개월): TradingView 차트, ATR 진입 계획, 알림 시스템
Phase 4 (3~6개월): 앙상블 모델, 백테스팅 6전략, 포트폴리오 최적화
Phase 5 (6개월+):  사용자 인증, PostgreSQL, Paper Trading
```
