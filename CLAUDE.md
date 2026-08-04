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

## 2026-07-28 세션 — 낙관 누출 3건 + CI 캡처가 실제로는 죽어 있었다 (PR #132~#138)
**교훈 한 줄: "고쳤다"와 "CI에서 실제로 돈다"는 다르다.** 7/26에 캡처를 CI로 옮겼는데
7/28에 확인하니 **한 번도 성공한 적이 없었다.** 레포 루트 `app.py`(스트림릿 2.8MB)가
백엔드 `app/` 패키지를 가려 `ModuleNotFoundError: 'app' is not a package`로 매번 죽었고,
워크플로가 `set +e`라 스텝은 계속 success로 찍혔다. CLAUDE.md #1의 sys.path 사고와 같은
계열 — **그 사고를 고치려고 만든 스크립트가 같은 함정에 빠졌다.** 헬스체크의
`prediction_capture=STALE`이 유일한 발견 경로였다(감시 장치가 실제로 값을 했다).
→ 수정 후 실측: 원장 834 → 852(+18). 새 스크립트는 반드시 **CI와 같은 조건**
(cwd=`mone-web-app/backend`, `PYTHONPATH=.`)으로 재현 테스트할 것.

**낙관 누출 3건(전부 서로 다른 층에 있었다):**
1. `probability`가 **백테스트** 승률(44~55%)을 "실증" 라벨로 노출 → 라이브 실측 우선으로.
2. `winRates[key] or default` — **실측 0.0%가 falsy라 하드코딩 0.525로 둔갑**. None 검사로.
3. `attribution_feedback`이 **과거 리플레이를 풀링**(1298건/39.8%) → forward만(569건/19.9%).
   `SOURCE_CALIBRATION_WEIGHTS`에 `HISTORICAL_REPLAY: 0.0`이 진작 있었고 자가보정 경로는
   지키고 있었는데 **귀속분석 경로만 안 봤다.** 이걸로 두 원장 3배 모순(9.1% vs 32.2%)이
   해소됐다 — 정의/기간 차이가 아니라 **표본 구성** 문제였다.

**스케일 버그 2건(승률 소스를 바꾸자 드러남):** `_apply_light_correction`이 퍼센트포인트를
절대 차감(`prob - 15`)해 10.5%가 0으로 뭉개짐 → 비율로. 귀속 배율 루프만 probability 상한이
`1.0`(0~1 분수 가정)이라 8.9%가 1.0으로 잘림 → 100으로. **낙관값일 땐 늘 상한에 걸려
아무도 못 느꼈다.**

**CI 60분 타임아웃 분할:** accumulator 40.6분(평일)+월요일 주간작업 → 60.3분 초과.
스텝별 실측으로 `Run MONE cloud update`가 **매번 정확히 1501초**(=내부 `timeout=25*60`)인 걸
발견. 추적해보니 체인 첫 두 모듈이 레포에 없고, 마지막 줄에서 쓰는 요약 JSON이 git에 한 번도
없었고, 레거시 산출물 68개가 **스테이징 allowlist에 0개** — **2026-05-28 이후 2개월째 빈 실행**.
→ 제거. 주간작업은 `mone-weekly-refresh.yml`로 분리. **결과 60.3분 → 16.9분**(3회 연속 성공).

**UI:** 9개 화면 375x812 실측 → 44px 위반 0/미명명 0/기계코드 0. 빈 상태만 보면 놓친다 —
휴장일 감사에선 근접 알림 칩이 아예 안 그려져서 못 봤다. 기계코드 스캔 정규식이 밑줄 있는
것만 찾아 `DEFERRED`를 놓친 것도 같은 실수. 분석 화면 기본 종목이 신규 ETF(19봉)라 늘
"준비 중"이던 것 → 추천 우선 + `ohlcvCount>=26` 필터.

**⚠️ 미해결:** `minCalibratedWinRate` 게이트는 여전히 기존 소스. 두 원장이 같은 기준을 말하게
됐으니 전제는 갖춰졌지만, 라이브 실측(~19.6%)으로 돌리면 통과가 거의 없어진다. clean window
표본이 쌓인 뒤 결정할 일.

## 2026-07-29 세션 — 감시 장치가 최신성만 보고 연속성을 안 봤다 + 승률 순위가 자본 순위와 반대
사용자가 TradingAgents 논문(2412.20138v7)과 유사 오픈소스 2종(virattt/ai-hedge-fund,
midnightnnn/llm_invest)을 참고자료로 줬다. **셋 다 out-of-sample 엣지를 공개하지 않았다**
— ai-hedge-fund v2는 validation 모듈이 아예 미구현, llm_invest는 walk-forward 인프라만 있고
결과 없음, 원논문은 3개월·3종목(SR 8.21을 저자도 각주에서 "기대 범위 초과"로 인정) + LLM
사전학습 룩어헤드 논의 없음. **MONE가 저들보다 앞서 있는 지점이 바로 측정 장치다.**
가져온 건 llm_invest의 sleeve 개념 하나뿐이고, 페르소나 에이전트·실주문 경로·백테스트 검증은
의도적으로 안 가져왔다(전자는 측정 불가, 후자는 팩터 귀속을 무력화).

**1) 캡처 "결손 9일"은 열린 버그가 아니었다(내 초기 오진 정정).** 타임라인: 7/10~25는 CI
캡처 스텝 자체가 없었고(스크립트 생성 7/26 `51577cc`), 7/26~27은 셰도잉·fastapi 누락으로
사망(`aafd943`, `8c310be`), **7/28이 첫 성공(22건)**. 즉 결손은 이미 고친 버그의 흔적이다.
다만 결론이 바뀐다 — **캡처가 정상 동작한 날은 아직 하루뿐**이라 내구성이 미검증이다.

**2) 진짜 갭: `data_freshness_healthcheck.py:245`가 최신성만 봤다.** `prediction_capture`는
`newestCapture`의 나이만 검사해서, 어제 22건이 들어왔으면 그 앞 9일이 비어도 OK다.
7/28에 배운 교훈("정산이 매일 돌아 mtime은 새것이었다")을 **감시 장치 쪽에서 그대로 반복**한
것이다. → `capture_continuity` 검사 추가. 거래일 달력을 **OHLCV 봉에서 역산**한다(공휴일
표를 하드코딩하면 그 표가 낡는 순간 헬스체크가 거짓말을 시작한다). 1일 결손=WARN, 2일=ERROR,
최신 거래일은 장마감/캡처 경합으로 1일 유예, `CAPTURE_CI_EPOCH=2026-07-28` 이전은 미판정.

**3) 소급 캡처는 하면 안 된다(조사 결론).** 누락 9일을 채우면 `HISTORICAL_REPLAY`가 되는데
`virtual_trade_journal.py:61`이 그 가중치를 **0.0**으로 못박고 있다. 7/28에 두 원장 3배
모순(9.1% vs 32.2%)을 해소한 근거가 그 정책이라, 소급분은 clean window 분모에 한 건도 못
들어간다. 넣으면 그때 고친 낙관 누출이 되살아난다.

**4) 승률로 전략을 고르면 거의 반대로 고른다(신규 실측).** `update_strategy_sleeve_nav.py`
추가 — 9개 셀(mode×horizon)을 등가중·고정비율 가상 sleeve로 굴려 자본곡선을 그린다.
오염 구간 662건 기준 **승률 순위 vs NAV 순위 스피어만 상관 = −0.3**:

| sleeve | 승률 | 페이오프 | NAV 수익% |
|---|---|---|---|
| aggressive_mid | **19.4% (1위)** | 0.59 | **−44.5% (8위)** |
| conservative_short | 14.3% (4위) | 1.40 | **−11.7% (1위)** |
| balanced_swing | 15.4% | 1.30 | −58.8% (9위, n=175) |

즉 `strategy_win_rates.json`만 보고 전략을 고르면 손익 비대칭을 정면으로 놓친다. 북극성이
"손익 비대칭 개선"이므로 비교축을 페이오프·자본곡선으로 옮겨야 한다. (단 이 662건은 **오염
구간**이라 진단용이다. clean window는 아직 3건.)

**5) 청산 **날짜**가 버려지고 있었다.** `settle_pending_validations.py`가 `best_exec[0]`에
청산일을 들고 있으면서 안 남겨서, 손절로 3일 만에 끝난 거래와 만기까지 끈 거래가 같은 날
실현된 것처럼 보였다. → `exitDate` 기록 추가(OHLCV 경로·인덱스 경로 양쪽). 과거 행은
만기일로 근사하되 `estimatedTimingTrades`로 정직하게 카운트한다.

**설계 원칙(멀티에이전트를 안 넣은 이유):** sleeve는 **새 예측을 만들지 않는다** — 이미
정산된 표본을 다시 묶을 뿐이라 기존 게이트·기준선을 건드리지 않는다. 미청산 건의 평가손익도
안 쓴다(라이브 시세를 다시 끌면 정산 경로와 두 번째 산식이 생긴다 — 손절가 3중 계산의 전례).
사이징도 등가중 고정이다(Kelly를 쓰면 사이징 스킬과 **선택 스킬**이 섞여 #3 진단이 안 보인다).

**6) 의존성이 무핀이었다(추가 발견).** `requirements.txt`와 워크플로 7곳이 `pandas numpy`를
상한 없이 설치하고 있었다. pandas 3.0.5가 풀리면 테스트 5개가 죽는다 — **코드를 아무도 안
건드린 날 CI가 깨지는** 종류라 원인 추적이 제일 오래 걸린다. 상한 적용 + `test_dependency_pins.py`로
재발 차단(이 테스트가 내가 손으로 놓친 `mone-news-refresh.yml` 1곳을 실제로 잡았다).

**⚠️ 남은 것:** clean window 표본은 여전히 3건. sleeve 순위는 30건 넘기 전엔 노이즈
(`sampleWarning`이 자동으로 뜬다). `minCalibratedWinRate` 게이트 결정은 그 뒤 일로 그대로 남음.
UI(#7 잔여: AI매매·관리자 계측, 빈/에러 상태 QA, 색 대비)도 손대지 않았다.

## 2026-07-29 (2) — 테스트가 처음 완주하자 관리자 인증 우회가 나왔다
**환경이 없다고 적어둔 게 실제로는 안 해본 것이었다.** `pip install` 한 줄로 전체
테스트가 돌았고(624 passed), 그 상태에서 `pip-audit`를 돌리니 백엔드 핀에 CVE 12건이
쌓여 있었다. 루트 requirements는 **무핀**(최신 메이저를 끌어옴), 백엔드는 **핀은 있는데
한 번도 안 올림** — 정반대 실패가 한 레포에 같이 있었다.

**실제로 뚫렸다(재현 완료).** `main.py:550` `admin_auth_middleware`가
`path = request.url.path`로 `/api/admin/` prefix를 검사했다. `request.url`은
`{scheme}://{host}{path}`를 이어붙였다 다시 파싱해 만들어지므로 Host에 `/`가 섞이면
경로 경계가 밀린다. 라우팅은 raw scope path를 쓰므로 **엔드포인트는 정상 실행되고
앞단 인증만 건너뛴다**(starlette PYSEC-2026-161). 레포 핀 버전 0.41.3에서 실측:

    GET /api/admin/secret  +  Host: example.com/abc?bar=
    -> request.url.path == "/abc"  (prefix 불일치 -> 인증 통과)
    -> 라우팅은 /api/admin/secret  -> 200 + 데이터 노출

백엔드는 Render에 배포돼 있어 인터넷에서 닿는다. rate limiter도 같은 패턴이었다.

**수정: 라이브러리가 아니라 습관을 고쳤다.** 보안 판정을 `request.scope["path"]`로
옮겼다(`_raw_path()`). starlette 0.41.3에서도 막힌다 — 버전 독립. starlette 1.x 승격은
FastAPI 메이저 동반 이동이라 **안 했다**(코드 수정으로 해당 CVE가 무력화되고, 나머지
starlette CVE는 StaticFiles/FileResponse/HTTPEndpoint/`request.form()`을 안 써서 미해당).
`requests==2.33.0`, `python-dotenv==1.2.2`만 안전 승격.
`tests/test_admin_auth_host_header_bypass.py`가 AST로 `request.url.path` 재발을 막는다
(정규식으로 짰더니 자기 docstring을 잡았다 — 검사 대상이 문자열을 담고 있을 땐 AST로).

**같이 나온 것 — 500 응답이 스택트레이스를 무조건 실어보냈다.** `global_exception_handler`가
`traceback.format_exc()[-800:]`를 조건 없이 본문에 넣고 있었다. 파일 경로·코드 구조가 새고,
예외 메시지엔 자격증명이 섞이기 쉽다(psycopg2 접속 문자열, URL에 키를 실은 클라이언트).
→ 기본 차단 + `MONE_DEBUG_ERRORS=1`일 때만 노출. 서버 로그엔 항상 전문을 남긴다.

**점검했고 문제 없던 것:** 관리자 토큰 검증(HMAC-SHA256 + `compare_digest` + 만료),
CORS(와일드카드 없는 화이트리스트), `urlopen` 호출부(URL이 하드코딩 OAuth 엔드포인트라
SSRF 아님), `request.form()`/StaticFiles/FileResponse/HTTPEndpoint 미사용.

⚠️ **남음:** starlette 0.41.3 핀 자체는 그대로다. 지금은 미해당이지만 나중에
StaticFiles/`request.form()`을 쓰기 시작하면 Range DoS·폼 한도 무시가 바로 살아난다.
그때는 FastAPI 승격이 선행돼야 한다.

## 2026-07-29 (3) — UI 계측을 손에서 스크립트로 + 앙상블 82,251건이 말한 것
**손 계측이 화면을 빠뜨리는 구조였다.** 07-26에 4개, 07-28에 9개만 쟀고 AI매매·관리자는
두 번 다 누락됐다. `scripts/measure_frontend_touch_targets.py`가 `app/page.tsx`의
`pageIds`를 그대로 순회해 **12개 전 화면**을 375x812 실측한다(Playwright+Chromium).
실측 31건 위반 → 0건. 기계코드 4종(`UNKNOWN`/`DATA_PENDING`/`UNPROVEN`/`NEUTRAL`) 차단.
최종: 44px미달 0 / 무명 0 / 기계코드 0 / 가로스크롤 0 / JS에러 0.

**계측기를 먼저 두 번 고쳐야 했다 — 도구를 못 믿으면 멀쩡한 코드를 고치게 된다.**
① 정적 Tailwind 분석은 169건을 뱉었는데 실측은 31건. flex 부모가 늘려주는 높이를 못 본다
→ 정적 스크립트 폐기(과탐 감시는 없느니만 못하다).
② `::after`로 히트영역을 넓히는 패턴(`after:-inset-1`)을 안 보면 이미 44px인 요소를 위반으로
센다. 실제로 그걸 모르고 `size-9`→`size-11`로 바꿨다가 되돌렸다.
③ JSX 속성의 화살표 함수 `=>`에서 태그를 자르는 정규식 때문에 `placeholder`/`label`을 못 봐
무명 컨트롤을 19건 오탐했다(실측 0건).
**부수 소득:** 백엔드 미기동(502) 상태로 쟀으므로 12개 화면의 **에러 상태 QA**를 겸했다.

**보안 마무리:** starlette 0.41.3 → 1.3.1(+fastapi 0.140.13/pydantic 2.13.4/uvicorn 0.51.0).
pip-audit 12건 → **0건**. 라이브 백엔드에서 재확인: `Host: example.com/abc?bar=` 우회 → 401.

**⚠️ 앙상블 82,251건(walk-forward)이 말한 것 — 수치는 못 믿되 구조는 볼 만하다.**
`run_ensemble_calibration`은 **walk-forward** 산출이라 절대 수준은 낙관 쪽이다
(풀링 +0.113% vs 라이브 −2%/거래). 그러나 **같은 방법 안에서의 상대 비교**는 유효하다:

| 국면 | n | 승률 | 평균손익 |   | 점수구간 | n | 평균손익 |
|---|---|---|---|---|---|---|---|
| BULL | 57,566 | 41.8% | **+0.241** |   | 50-55 | 5,586 | −0.210 |
| SIDE | 16,785 | 41.8% | +0.064 |   | 55-60 | 11,718 | +0.114 |
| BEAR | 7,900 | 31.3% | **−0.714** |   | 60-65 | 18,002 | **+0.172** |
|  |  |  |  |   | 65-70 | 17,475 | +0.150 |
|  |  |  |  |   | 70-100 | **29,470** | +0.116 |

1. **국면이 점수보다 훨씬 강하다.** BULL−BEAR 격차 0.955%p. 라이브 실측(강세 +0.2%/약세
   −3.4%)과 **방향이 일치**하므로 백테스트 아티팩트가 아니다.
   ~~베어 게이트는 aggressive에만 걸려 있다~~ → **오기. 정정:** `_bear_reversal_entry_gate`는
   mode 인자를 아예 받지 않고 `quant_scanner.py:2782`가 전 모드에 적용한다(`test_bear_market_
   aggressive_disable.py`는 이름과 달리 CSV 쓰기 테스트다). **확대할 게 없었다.**
2. **점수는 55 위로 단조가 아니다.** 최상위 구간(70-100)이 60-65보다 나쁘고, 그게 **전체의
   36%**다. "확신도 높은 걸 고르면 낫다"가 성립하지 않는다 — CLAUDE.md #3의
   "probability anti-predictive"가 규모까지 붙어 재확인됐다.

## 2026-07-29 (4) — 두 가설을 라이브로 잴 축이 아예 없었다
앙상블이 낸 두 가설(국면 격차, 점수 비단조)을 게이트에 반영하려다 **원장에 `finalScore`가
안 남는다**는 걸 발견했다. 원장 컬럼은 `probability`뿐인데, 그건 CLAUDE.md #3에서 이미
anti-predictive로 판정된 값이고 **랭킹이 실제로 쓰는 건 `finalScore`**다(서빙은
`mone_v65_api_stabilizer.py:5072`에서 `-x["finalScore"]` 내림차순 정렬).
`regime`도 마찬가지로 안 남았다.

→ 즉 "점수 상위가 정말 더 나은가", "약세장이 얼마나 갉아먹는가"를 **라이브 표본으로는
검증할 방법이 없었고**, 그래서 지금까지 그 판정을 walk-forward(낙관 편향)에만 의존해 왔다.
`_record_virtual_ledger`에 `finalScore`/`regime` 추가 + sleeve 스크립트에 `byRegime`·
`byScoreBin` 축 추가. **게이트는 하나도 안 건드렸다** — 라이브가 같은 말을 하는지 본 뒤에
논할 일이다(walk-forward 풀링 +0.113% vs 라이브 −5.02%/거래, 낙관 간극이 그만큼 크다).

기존 662건은 필드가 없어 `UNRECORDED`로 모인다. 이걸 안 밝히면 "국면 분석이 고장났다"로
보이므로 `regimeRecordedTrades`/`scoreRecordedTrades`/`axisCoverageNote`로 커버리지를 명시.

## 2026-07-29 (5) — 기다릴 필요가 없었다. 두 축은 VTJ 저널에 처음부터 있었다
"원장에 `finalScore`가 없으니 표본이 쌓일 때까지 기다린다"가 **틀렸다.**
`data/virtual_trade_journal.csv`에 `final_rank_score`·`market_regime_at_signal`이
**2,178행 전부** 있었고, 결과는 `virtual_trade_evaluations.csv`의 `net_pnl_pct`에 있다.
`scripts/analyze_live_axes.py`로 조인(FORWARD_PAPER_TRADE만, PENDING 제외) → **600건 즉시 검증.**

**결과 ① 국면 가설은 라이브에서 재현되지 않는다 — 부호가 뒤집힌다.**

| | walk-forward(82,251) | 라이브 forward(600) |
|---|---|---|
| BULL | **+0.241** | −6.611 (n=159) |
| SIDE | +0.064 | −5.427 (n=425) |
| BEAR | **−0.714 (최악)** | **−1.561 (최선, n=16 ⚠)** |

BEAR가 walk-forward에선 최악인데 라이브에선 **가장 덜 나쁘다**. n=16이라 단정은 못 하지만,
**"약세장을 막으면 나아진다"는 라이브 근거가 없다.** 게이트를 백테스트 수치로 바꿨으면
정확히 반대로 갔을 것이다 — 관측만 하고 미룬 판단이 옳았다.

**결과 ② 점수 가설은 방향이 맞지만 표가 쓸모없다.** 70-100(−5.788)이 65-70(−5.169)보다
나쁘다 → 비단조 재현. 그런데 **서빙이 실제로 내는 점수는 68.0~92.1(중앙 72.5)뿐**이다.
앙상블 표의 50-55/55-60/60-65 구간은 **프로덕션에 존재하지 않는다.** 즉 그 표로 임계값을
정하는 건 애초에 불가능했다. 쓸 수 있는 건 "68 이상 구간 안에서 상위가 더 나쁘다" 하나뿐.

**⚠️ 표본 수가 또 두 값을 말한다.** sleeve 스크립트(=`virtual_validation_results.csv` 기반)는
clean window 정산 표본을 **3건**이라 하고, VTJ 저널 기반은 **65건**이다. 20배 차이다.
둘은 서로 다른 캡처 시스템(추천 원장 vs 페이퍼 저널)이라 버그는 아니지만, **"표본 3건이라
아무것도 못 한다"는 결론은 틀렸다.** 어느 쪽이 엣지 판정의 분모인지 정리가 필요하다.

clean window(7-10~) 라이브 실측: **65건 / 승률 12.3% / 평균 −6.452%**.

## 2026-07-29 (6) — 두 원장은 같은 걸 다르게 센 게 아니라 **다른 걸** 담고 있었다
"3건 vs 65건"의 정체를 팠다. 결론: **교집합이 854 vs 880 중 88건뿐**이다.
2026-07-28의 "승률 9.1% vs 32.2%"는 표본 구성(리플레이 풀링) 문제였는데, 이번은
**모집단 자체가 다르다.**

| | 원장A `virtual_prediction_ledger` | 원장B `virtual_trade_journal` |
|---|---|---|
| 캡처 | `_recommendations_payload(limit=50)` 서빙 경로, **필터 없음** | 리포트 CSV → `_reject_reason` → `_unique_by_symbol`**[:5]** |
| 질문 | "보여준 추천 **전체**에 엣지가 있나" | "**상위 5개**만 담았다면 어땠나" |
| 정산 | `settle_pending_validations` → `virtual_validation_results` | `vtj.evaluate()` → `virtual_trade_evaluations` |
| 소비 | `update_win_rates` → `strategy_win_rates.json` (**화면 승률**) | `build_live_calibration`, `calibration_gate_shadow` (**게이트**) |
| 실측 | n=662 승률 15.1% 평균 **−5.018%** | n=600 승률 19.8% 평균 **−5.638%** |

**결정: 엣지 판정 분모=B, 화면 표시 분모=A.** 게이트가 답할 질문은 "따라 샀을 때의
기댓값"이라 상위 N 부분집합(B)이 맞고, 화면 승률은 사용자가 보는 카드 전체(A)를
설명해야 한다. 이 **비대칭을 문서화하지 않으면 또 헷갈린다** → `scripts/reconcile_ledgers.py`가
정의·소비자·수치를 `reports/ledger_reconciliation.json`으로 남기고,
`tests/test_ledger_reconciliation.py`가 소비자 배선이 뒤바뀌는 걸 막는다.

**⚠️ 내 가설이 실측에 반박당했다(기록용).** "B는 필터가 걸린 부분집합이니 A보다
좋게 나오는 게 정상"이라고 스크립트에 써뒀는데, 실측은 **B가 승률은 높고(19.8% vs
15.1%) 평균손익은 더 나쁘다(−5.638% vs −5.018%)**. 상위 5개 필터는 **적중률만 올리고
기댓값은 못 올린다** — 더 자주 맞히는 대신 틀릴 때 더 크게 잃는다. 손익 비대칭이
선택 단계에서도 그대로 재현된 것이고, `payoffRatio`를 비교축으로 옮긴 판단(#4)과 같은 방향이다.

## 2026-07-29 (7) — 알파와 베타를 한 번도 분리한 적이 없었다 (링크 레포에서 건진 것)
사용자가 공유한 두 레포를 **클론해서 코드를 읽었다**(그전엔 README만 봤다 — 게을렀다).

**확인된 것:** `ai-hedge-fund/v2/validation/__init__.py`는 **5줄 docstring뿐**(CPCV/PBO 미구현).
`v2/signals/pead.py`는 실물이나 서프라이즈=실적−컨센서스인데 MONE엔 **컨센서스가 없어** 못 쓴다.

**건진 것 = `v2/event_study/`** (413줄, 시장모형+CAR+t검정+부트스트랩). 그쪽은 실적발표를
이벤트로 쓰지만, **추천 시그널일을 이벤트로 바꾸면 MONE가 한 번도 안 한 측정이 된다.**

**MONE의 모든 엣지 진단(`net_pnl_pct`·sleeve NAV·승률)은 원시 수익률이다.** 보유 기간에
시장이 빠졌으면 그 손실은 선택 실패가 아니라 베타다. 실제로 표본 구간에 **KOSPI가 고점
8930(6/25) → 6755(7/27)로 −24.4%** 빠졌다. → `scripts/analyze_recommendation_alpha.py` 추가.
추정창 [-250,-11]에서 `R_stock = α + β·R_KOSPI` OLS 적합 → 이벤트창 초과수익 누적(CAR).

| 창 | n | 원시% | 시장 몫% | **알파(CAR)%** | p |
|---|---|---|---|---|---|
| D+1 | 150 | −1.30 | −2.21 | **+0.909** | 0.033 |
| D+5 | 150 | −2.23 | −4.94 | **+2.712** | 0.001 |
| D+20 | 150 | −14.59 | −20.24 | **+5.653** | <0.0001 |

**⚠️ 그런데 이 p값은 못 쓴다 — 도구가 스스로 그렇게 말한다.** D+20 이벤트 150건이
**2026-06-19~26 6일 안에 몰려**(25건/일) 있어 전부 같은 시장 충격을 공유한다. t검정의
독립성 가정이 깨져 유효 표본은 150이 아니라 6에 가깝다 → `clustering.isClustered=true`,
`significanceUsable=false`. 창이 길수록 최근 시그널이 제외돼(앞으로의 봉 부족) **표본이
과거로 편향**되는 것도 `eventsByMonth`로 드러낸다. 베타를 급락 **이전** 창에서 적합하므로
국면 급변 시 시장 몫이 과소·알파가 과대평가될 수 있다는 것도 `caveats`에 실었다.

**그래도 방향은 남는다:** "−5.6%/거래"를 전부 선택 오차로 읽어온 것은 **틀렸을 수 있다.**
알파(+)는 "시장보다 덜 빠졌다"는 뜻이지 "벌었다"가 아니지만, 고칠 대상이 선택인지 노출인지
가 달라진다. 군집 없는 표본(여러 달에 분산)이 쌓이면 그때 결론을 낸다.

## 2026-07-29 (8) — PR에서는 아무 검사도 안 돌고 있었다 + 알파를 화면에
**실측: 피처 브랜치 대상 GitHub Actions 실행 0건.** 모든 워크플로가
`schedule`/`workflow_dispatch`뿐이라 PR에 붙는 체크는 **Vercel 배포 3개가 전부**였고,
그건 프론트가 빌드되는지만 본다. 즉 **테스트를 깨는 PR도 초록으로 통과**했다.
이 세션 내내 로컬에서 660여 개를 돌려 확인했지만 CI는 그걸 한 번도 안 봤다.
→ `.github/workflows/pr-checks.yml` 추가(pytest + tsc + eslint + next build).
   **`set +e`를 쓰지 않는다** — 이 레포가 34곳의 `set +e`로 조용한 실패를 반복한
   전례가 있어, PR 게이트만큼은 실패가 실패로 보여야 한다.

**`37f8fa7`의 X는 코드 문제가 아니었다(조사 완료).** 그 커밋은 프론트 파일을 0개
건드렸고(Python·CSV·테스트만), 해당 시점 `next build`는 exit 0으로 통과하며,
PR head는 Vercel 3개 모두 success였다. 루트 `vercel.json`은 `deploymentEnabled:false`다.
커밋 간격이 51분이라 "후속 커밋에 밀린 취소"로도 설명이 안 된다 → **Vercel 인프라/쿼터
쪽으로 추정되나 대시보드 접근이 없어 확정 불가.** 코드 원인이 아니라는 것까지만 확인했다.

**알파를 화면에 올렸다.** 지금까지 `recommendation_alpha.json`에만 있어서 사용자는
여전히 −14%만 보고 "앱이 틀렸다"로 읽게 돼 있었다. `/api/edge/alpha` + `AlphaPanel.tsx`
(AI저널 화면 최상단, 원시 수익률 표보다 **위**). 카드가 **원시 / 시장 몫 / 차이**를
나란히 그린다. 과대 해석 방지 문구 2개를 테스트로 고정했다:
  - "차이가 (+)여도 **시장보다 덜 빠졌다**는 뜻이지 수익이 났다는 뜻이 아니다"
  - 군집이면 "**통계적 유의성은 주장할 수 없습니다**"
리포트가 없으면 0이나 빈 표가 아니라 `DATA_PENDING`을 돌려준다.

⚠️ 테스트를 쓰다 **또 자기 문서를 잡았다** — `set +e` 부재 검사가 "왜 안 쓰는가"를
설명한 주석에 걸렸다. 검사 대상이 그 문자열을 담고 있을 땐 주석/문자열을 제외할 것
(2026-07-29 AST 사건과 같은 계열, 이번 세션에만 두 번째다).

## 2026-07-29 (9) — PR 게이트가 첫 실행에서 **내 실수**를 잡았다
`pr-checks.yml`을 넣자마자 첫 PR에서 빨간불이 떴다. 잡힌 건 다름 아닌 **내가 만든
테스트**다: `ERROR tests/test_alpha_display_and_pr_checks.py` / exit 2.

원인은 `import yaml`인데 워크플로 설치 목록에 **PyYAML을 안 넣은 것**. 로컬엔 다른
패키지의 전이 의존으로 이미 깔려 있어서 666개가 통과했다. 즉 이 세션 내내 반복해
말한 **"로컬에서 되는 것과 CI에서 되는 것은 다르다"를 내가 그대로 밟았고**, 게이트가
없었으면 이 PR은 초록으로 머지됐을 것이다. (CLAUDE.md 2026-07-28의 캡처 사고와 같은 계열.)

**핀 하나 추가로 끝내지 않았다** — 설치 목록은 손으로 관리하는 중복이라 또 빠진다.
`test_pr_workflow_installs_everything_tests_import`가 tests/의 서드파티 임포트를
**AST로** 모아 워크플로 설치 목록과 대조한다.

⚠️ 그 테스트를 쓰면서 **같은 실수를 한 번 더 했다**: 표준 라이브러리 목록을 손으로
적다가 `inspect`를 빠뜨렸다. 낡는 표를 만들지 말라는 게 이 파일의 교훈인데 그걸
어긴 것이라, `sys.stdlib_module_names`(인터프리터 권위 목록)로 교체했다.

**검증 방식도 바꿨다.** 앞으로는 로컬 통과로 끝내지 말고 **깨끗한 venv에 워크플로와
같은 목록만 설치해** 돌릴 것:
    python -m venv /tmp/cienv && /tmp/cienv/bin/pip install <워크플로와 동일 목록>
    /tmp/cienv/bin/python -m pytest tests -q
이 방식으로 재검증 → **667 passed / 0 failed**.

## 2026-07-29 (10) — 색 대비 감사: 계측기가 코드보다 먼저 세 번 틀렸다
PR #147 체크 실측 확인(**Python 테스트 / 프론트 타입·린트·빌드 둘 다 success**,
`667 passed, 1 skipped in 85.42s`, CI가 푼 핀 = pandas 2.3.3 / numpy 2.4.6 /
starlette 1.3.1). **이 레포에서 PR 트리거 테스트가 실제로 돌아 통과한 첫 사례**다.

그다음 #7의 마지막 항목(색 대비 전수)을 했다. **세 번의 오류가 전부 앱을 실제보다
좋아 보이게 만드는 방향이었다** — 감시 장치는 이 방향으로 틀리면 아무도 눈치 못 챈다.

1. **색 파싱을 `rgba?\(` 정규식으로 했다.** Chromium은 계산값을 `oklab()`/`oklch()`로
   돌려준다(Tailwind v4 팔레트 + `/opacity` 수정자). journal 화면에서 텍스트 200개 중
   **141개를 조용히 건너뛰고** "위반 5건"이라 보고했다. → 캔버스에 맡겨 CSS Color 4 전부 처리.
2. **로딩 화면을 쟀다.** home의 가시 텍스트가 56자("MONE 준비 중…")일 때 "위반 0"이
   나왔다. 처음엔 "가시 글자수 200자"를 렌더 완료 신호로 썼는데 **틀린 대리지표**였다 —
   broker/admin은 로그인 게이트라 본문이 원래 140자다. → 로딩 문구 존재 여부로 교체.
3. **`opacity` 누적 방향이 반대였다.** 요소에서 위로 곱한 prefix를 배경에도 써서
   자식의 `opacity-70`이 **부모 배경까지** 흐리게 만들었다. 브랜드 teal(#14b8a6)이
   #11867f로 계산돼 2.58:1로 보고됐다(**참값 3.67:1**). → suffix 곱으로 수정.

계측기를 고치자 **고유 41건 / 총 139건** — 버그 버전이 말한 5건의 8배였다.

**원인은 하나였다.** `text-slate-600`(#45556c, 2.50~2.64:1)이 렌더된 11개 화면 **전부**에
깔려 있었다. 그런데 `text-slate-400`은 이미 이 앱의 지배적 관례(1124곳)이고 7.6:1로
통과한다 → **새 룩을 만든 게 아니라 예외 131곳을 관례로 되돌린 것**이다. 강조색 칩도
같다: 이 앱은 이미 브랜드색 위에 어두운 잉크를 깐다(`globals.css:512`가 teal 위에
#052420). 그래서 emerald/cyan-600 위 흰 글자(3.6:1)를 `text-slate-950`(5.5:1)로.

**계속 찾아서만 나온 것 2개:**
- **라이트 테마는 한 번도 감사된 적이 없었다.** 헤더에 토글이 있어 사용자가 실제로 보는데
  (`app/page.tsx:122`), 거기 `--text-muted`는 3.78:1이었다. 이제 두 테마 다 잰다.
- **`::placeholder`는 텍스트 노드가 아니라** TreeWalker에 안 걸린다 → 실측에서도 못 보던
  사각지대. `AdminLoginPage`에 1.93:1짜리가 있었다.

**부수 사고(테스트가 잡았다):** 색을 일괄 승격하니 `text-slate-600 hover:text-slate-400`
3곳이 `text-slate-400 hover:text-slate-400`이 됐다 — 대비는 통과하는데 **hover 피드백이
조용히 죽는다.** `test_hover_states_are_not_no_ops`가 잡았다.

`tests/test_frontend_contrast.py`는 WCAG 공식을 **파이썬으로 직접 구현**해 브라우저 없이
CI에서 토큰 명암비를 검증한다(실측 스크립트는 dev 서버가 필요해 CI에서 못 돈다).
계측기 버그 3종의 재발도 같이 막는다.

⚠️ **남은 한계:** 실측은 **375x812 모바일 뷰포트만** 본다. `Sidebar.tsx`처럼 데스크톱
전용 UI는 측정 대상에 안 들어간다(그래서 이번엔 계산으로 확인해 고쳤다). 빈 상태·에러
상태에서만 그려지는 텍스트도 그 상태를 만들어야 잡힌다.

## 제약 / 운영 메모
- CI dispatch 권한 없음(403) → 파이프라인 실행은 사용자 손 필요.
- 이 환경엔 과학 스택이 **선설치만 안 돼 있을 뿐 설치하면 전체 검증이 된다**
  (이전 노트의 "구동 불가"는 틀렸다). 한 줄로 끝:
  `pip install "pandas>=2.2,<3" "numpy>=1.26,<3" fastapi plotly python-dotenv streamlit yfinance httpx pytest`
  → 2026-07-29 기준 **622 passed / 0 failed**. 앞으로 "환경이 없어서 못 돌린다"고
  적기 전에 설치부터 시도할 것.
- ⚠️ **pandas는 반드시 `<3`**. 무핀이면 CI가 최신 메이저를 풀어와 코드를 안 건드린 날
  깨진다 — pandas 3.0.5에서 5개가 `TypeError: Invalid value 'True' for dtype 'str'`로
  사망(문자열 컬럼 bool 대입 금지, 예측 원장이 그 패턴을 씀). requirements.txt + 워크플로
  7곳에 상한 적용, `tests/test_dependency_pins.py`가 무핀 재발을 막는다.
- ~~이 실행 환경엔 프론트 빌드/`fastapi`/`yfinance`/`FDR` 없음 → 백엔드 라이브 구동·시각 QA 불가~~
  → **틀렸다(2026-07-29 반증).** 백엔드·프론트 **둘 다 이 환경에서 뜬다**:
  `cd mone-web-app/backend && MONE_STARTUP_SYNC=0 MONE_AUTO_SYNC_DISABLE=1 PYTHONPATH=. python -m uvicorn app.main:app --port 8050`
  (프론트 프록시 기본 대상이 **8050**이다 — 8000에 띄우면 502가 난다)
  + `cd mone-web-app/frontend && npx next dev -p 3000`. 이 조합으로 12개 화면 실측을 끝냈다.
- ⚠️ **로컬 백엔드를 띄우면 예측 원장에 쓴다.** UI 계측 중 `/api/final/recommendations`가
  수십 번 호출되면서 `data/signal_ledger.csv`에 4행, `reports/virtual_validation_results.csv`에
  877/835행 churn, 추천 CSV 5개가 **오늘 날짜로** 생성됐다. 이건 CI 캡처가 아니라
  **UI 계측의 부산물**인데 원장에서는 구별이 안 된다 → clean window 표본을 오염시킨다.
  계측 후 반드시 `git checkout -- data/ reports/*.csv`로 되돌릴 것(이번에 되돌렸다).
- 보유 **수량** 동기화는 로컬 브릿지(`scripts/sync_all.ps1`, 사용자 PC) 담당 — 안 돌리면 수량이 조용히 낡음.
