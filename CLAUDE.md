# MONE — 세션 메모리 / 북극성 (2026-07-10 갱신)

> 새 세션은 이 파일을 먼저 읽고 이어서 작업할 것.
> 2026-07-10 로드맵 세션에서 다음작업 #1~5,8 처리(아래 상태표). 남은 큰 항목=#6 UI 감사·#7 모바일.
> (프론트 상세 문서는 `mone-web-app/frontend/CLAUDE.md` 참고)

## 앱의 목적 (북극성)
**자가보정형 AI 퀀트 의사결정 앱.** 차트패턴·공시·수급·이벤트·재무·뉴스를 활용해
매수 후보를 제안하고, 가상매매(paper/VTJ)로 성과를 검증해 스스로 보정한다.
- **실제 자동주문은 하지 않는다**(브로커 read-only). "실전"=사람이 실행하는 의사결정 보조.
- **배포 목적 아님.** 개인용 정확도/신뢰도 향상이 목표.
- 목표는 "수익 보장"이 아니라 **예측 오차를 줄여 손익 비대칭(손실↓·수익↑)을 개선**하는 것.

## "완벽"의 합격선 (사용자와 합의)
- (A) 코드/구조/UI가 목적에 맞게 완결 + 엣지를 **정직하게 측정·표시** → 보장 가능.
- (B) out-of-sample 기댓값 (+) → 노력하되 시장이 좌우, **보장 불가**.
- 갈아엎기 허용. 단 **측정 우선 → 핵심만 클린 재구축 → 작동하는 건 보존 → 엣지 입증** 순서.
  (이 레포는 v40~v92 패치 누더기가 심함. 무계획 빅뱅 리라이트 = v93 하나 더 얹는 것 = 금지.)

## 이번 세션에 고친 것 (브랜치에 커밋·푸시됨)
1. `b0fda86` 9전략 시간초과: `generate_kr_recommendations.py` ModuleNotFoundError(=`sys.path`에 레포 루트 누락)로 KR 추천 생성이 6/26부터 조용히 실패 → 수정.
2. `8d863cd` NAV를 CI에 연결 + 보유 종목 종가 수집 유니버스에 브로커 원장 추가(6/30 동결 해소). `update_portfolio_nav.py`가 실제 원장(kis_2/toss)을 읽도록.
3. `a4abc76` 유령 보유 009150(삼성전기, 실보유 아님) 제거 + NAV 시리즈 일관 기준 재계산(누적수익률 -90% 절벽 해소).
4. `2668561` USD/KRW 환율 반영(NAV·보유). `fetch_benchmark_data.py`가 `fx_USDKRW_daily.csv` 수집, seed 1477.6. 혼합통화 요약(mixedCurrency/marketBreakdown) + `/api/exchange-rate` 로컬 CSV 폴백.
5. `5eb8ef6` 보유 종목 KIS 라이브 시세 수집 대상에 포함(현재가 6/30 고정 해소) + 요약카드 환율합산 + aria-label.
6. `d13d0ad` 탐색 빈 렌즈 안내: 같은 조합의 결과 많은 다른 렌즈로 안전 점프 + 렌즈↔전략 관계 문구.

## 핵심 진단 결과 (신뢰도/정확도)
- **자가보정 루프는 실제로 돎**: 캡처→정산→OLS 팩터귀속(`factor_attribution.json`)→필터보정(`factor_based_filter_adjustments.json` APPLIED). 피처(수급·공시·재무·뉴스·이벤트·패턴·섹터) 전부 추천에 들어감. **입력·검증 인프라는 갖춰짐.**
- **그러나 실측 기댓값 = −0.89%/거래** (238건 정산 당시): 평균이익 +1.70% < 평균손실 −2.15%, RR 0.79, 승률 33%.
- ⚠️**2026-07-10 재측정(1644건)**: 음의 엣지는 "항상"이 아니라 **장세 조건부**(강세기 +0.2%/약세기 −3.4%, 풀링 −1.6~−2%). 원인은 exit 관리가 아니라 **선택(진입) 오차** — 승률 32~36%/RR~1.16. 모델 probability·EV는 anti-predictive(finalScore만 유효). → 라이브 롤링 보정 도입(#3).

## 다음 작업 (우선순위 순) — ⬇️ 2026-07-10 로드맵 세션 상태 반영
1. ✅ **[해결·반증] exit 일봉 판정 편향** — `_find_exit`가 같은날 양쪽터치→강제손절하나, 측정 결과 **전체의 1.1%뿐, EV 보정 천장 +0.09%p**. 분봉 재판정 인프라는 가치 없음 → 착수 안 함. **−2%/거래 음의 엣지는 측정 착시 아니라 실재.**
2. ✅ **[마커 추가] 깨끗한 표본 재축적** — 데이터 fix가 origin/main 반영, recommendations_kr 2026-07-10부터 정상. `reports/clean_window_marker.json`(cleanWindowStart=2026-07-10) 추가 — 배치 분석은 이 컷오프 사용. 표본 축적 자체는 시간 필요(진행중).
3. ✅ **[완료] 엣지 진단 = 부품 분리** — 음의 엣지는 **장세 조건부**(강세 +0.2%/약세 −3.4%). 모델 probability·EV는 **anti-predictive**, finalScore만 순위 스킬. 서빙 calibratedWinRate 이중 낙관(백테44~55%+하드코딩 공식 폴백) → **라이브 VTJ 롤링 보정** 도입(PR #116, shadow). 상세 [`memory/project_selection_edge_diagnosis`].
4. ✅ **[완료] 조용한 실패 + 신선도 경보** — `scripts/data_freshness_healthcheck.py`(임베디드 날짜 검사 + 상태JSON ERROR 스텝 재귀 탐지 → `reports/data_freshness_status.json`, critical 노후시 exit1) + `mone-settle-validations`에 헬스게이트 스텝 + 텔레그램 경보 배선.
5. ✅ **[disclosure] 생존편향/룩어헤드** — 룩어헤드(가격)는 walk-forward cutoff_date로 **처리됨**. 생존편향은 universe가 현재 상장 심볼 glob뿐이라 **실재**(상폐/제외 부재, point-in-time 상장필터 미적용) → `run_walkforward` 반환 `dataQuality`에 정직 disclosure. 완전 수정은 상폐 OHLCV 이력 수집 필요(미보유) → **실용 해법=생존편향 없는 라이브 VTJ 보정 참조**.
6. ✅**[2026-07-26 완료: 터치타깃·기계코드]** 앱을 375x812로 실제 구동해 홈·탐색·보유·분석 4개 화면 계측 → 44px 위반 **전부 0**. 실측 위반이 홈 4·탐색 7·보유 7·분석 9건 있었다(**"보유만 44px 완료"는 오해였음** — 보유에 인라인 링크 16px짜리 2개 포함). 분석 화면 종목검색 combobox는 **접근가능한 이름이 아예 없었다** → aria-label 추가. `statusLabel`이 미매핑 코드를 그대로 반환해 **"EMPTY_RESULT"가 사용자에게 노출**되던 것도 수정. 검증: tsc 0/eslint 에러 0/콘솔 에러 0/가로스크롤 0.
   ▶ 남은 UI 작업: AI매매(VTJ·paper)·관리자 화면 미계측, 빈·에러 상태 시나리오별 QA, 실기기 시각 QA, 색 대비 전수.
7. 🔶 **[부분 완료] 나머지 UI/모바일 폴리시** — 4개 주요 화면의 터치타깃·미명명 컨트롤·기계코드 노출은 #6에서 해결. **남은 것**: AI매매(VTJ/paper)·관리자 화면 계측, 빈·에러 상태 시나리오 QA, 색 대비 전수, 실기기 시각 QA.
8. ✅ **[조사·doc 정정] 문서상 미구현** — 손절지연 행동분석은 `mone_v802_holdings_clean.py:291-321`에 **실재**(delay_risk), 매물대 압축은 `chart_analysis_engine.py:869-961`에 **실재**(zone+피보 겹침). 이전 노트 stale. toggle-only 감사만 #6로 이관.

## 내일(데이터 갱신 후) 실행 순서 (합의)
0. **데이터 갱신 확인**: ETF 카드 오늘 날짜·라이브 현재가·"부분 데이터" 사라짐 / 누적수익률 오늘까지+환율합산 / 홈 국장 "오늘 후보" 채워짐(신선 데이터엔 EV+ 오늘진입 25건 있음) / 9전략·탐색 신선.
   - 갱신 안 됐으면 = CI 수동실행이 안 된 것(내 GitHub 권한으론 dispatch가 403). 사용자/관리자가 Actions에서 "MONE Auto Accumulator" Run 필요.
1. **엣지 진단 우선(항목 1~3)** — 분봉 exit 재판정으로 실제 RR부터 확인(현재 −0.89%가 상당 부분 측정 착시일 수 있음).
2. 그다음 UI 전면 감사(항목 6) + 시스템 헬스게이트(항목 4).
- 원칙: **엣지 > UI**. 화면이 예뻐도 추천 기댓값이 (−)면 신뢰가 안 생김.

## 2026-07-26 세션 — 자가보정 루프의 입력이 끊겨 있었다 (브랜치 `fix/revive-prediction-capture-loop`)
**핵심 발견:** "시간이 지나면 표본이 쌓여 자동 보정된다"는 전제가 **깨져 있었다.**
- `_record_virtual_ledger`는 `mone_v65_api_stabilizer.py:3254`(=`/api/final/recommendations` 핸들러) **한 곳에서만** 불린다. 즉 예측 캡처가 **"누가 앱을 열어야" 일어나는 요청 시간 부작용**이었다. 배포 백엔드(Render)는 디스크가 휘발성이고 git push도 안 해서 원장에 남지 않는다.
- 게다가 `mone-auto-accumulator`는 원장을 **stage조차 안 했다**(정산 워크플로만 stage) → 캡처돼도 매번 버려짐.
- 실측: `virtual_prediction_ledger.csv` 2026-06 **818건** → 2026-07 **21건(전부 PENDING)**. clean window(7-10~) 안의 정산 표본 **0건**. 즉 화면 승률은 전부 오염 구간(6월) 산출물.
- 헬스체크는 그동안 OK를 찍었다 — 정산 스크립트가 매일 돌아 파일 mtime은 새것이었기 때문.

**조치:** `scripts/capture_recommendation_predictions.py`(서빙 경로 그대로 호출, 주말·노후 OHLCV 가드) + accumulator에 캡처 스텝·stage 추가 + 헬스체크에 `prediction_capture`(critical)/`settlement_backlog`/`clean_window_samples` 검사 추가.
**남은 실측 문제(수정 아님, 관측):** 미정산 **124건**, clean window 표본 **0건**. 캡처가 돌기 시작하면 여기서부터 쌓인다.

⚠️**지표 2개가 서로 다른 값을 말한다(미해결):** `strategy_win_rates.json`(=API `netWinRate` 소스, 검증 CSV 기반)은 KR 승률 **9.1%**·US 20.4%인데, `attribution_feedback.json`(VTJ 저널 기반, n=1778)은 **32.2%**. 캡처 시스템·정의·기간이 달라서인데, 화면에 어느 쪽이 뜨는지 정리 안 됨. 다음 세션 우선순위.
⚠️`winRates`는 표본<20이면 **하드코딩 기본값**으로 폴백한다(예: KR conservative_mid 실측 0.0인데 표시 0.525). 이중 낙관 미해소.

⚠️**auto_sync 위험 실측·차단(2026-07-26):** 방아쇠는 백그라운드 루프만이 아니라 **`MONE_STARTUP_SYNC=1`(백엔드 기동 시 1회)**이 더 빠르다. 레포 루트 `.env`(gitignore)가 출처이고 `data_loader.py:31`이 로드하므로 **셸 env가 비어 있어도 켜진다**. 이번 세션에 백엔드 기동 수십 초 만에 피처 브랜치가 origin/main 위로 리베이스돼 추천 CSV 3건 충돌(`git rebase --abort`로 복구). 또 7/23에 남은 **고아 `.git/rebase-merge`가 3일간 모든 git 작업을 막고** 있었다(안에 autostash 1개 → `rescue/autostash-20260723` 태그로 보존 후 제거). → `.env`에 `MONE_STARTUP_SYNC=0` + `MONE_AUTO_SYNC_DISABLE=1` 적용. 상세 [[project_local_collector_git_hazard]].

## 제약 / 운영 메모
- CI dispatch 권한 없음(403) → 파이프라인 실행은 사용자 손 필요.
- 이 실행 환경엔 프론트 빌드/`fastapi`/`yfinance`/`FDR` 없음 → 백엔드 라이브 구동·시각 QA 불가(코드/로직 단위검증으로 대체).
- 보유 **수량** 동기화는 로컬 브릿지(`scripts/sync_all.ps1`, 사용자 PC) 담당 — 안 돌리면 수량이 조용히 낡음.
