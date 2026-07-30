#!/usr/bin/env python3
"""
KR 마켓 레짐 — 단일 진실원(single source of truth).

메인 추천 엔진(generate_kr_recommendations._load_market_regime)과 동일한 로직:
KOSPI 20일선 이격 + 5일 모멘텀으로 BULL/BEAR/SIDE 판정. 렌즈·스마트순위가 각자
breadth로 따로 판정하던 파편화를 없애기 위해, 모두 이 모듈을 쓴다.

  dist>0 and mom5>0        -> BULL (강세장)
  dist<-2 or mom5<-2       -> BEAR (약세장)
  else                     -> SIDE (횡보장)
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
    """**60일 추세 + 거래량 확인.** dist/mom5는 폴백용으로만 남긴다.

    2026-07-30 검증: 15년 전략 재현(110종목 x 3 호라이즌, 약 79,000건, 앱과
    같은 ATR 밴드·선착순 청산·왕복비용)으로 네 정의를 비교했다. 국면 간
    평균손익 격차(mid 기준):

        current(단기2: dist>0 and mom5>0)   0.74pp
        trend60확인                         1.28pp
        **trend60단독                       1.80pp**   <- 채택
        dual(60+120)                        0.67pp

    단기 잡음(20일선 이격·5일 모멘텀)을 **배제한** 쪽이 더 잘 가른다.
    현행 정의가 하락장 반등을 BULL로 부른 것과 같은 뿌리다 — 실측에서
    "BULL" 라벨이 붙은 시점의 직전 20일 KOSPI 중앙값이 **-5.66%**였다.

    채택한 정의의 호라이즌별 승률(EV 보정 표와 **반드시 같은 정의**여야 한다):
        short  BEAR 0.449 / BULL 0.435 / SIDE 0.381
        swing  BEAR 0.444 / BULL 0.433 / SIDE 0.386
        mid    BEAR 0.440 / BULL 0.438 / SIDE 0.368
    세 호라이즌 전부 **SIDE가 최악**이다.
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
    # 2026-07-30 검증(각 26,000여 건): 거래량 확인을 넣으면 국면 간 격차가
    #   swing 0.839 -> **1.033pp**,  mid 1.796 -> **2.021pp**
    # 로 커진다. short만 0.671 -> 0.494pp로 나빠진다 — 5봉 보유에서는 거래량
    # 확인이 너무 많이 걸러낸다. 2/3에서 개선되고 mid에서 이득이 가장 크므로
    # 채택하되, short의 손실은 알려진 대가로 남긴다.
    if vol_ratio is not None and vol_ratio < VOL_DRYUP_RATIO:
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


def latest_regime(repo: str) -> tuple[str, str, dict]:
    """(regime, label, detail) — 최신 KOSPI 봉 기준. detail엔 asOf/dist/mom5."""
    rows = _kospi_closes(repo)
    closes = [r[1] for r in rows]
    vols = [r[2] for r in rows]
    if len(closes) < 20:
        return ("SIDE", "횡보장", {"reason": "KOSPI 데이터 부족"})
    ma20 = sum(closes[-20:]) / 20
    dist = (closes[-1] - ma20) / ma20 * 100
    mom5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 and closes[-6] else 0.0
    t60 = ((closes[-1] - closes[-61]) / closes[-61] * 100) if len(closes) >= 61 and closes[-61] else None
    vr = _vol_ratio(vols, len(vols) - 1)
    reg = _classify(dist, mom5, t60, vr)
    return (reg, LABEL[reg], {"asOf": rows[-1][0], "distToMa20": round(dist, 2),
                              "mom5": round(mom5, 2),
                              "trend60": round(t60, 2) if t60 is not None else None,
                              "definition": "trend60+거래량",
                              "volRatio": round(vr, 3) if vr is not None else None,
                              "kospi": round(closes[-1], 2)})


if __name__ == "__main__":
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reg, label, detail = latest_regime(repo)
    print(f"현재 KR 레짐: {reg} ({label}) — {detail}")
    ser = kospi_regime_series(repo)
    from collections import Counter
    print(f"이력 {len(ser)}일: {dict(Counter(ser.values()))}")
