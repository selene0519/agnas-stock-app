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
mone-web-app/backend/app/main.py                          ← API 엔드포인트 (전체 목록)
mone-web-app/backend/app/engine/quant_scanner.py          ← 퀀트 scoring 엔진 (v2)
mone-web-app/backend/app/engine/mone_v65_api_stabilizer.py ← 추천 API 핵심
mone-web-app/backend/app/services/final_engine.py         ← 최종 추천 계산
mone-web-app/backend/app/services/data_loader.py          ← 데이터 로딩
mone-web-app/backend/app/services/quotes.py               ← KIS 현재가 수집
mone-web-app/backend/app/services/virtual_trade_journal.py ← VTJ 서비스
```

### 프론트엔드
```
mone-web-app/frontend/components/pages/HomePage.tsx       ← 3×3 매트릭스 (v2)
mone-web-app/frontend/components/pages/StocksPage.tsx     ← 종목 탐색
mone-web-app/frontend/components/pages/HoldingsPage.tsx   ← 보유·리스크
mone-web-app/frontend/components/pages/ChartPage.tsx      ← 차트 + ATR 진입계획
mone-web-app/frontend/components/pages/AdvancedPage.tsx   ← 전략도구 5탭 (스크롤)
mone-web-app/frontend/components/pages/VirtualJournalPage.tsx ← 매매일지 (VTJ)
mone-web-app/frontend/components/pages/AdminPage.tsx      ← 관리자 5탭
mone-web-app/frontend/components/BottomNav.tsx            ← 모바일 하단 내비
mone-web-app/frontend/lib/api.ts                          ← API 클라이언트
```

### 데이터
```
data/market/ohlcv/kr_{symbol}_daily.csv    ← KR OHLCV (100종목, 매일 갱신)
data/stockapp/kis_current_price_kr.csv     ← KIS 현재가
reports/mone_v36_final_recommendations_kr_{mode}_{horizon}.csv  ← 추천 파일 (18개)
data/kis_2_holdings_kr.csv / holdings_us.csv  ← 보유종목 원장
data/signal_ledger.csv                     ← 예측 신호 원장
reports/virtual_prediction_ledger.csv      ← VTJ 가상 체결 원장
```

---

## 현재 상태 (2026-06-18 기준)

### 완료된 Phase 목록

#### Phase 1 · 기반 인프라
- KIS API 키 설정 + GitHub Secrets 등록
- GitHub Actions cron 스케줄 (mone-auto-accumulator.yml)
- Actions 내 주간 KR 재무데이터 fetch (scripts/fetch_kr_financial_data.py, 월요일 실행)
- OHLCV fallback: 현재가 없으면 OHLCV 최신 close 자동 사용
- 진입가 괴리 15% 초과 시 현재가 기준 자동 재산출

#### Phase 2 · 스코어링 & 탐색
- V2 Scoring (7개 세부 점수, 전략별 가중치)
- EV(기댓값) 계산 및 표시
- 이격도 수렴 신호, 기관 순매수 신호
- EV 음수 필터 (/api/final/recommendations-ev-filtered)
- 마켓 레짐 감지 (KOSPI/SPY 20일선 → RISK_ON/RISK_OFF/NEUTRAL)
- 뉴스 감성 분석: ANTHROPIC_API_KEY 있으면 Claude API, 없으면 keyword fallback
- StocksPage 빠른 스크리닝 프리셋 + 그룹 필터
- 감성 뱃지 (HomePage TodayEntryCard·WatchCard, StocksPage 종목카드)

#### Phase 3 · 차트 & 알림
- lightweight-charts v4.2.3 (v5 API 제거 대응)
- ATR 기반 진입 계획 UI (ChartPage.tsx)
- holdings_kr/us.csv stopPrice/targetPrice 컬럼
- Telegram 알림 설정 (AlertsPanel, HoldingsPage 내 아코디언)

#### Phase 4 · 앙상블 & 포트폴리오
- 앙상블 5모델 (M1전략·M2리스크·M3모멘텀·M4밸류·M5레짐 가중 앙상블)
- 백테스팅 (AdvancedPage BacktestPanel)
- 포트폴리오 최적화 (PortfolioOptimizePanel, HoldingsPage 내 아코디언)
- 3주 예측 히스토리 + 정확도 통계 패널
- v10.2 누락 API 엔드포인트 28개 일괄 구현 (2026-06-04)

#### Phase 5 · 인증
- Google / Kakao OAuth: `/api/auth/oauth/{provider}/start|callback` 구현 완료
- 관리자 로그인: `/api/auth/admin-login`
- BottomNav 더보기: 로그인 버튼 (미로그인) / 유저 프로필 + 로그아웃 (로그인 시)
- DB 연동 완료 (2026-06-18): `db.py`에 `users` 테이블 추가, OAuth 콜백에서 `upsert_user()`로
  프로필 영속화. 로그인 시 익명 UUID(localStorage)의 holdings/watchlist/broker_connections를
  `migrate_user_data()`로 실제 user_id에 병합(기존 로그인 데이터 우선, old 쪽 폐기) — 익명 상태로
  쌓은 데이터가 로그인 후 고아 데이터가 되는 문제 해결. state 파라미터에 `anonId` 서명 포함(HMAC),
  프론트 `getUserId()`로 OAuth start 호출 시 전달.

#### VTJ (Virtual Trade Journal)
- 가상 체결 원장 (immutable snapshots, conservative fill model)
- 실패 태그: REGIME_MISMATCH, SECTOR_WEAKNESS, POSITION_SIZE, MARKET_GAP, STOP_TOO_TIGHT
- 소스 타입: FORWARD_PAPER_TRADE(1.0) / MANUAL_REVIEWED(1.2) / HISTORICAL_REPLAY(0.3~0.5)
- 복기 버튼: FORWARD_PAPER_TRADE + EVALUATED → MANUAL_REVIEWED 승격 (보정 가중치 1.2)
- 분석 패널: regime_transition, confidence_breakdown, entry_type_comparison, source_comparison
- API: POST /api/journal/virtual-trades/{journal_id}/review, GET /api/journal/analytics

---

## 내비게이션 구조

### 모바일 BottomNav
```
[홈] [탐색] [보유] [분석]  [더보기 ▼]
                         ┌──────────────────────────────────────┐
                         │ 트레이딩  모의투자·AI매매일지·계산기 등  │
                         │ (관리자 - 어드민 로그인 시 표시)         │
                         │ [로그인 / 유저 프로필]                  │
                         └──────────────────────────────────────┘
```

### 페이지별 주요 기능
| PageId | 파일 | 주요 기능 |
|--------|------|-----------|
| home | HomePage.tsx | 3×3 매트릭스, 마켓 레짐 배너, EV 카드 |
| stocks | StocksPage.tsx | 퀀트 스캐너, 프리셋, 그룹 필터, 감성 뱃지 |
| holdings | HoldingsPage.tsx | 보유 리스크, 현금입력, 포트폴리오·알림(아코디언) |
| chart | ChartPage.tsx | 종목 차트, ATR 진입계획 |
| advanced | AdvancedPage.tsx | 모의투자·AI매매일지·계산기·몬테카를로·전략검증 (5탭, 드롭다운) |
| admin | AdminPage.tsx | 운영·예측분석·뉴스공시·자가보정 (4탭) |

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
GET  /api/final/recommendations-ev-filtered
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
GET  /api/advanced/correlation
GET  /api/home/summary
GET  /api/journal/virtual-trades
POST /api/journal/virtual-trades/{journal_id}/review
GET  /api/journal/analytics
GET  /api/admin/sync-status
POST /api/admin/sync-now
POST /api/admin/clear-cache
GET  /api/correction/dashboard
GET  /api/correction/preview
POST /api/correction/rebuild
GET  /api/auth/oauth/{provider}/start
GET  /api/auth/oauth/{provider}/callback
POST /api/auth/admin-login
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
ANTHROPIC_API_KEY  ← Render 미등록 시 keyword fallback 사용
SEC_USER_AGENT (이메일)
GITHUB_TOKEN
```

---

## 주의사항

1. **lru_cache**: quant_scanner.py, mone_v65_api_stabilizer.py 수정 후 백엔드 재시작 필수
2. **holdings_kr.csv**: 보유종목 원장, 직접 수정됨. 수정 전 백업
3. **추천 파일**: reports/mone_v36_final_recommendations_*.csv는 GitHub Actions 실행 시만 갱신
4. **VTJ 원장**: reports/virtual_prediction_ledger.csv — 불변 스냅샷, 직접 수정 금지
5. **V2 패치 확인**: GET /api/final/recommendations 응답에 finalScore, expectedValue 필드 있어야 정상

---

## 남은 작업

```
- ANTHROPIC_API_KEY Render 등록 → Claude API 감성 분석 활성화
- localStorage → PostgreSQL DB 연동 (Phase 5 마무리)
```

### 완료 확인 (2026-06-18)
- 보정 테이블(run_ensemble_calibration): mone-walkforward.yml이 매주 토요일 자동 실행,
  18개 조합(KR/US × 3모드 × 3기간) 모두 470~1113건으로 갱신 완료, quant_scanner.py의
  ensemble_score_v2에서 실시간 로드/적용 중. walk-forward 구조 + self_correction_v2의
  point-in-time 가드로 미래 데이터 누출 불가능.
