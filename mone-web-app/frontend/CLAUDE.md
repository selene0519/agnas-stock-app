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
- 데이터 저장: CSV 파일 기반 + Supabase 동기화 코드 연결됨(`supabase_db.py`),
  단 `.env`에 SUPABASE_URL/SUPABASE_KEY 미설정으로 현재 비활성 (2026-06-27 확인)

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

## 현재 상태 (2026-06-18 기준, 일부 항목 2026-06-27 갱신 — 아래 날짜 표시된 항목만 최신)

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

#### Phase 5 · 인증 + 동기화
- Google / Kakao OAuth: `/api/auth/oauth/{provider}/start|callback` 구현 완료
- 관리자 로그인: `/api/auth/admin-login`
- BottomNav 더보기: 로그인 버튼 (미로그인) / 유저 프로필 + 로그아웃 (로그인 시)
- 보유종목/관심종목 Supabase 동기화: `user_data.py`(upsert/delete) ↔ `supabase_db.py`,
  서버 시작 시 `auto_sync.py`가 `pull_to_csv()` 호출 — **코드는 완료, 연결은 미완**
  (SUPABASE_URL/SUPABASE_KEY를 .env에 채우기만 하면 동작. 기존 메모에 있던
  Supabase 프로젝트 `tzbwktslzquogjvfllpl` 키를 등록하면 끝)

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
4. **VTJ 원장**: reports/virtual_prediction_ledger.csv — `scripts/settle_pending_validations.py`가
   매일 자동 정산함(상태: PENDING/WIN/LOSS/CLOSED/NOT_EXECUTED/INVALID_SYMBOL/EXPIRED).
   이 스크립트 밖에서 손으로 행을 고치지 말 것 — predictionId 누락/파편 행이 과거에
   섞여 들어온 적 있어 `_sanitize_ledger_rows()`가 매 실행마다 정리함 (2026-06-27)
5. **V2 패치 확인**: GET /api/final/recommendations 응답에 finalScore, expectedValue 필드 있어야 정상
6. **BEAR 레짐 = 공격형 추천 전부 비활성화**: `generate_kr/us_recommendations.py`가 의도적으로
   aggressive_{short,swing,mid} 추천 파일을 비운다 (정상 동작, 버그 아님). `_write_csv(path, [], force=True)`
   를 써야 실제로 비워짐 — force 없이는 "결과 0건이면 기존 파일 보존" 가드 때문에 약세장 진입 전
   추천이 그대로 남는 버그가 있었음 (2026-06-27 수정)

---

## 남은 작업 (2026-06-27 기준)

```
- ANTHROPIC_API_KEY Render 등록 → Claude API 감성 분석 활성화
- 백테스트 데이터 500건+ 후 보정 테이블 재생성 (run_ensemble_calibration 호출)
- Supabase SUPABASE_URL/SUPABASE_KEY를 .env에 등록 (코드는 이미 완료, Phase 5 마무리는
  키 등록만 남음 — 프로젝트 tzbwktslzquogjvfllpl)
- 매물대 압축(Phase 6) 계산 로직 미발견 — 토글(toggles.supply)은 있는데 실제 계산부 확인 필요
- 손절지연(추격매수 반대 패턴) 행동분석 미시작
- 유료 전환/구독 게이팅 미시작
- mid 호라이즌 9전략 표본 누적 대기 중 (가장 빠른 마감일 2026-06-30, 그 전까진 정상)
- US conservative/balanced 추천이 RSI/거래량 밴드 때문에 가뭄(2~12건) — aggressive는 20건
  꽉 참. 의도된 차등인지 밴드가 너무 좁은지 추가 검토 필요
- strategy_win_rates.json 첫 실측치 나옴(194건, 전체승률 32.5%) — 6/2~6/12 예측 기준이라
  이후 적용된 섹터캡/상관위험/regime 보정을 반영 못 함. 표본이 더 쌓여야 신뢰 가능
```
