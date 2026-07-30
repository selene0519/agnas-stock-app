#!/usr/bin/env python3
"""미장 국면 판정 — **국장과 다른 표를 쓴다.**

⚠️ 2026-07-30까지 미장 판정은 `generate_us_recommendations._load_us_market_regime`의
SPY/QQQ/DIA **3지수 투표**였고, 각 지수를 옛 정의(MA20 이격 + 5일 모멘텀)로
분류했다. 그 정의는 국장에서 국면을 못 가른다고 판정돼 폐기된 것과 같은 식이다.
SPY 15년으로 맞춰보니 검증정의와 **일치가 51.1%**(3,711일 중 1,813일 불일치)였다.

더 나빴던 것: `_price_band`가 국장 모듈 함수라 **미장 EV가 KOSPI 국면과 국장
승률표로 보정**되고 있었다. 두 시장의 국면 순서는 정반대다 —

    KR   SIDE가 최악          (횡보 구간에서 좁은 손절이 잡음에 털린다)
    US   BULL이 최악, BEAR가 최고 (하락 뒤 되돌림이 훨씬 강하다)

즉 미장에서 가장 나쁜 국면에 국장 표는 두 번째로 높은 승률을 매기고 있었다.
정확한 수치는 `WIN_RATES`에 있다 — **여기에 복제하지 말 것.**

⚠️ **생존편향이 국장보다 훨씬 심하다.** 유니버스가 15년 강세장을 살아남은
   158종목이고, 그 종목들의 하락을 사는 것은 사후적으로 매우 유리하다.
   상장폐지·피인수 종목이 없다. 그래서 이 표는 **국면 간 상대 순서**를
   말할 뿐이고 절대 수준은 크게 낙관 쪽이다.
   BEAR 가중치를 그대로 EV에 쓰면 하락장에 과도하게 공격적이 될 수 있어,
   **풀링 대비 비율을 1.0 이상으로는 올리지 않는다**(아래 clamp).
"""
from __future__ import annotations

import csv
import os

LABEL = {"BULL": "강세장", "BEAR": "약세장", "SIDE": "횡보장"}

# 국장과 동일 구조의 임계. 미장 벤치마크는 SPY.
TREND60_BULL = 3.0
TREND60_BEAR = -3.0
VOL_DRYUP_RATIO = 0.85
# |trend60|가 이만큼 크면 거래량과 무관하게 추세를 인정한다. 근거는 regime_kr
# 과 동일하며, 미장에서 이득이 더 크다(격차가 세 호라이즌 **전부** 개선).
TREND60_STRONG = 8.0

# 채택 정의 `trend60+거래량(약추세만)`의 **같은 실행 산출**:
#   reports/regime_recalibration_us_{short,swing,mid}.json
# **`_classify`와 반드시 같은 정의여야 한다.** 표를 손으로 고치지 말고
# `recalibrate_regime_definition.py --market us`를 다시 돌려 옮길 것.
WIN_RATES = {
    "short": {"BULL": 0.441, "SIDE": 0.464, "BEAR": 0.496},   # n=75,479
    "swing": {"BULL": 0.432, "SIDE": 0.453, "BEAR": 0.500},   # n=75,324
    "mid":   {"BULL": 0.427, "SIDE": 0.449, "BEAR": 0.512},   # n=75,010
}
POOLED = {"short": 0.456, "swing": 0.448, "mid": 0.446}
# 국면별 점수 가감. 국장과 동일하게 근거 없는 레거시 값이라 그대로 옮긴다.
SCORE_ADJUST = {"BULL": 5.0, "SIDE": 0.0, "BEAR": -15.0}


def _spy(repo: str):
    path = os.path.join(repo, "data", "market", "ohlcv", "us_SPY_daily.csv")
    if not os.path.exists(path):
        return []
    out = []
    for x in csv.reader(open(path, encoding="utf-8-sig")):
        if not x or not x[0] or x[0] == "date":
            continue
        try:
            out.append((x[0], float(x[6]), float(x[7] or 0)))
        except (ValueError, IndexError):
            continue
    out.sort(key=lambda r: r[0])
    return out


def _vol_ratio(vols: list, i: int) -> float | None:
    """결측(0) 봉은 건너뛴다 — 한 개 때문에 기능이 조용히 꺼지는 것을 막는다."""
    if i < 59:
        return None
    v20 = [v for v in vols[i - 19:i + 1] if v]
    v60 = [v for v in vols[i - 59:i + 1] if v]
    if len(v20) < 10 or len(v60) < 30:
        return None
    b = sum(v60) / len(v60)
    return (sum(v20) / len(v20) / b) if b else None


def _classify(trend60: float | None, vol_ratio: float | None = None) -> str:
    if trend60 is None:
        return "SIDE"
    if (vol_ratio is not None and vol_ratio < VOL_DRYUP_RATIO
            and abs(trend60) < TREND60_STRONG):
        return "SIDE"
    if trend60 > TREND60_BULL:
        return "BULL"
    if trend60 < TREND60_BEAR:
        return "BEAR"
    return "SIDE"


def regime_from_rows(rows: list, benchmark: str = "SPY") -> tuple[str, str, dict]:
    """(date, close, volume) 리스트에서 최신 국면. **판정식의 유일한 입구.**"""
    closes = [r[1] for r in rows]
    vols = [r[2] if len(r) > 2 else 0 for r in rows]
    if len(closes) < 61:
        return ("SIDE", LABEL["SIDE"], {"reason": f"{benchmark} 데이터 부족(61봉 미만)",
                                        "benchmark": benchmark,
                                        "definition": "trend60+거래량(약추세만)"})
    t60 = ((closes[-1] - closes[-61]) / closes[-61] * 100) if closes[-61] else None
    vr = _vol_ratio(vols, len(vols) - 1)
    reg = _classify(t60, vr)
    return (reg, LABEL[reg], {
        "asOf": rows[-1][0], "benchmark": benchmark,
        "trend60": round(t60, 2) if t60 is not None else None,
        "volRatio": round(vr, 3) if vr is not None else None,
        "definition": "trend60+거래량(약추세만)",
    })


def latest_regime(repo: str) -> tuple[str, str, dict]:
    rows = _spy(repo)
    if not rows:
        return ("SIDE", LABEL["SIDE"], {"reason": "SPY 데이터 없음",
                                        "benchmark": "SPY",
                                        "definition": "trend60+거래량(약추세만)"})
    return regime_from_rows(rows, "SPY")


def ev_multiplier(regime: str, horizon: str) -> float:
    """EV 보정 배수. **1.0을 넘기지 않는다** — 생존편향이 심한 표라
    유리한 쪽으로는 키우지 않고 불리한 쪽만 깎는다."""
    wr = WIN_RATES.get(horizon, WIN_RATES["swing"]).get(str(regime or "").upper())
    pooled = POOLED.get(horizon, 0.446)
    if not wr or not pooled:
        return 1.0
    return min(1.0, wr / pooled)
