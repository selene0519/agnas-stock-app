# 주식 의사결정 보조 시스템 — 구조 분석 및 마이그레이션 보고서

**작성일:** 2026-05-14  
**대상 코드:** 루트 `app.py` (단일 모놀리스, 약 27,500+ 줄, `def` 약 651개)  
**백업:** `backups/app_backup_20260514_110242.py`  
**원칙:** 레거시 `app.py` / 루트 `predictions.csv` / 기존 watchlist / logs / reports **삭제·덮어쓰기 없음**. 신규 트리는 `core/`, `runners/`, `config/decision_system/`, `data/decision_system/`에 추가.

---

## [백업 결과]

| 항목 | 내용 |
|------|------|
| 백업 파일 | `backups/app_backup_20260514_110242.py` |
| 보존 | `app.py`, 루트 `predictions.csv`, `watchlist_*`, `logs/`, `reports/`, 기존 `runner_status_*.json` |
| 삭제 | 없음 |

---

## [현재 구조 분석] — 요구사항 §20 대응

### 규모

- **함수 정의:** 약 651개 `def` (단일 파일).
- **진입점:** `python app.py` → Streamlit `main()`; `python app.py --runner <action>` → `run_headless_runner(action)` (Streamlit UI 미실행이나 **모듈 최상단에서 `streamlit` import**).

### [현재 구현된 기능] (요약)

| 영역 | 구현 여부 | 주요 위치 / 설명 |
|------|-----------|-------------------|
| **예측** | 있음 | `auto_create_prediction_for_ticker`, `auto_generate_predictions_for_watchlist`, `load_prediction_log` / `save_prediction_row`, `build_auto_event_context` 등. 결과는 주로 **`predictions.csv`** (루트 `PREDICTION_FILE`). |
| **업데이트** | 있음 | `update_actual_results` — 예측 로그에 실제 OHLC/방향 등 반영 후 CSV 저장. `us_sync`/`kr_sync` 러너에서 예측 생성과 묶여 실행. |
| **검증** | 부분 | `calculate_order_backtest_stats`, `save_backtest_snapshot_v9985`, 무효화 패널 `invalidation_reasons_from_context_v9951` 등. **별도 `error_logs.csv` / 통합 `validation_engine` 없음.** |
| **학습** | 부분 | `build_learning_adjustment_v9987`, `compute_app_reliability_score`, 종목별 프로파일/보정 로직 분산. **요구 스펙의 `weight_config.json` / `learning_patterns.json` 고정 스키마와 1:1 대응 아님.** |
| **스캔** | 부분 | `run_swing_candidate_scan`, `scan_candidate_tickers_kr` 등, 산출물은 `reports/swing_candidates_*.csv`. **코스피·코스닥 전 종목을 항상 스캔하는 구조는 아니며**, 유니버스/한도/후보 파일 의존. |
| **관심종목** | 있음 | `watchlist_kr_growth.csv` / `watchlist_us_growth.csv`, `watchlist_symbols`, `load_watchlist_df` 등. |
| **runner** | 부분 | `run_headless_runner` — **내장 액션만** (아래 표). 별도 `runners/*.py` 없음. |
| **UI** | 있음 | `main()`, `render_native_*` 다수 (예측 히어로, 뉴스, 일일 플랜, 랭킹, 포트폴리오, 백테스트, 설정 등). |

### `run_headless_runner` 지원 액션 (현재)

| 액션 | 역할 |
|------|------|
| `us_predict` / `kr_predict` | 관심종목 기준 자동 예측 생성 + 일부 리포트 + 스윙 스캔 연동 |
| `us_update` / `kr_update` / `update` | `update_actual_results` + 주문/백테스트 스냅샷 |
| `us_sync` / `kr_sync` | 실제값 갱신 후 watchlist 전체에 대해 예측 생성 |
| `us_swing_scan` / `kr_swing_scan` / `swing_scan` | 스윙 후보 스캔 |
| `no_buy_self_check` | 매수금지 규칙 자가점검 (JSON 출력) |
| `us_predict_lock_skip` / `kr_predict_lock_skip` | 락 파일 시 상태/페이퍼만 기록 |

**없음:** `runner_news_update` 전용 액션(뉴스는 UI에서 `modules.news_scheduler.run_news_update` 호출 등). **독립 `runner_validation` / `runner_learning` / `runner_full_daily_cycle` 없음.**

### [핵심 문제]

| 구분 | 문제 |
|------|------|
| **구조** | 예측·이벤트·스캔·UI·러너·페이퍼트레이딩이 **한 파일**에 혼재. 테스트·단계적 배포 어려움. |
| **데이터** | 요구 컬럼 세트(`prediction_id`, `source_type`, OHLC 범위 전부, `trade_simulations.csv` 등)와 **레거시 `predictions.csv` 스키마 불일치**. 병행 스키마 필요. |
| **자동 실행** | 스케줄러는 `app.py --runner`에 의존. **표준화된 `run_status.json`(러너별 단일 파일) 없음** — `runner_status_kr.json` / `runner_status_us.json` 등 분산. |
| **전체 종목 스캔** | 스윙/후보 스캔은 있으나 **“코스피+코스닥 전 종목”을 매일 전량 스캔**하는 전용 파이프라인은 아님. |
| **국장 관심종목** | **`KR_CORE_WATCHLIST_V9922`** 및 **`ensure_kr_core_watchlist_v9922`**가 파일에 없을 때 **삼성전자·SK하이닉스 등 9개를 자동 보강** — 사용자 요구사항 **“국장 관심종목 기본값 없음”과 정면 충돌**. |
| **관심종목 상세 OHLC 예측** | watchlist 기반 예측·범위 계산은 존재하나, **스캔 후보와 UI가 분리된 13개 화면 구조**는 아님. |
| **자기보정 학습** | 점수 보정·신뢰도 일부 있으나, **오차 원인 분류 → `error_logs.csv` → 가중치 자동 반영**의 닫힌 루프는 스펙 대비 **부분 구현**. |
| **headless** | `--runner` 경로는 UI를 띄우지 않지만 **`import streamlit`이 모듈 로드 시 항상 실행**되어 무거움/부작용 가능. |

### [파일/함수 연결표] (핵심만; 전체 651개 함수는 별도 스크립트로 덤프 권장)

| 함수명 | 역할 | 입력 | 출력 | 저장 파일 | 호출 위치 |
|--------|------|------|------|-----------|-----------|
| `load_prediction_log` | 예측 CSV 로드 | `PREDICTION_FILE` | `DataFrame` | 읽기: `predictions.csv` | UI, 러너, 다수 분석 함수 |
| `save_prediction_row` | 행 추가/갱신 | row dict | bool | 쓰기: `predictions.csv` | 예측 생성 흐름 |
| `update_actual_results` | 실제 시세 반영 | `log_df` | `(df, count)` | 쓰기: `predictions.csv` | `kr_update`/`us_update`/`sync` |
| `auto_create_prediction_for_ticker` | 단일 종목 예측 생성 | ticker, market, … | 예측 row / side effect | `predictions.csv` | 배치 생성에서 호출 |
| `auto_generate_predictions_for_watchlist` | watchlist 배치 예측 | tickers, … | `(saved_count, messages)` | `predictions.csv` | `run_headless_runner` predict/sync |
| `build_auto_event_context` | 매크로/뉴스 등 이벤트 컨텍스트 | 날짜, market 등 | dict | 주로 예측 row 필드에 반영 | 예측·UI |
| `run_swing_candidate_scan` | 스윙 후보 스캔 | market, max_symbols | dict (paths, counts) | `reports/swing_candidates_*.csv` | 러너 swing_scan, predict 후 |
| `run_headless_runner` | 스케줄러용 CLI | `action: str` | exit code | `runner_status_*.json`, `predictions.csv`, reports | `if __name__` 블록 |
| `save_backtest_snapshot_v9985` | 백테스트 스냅샷 | log_df, market | paths dict | reports 하위 | `us_update`/`kr_update` 등 |
| `build_learning_adjustment_v9987` | 학습 보정 요소 | (시그니처 내부) | 보정 관련 값 | 주로 메모리/예측 필드 | 예측 경로 |
| `compute_app_reliability_score` | 신뢰도 점수 | market, log_df | dict/수치 | 간접 반영 | 러너 finalize |
| `ensure_kr_core_watchlist_v9922` | KR 코어 9종 자동 삽입 | save 플래그 | DataFrame | **쓰기: watchlist CSV** | 패치된 watchlist 로드 경로 |
| `main` | Streamlit 앱 전체 | — | — | 세션/캐시 | `python app.py` |

### [가능 여부] (요구 §20 하단 질문에 대한 답)

| 질문 | 판정 | 이유 | 추가 작업 |
|------|------|------|-----------|
| 전체 종목 스캔 | **부분 가능** | 스윙/후보 스캔·국장 후보 틱커 로직 있음. 전 시장 일괄 스캔·랭킹 산출 파이프라인은 미완. | 유니버스 소스, API 한도, `scanner_engine` + `scanner_results_kr.csv` 전용 러너 |
| 관심종목 OHLC 상세 예측 | **부분 가능** | watchlist 기반 예측·범위 필드 존재. 스펙의 13개 화면/최종판단 5분류 고정 출력은 UI/스키마 정리 필요. | `watchlist_user_kr.csv` 분리, 빈 목록 UX, `prediction_engine` 출력 표준화 |
| 자기보정 학습 | **부분 가능** | 보정·신뢰도·백테스트 일부. `error_logs.csv`·가중치 JSON 루프는 미구축. | `learning_engine` + 검증 결과를 오차 분류와 연결 |
| runner/headless | **부분 가능** | `--runner` 동작. Streamlit import 부담, 뉴스/검증/학습 전용 액션 부재. | `runners/*.py` + `core/`로 이전, 뉴스는 `python modules/news_scheduler.py` 패턴 활용 |

### [리팩토링 제안] (단계)

1. **스키마 병행:** 루트 `predictions.csv` 유지 + `data/decision_system/`에 신규 CSV 헤더만 생성, ETL/듀얼라이트 기간 둠.  
2. **`KR_CORE_WATCHLIST` 제거/비활성화:** 사용자 등록 파일만 “관심종목”; 스캐너는 별 유니버스.  
3. **러너 외부화:** `runners/*.py`가 로그·`config/decision_system/run_status.json` 기록 후, 과도기에는 `subprocess`로 `app.py --runner` 브리지 → 이후 `core`로 이전.

---

## [구현/분리한 파일 목록] (이번 커밋에서 추가)

| 파일 | 역할 |
|------|------|
| `core/*.py` | 엔진 **자리 표시자** (로직은 `app.py`에서 단계적 이전 예정). |
| `runners/_common.py` | 프로젝트 루트, 로그 append, `run_status.json` 갱신. |
| `runners/runner_*.py` | 헤드리스 진입점 (브리지 + 뉴스/검증 스텁). |
| `runners/runner_full_daily_cycle.py` | 정해진 순서로 서브러너 실행. |
| `config/decision_system/*.json` | `weight_config`, `learning_patterns`, `run_status` 초기 템플릿. |
| `data/decision_system/*.csv` | 스펙 컬럼 헤더만 있는 빈 CSV (레거시 파일과 병행). |

---

## [데이터 저장 구조] (신규; 레거시 미삭제)

`data/decision_system/` 아래 CSV는 **헤더만** 있으며 행은 비어 있을 수 있음. 실제 적재는 이후 엔진 구현 시 채움.

| 파일 | 용도 |
|------|------|
| `predictions.csv` | 요구 스키마 정렬 예측 로그 |
| `actual_results.csv` | 일별 실제 OHLC |
| `market_updates.csv` | 장중/장후 스냅샷 |
| `trade_simulations.csv` | 시뮬레이션 결과 |
| `error_logs.csv` | 예측 오차·원인 |

`config/decision_system/weight_config.json`, `learning_patterns.json`, `run_status.json` — 스펙 예시 구조 준수(최소 키).

---

## [아직 미완성인 부분]

- `core/*.py` 내 **실제 점수 산식·이벤트 해석 파이프라인** 미이전.  
- `runner_validation` / `runner_learning`은 **최소 동작**(파일 점검·상태 기록) 또는 스텁; 완전 검증·가중치 학습은 `validation_engine` / `learning_engine` 구현 후 연결.  
- Streamlit **13 화면** 재구성은 스펙 순서상 **UI 마지막 단계**에서 수행.  
- **국장 기본 9종 자동 보강** 제거는 `app.py` 수정이 필요하므로, 별도 변경 승인 후 `ensure_kr_core_watchlist_v9922` 비활성화 권장.

---

## [주의사항]

- **API 키:** Finnhub 등 기존과 동일하게 환경/설정 파일 의존 가능.  
- **작업 스케줄러:** bat는 사용자 요청 시에만 추가; 현재는 `python runners\runner_kr_predict.py` 형태로 수동 실행 가능.  
- **확인 권장:** 백업 파일 존재, 신규 `runners` 실행 시 `logs/runner_*.log` 및 `config/decision_system/run_status.json` 갱신 여부.

---

## 부록: `run_headless_runner`와 신규 runner 매핑 (과도기)

| 신규 `runners/*.py` | 현재 브리지 |
|---------------------|-------------|
| `runner_kr_predict.py` | `python app.py --runner kr_predict` |
| `runner_us_predict.py` | `python app.py --runner us_predict` |
| `runner_kr_update.py` | `python app.py --runner kr_update` |
| `runner_us_update.py` | `python app.py --runner us_update` |
| `runner_news_update.py` | `python modules/news_scheduler.py` |
| `runner_validation.py` | `predictions.csv` 존재/행수 점검 + (선택) `app.py --runner no_buy_self_check` |
| `runner_learning.py` | 스텁: 마이그레이션 대기 기록만 |
| `runner_full_daily_cycle.py` | 위 러너 순차 실행 |

이 문서는 **§20 현재 진단**과 **§22 보고서**의 초안 겸용이며, 엔진 이전이 진행될 때마다 갱신하는 것을 권장합니다.
