#!/usr/bin/env python3
"""
KR 마켓 레짐 — 단일 진실원(single source of truth).

판정식은 **60일 추세 + 거래량 확인**이다(`_classify` 참고). 렌즈·스마트순위가
각자 breadth로 따로 판정하던 파편화를 없애기 위해, 모두 이 모듈을 쓴다.

  trend60 > +3%  &  (거래량 정상 or |trend60|>=8%)  -> BULL (강세장)
  trend60 < -3%  &  (거래량 정상 or |trend60|>=8%)  -> BEAR (약세장)
  그 외 / 약한 추세 + 거래량 고갈                    -> SIDE (횡보장)

⚠️ **2026-07-30 발견:** 이 모듈을 trend60으로 고쳤을 때 추천 생성기
`generate_kr_recommendations._load_market_regime`은 옛 정의(20일선 이격 +
5일 모멘텀)를 **자기 안에 복제해 두고** 있었고, 그래서 정의 교체가 정작
추천 경로에는 닿지 않았다. 15년 KOSPI로 두 정의를 맞춰보니 **일치가 46.2%**
(3,621일 중 1,949일 불일치)였다. 특히 검증정의가 SIDE(최악, 승률 0.368~0.386)로
본 653일을 옛 정의는 BULL(0.433~0.438)로 불러 EV를 1.13~1.19배 부풀렸다.
→ 생성기가 이 모듈에 위임하도록 바꿨다. **판정식을 다른 곳에 복제하지 말 것.**
"""
from __future__ import annotations
import csv
import os

LABEL = {"BULL": "강세장", "BEAR": "약세장", "SIDE": "횡보장"}


def _kospi_closes(repo: str):
    path = os.path.join(repo, "data", "market", "ohlcv", "kr_KOSPI_daily.csv")
    if not os.path.exists(path):
        return []
    out = []
    for x in csv.reader(open(path, encoding="utf-8-sig")):
        if not x or not x[0] or x[0] == "date":
            continue
        try:
            # 컬럼: date,market,symbol,open,high,low,close,volume,...
            out.append((x[0], float(x[6]), float(x[7] or 0)))
        except (ValueError, IndexError):
            continue
    out.sort(key=lambda r: r[0])
    return out


# 60일 추세 임계(%)와 거래량비 하한.
TREND60_BULL = 3.0
TREND60_BEAR = -3.0
# 최근 20일 평균 거래량 / 직전 60일 평균. 이보다 마르면 추세가 없다고 본다.
VOL_DRYUP_RATIO = 0.85
# 단, |trend60|가 이만큼 크면 거래량과 무관하게 추세를 인정한다. 왜: 거래량
# 고갈 검사를 먼저 하면 60일 -15%도 SIDE(횡보장)가 된다 — 2026-07-29 KOSPI가
# 정확히 그랬다(trend60 -15.36%, 거래량비 0.805). 화면에 급락장을 "횡보장"으로
# 쓰는 문제도 있고, `regime_type == "BEAR"` 게이트(공격형 차단)가 하필
# 급락장에서 꺼지는 문제도 있다.
TREND60_STRONG = 8.0


def _vol_ratio(vols: list, i: int) -> float | None:
    """최근 20일 평균 거래량 / 직전 60일 평균. 데이터가 모자라면 None."""
    if i < 59:
        return None
    # **결측(0) 봉은 건너뛴다.** 예전엔 `all()`로 검사해서 60봉 중 **한 개**만
    # 0이어도 None을 돌려주고 거래량 확인이 조용히 꺼졌다 — 실제로 KOSPI
    # 2026-06-29의 거래량 0 한 개 때문에 최신 판정에서 기능이 비활성됐다.
    # 이 레포가 반복해 당한 "조용히 꺼지는" 형태다.
    v20 = [v for v in vols[i - 19:i + 1] if v]
    v60 = [v for v in vols[i - 59:i + 1] if v]
    # 절반 이상이 결측이면 그때만 포기한다.
    if len(v20) < 10 or len(v60) < 30:
        return None
    a = sum(v20) / len(v20)
    b = sum(v60) / len(v60)
    return (a / b) if b else None


def _classify(dist: float, mom5: float, trend60: float | None = None,
              vol_ratio: float | None = None) -> str:
    """**60일 추세 + 거래량 확인(약한 추세에만).** dist/mom5는 폴백용으로만 남긴다.

    2026-07-30 검증: 15년 전략 재현(110종목 x 3 호라이즌, 앱과 같은 ATR 밴드·
    선착순 청산·왕복비용)으로 후보 정의들을 비교했다. 단기 잡음(20일선 이격·
    5일 모멘텀)을 **배제한** 쪽이 더 잘 가른다 — 옛 정의가 하락장 반등을 BULL로
    부른 것과 같은 뿌리다(실측에서 "BULL" 라벨 시점의 직전 20일 KOSPI 중앙값이
    **-5.66%**였다).

    국장은 세 호라이즌 전부 **SIDE가 최악**이다. 미장은 정반대로 BULL이 최악이라
    표를 따로 둔다(`regime_us`). 채택 정의의 승률은 `WIN_RATES`에 있다 —
    **여기에 값을 복제하지 말 것.** 주석에 적어둔 표가 판정과 어긋나는 사고를
    이 레포는 이미 세 번 겪었다. 각 정의의 격차 수치는
    `reports/regime_recalibration_{market}_{horizon}.json`에 남는다.
    """
    if trend60 is None:
        # 60일치 봉이 없을 때만 단기 지표로 폴백한다. 이 경로는 표와 정의가
        # 어긋나므로 가능한 한 SIDE(중립)로 남긴다 — 없는 정보를 만들지 않는다.
        if dist > 2.0 and mom5 > 2.0:
            return "BULL"
        if dist < -2.0 or mom5 < -2.0:
            return "BEAR"
        return "SIDE"
    # **거래량이 마르면 추세로 보지 않는다.** 나쁜 국면이 SIDE(횡보)이고,
    # 횡보는 거래량 고갈과 함께 온다 — 추세가 없어 좁은 손절이 잡음에 털린다.
    #
    # 단, **|trend60|가 크면 거래량과 무관하게 추세를 인정한다**(TREND60_STRONG).
    # 이 예외가 없으면 60일 -15%가 SIDE(횡보장)가 된다 — 2026-07-29 KOSPI가
    # 정확히 그 경우였고, 15년 중 국장 154일이 |trend60|>=8%인데 SIDE로 덮였다.
    # 재검증(국장·미장 x 3호라이즌 = 6셀, 각 5만~7만건): 예외를 두면 국면 간
    # 격차가 **6셀 중 5셀에서 커진다**(국장 short 0.522->0.544, swing 0.987->1.038;
    # 미장 short 0.556->0.657, swing 0.805->1.005, mid 1.786->2.188). 국장 mid만
    # 1.880->1.769로 나빠지며, 이는 알려진 대가로 남긴다.
    if (vol_ratio is not None and vol_ratio < VOL_DRYUP_RATIO
            and abs(trend60) < TREND60_STRONG):
        return "SIDE"
    if trend60 > TREND60_BULL:
        return "BULL"
    if trend60 < TREND60_BEAR:
        return "BEAR"
    return "SIDE"


def kospi_regime_series(repo: str) -> dict:
    """{date: 'BULL'|'BEAR'|'SIDE'} — 모든 KOSPI 거래일. 백테스트 라벨링용(룩어헤드 없음)."""
    rows = _kospi_closes(repo)
    closes = [r[1] for r in rows]
    vols = [r[2] for r in rows]
    out = {}
    for i in range(len(rows)):
        if i < 20:
            continue
        ma20 = sum(closes[i - 19:i + 1]) / 20
        if ma20 == 0:
            continue
        dist = (closes[i] - ma20) / ma20 * 100
        prev5 = closes[i - 5] if i >= 5 else 0
        mom5 = (closes[i] - prev5) / prev5 * 100 if prev5 else 0.0
        prev60 = closes[i - 60] if i >= 60 else None
        t60 = ((closes[i] - prev60) / prev60 * 100) if prev60 else None
        out[rows[i][0]] = _classify(dist, mom5, t60, _vol_ratio(vols, i))
    return out


# 15년 전략 재현(110종목 x 3 호라이즌, 앱과 같은 ATR 밴드·선착순 청산·왕복비용
# 0.41%)으로 얻은 국면별 승률.
#
# ⚠️ **`_classify`와 반드시 같은 정의여야 한다.** 2026-07-30에 판정기에 거래량
# 확인을 넣으면서 표를 다시 내지 않아, 판정기는 `trend60+거래량`인데 표는
# `trend60단독` 값이었다(같은 계열 사고 세 번째). 아래 값은 채택 정의
# `trend60+거래량(약추세만)`의 **같은 실행 산출**이다:
#   reports/regime_recalibration_kr_{short,swing,mid}.json
# 표를 손으로 고치지 말고 `recalibrate_regime_definition.py`를 다시 돌려 옮길 것.
WIN_RATES = {
    "short": {"BULL": 0.433, "SIDE": 0.407, "BEAR": 0.455},   # n=52,980
    "swing": {"BULL": 0.430, "SIDE": 0.392, "BEAR": 0.459},   # n=52,861
    "mid":   {"BULL": 0.437, "SIDE": 0.374, "BEAR": 0.462},   # n=52,631
}
POOLED = {"short": 0.429, "swing": 0.424, "mid": 0.421}
# 국면별 점수 가감(추천 통과 바). 이 값들은 국면 재검증의 산출이 **아니다** —
# v40 시절부터 손으로 정해진 값이라 근거가 없다. 정의를 통일하면서 값은
# 그대로 옮겼다(근거 없이 바꾸면 그것도 근거 없는 변경이다).
SCORE_ADJUST = {"BULL": 5.0, "SIDE": 0.0, "BEAR": -15.0}


def ev_multiplier(regime: str, horizon: str) -> float:
    """EV 보정 배수. **1.0을 넘기지 않는다.**

    승률표는 **현재 상장된 110종목**으로 만든 것이라 생존편향이 있다(상장폐지
    종목의 하락이 표본에 없다). 그런 표로 EV를 **키우면** 편향이 그대로 낙관으로
    번역된다. 그래서 불리한 국면만 깎고 유리한 쪽으로는 올리지 않는다.
    """
    wr = WIN_RATES.get(horizon, WIN_RATES["swing"]).get(str(regime or "").upper())
    pooled = POOLED.get(horizon, 0.422)
    if not wr or not pooled:
        return 1.0
    return min(1.0, wr / pooled)


def regime_from_rows(rows: list) -> tuple[str, str, dict]:
    """(date, close, volume) 리스트에서 최신 국면. **판정식의 유일한 입구.**

    생성기가 KOSPI 파일이 없어 다른 소스(benchmark_daily.csv)로 폴백할 때도
    이 함수를 거치게 해서 정의가 갈라지지 않게 한다.
    """
    closes = [r[1] for r in rows]
    vols = [r[2] if len(r) > 2 else 0 for r in rows]
    if len(closes) < 20:
        return ("SIDE", LABEL["SIDE"], {"reason": "데이터 부족(20봉 미만)",
                                        "definition": "trend60+거래량(약추세만)"})
    ma20 = sum(closes[-20:]) / 20
    dist = (closes[-1] - ma20) / ma20 * 100 if ma20 else 0.0
    mom5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 and closes[-6] else 0.0
    t60 = ((closes[-1] - closes[-61]) / closes[-61] * 100) if len(closes) >= 61 and closes[-61] else None
    vr = _vol_ratio(vols, len(vols) - 1)
    reg = _classify(dist, mom5, t60, vr)
    return (reg, LABEL[reg], {
        "asOf": rows[-1][0], "distToMa20": round(dist, 2), "mom5": round(mom5, 2),
        "trend60": round(t60, 2) if t60 is not None else None,
        "volRatio": round(vr, 3) if vr is not None else None,
        "definition": "trend60+거래량(약추세만)",
        "kospi": round(closes[-1], 2),
    })


def latest_regime(repo: str) -> tuple[str, str, dict]:
    """(regime, label, detail) — 최신 KOSPI 봉 기준."""
    rows = _kospi_closes(repo)
    if not rows:
        return ("SIDE", LABEL["SIDE"], {"reason": "KOSPI 데이터 없음",
                                        "definition": "trend60+거래량(약추세만)"})
    return regime_from_rows(rows)


if __name__ == "__main__":
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reg, label, detail = latest_regime(repo)
    print(f"현재 KR 레짐: {reg} ({label}) — {detail}")
    ser = kospi_regime_series(repo)
    from collections import Counter
    print(f"이력 {len(ser)}일: {dict(Counter(ser.values()))}")
