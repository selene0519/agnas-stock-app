#!/usr/bin/env python3
"""국면 정의를 재설계하고 **같은 실행에서** 국면별 승률표를 재계산한다.

왜 같이 해야 하나: 정의만 바꾸면 기존 승률표(BULL 41.8% / BEAR 31.3%)와
어긋나고, 표만 다시 돌리면 정의가 그대로다. 2026-07-29에 60일 추세를
넣어봤다가 되돌린 이유가 그것이다.

검증 기준을 바꿨다 — **이게 앞선 실패의 원인이었다.**
  틀린 기준: 국면별 **지수** 향후 수익 -> BULL +1.42 / BEAR +1.36 (분리 안 됨)
  맞는 기준: 국면별 **전략** 성과      -> 앱이 실제로 하는 일

전략을 15년에 걸쳐 재현한다: 110개 KR 종목에 대해 표본일마다
진입가=종가, 손절/목표=ATR 배수(앱과 동일), 선착순 청산, 왕복 비용.
그 결과를 진입일의 국면으로 묶는다.

⚠️ 생존편향: 유니버스가 **오늘 상장된 110종목**이다. 상장폐지 종목이 없어
   절대 수준은 낙관 쪽이다. 그러나 **국면 간 상대 비교**는 같은 편향을
   공유하므로 유효하다 — 이 스크립트가 답하는 건 "어느 정의가 국면을 더 잘
   가르나"이고 "기댓값이 얼마냐"가 아니다.

실행: python scripts/recalibrate_regime_definition.py [--step 5]
쓰기: reports/regime_recalibration.json
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
OHLCV = ROOT / "data" / "market" / "ohlcv"
OUT = ROOT / "reports" / "regime_recalibration.json"

# 앱의 호라이즌별 설정 (mone_v65 / generate_*_recommendations의 _ATR_MULT와 동일)
HORIZONS = {
    "short": {"bars": 5,  "stop": 1.2, "target": 2.8},
    "swing": {"bars": 10, "stop": 1.5, "target": 4.5},
    "mid":   {"bars": 21, "stop": 2.0, "target": 5.5},
}
HOLD_BARS = 10          # run()에서 호라이즌별로 덮어쓴다
ATR_STOP_MULT = 1.5
ATR_TARGET_MULT = 4.5
COST_PCT_BY_MARKET = {"kr": 0.41, "us": 0.30}   # 왕복
COST_PCT = 0.41
MIN_CELL = 200


# ── 후보 국면 정의 ────────────────────────────────────────────────────
# 각 함수는 (20일선 이격%, 5일 모멘텀%, 60일 추세%, 120일 추세%)를 받아
# BULL/SIDE/BEAR를 돌려준다.
def _def_current(d20, m5, t60, t120, vr=None):
    """현행: 단기 둘로만 판정. 하락장 반등을 BULL로 부른다."""
    if d20 > 0 and m5 > 0:
        return "BULL"
    if d20 < -2.0 or m5 < -2.0:
        return "BEAR"
    return "SIDE"


def _def_trend60(d20, m5, t60, t120, vr=None):
    """60일 추세를 확인 조건으로 추가."""
    if t60 is None:
        return _def_current(d20, m5, t60, t120)
    if t60 <= -5.0:
        return "BEAR"
    if d20 > 0 and m5 > 0 and t60 > 0:
        return "BULL"
    if d20 < -2.0 or m5 < -2.0:
        return "BEAR"
    return "SIDE"


def _def_trend_only(d20, m5, t60, t120, vr=None):
    """중기 추세만 본다 — 단기 잡음을 아예 배제."""
    if t60 is None:
        return "SIDE"
    if t60 > 3.0:
        return "BULL"
    if t60 < -3.0:
        return "BEAR"
    return "SIDE"


def _def_trend60_vol(d20, m5, t60, t120, vr=None):
    """trend60단독 + **거래량 확인**. 거래량이 고갈된 구간은 SIDE로 본다.

    발상: 나쁜 국면이 SIDE(횡보)인데, 횡보는 거래량 고갈과 함께 온다.
    거래량이 마르면 추세가 없어 손절이 잡음에 털린다.
    """
    if t60 is None:
        return "SIDE"
    if vr is not None and vr < 0.85:
        return "SIDE"          # 거래량 고갈 -> 추세 없음
    if t60 > 3.0:
        return "BULL"
    if t60 < -3.0:
        return "BEAR"
    return "SIDE"


def _def_trend60_vol_weak(d20, m5, t60, t120, vr=None):
    """거래량 고갈 규칙을 **약한 추세에만** 적용한다.

    왜 이 후보가 필요했나: 채택된 `trend60+거래량`은 고갈 검사를 추세 검사보다
    **먼저** 하므로, 거래량만 마르면 60일 -15%도 SIDE(횡보장)로 부른다.
    2026-07-29 KOSPI 실측이 정확히 그 경우다(trend60 -15.36%, 거래량비 0.805
    -> 라벨 "횡보장"). 15년 중 국장 154일·미장 180일이 |trend60|>=8%인데
    SIDE로 덮였다.

    문제가 둘이다. (1) 화면에 급락장을 "횡보장"이라 쓰면 사용자가 앱을 못 믿는다.
    (2) `regime_type == "BEAR"` 게이트(공격형 차단)가 하필 급락장에서 꺼진다.
    그래서 |trend60|가 확실히 큰 구간은 거래량과 무관하게 추세를 인정한다.
    """
    if t60 is None:
        return "SIDE"
    strong = abs(t60) >= 8.0
    if vr is not None and vr < 0.85 and not strong:
        return "SIDE"
    if t60 > 3.0:
        return "BULL"
    if t60 < -3.0:
        return "BEAR"
    return "SIDE"


def _def_vol_only(d20, m5, t60, t120, vr=None):
    """거래량만으로 판정 — 거래량이 정말 정보인지 단독 검정."""
    if vr is None:
        return "SIDE"
    if vr > 1.15:
        return "BULL"
    if vr < 0.85:
        return "SIDE"
    return "BEAR" if (t60 is not None and t60 < 0) else "SIDE"


def _def_dual_trend(d20, m5, t60, t120, vr=None):
    """60일과 120일이 **같은 방향**일 때만 국면을 선언한다."""
    if t60 is None or t120 is None:
        return "SIDE"
    if t60 > 2.0 and t120 > 0:
        return "BULL"
    if t60 < -2.0 and t120 < 0:
        return "BEAR"
    return "SIDE"


DEFS = {
    "current(단기2)": _def_current,
    "trend60확인": _def_trend60,
    "trend60단독": _def_trend_only,
    "dual(60+120)": _def_dual_trend,
    "trend60+거래량": _def_trend60_vol,
    "trend60+거래량(약추세만)": _def_trend60_vol_weak,
    "거래량단독": _def_vol_only,
}


def _load(path: Path) -> list[tuple[str, float, float, float]]:
    out = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            d = str(r.get("date") or "")[:10]
            try:
                h, lo, c = float(r["high"]), float(r["low"]), float(r["close"])
            except (KeyError, TypeError, ValueError):
                continue
            try:
                v = float(r.get("volume") or 0)
            except (TypeError, ValueError):
                v = 0.0
            if d and c > 0:
                out.append((d, h, lo, c, v))
    out.sort()
    return out


def _atr(bars, i, n=14):
    if i < n:
        return None
    trs = []
    for j in range(i - n + 1, i + 1):
        prev_c = bars[j - 1][3]
        trs.append(max(bars[j][1] - bars[j][2], abs(bars[j][1] - prev_c),
                       abs(bars[j][2] - prev_c)))
    return statistics.fmean(trs) if trs else None


def run(step: int, horizon: str = "swing", market: str = "kr") -> dict:
    cfg = HORIZONS[horizon]
    cost = COST_PCT_BY_MARKET.get(market, 0.41)
    bench = "KOSPI" if market == "kr" else "SPY"
    hold_bars, stop_mult, target_mult = cfg["bars"], cfg["stop"], cfg["target"]
    kospi = _load(OHLCV / f"{market}_{bench}_daily.csv")
    kdate = {d: i for i, (d, *_r) in enumerate(kospi)}
    kclose = [x[3] for x in kospi]
    kvol = [x[4] for x in kospi]

    def _feats(i):
        if i < 120:
            return None
        ma20 = statistics.fmean(kclose[i - 19:i + 1])
        d20 = (kclose[i] - ma20) / ma20 * 100 if ma20 else 0.0
        m5 = (kclose[i] - kclose[i - 5]) / kclose[i - 5] * 100
        t60 = (kclose[i] - kclose[i - 60]) / kclose[i - 60] * 100
        t120 = (kclose[i] - kclose[i - 120]) / kclose[i - 120] * 100
        # 거래량비: 최근 20일 평균 / 직전 60일 평균. 1보다 작으면 거래량 고갈.
        v20 = statistics.fmean(kvol[i - 19:i + 1]) if all(kvol[i - 19:i + 1]) else 0.0
        v60 = statistics.fmean(kvol[i - 59:i + 1]) if i >= 59 and all(kvol[i - 59:i + 1]) else 0.0
        vr = (v20 / v60) if v60 else None
        return d20, m5, t60, t120, vr

    # 국면 라벨을 정의별로 미리 계산
    labels = {name: {} for name in DEFS}
    for d, i in kdate.items():
        f = _feats(i)
        if not f:
            continue
        for name, fn in DEFS.items():
            labels[name][d] = fn(*f)

    # 전략 재현
    buckets = {name: {} for name in DEFS}
    trades = 0
    for path in sorted(OHLCV.glob(f"{market}_*_daily.csv")):
        if bench in path.name or "KOSDAQ" in path.name or "QQQ" in path.name:
            continue
        bars = _load(path)
        if len(bars) < 200:
            continue
        for i in range(20, len(bars) - hold_bars - 1, step):
            entry_date, entry = bars[i][0], bars[i][3]
            if entry_date not in labels["current(단기2)"]:
                continue
            atr = _atr(bars, i)
            if not atr or atr <= 0 or entry <= 0:
                continue
            stop = entry - atr * stop_mult
            target = entry + atr * target_mult
            if stop <= 0:
                continue
            ret = None
            for j in range(i + 1, min(i + 1 + hold_bars, len(bars))):
                if bars[j][2] <= stop and bars[j][1] >= target:
                    ret = (stop - entry) / entry * 100          # 동시 -> 보수적
                    break
                if bars[j][2] <= stop:
                    ret = (stop - entry) / entry * 100
                    break
                if bars[j][1] >= target:
                    ret = (target - entry) / entry * 100
                    break
            if ret is None:
                j = min(i + hold_bars, len(bars) - 1)
                ret = (bars[j][3] - entry) / entry * 100
            ret -= cost
            trades += 1
            for name in DEFS:
                reg = labels[name].get(entry_date)
                if reg:
                    buckets[name].setdefault(reg, []).append(ret)

    def _stat(v):
        if not v:
            return {"n": 0}
        w = [x for x in v if x > 0]
        return {"n": len(v), "winRatePct": round(len(w) / len(v) * 100, 1),
                "meanPct": round(statistics.fmean(v), 4)}

    results = {}
    for name in DEFS:
        cells = {r: _stat(v) for r, v in sorted(buckets[name].items())}
        usable = [c for c in cells.values() if c.get("n", 0) >= MIN_CELL]
        spread = (max(c["meanPct"] for c in usable) - min(c["meanPct"] for c in usable)
                  if len(usable) >= 2 else None)
        results[name] = {
            "cells": cells,
            # 국면 간 평균손익 격차 — 클수록 국면을 잘 가른다.
            "regimeSpreadPp": round(spread, 4) if spread is not None else None,
            "bearIsWorst": bool(cells.get("BEAR") and cells.get("BULL")
                                and cells["BEAR"].get("meanPct", 0)
                                < cells["BULL"].get("meanPct", 0)),
        }

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "tradesSimulated": trades,
        "sampleStep": step,
        "market": market,
        "horizon": horizon,
        "holdBars": hold_bars,
        "atrMult": {"stop": stop_mult, "target": target_mult},
        "costPct": COST_PCT,
        "method": ("110개 KR 종목 15년에 대해 앱과 같은 규칙(ATR 배수 밴드, 선착순 "
                   "청산, 왕복 비용)으로 전략을 재현하고, 진입일 국면으로 묶었다. "
                   "검증 기준을 '지수 향후 수익'에서 '전략 성과'로 바꿨다 — "
                   "앞선 시도가 실패한 원인이 그 기준이었다."),
        "definitions": results,
        "caveats": [
            "생존편향: 유니버스가 오늘 상장된 110종목이라 절대 수준은 낙관 쪽이다. "
            "국면 간 **상대 비교**는 같은 편향을 공유하므로 유효하다.",
            "호라이즌별로 따로 돌려야 한다(--horizon). ATR 배수와 보유 기간이 다르다.",
            f"셀 표본 {MIN_CELL}건 미만은 격차 계산에서 제외한다.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=5, help="표본일 간격(거래일)")
    ap.add_argument("--horizon", default="swing", choices=list(HORIZONS))
    ap.add_argument("--market", default="kr", choices=("kr", "us"))
    args = ap.parse_args()
    d = run(args.step, args.horizon, args.market)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = OUT.with_name(f"regime_recalibration_{args.market}_{args.horizon}.json")
    out.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.horizon == "swing" and args.market == "kr":
        OUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== 국면 재검증 [{args.market}/{args.horizon}] 보유{d['holdBars']}봉 "
          f"ATR {d['atrMult']['stop']}/{d['atrMult']['target']} · 재현 {d['tradesSimulated']:,}건 ===\n")
    for name, r in d["definitions"].items():
        cells = r["cells"]
        parts = "  ".join(
            f"{k} n={v.get('n',0):>5} 승률{v.get('winRatePct',0):>5.1f}% 평균{v.get('meanPct',0):>+7.3f}"
            for k, v in cells.items())
        mark = "✓" if r["bearIsWorst"] else "✗ BEAR가 최악이 아님"
        print(f"[{name}]  격차 {r['regimeSpreadPp']}pp   {mark}")
        print(f"   {parts}\n")
    print("판정: 격차가 크고 BEAR가 최악인 정의가 국면을 옳게 가른다.")
    for c in d["caveats"]:
        print(f"  · {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
