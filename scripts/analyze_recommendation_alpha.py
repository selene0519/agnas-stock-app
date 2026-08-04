#!/usr/bin/env python3
"""추천의 **알파**를 잰다 — 지금까지는 베타와 섞어서 재고 있었다.

문제:
  MONE의 모든 엣지 진단(`net_pnl_pct`, sleeve NAV, 승률)은 **원시 수익률**이다.
  보유 기간에 KOSPI가 5% 빠졌으면 −5% 거래는 실력 손실이 아니라 시장을 그대로
  탄 것이다. 반대로 시장이 10% 올랐는데 +2%면 그건 **마이너스 알파**다.

  즉 지금까지의 "−5.6%/거래"는 **선택 오차와 시장 하락이 섞인 값**이고,
  둘을 분리해본 적이 한 번도 없다. 분리하지 않으면 "추천이 나쁜 것"인지
  "장이 나빴던 것"인지 알 수 없고, 고칠 대상을 못 정한다.

방법 (표준 이벤트 스터디):
  참고: virattt/ai-hedge-fund `v2/event_study/` (시장모형 + CAR + t검정 + 부트스트랩).
  그쪽은 실적발표를 이벤트로 쓰지만, 여기서는 **추천 시그널일**을 이벤트로 둔다.

    1. 종목별로 추정창 [-250, -11] 거래일에서 시장모형을 OLS 적합
         R_stock = alpha + beta * R_market          (market = KOSPI/KOSDAQ)
       추정창이 이벤트 **이전**에서 끝나므로 룩어헤드가 없다.
    2. 이벤트창 [0, +N]에서 초과수익
         AR_t = R_stock,t - (alpha + beta * R_market,t)
    3. CAR = sum(AR). 이벤트 전체에 대해 평균 CAR, t검정, 부트스트랩 CI.

  H0: 평균 CAR = 0 (추천에 시장 대비 초과 설명력이 없다)
  p < 0.05로 H0을 기각하고 CAR > 0이면 그때 비로소 "알파가 있다"고 말할 수 있다.

무엇을 하지 않는가:
  - 게이트를 건드리지 않는다. 관측 전용이다.
  - HISTORICAL_REPLAY는 제외한다(가중치 0 정책).
  - 표본이 적으면 숨기지 않고 그대로 경고를 붙인다.

실행: python scripts/analyze_recommendation_alpha.py [--windows 1,5,20]
쓰기: reports/recommendation_alpha.json
의존: numpy (CI에 이미 설치됨)
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
OHLCV = ROOT / "data" / "market" / "ohlcv"
JOURNAL = ROOT / "data" / "virtual_trade_journal.csv"
MARKER = ROOT / "reports" / "clean_window_marker.json"
OUT = ROOT / "reports" / "recommendation_alpha.json"
KR_MASTER = ROOT / "data" / "stock_master_kr.csv"

# 추정창: 이벤트 11거래일 전에서 끝난다. 이벤트 직전 며칠은 정보가 새기
# 시작하는 구간이라 시장모형 적합에서 빼는 것이 표준이다.
EST_START, EST_END = -250, -11
MIN_EST_OBS = 60           # 이보다 적으면 alpha/beta를 못 믿는다
DEFAULT_WINDOWS = (1, 5, 20)
MIN_TRUSTWORTHY_N = 30
MIN_TRUSTWORTHY_DATES = 30

DEFAULT_BENCHMARKS = {"kr": "KOSPI", "us": "SPY"}
BENCHMARK = DEFAULT_BENCHMARKS  # compatibility for the retained v1 diagnostic


def _read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _num(v):
    try:
        s = str(v or "").replace(",", "").strip()
        return float(s) if s else None
    except Exception:
        return None


def _clean_window() -> str | None:
    try:
        return str(json.load(open(MARKER, encoding="utf-8")).get("cleanWindowStart") or "")[:10] or None
    except Exception:
        return None


def _load_series(path: Path) -> tuple[list[str], np.ndarray] | None:
    """(날짜 오름차순, 종가) — 로그수익률 계산용."""
    rows = _read_csv(path)
    if len(rows) < MIN_EST_OBS + 30:
        return None
    pairs = []
    for r in rows:
        d = str(r.get("date") or r.get("Date") or "")[:10]
        c = _num(r.get("close") or r.get("Close"))
        if d and c and c > 0:
            pairs.append((d, c))
    if len(pairs) < MIN_EST_OBS + 30:
        return None
    pairs.sort()
    dates = [d for d, _ in pairs]
    closes = np.array([c for _, c in pairs], dtype=float)
    return dates, closes


def _returns(closes: np.ndarray) -> np.ndarray:
    """단순 수익률. 길이는 closes보다 1 짧고 인덱스 i는 closes[i+1] 시점."""
    return closes[1:] / closes[:-1] - 1.0


def fit_market_model(stock: np.ndarray, market: np.ndarray) -> tuple[float, float, float]:
    """R_stock = alpha + beta * R_market 를 OLS로 적합. (alpha, beta, r2)."""
    X = np.column_stack([np.ones(len(stock)), market])
    coeffs, *_ = np.linalg.lstsq(X, stock, rcond=None)
    alpha, beta = float(coeffs[0]), float(coeffs[1])
    pred = alpha + beta * market
    ss_res = float(np.sum((stock - pred) ** 2))
    ss_tot = float(np.sum((stock - stock.mean()) ** 2))
    return alpha, beta, (1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0)


def _t_test(values: np.ndarray) -> tuple[float, float]:
    """일표본 t검정 (H0: 평균=0). scipy 없이 t분포 근사로 p를 낸다.

    표본이 30을 넘으면 정규근사 오차가 무시할 수준이라, 의존성을 늘리지 않고
    정규 CDF로 양측 p를 계산한다. 표본이 그보다 적으면 어차피 결론을 내면
    안 되는 구간이고, 호출부가 sampleWarning으로 그걸 밝힌다.
    """
    n = len(values)
    if n < 2:
        return 0.0, 1.0
    sd = float(np.std(values, ddof=1))
    if sd == 0:
        return 0.0, 1.0
    t = float(np.mean(values)) / (sd / np.sqrt(n))
    # 표준정규 양측 p — math.erfc로 계산(추가 의존성 없음).
    from math import erfc, sqrt
    p = erfc(abs(t) / sqrt(2.0))
    return t, p


def _bootstrap_ci(values: np.ndarray, n_boot: int = 5000,
                  confidence: float = 0.95, seed: int = 20260729) -> tuple[float, float]:
    """평균의 백분위 부트스트랩 신뢰구간. 분포 가정을 안 해서 소표본에 낫다."""
    if len(values) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(n_boot, len(values)))
    means = values[idx].mean(axis=1)
    lo = float(np.percentile(means, (1 - confidence) / 2 * 100))
    hi = float(np.percentile(means, (1 + confidence) / 2 * 100))
    return lo, hi


def _cluster_bootstrap_ci(
    values: np.ndarray,
    clusters: list[str],
    n_boot: int = 5000,
    confidence: float = 0.95,
    seed: int = 20260730,
) -> tuple[float, float, float, int]:
    """Equal-date block bootstrap for signals sharing one market shock."""
    grouped: dict[str, list[float]] = {}
    for value, cluster in zip(values, clusters):
        grouped.setdefault(str(cluster), []).append(float(value))
    daily_means = np.array([np.mean(grouped[key]) for key in sorted(grouped)], dtype=float)
    if len(daily_means) < 2:
        mean = float(daily_means.mean()) if len(daily_means) else float("nan")
        return float("nan"), float("nan"), mean, len(daily_means)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(daily_means), size=(n_boot, len(daily_means)))
    means = daily_means[idx].mean(axis=1)
    lo = float(np.percentile(means, (1 - confidence) / 2 * 100))
    hi = float(np.percentile(means, (1 + confidence) / 2 * 100))
    return lo, hi, float(daily_means.mean()), len(daily_means)


def _kr_benchmark_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in _read_csv(KR_MASTER):
        code = str(row.get("code") or row.get("symbol") or "").strip().split(".")[0].zfill(6)
        market_type = str(row.get("market_type") or row.get("note") or "").upper()
        if code.isdigit():
            mapping[code] = "KOSDAQ" if "KOSDAQ" in market_type or "코스닥" in market_type else "KOSPI"
    return mapping


def _decision_key(row: dict) -> str:
    return "|".join(
        str(row.get(key) or "").strip().lower()
        for key in ("as_of_date", "market", "symbol")
    )


def _dedupe_journal_rows(rows: list[dict]) -> tuple[list[dict], int]:
    selected: dict[str, dict] = {}
    for row in rows:
        key = _decision_key(row)
        previous = selected.get(key)
        if previous is None:
            selected[key] = row
            continue
        previous_score = _num(previous.get("final_rank_score"))
        score = _num(row.get("final_rank_score"))
        if (score if score is not None else float("-inf")) > (
            previous_score if previous_score is not None else float("-inf")
        ):
            selected[key] = row
    return list(selected.values()), len(rows) - len(selected)


def _select_strategy_cohort(rows: list[dict], fingerprint: str | None) -> tuple[list[dict], str]:
    if fingerprint:
        return [row for row in rows if str(row.get("strategy_fingerprint") or "").strip() == fingerprint], fingerprint
    identified = [row for row in rows if str(row.get("strategy_fingerprint") or "").strip()]
    if not identified:
        return rows, "LEGACY_UNFINGERPRINTED"
    latest_by_fingerprint: dict[str, str] = {}
    for row in identified:
        fp = str(row.get("strategy_fingerprint") or "").strip()
        date = str(row.get("as_of_date") or "")[:10]
        latest_by_fingerprint[fp] = max(latest_by_fingerprint.get(fp, ""), date)
    selected = max(latest_by_fingerprint, key=lambda fp: latest_by_fingerprint[fp])
    return [row for row in identified if str(row.get("strategy_fingerprint") or "").strip() == selected], selected


def _compute_v1_legacy(windows: tuple[int, ...], since: str | None) -> dict:
    bench = _load_series(OHLCV / f"kr_{BENCHMARK['kr']}_daily.csv")
    if not bench:
        return {"status": "NO_BENCHMARK"}
    bdates, bcloses = bench
    bret = _returns(bcloses)
    bidx = {d: i for i, d in enumerate(bdates)}

    events: list[dict] = []
    skipped = {"noOhlcv": 0, "shortEstimation": 0, "noBenchmarkDate": 0,
               "shortEventWindow": 0, "replaySource": 0, "beforeSince": 0}

    cache: dict[str, tuple[list[str], np.ndarray] | None] = {}

    for row in _read_csv(JOURNAL):
        if str(row.get("source_type") or "").upper() != "FORWARD_PAPER_TRADE":
            skipped["replaySource"] += 1
            continue
        if str(row.get("market") or "").lower() != "kr":
            continue
        date = str(row.get("as_of_date") or row.get("captured_at") or "")[:10]
        symbol = str(row.get("symbol") or "").strip().zfill(6)
        if not date or not symbol.isdigit():
            continue
        if since and date < since:
            skipped["beforeSince"] += 1
            continue

        if symbol not in cache:
            cache[symbol] = _load_series(OHLCV / f"kr_{symbol}_daily.csv")
        series = cache[symbol]
        if not series:
            skipped["noOhlcv"] += 1
            continue
        sdates, scloses = series
        sret = _returns(scloses)

        # 이벤트일 = 시그널 당일. 그 날짜가 없으면 다음 거래일로 민다.
        pos = bisect.bisect_left(sdates, date)
        if pos <= 0 or pos >= len(sdates):
            skipped["noBenchmarkDate"] += 1
            continue
        # sret 인덱스는 sdates[i+1] 시점이므로 -1 보정
        ev = pos - 1
        est_lo, est_hi = ev + EST_START, ev + EST_END
        if est_lo < 0 or (est_hi - est_lo) < MIN_EST_OBS:
            skipped["shortEstimation"] += 1
            continue
        # **가장 짧은 창만 만족하면 채택한다.** 예전엔 `max(windows)`를 요구해서
        # D+20치 미래 봉이 없는 최근 시그널이 **통째로** 버려졌고, 그 결과 남은
        # 표본이 과거 며칠에 몰려 군집이 됐다(실측: 150건 전부 2026-06의 6일).
        # D+1·D+5는 훨씬 최근까지 계산 가능한데 D+20 요건에 끌려 같이 죽은 것이다.
        if ev + min(windows) >= len(sret):
            skipped["shortEventWindow"] += 1
            continue

        # 시장 수익률을 종목 거래일에 맞춰 정렬한다. 벤치마크에 없는 날은 버린다.
        def _bench_at(day: str) -> float | None:
            i = bidx.get(day)
            return float(bret[i - 1]) if i and 0 < i <= len(bret) else None

        est_days = sdates[est_lo + 1: est_hi + 1]
        pairs = [(sret[est_lo + k], _bench_at(d)) for k, d in enumerate(est_days)]
        pairs = [(s, m) for s, m in pairs if m is not None]
        if len(pairs) < MIN_EST_OBS:
            skipped["shortEstimation"] += 1
            continue
        s_arr = np.array([s for s, _ in pairs])
        m_arr = np.array([m for _, m in pairs])
        alpha, beta, r2 = fit_market_model(s_arr, m_arr)

        # 이벤트창 초과수익
        # 창마다 **독립적으로** 계산한다. 봉이 모자란 창만 비우고 나머지는 살린다.
        cars: dict[str, float] = {}
        raws: dict[str, float] = {}
        for w in windows:
            if ev + w >= len(sret):
                skipped[f"shortWindow_D+{w}"] = skipped.get(f"shortWindow_D+{w}", 0) + 1
                continue
            ar_sum = 0.0
            raw_sum = 0.0
            for k in range(0, w + 1):
                j = ev + k
                d = sdates[j + 1]
                mr = _bench_at(d)
                if mr is None:
                    continue
                ar_sum += float(sret[j]) - (alpha + beta * mr)
                raw_sum += float(sret[j])
            cars[f"car{w}"] = ar_sum * 100.0
            raws[f"raw{w}"] = raw_sum * 100.0
        if not cars:
            skipped["shortEventWindow"] += 1
            continue

        events.append({"date": date, "symbol": symbol, "beta": round(beta, 3),
                       "r2": round(r2, 3), **{k: round(v, 4) for k, v in cars.items()},
                       **{k: round(v, 4) for k, v in raws.items()}})

    result: dict = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "since": since,
        "method": ("시장모형 이벤트 스터디. 추정창 [-250,-11] 거래일에서 "
                   "R_stock = alpha + beta*R_KOSPI 를 OLS 적합 후, 이벤트창의 "
                   "초과수익을 누적(CAR). 추정창이 이벤트 이전에서 끝나 룩어헤드 없음."),
        "reference": "virattt/ai-hedge-fund v2/event_study (실적발표 대신 추천일을 이벤트로 사용)",
        "events": len(events),
        "skipped": skipped,
        "windows": {},
    }
    if not events:
        result["status"] = "NO_EVENTS"
        return result
    result["status"] = "OK"
    result["avgBeta"] = round(float(np.mean([e["beta"] for e in events])), 3)

    # 표본이 어느 구간에 몰려 있는지 반드시 밝힌다. 긴 창(D+20)일수록 최근
    # 시그널이 통째로 빠져(앞으로의 봉이 없어서) **과거 쪽으로 편향된다.**
    # 이걸 안 보이면 "알파가 있다"를 최근 성적으로 오독하게 된다.
    dates = sorted(e["date"] for e in events)
    months: dict[str, int] = {}
    for d in dates:
        months[d[:7]] = months.get(d[:7], 0) + 1
    result["eventDateRange"] = {"min": dates[0], "max": dates[-1]}
    result["eventsByMonth"] = months
    result["caveats"] = [
        ("긴 이벤트창일수록 최근 시그널이 제외되어(앞으로의 봉 부족) 표본이 "
         "과거로 편향된다. windows별 events 수와 eventsByMonth를 같이 볼 것."),
        ("베타는 이벤트 **이전** 추정창에서 적합된다. 국면이 급변하면(예: 급락장) "
         "실제 베타가 커져 시장 몫이 과소평가되고 알파가 과대평가될 수 있다."),
        ("알파가 (+)라는 것은 '시장보다 덜 빠졌다'는 뜻이지 '돈을 벌었다'가 아니다. "
         "원시수익(meanRawReturnPct)이 (-)면 실제 계좌는 줄어든다."),
    ]

    # ── 이벤트 군집 진단 (이게 없으면 p값을 믿게 된다) ─────────────────────
    # 표준 이벤트 스터디의 t검정은 이벤트끼리 **독립**임을 가정한다. 그런데
    # 시그널이 며칠 안에 몰려 있으면 모든 이벤트가 같은 시장 충격을 공유해서
    # 사실상 표본 1개짜리 관측이 된다. 그 상태의 p값은 실제보다 훨씬 작게 나온다.
    # 2026-07-29 실측: D+20 이벤트 150건이 2026-06-19~26 8일 안에 전부 몰려 있었고,
    # 그 직후 KOSPI가 24% 빠졌다. 즉 "150건"이 아니라 "한 주"짜리 관측이다.
    distinct_days = len(set(dates))
    span_days = (datetime.fromisoformat(dates[-1]) - datetime.fromisoformat(dates[0])).days + 1
    clustered = distinct_days < 10 or (len(events) / max(distinct_days, 1)) > 10
    result["clustering"] = {
        "distinctEventDates": distinct_days,
        "calendarSpanDays": span_days,
        "eventsPerDate": round(len(events) / max(distinct_days, 1), 1),
        "isClustered": clustered,
        "note": ("이벤트가 며칠에 몰려 있으면 t검정의 독립성 가정이 깨진다. "
                 "모든 이벤트가 같은 시장 충격을 공유하므로 유효 표본은 "
                 "'이벤트 수'가 아니라 '서로 다른 날 수'에 가깝다. "
                 "isClustered=true면 pValue/significant를 근거로 쓰지 말 것."),
    }

    for w in windows:
        rows = [e for e in events if f"car{w}" in e]
        if not rows:
            continue
        car = np.array([e[f"car{w}"] for e in rows])
        raw = np.array([e[f"raw{w}"] for e in rows])
        # **군집은 창마다 다르다.** 짧은 창일수록 최근 시그널까지 들어와
        # 여러 날에 퍼지고, 긴 창은 과거 며칠에 몰린다. 전체 기준 하나로
        # 판정하면 짧은 창의 결론까지 같이 못 쓰게 된다.
        wdates = sorted(e["date"] for e in rows)
        wdistinct = len(set(wdates))
        wclustered = wdistinct < 10 or (len(rows) / max(wdistinct, 1)) > 10
        wmonths: dict[str, int] = {}
        for d in wdates:
            wmonths[d[:7]] = wmonths.get(d[:7], 0) + 1
        t, p = _t_test(car)
        lo, hi = _bootstrap_ci(car)
        result["windows"][f"D+{w}"] = {
            "events": len(car),
            "dateRange": {"min": wdates[0], "max": wdates[-1]},
            "distinctEventDates": wdistinct,
            "eventsPerDate": round(len(rows) / max(wdistinct, 1), 1),
            "isClustered": wclustered,
            "eventsByMonth": wmonths,
            "meanCarPct": round(float(car.mean()), 4),
            "meanRawReturnPct": round(float(raw.mean()), 4),
            # 원시수익 − 알파 = 시장이 끌고 간 몫. 이 값이 크면 "장 탓"이 크다.
            "marketComponentPct": round(float(raw.mean() - car.mean()), 4),
            "positiveShare": round(float((car > 0).mean()), 4),
            "tStat": round(t, 3),
            "pValue": round(p, 5),
            "significant": bool(p < 0.05),
            "bootstrapCi95": [round(lo, 4), round(hi, 4)],
            "sampleWarning": (None if len(car) >= MIN_TRUSTWORTHY_N
                              else f"표본 {len(car)}건 — {MIN_TRUSTWORTHY_N}건 미만이라 결론 금지"),
            # 군집이면 significant를 그대로 읽으면 안 된다. **창별 군집**으로 판정한다.
            "significanceUsable": bool(p < 0.05 and not wclustered
                                       and len(car) >= MIN_TRUSTWORTHY_N),
        }
    return result


def compute(
    windows: tuple[int, ...],
    since: str | None,
    fingerprint: str | None = None,
    market: str = "all",
) -> dict:
    """Compute fingerprint-isolated, market/date-cluster-aware recommendation alpha."""
    events: list[dict] = []
    skipped = {
        "noOhlcv": 0,
        "noBenchmark": 0,
        "shortEstimation": 0,
        "noBenchmarkDate": 0,
        "shortEventWindow": 0,
        "replaySource": 0,
        "beforeSince": 0,
        "marketMismatch": 0,
        "duplicateDecision": 0,
    }
    requested_market = str(market or "all").lower()
    raw_forward: list[dict] = []
    for row in _read_csv(JOURNAL):
        if str(row.get("source_type") or "").upper() != "FORWARD_PAPER_TRADE":
            skipped["replaySource"] += 1
            continue
        row_market = str(row.get("market") or "").lower()
        if row_market not in {"kr", "us"} or (requested_market != "all" and row_market != requested_market):
            skipped["marketMismatch"] += 1
            continue
        raw_forward.append(row)

    cohort_rows, selected_fingerprint = _select_strategy_cohort(raw_forward, fingerprint)
    filtered: list[dict] = []
    for row in cohort_rows:
        signal_date = str(row.get("as_of_date") or row.get("captured_at") or "")[:10]
        if since and signal_date < since:
            skipped["beforeSince"] += 1
            continue
        filtered.append(row)
    rows, duplicate_count = _dedupe_journal_rows(filtered)
    skipped["duplicateDecision"] = duplicate_count

    kr_benchmarks = _kr_benchmark_map()
    stock_cache: dict[tuple[str, str], tuple[list[str], np.ndarray] | None] = {}
    benchmark_cache: dict[tuple[str, str], tuple[list[str], np.ndarray] | None] = {}

    for row in rows:
        row_market = str(row.get("market") or "").lower()
        signal_date = str(row.get("as_of_date") or row.get("captured_at") or "")[:10]
        raw_symbol = str(row.get("symbol") or "").strip().upper().split(".")[0]
        symbol = raw_symbol.zfill(6) if row_market == "kr" else raw_symbol
        if not signal_date or not symbol or (row_market == "kr" and not symbol.isdigit()):
            continue

        benchmark_symbol = kr_benchmarks.get(symbol, DEFAULT_BENCHMARKS["kr"]) if row_market == "kr" else DEFAULT_BENCHMARKS["us"]
        benchmark_key = (row_market, benchmark_symbol)
        if benchmark_key not in benchmark_cache:
            benchmark_cache[benchmark_key] = _load_series(OHLCV / f"{row_market}_{benchmark_symbol}_daily.csv")
        bench = benchmark_cache[benchmark_key]
        if not bench:
            skipped["noBenchmark"] += 1
            continue
        benchmark_dates, benchmark_closes = bench
        benchmark_returns = _returns(benchmark_closes)
        benchmark_index = {day: idx for idx, day in enumerate(benchmark_dates)}

        stock_key = (row_market, symbol)
        if stock_key not in stock_cache:
            stock_cache[stock_key] = _load_series(OHLCV / f"{row_market}_{symbol}_daily.csv")
        series = stock_cache[stock_key]
        if not series:
            skipped["noOhlcv"] += 1
            continue
        stock_dates, stock_closes = series
        stock_returns = _returns(stock_closes)

        position = bisect.bisect_left(stock_dates, signal_date)
        if position <= 0 or position >= len(stock_dates):
            skipped["noBenchmarkDate"] += 1
            continue
        event_index = position - 1
        estimate_low, estimate_high = event_index + EST_START, event_index + EST_END
        if estimate_low < 0 or (estimate_high - estimate_low) < MIN_EST_OBS:
            skipped["shortEstimation"] += 1
            continue
        if event_index + max(windows) >= len(stock_returns):
            skipped["shortEventWindow"] += 1
            continue

        def benchmark_at(day: str) -> float | None:
            idx = benchmark_index.get(day)
            return float(benchmark_returns[idx - 1]) if idx and 0 < idx <= len(benchmark_returns) else None

        estimate_days = stock_dates[estimate_low + 1: estimate_high + 1]
        pairs = [
            (stock_returns[estimate_low + offset], benchmark_at(day))
            for offset, day in enumerate(estimate_days)
        ]
        pairs = [(stock_return, benchmark_return) for stock_return, benchmark_return in pairs if benchmark_return is not None]
        if len(pairs) < MIN_EST_OBS:
            skipped["shortEstimation"] += 1
            continue
        estimate_stock = np.array([stock_return for stock_return, _ in pairs])
        estimate_benchmark = np.array([benchmark_return for _, benchmark_return in pairs])
        alpha, beta, r2 = fit_market_model(estimate_stock, estimate_benchmark)

        cars: dict[str, float] = {}
        raw_returns: dict[str, float] = {}
        complete = True
        for window in windows:
            abnormal_sum = 0.0
            raw_sum = 0.0
            for offset in range(0, window + 1):
                idx = event_index + offset
                if idx >= len(stock_returns):
                    complete = False
                    break
                benchmark_return = benchmark_at(stock_dates[idx + 1])
                if benchmark_return is None:
                    continue
                abnormal_sum += float(stock_returns[idx]) - (alpha + beta * benchmark_return)
                raw_sum += float(stock_returns[idx])
            if not complete:
                break
            cars[f"car{window}"] = abnormal_sum * 100.0
            raw_returns[f"raw{window}"] = raw_sum * 100.0
        if not complete:
            skipped["shortEventWindow"] += 1
            continue

        events.append({
            "date": signal_date,
            "cluster": f"{row_market}|{signal_date}",
            "market": row_market,
            "symbol": symbol,
            "benchmark": benchmark_symbol,
            "strategyFingerprint": selected_fingerprint,
            "beta": round(beta, 3),
            "r2": round(r2, 3),
            **{key: round(value, 4) for key, value in cars.items()},
            **{key: round(value, 4) for key, value in raw_returns.items()},
        })

    result: dict = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "since": since,
        "market": requested_market,
        "strategyFingerprint": selected_fingerprint,
        "sampleUnit": "UNIQUE_AS_OF_DATE_MARKET_SYMBOL",
        "method": (
            "Pre-event market-model CAR. KR uses KOSPI/KOSDAQ by listing market; US uses SPY. "
            "Inference resamples equal-weight market-date blocks instead of recommendation rows."
        ),
        "reference": "virattt/ai-hedge-fund v2/event_study (recommendation date as event)",
        "events": len(events),
        "skipped": skipped,
        "windows": {},
    }
    if not events:
        result["status"] = "NO_EVENTS"
        return result

    result["status"] = "OK"
    result["avgBeta"] = round(float(np.mean([event["beta"] for event in events])), 3)
    result["eventsByMarket"] = {
        name: sum(1 for event in events if event["market"] == name)
        for name in ("kr", "us")
        if any(event["market"] == name for event in events)
    }
    result["benchmarks"] = sorted({f"{event['market']}:{event['benchmark']}" for event in events})

    dates = sorted(event["date"] for event in events)
    months: dict[str, int] = {}
    for event_date in dates:
        months[event_date[:7]] = months.get(event_date[:7], 0) + 1
    result["eventDateRange"] = {"min": dates[0], "max": dates[-1]}
    result["eventsByMonth"] = months
    result["caveats"] = [
        "Long event windows exclude recent signals and bias the sample toward older cohorts.",
        "Pre-event beta can be stale during abrupt regime changes.",
        "Positive CAR does not imply positive account PnL; raw return must also be positive.",
        "US sector benchmarks are not yet applied; US residuals currently use SPY.",
    ]

    clusters = [event["cluster"] for event in events]
    distinct_clusters = len(set(clusters))
    distinct_dates = len(set(dates))
    span_days = (datetime.fromisoformat(dates[-1]) - datetime.fromisoformat(dates[0])).days + 1
    result["clustering"] = {
        "distinctEventDates": distinct_dates,
        "distinctMarketDateBlocks": distinct_clusters,
        "calendarSpanDays": span_days,
        "eventsPerDate": round(len(events) / max(distinct_clusters, 1), 1),
        "isClustered": len(events) > distinct_clusters,
        "inferenceMethod": "EQUAL_MARKET_DATE_BLOCK_BOOTSTRAP",
        "minBlocksForUse": MIN_TRUSTWORTHY_DATES,
        "note": (
            "Signals from one market-date share a shock. Row-level inference is diagnostic only; "
            "promotion uses equal market-date block means and block bootstrap confidence intervals."
        ),
    }

    unique_clusters = sorted(set(clusters))
    for window in windows:
        car = np.array([event[f"car{window}"] for event in events])
        raw = np.array([event[f"raw{window}"] for event in events])
        naive_t, naive_p = _t_test(car)
        naive_low, naive_high = _bootstrap_ci(car)
        block_low, block_high, block_mean, block_count = _cluster_bootstrap_ci(car, clusters)
        daily_means = np.array([
            np.mean([event[f"car{window}"] for event in events if event["cluster"] == cluster])
            for cluster in unique_clusters
        ])
        block_t, block_p = _t_test(daily_means)
        significant = bool(block_p < 0.05 and block_low > 0)
        usable = bool(significant and block_count >= MIN_TRUSTWORTHY_DATES)
        result["windows"][f"D+{window}"] = {
            "events": len(car),
            "independentMarketDateBlocks": block_count,
            "meanCarPct": round(float(car.mean()), 4),
            "blockMeanCarPct": round(block_mean, 4),
            "meanRawReturnPct": round(float(raw.mean()), 4),
            "marketComponentPct": round(float(raw.mean() - car.mean()), 4),
            "positiveShare": round(float((car > 0).mean()), 4),
            "tStat": round(block_t, 3),
            "pValue": round(block_p, 5),
            "significant": significant,
            "bootstrapCi95": [round(block_low, 4), round(block_high, 4)],
            "naiveRowInference": {
                "tStat": round(naive_t, 3),
                "pValue": round(naive_p, 5),
                "bootstrapCi95": [round(naive_low, 4), round(naive_high, 4)],
                "usableForPromotion": False,
            },
            "sampleWarning": (
                None if block_count >= MIN_TRUSTWORTHY_DATES
                else f"Only {block_count} independent market-date blocks; need {MIN_TRUSTWORTHY_DATES}."
            ),
            "significanceUsable": usable,
        }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", default="1,5,20")
    ap.add_argument("--all", action="store_true", help="clean window 이전 표본도 포함")
    ap.add_argument("--market", choices=("all", "kr", "us"), default="all")
    ap.add_argument("--fingerprint", default=None, help="특정 전략 fingerprint cohort만 분석")
    args = ap.parse_args()
    windows = tuple(int(x) for x in args.windows.split(",") if x.strip())
    since = None if args.all else _clean_window()

    data = compute(windows, since, fingerprint=args.fingerprint, market=args.market)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== 추천 알파 (시장모형 이벤트 스터디{', ' + since + '~' if since else ', 전체'}) ===")
    if data.get("status") != "OK":
        print(f"  {data.get('status')} — 제외: {data.get('skipped')}")
        return 0
    print(f"  이벤트 {data['events']}건 · 평균 베타 {data['avgBeta']}")
    print(f"  제외: {data['skipped']}\n")
    c = data.get("clustering") or {}
    if c.get("isClustered"):
        print(f"  [!] 이벤트 군집: 서로 다른 날 {c['distinctEventDates']}일에 "
              f"{data['events']}건이 몰려 있다 ({c['eventsPerDate']}건/일).")
        print("      독립성 가정이 깨져 p값을 근거로 쓸 수 없다.")
    print(f"  기간 {data['eventDateRange']['min']} ~ {data['eventDateRange']['max']}\n")
    # **`significant`(p<0.05)를 그대로 찍으면 안 된다.** 군집이면 그 p값은
    # 독립성 가정이 깨진 상태의 값이라 근거가 못 된다. 화면에는 반드시
    # `significanceUsable`(군집·표본수까지 통과한 것)을 찍는다 — 이 레포가
    # 반복해서 당한 낙관 누출과 같은 형태다.
    print(f"  {'창':<7}{'n':>6}{'날수':>6}{'원시%':>9}{'시장몫%':>10}"
          f"{'알파(CAR)%':>12}{'p값':>9}{'쓸수있나':>9}")
    for name, w in data["windows"].items():
        if w.get("significanceUsable"):
            verdict = "예"
        elif w.get("isClustered"):
            verdict = "군집"
        elif w.get("sampleWarning"):
            verdict = "표본부족"
        else:
            verdict = "아니오"
        print(f"  {name:<7}{w['events']:>6}{w.get('distinctEventDates', 0):>6}"
              f"{w['meanRawReturnPct']:>9.2f}{w['marketComponentPct']:>10.2f}"
              f"{w['meanCarPct']:>12.3f}{w['pValue']:>9.4f}{verdict:>9}")
    print("\n  '쓸수있나' = 군집 아님 + 표본 30건 이상 + p<0.05 를 모두 통과했는가.")
    print("  '군집'이면 p값이 아무리 작아도 근거로 쓸 수 없다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
