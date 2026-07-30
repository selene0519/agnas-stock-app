#!/usr/bin/env python3
"""국면 판정의 **시장별 단일 입구**. 정의 복제를 구조적으로 막는다.

왜 이 모듈이 필요했나 (2026-07-30 실측):

`regime_kr.py`를 검증된 정의(trend60+거래량)로 고쳤는데, 추천 생성기
`generate_kr_recommendations._load_market_regime`이 옛 정의(MA20 이격 +
5일 모멘텀)를 **자기 안에 복제해 두고** 있어서 교체가 추천 경로에 닿지 않았다.
15년 KOSPI로 맞춰보니 두 정의의 일치율이 **46.2%**(3,621일 중 1,949일 불일치).
미장은 더 나빴다 — `_price_band`가 국장 모듈 것이라 **미장 EV가 KOSPI 국면과
국장 승률표로 보정**되고 있었고, 두 시장의 국면 순서는 정반대다:

    KR mid  BULL 0.438  BEAR 0.440  **SIDE 0.368(최악)**
    US mid  BEAR 0.519  SIDE 0.460  **BULL 0.427(최악)**

즉 미장에서 가장 나쁜 국면(BULL)에 국장 표는 가장 높은 승률을 매겼다.

그래서 "어느 시장이냐"만 넘기면 **판정·승률표·점수가감이 한 세트로** 나오게
했다. 표와 판정이 갈라질 통로를 없애는 것이 목적이다.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# (모듈, 벤치마크 파일) — 판정에 쓰는 지수 파일의 mtime으로 캐시를 무효화한다.
_BENCH = {"kr": "kr_KOSPI_daily.csv", "us": "us_SPY_daily.csv"}
_cache: dict = {}


def module(market: str):
    """시장별 국면 모듈. 알 수 없는 시장은 국장으로 본다(기존 동작)."""
    if str(market or "").lower() == "us":
        import regime_us as m
    else:
        import regime_kr as m
    return m


def _mtime(repo: str, market: str) -> float:
    p = os.path.join(repo, "data", "market", "ohlcv",
                     _BENCH.get(str(market or "kr").lower(), _BENCH["kr"]))
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def latest(repo: str, market: str = "kr") -> tuple[str, str, dict]:
    """(regime, label, detail). 지수 CSV mtime이 같으면 캐시를 쓴다.

    캐시가 필요한 이유: `_price_band`가 후보 **한 건마다** 불리는데, 매번
    3,700행 CSV를 다시 읽으면 생성이 눈에 띄게 느려진다.
    """
    mk = str(market or "kr").lower()
    key = (repo, mk, _mtime(repo, mk))
    if key not in _cache:
        _cache.clear()          # 지수가 갱신되면 옛 항목은 전부 버린다
        _cache[key] = module(mk).latest_regime(repo)
    return _cache[key]


def ev_multiplier(market: str, regime: str, horizon: str) -> float:
    """국면 EV 배수 — **시장의 자기 표**로만 계산한다. 1.0을 넘지 않는다."""
    return module(market).ev_multiplier(regime, horizon)


def score_adjust(market: str, regime: str) -> float:
    return module(market).SCORE_ADJUST.get(str(regime or "").upper(), 0.0)


if __name__ == "__main__":
    repo = os.path.dirname(_HERE)
    for mk in ("kr", "us"):
        reg, label, detail = latest(repo, mk)
        muls = {h: round(ev_multiplier(mk, reg, h), 4) for h in ("short", "swing", "mid")}
        print(f"[{mk}] {reg}({label})  EV배수={muls}  점수가감={score_adjust(mk, reg):+.1f}")
        print(f"      {detail}")
