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
            out.append((x[0], float(x[6])))
        except (ValueError, IndexError):
            continue
    out.sort(key=lambda r: r[0])
    return out


def _classify(dist: float, mom5: float) -> str:
    if dist > 0 and mom5 > 0:
        return "BULL"
    if dist < -2.0 or mom5 < -2.0:
        return "BEAR"
    return "SIDE"


def kospi_regime_series(repo: str) -> dict:
    """{date: 'BULL'|'BEAR'|'SIDE'} — 모든 KOSPI 거래일. 백테스트 라벨링용(룩어헤드 없음)."""
    rows = _kospi_closes(repo)
    closes = [c for _d, c in rows]
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
        out[rows[i][0]] = _classify(dist, mom5)
    return out


def latest_regime(repo: str) -> tuple[str, str, dict]:
    """(regime, label, detail) — 최신 KOSPI 봉 기준. detail엔 asOf/dist/mom5."""
    rows = _kospi_closes(repo)
    closes = [c for _d, c in rows]
    if len(closes) < 20:
        return ("SIDE", "횡보장", {"reason": "KOSPI 데이터 부족"})
    ma20 = sum(closes[-20:]) / 20
    dist = (closes[-1] - ma20) / ma20 * 100
    mom5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 and closes[-6] else 0.0
    reg = _classify(dist, mom5)
    return (reg, LABEL[reg], {"asOf": rows[-1][0], "distToMa20": round(dist, 2),
                              "mom5": round(mom5, 2), "kospi": round(closes[-1], 2)})


if __name__ == "__main__":
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reg, label, detail = latest_regime(repo)
    print(f"현재 KR 레짐: {reg} ({label}) — {detail}")
    ser = kospi_regime_series(repo)
    from collections import Counter
    print(f"이력 {len(ser)}일: {dict(Counter(ser.values()))}")
