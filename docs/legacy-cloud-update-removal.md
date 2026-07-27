# 레거시 cloud update 제거 근거 (2026-07-28 조사)

`mone-auto-accumulator`의 `Run MONE cloud update` 스텝
(`scripts/mone_github_auto_update.py` → `run_cloud_accumulator.py`)을 제거했다.
"25분짜리 무거운 작업"이 아니라 **2026-05-28 이후 아무 산출물도 남기지 못하는
빈 실행**이었기 때문이다.

## 실측 근거

**1. 매번 정확히 25분 내부 타임아웃에 걸린다**

`mone_github_auto_update.run_base_update()`가 `timeout=25*60`으로 서브프로세스를
띄운다. CI 스텝 소요시간이 run #337·#343 모두 **1501초**(=1500초 + 1초).
즉 25분을 기다린 뒤 죽는다.

**2. 체인의 첫 두 엔진은 아예 존재하지 않는다**

`run_cloud_accumulator.py`가 부르는 `run_auto_accumulator`,
`run_v36_full_update` 모듈이 레포에 없다 → 즉시 ImportError(삼켜짐).
남은 12개 엔진(v43~v74)은 각각 뉴스·시세를 새로 받아오며 순차 실행되고,
그 중 `v65_maximum_ux_engine`은 **같은 호출이 두 번** 들어가 있다.

**3. 스크립트가 끝까지 도달한 적이 없다**

`run_cloud_accumulator.main()`이 맨 마지막 줄에서 쓰는
`reports/cloud_accumulator_last_run.json`이 **git에 한 번도 존재한 적 없다.**

**4. 산출물이 커밋 대상이 아니다**

레거시 고유 산출물(v40~v74 접두) **68개 중 68개가 스테이징 allowlist에 없다.**
CI 러너는 휘발성이므로 생성해도 그대로 사라진다.
전체 98개 산출물 중 79개가 7월 이전(대부분 5~6월)에 갱신이 멈췄다.

**5. 앱이 읽는 미러 파일도 2개월째 동결**

`mirror_core_reports()`가 만드는 `v92_*`/`v93_*` 미러는 백엔드가 실제로 읽는다.
그런데 git 상의 106개가 **전부 2026-05-28 커밋**이 마지막이고, 이 역시
스테이징 목록에 0개 포함이라 CI에서 재생성돼도 커밋되지 않는다.

**6. 겹치는 산출물은 현대 파이프라인에 생산자가 있다**

| 파일 | 현대 생산자 |
|---|---|
| `reports/news_summary_*.csv`, `data/news/gnews_cache.csv` | accumulator GNews 스텝 + `mone-news-refresh.yml` (2026-07-27 갱신 확인) |
| `benchmark_daily.csv` | `scripts/fetch_benchmark_data.py` |
| `intraday_realtime_snapshot*.csv` | accumulator "Refresh live KIS quotes" |
| `data/market/ohlcv/*` | `scripts/backfill_ohlcv_history.py` 외 |

## 결론

제거해도 앱 동작은 바뀌지 않는다. 하루 25분을 되찾는다.

## 남은 숙제 (이 PR 범위 밖)

백엔드가 여전히 `v92_*` 미러를 읽는데 그 데이터는 **2026-05-28에 멈춰 있다.**
제거 때문에 멈추는 게 아니라 이미 2개월째 그 상태였다. 어떤 화면이 이걸
참조하는지 훑어서 (a) 현대 소스로 갈아끼우거나 (b) 해당 기능을 접는 판단이
필요하다. 값이 조용히 낡은 채로 서빙되는 것이 더 위험하다.
