# MONE 앱 완전 가이드

---

## 1. 전체 구조

```
agnas-stock-app/
├── mone-web-app/
│   ├── backend/                  ← Python FastAPI 서버 (포트 8050)
│   │   └── app/
│   │       ├── main.py           ← API 엔드포인트 등록
│   │       ├── engine/           ← 핵심 로직 엔진
│   │       │   ├── mone_v65_api_stabilizer.py  ← 추천 API 핵심
│   │       │   ├── quant_scanner.py             ← 퀀트 scoring (v2 패치)
│   │       │   ├── mone_v77_holdings_risk.py    ← 보유종목 리스크
│   │       │   ├── mone_v802_holdings_clean.py  ← 보유종목 정제
│   │       │   └── backtest.py / risk.py 등
│   │       └── services/
│   │           ├── final_engine.py   ← 최종 추천 계산
│   │           ├── data_loader.py    ← CSV/JSON 데이터 로딩
│   │           ├── quotes.py         ← KIS/Finnhub 현재가 수집
│   │           └── user_data.py      ← 관심/보유종목 저장
│   └── frontend/                 ← Next.js 앱 (포트 3001)
│       ├── app/page.tsx          ← 루트 페이지
│       ├── components/pages/     ← 각 화면 컴포넌트
│       └── lib/api.ts            ← 백엔드 API 클라이언트
├── data/
│   ├── market/ohlcv/             ← 일별 OHLCV CSV (KR 100종목, US 다수)
│   ├── stockapp/                 ← KIS 현재가 스냅샷
│   └── fundamental/              ← 재무 데이터
├── reports/                      ← 추천/검증/리포트 CSV
│   ├── mone_v36_final_recommendations_kr_balanced_swing.csv  ← 추천 파일 (18개)
│   ├── kis_current_price_kr.csv  ← KIS 현재가
│   └── kr_close_ohlcv_*.csv     ← OHLCV 갱신 상태
├── watchlist_kr.csv / watchlist_us.csv   ← 관심종목
├── holdings_kr.csv / holdings_us.csv     ← 보유종목 원장
└── .github/workflows/
    └── mone-auto-accumulator.yml  ← GitHub Actions 자동화
```

---

## 2. 데이터 흐름

```
[GitHub Actions / 수동 실행]
        ↓
KIS API → kis_current_price_kr.csv (현재가)
FinanceDataReader → data/market/ohlcv/kr_*_daily.csv (OHLCV)
DART API → data/disclosures/ (공시)
GNews API → data/news/ (뉴스)
        ↓
[백엔드 서버 실행 중]
        ↓
final_engine.py → reports/mone_v36_final_recommendations_*.csv 읽기
quant_scanner.py → OHLCV로 지표 계산 → finalScore, EV 산출
mone_v65_api_stabilizer.py → 현재가 매핑 + 가격 재산출
        ↓
API 응답 → 프론트엔드
        ↓
HomePage 3×3 매트릭스 표시
```

---

## 3. 핵심 API 엔드포인트

| 엔드포인트 | 역할 | 파라미터 |
|---|---|---|
| `GET /api/final/recommendations` | 3×3 추천 핵심 API | market, mode, horizon |
| `GET /api/final/conditional-executions` | 조건부 실행 요약 | market, mode, horizon |
| `GET /api/final/prediction-validation` | 예측 검증 결과 | market |
| `GET /api/final/trade-validation` | 매매 검증 | market, mode, horizon |
| `GET /api/final/portfolio-risk` | 포트폴리오 리스크 | market, mode, horizon |
| `GET /api/market/summary` | 시장 요약 | market |
| `GET /api/chart/{symbol}` | 차트 OHLCV | symbol, market |
| `GET /api/holdings` | 보유종목 조회 | market |
| `POST /api/holdings` | 보유종목 추가 | body: {symbol, market, quantity, avgPrice} |
| `PATCH /api/holdings/{symbol}` | 보유종목 수정 | symbol, body |
| `DELETE /api/holdings/{symbol}` | 보유종목 삭제 | symbol, market |
| `GET /api/watchlist` | 관심종목 조회 | market |
| `POST /api/watchlist` | 관심종목 추가 | body |
| `DELETE /api/watchlist/{symbol}` | 관심종목 삭제 | symbol, market |
| `POST /api/quotes/refresh` | KIS 현재가 수집 | market, max_symbols |
| `GET /api/news` | 뉴스 | market |
| `GET /api/disclosures` | 공시 | market |
| `GET /api/advanced/backtest` | 백테스트 | market |
| `GET /api/advanced/scanner` | 퀀트 스캐너 | market |
| `POST /api/advanced/calculator/kelly` | 켈리 기준 계산 | body |
| `POST /api/advanced/monte-carlo` | 몬테카를로 | body |
| `GET /health` | 서버 상태 확인 | - |

---

## 4. 화면 구성 (프론트엔드)

| 페이지 | 파일 | 핵심 기능 |
|---|---|---|
| 시장 홈 | HomePage.tsx | 3×3 전략 매트릭스, 보유종목 요약, 국장/미장 자동전환 |
| 종목 탐색 | StocksPage.tsx | 종목 검색, 관심/보유 등록, 매수 검토 목록 |
| 보유·리스크 | HoldingsPage.tsx | 보유종목 관리, 손절/목표 근접도, 포트폴리오 위험도 |
| 운용 리포트 | ReportPage.tsx | 장전/장중/장마감, 가상운용, 검증 결과 |
| 차트·기술분석 | ChartPage.tsx | 캔들차트, 이동평균, RSI, MACD, 볼린저 |
| 뉴스·기업분석 | NewsPage.tsx | 뉴스, 공시, 재무 지표 |
| 예측·검증 | PredictionPage.tsx | 확률 예측, 결과 검증, 실패 복기 |
| 고급분석 | AdvancedPage.tsx | 퀀트 스캐너, 백테스트, 몬테카를로, 켈리 계산기 |
| 관리 | AdminPage.tsx | 데이터 상태, GitHub 동기화, 오류 로그 |

---

## 5. 추천 로직 흐름

```
① reports/mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv 읽기
        ↓
② 현재가 매핑
   우선순위: KIS 실시간 → OHLCV 최신 close (fallback)
        ↓
③ quant_scanner.py → apply_quant_overlay()
   OHLCV 로드 → 지표 계산 (RSI, ATR, MDD, 이격도, 모멘텀)
   → _compute_sub_scores() → 7개 세부 점수
   → _score() → 전략별 가중합 → finalScore
   → EV(기댓값) 계산
   → 진입가 괴리 15% 초과 시 현재가 기준 재산출
        ↓
④ 추천 카드 반환
   finalScore, riskScore, upsideScore, momentumScore,
   entryScore, rrScore, qualityScore, expectedValue, rrActual
```

---

## 6. 전략별 scoring 기준 (v2 패치 적용 후)

### 가중치

| 점수항목 | 보수형 | 균형형 | 공격형 |
|---|---|---|---|
| upsideScore (상승여력) | 0% | 25% | 35% |
| riskScore (안정성) | 35% | 25% | 10% |
| momentumScore (모멘텀) | 15% | 15% | 25% |
| entryScore (진입접근성) | 20% | 10% | 10% |
| rrScore (손익비) | 15% | 20% | 15% |
| qualityScore (기업안정) | 10% | 0% | 0% |
| newsRiskPenalty (리스크감점) | -5% | -5% | -5% |

### 기간별 가격 밴드

| 기간 | 손절폭 | 목표수익 | 최소 RR |
|---|---|---|---|
| 단기 (1~3일) | -2.5% ~ -5% | +4% ~ +8% | 1.5 |
| 스윙 (5~15일) | -5% ~ -8% | +8% ~ +18% | 1.8 |
| 중기 (20~60일) | -7% ~ -12% | +15% ~ +30% | 2.0 |

---

## 7. 데이터 파일 역할

| 파일 | 역할 | 갱신 주기 |
|---|---|---|
| `reports/mone_v36_final_recommendations_kr_{mode}_{horizon}.csv` | 9개 조합 추천 파일 | GitHub Actions |
| `data/market/ohlcv/kr_{symbol}_daily.csv` | 일별 OHLCV | GitHub Actions 매일 |
| `data/stockapp/kis_current_price_kr.csv` | KIS 실시간 현재가 | GitHub Actions / 수동 |
| `reports/intraday_realtime_snapshot_kr.csv` | 장중 스냅샷 | GitHub Actions |
| `holdings_kr.csv` | 보유종목 원장 | 사용자 수동 입력 |
| `watchlist_kr.csv` | 관심종목 | 사용자 수동 입력 |
| `data/stockapp/kis_collection_targets_kr.csv` | KIS 수집 대상 목록 | 자동 갱신 |
| `predictions.csv` | 예측 기록 | GitHub Actions |

---

## 8. 현재 데이터 현황 (2026-06-01 기준)

```
KR OHLCV:      100종목  ← 2026-06-01 최신 (FinanceDataReader)
US OHLCV:      다수 종목 ← 정상
KIS 현재가:    9종목    ← 미완 (Actions secrets 설정 필요)
추천 파일:     18개     ← KR 9개 + US 9개 정상
OHLCV fallback: 작동 중  ← 현재가 없으면 OHLCV close 사용
```

### KIS 현재가 9종목만 있는 이유
GitHub Actions secrets에 KIS 키가 완전히 연결되지 않아서
수동 새로고침된 9종목만 남아 있음.

**해결**: GitHub → Settings → Secrets → Actions에
KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO 입력 후
Actions 수동 실행 → 100종목 자동 수집

---

## 9. 주요 상태값

| 상태 | 의미 |
|---|---|
| NORMAL | 정상 데이터, 현재가 있음 |
| PARTIAL | 일부 데이터 보강됨 (OHLCV close 사용 등) |
| PRICE_PENDING | 현재가 수집 대기 |
| DATA_PENDING | OHLCV 30거래일 미만 |
| STALE | 오래된 데이터 |
| NO_DATA | 원본 없음 |
| FALLBACK | 요청한 전략/기간 파일 없어 대체 소스 사용 |

---

## 10. 전략 태그

| 태그 | 조건 |
|---|---|
| 눌림목 매수 (PULLBACK_BUY) | 20일선 이격도 -2% ~ +5%, RSI < 80 |
| 모멘텀 강세 (MOMENTUM) | 5일 모멘텀 > 3% 또는 20일 모멘텀 > 8% |
| 거래대금 증가 (VOLUME_BREAKOUT) | 거래대금 값 존재 |
| 안정형 (STABLE_LOW_RISK) | MDD > -12%, 60일선 이격도 > -8% |
| 주의 (CAUTION) | RSI ≥ 80, 데이터 부족, EV 음수 |

---

## 11. 포트 정보

```
백엔드: http://localhost:8050
프론트엔드: http://localhost:3001
API 프록시: /mone-api → localhost:8050 (Next.js rewrites)
```

---

## 12. 시장 자동 전환 기준 (KST)

```
09:00 ~ 15:30 → 국장 (KR)
15:30 이후    → 미장 (US)
22:30 ~ 05:00 → 미장 장중
```

---

## 13. 알아야 할 핵심 주의사항

### lru_cache
`mone_v65_api_stabilizer.py`와 `quant_scanner.py`에 `@lru_cache` 사용.
코드 수정 후 **반드시 백엔드 재시작** 필요. 재시작 없으면 변경사항 반영 안 됨.

### 추천 파일 갱신 주기
`reports/mone_v36_final_recommendations_*.csv`는 GitHub Actions가 돌 때만 갱신됨.
Actions를 자주 실행할수록 추천 품질이 올라감.

### 진입가 vs 현재가 괴리
추천 파일의 진입가는 Actions 실행 시점 기준.
현재가가 많이 변했으면 진입가가 구식일 수 있음.
→ v2 패치에서 15% 초과 괴리 시 자동 재산출 적용됨.

### holdings_kr.csv
보유종목 원장 파일. 앱에서 추가/수정/삭제할 때 이 파일이 직접 수정됨.
백업 권장.

### GitHub Actions 실행 횟수
무료 계정은 월 2,000분 제한.
현재 workflow 1회 실행 약 5~10분.
월 200~400회 실행 가능.

---

## 14. 다음 개발 우선순위 (현재 기준)

```
1. GitHub Secrets KIS 키 설정 → 현재가 100종목 자동 수집
2. Actions 스케줄 설정 (현재 수동 실행만) → 장 마감 후 자동 실행
3. 추천 파일 생성 로직 개선 → OHLCV + 지표 기반으로 재산출
4. 전략별 결과 추적 시작 → 성과 보정 루프
5. 뉴스/공시 감성 점수 연결 → newsRiskPenalty 실제화
```

---

## 15. 자주 쓰는 진단 명령

```powershell
# 서버 상태 확인
curl http://localhost:8050/health

# 추천 API 직접 확인
curl "http://localhost:8050/api/final/recommendations?market=kr&mode=balanced&horizon=swing"

# 현재가 수동 새로고침
curl -X POST "http://localhost:8050/api/quotes/refresh?market=kr&max_symbols=100"

# 데이터 상태 확인
curl http://localhost:8050/api/status
```
