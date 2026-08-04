#!/usr/bin/env python3
"""
Regime lens journal builder (KR) — Step 2 of the self-calibrating loop.

레짐 렌즈(BOTTOM_CATCH / BREAKOUT)의 과거 신호와 '실제로 어떻게 됐는지'(실현 손익)를
per-trade 저널로 기록한다. 이게 자가보정(Step 3)의 연료 = "AI 매매일지 값".

- 룩어헤드 없음: 신호=당일 종가까지 지표, 진입=익일 시가, 이후 최대 H거래일 전방 시뮬.
- 청산: 목표(+T%) 또는 손절(-S%) 터치(같은날 둘다면 보수적 손절), 아니면 H일째 종가.
- 비용 왕복 COST% 차감(순손익 net).
- 시장레짐 = KOSPI 60일 추세+거래량(regime_kr, 메인 엔진과 동일 단일 진실원).

읽기전용 입력: data/market/ohlcv/kr_*_daily.csv
출력: reports/lens_journal_kr.csv  (signalDate 정렬)
"""
from __future__ import annotations
import csv
import glob
import os
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MA_TREND, MA_MID, RSI_N = 60, 20, 14
BOTTOM_RSI_MAX, BREAKOUT_RSI_MIN = 32.0, 60.0
NEAR_HIGH_PCT = 0.02
HOLD = 10
COST = 0.5  # 왕복 % (매도세 0.23 + 슬리피지 근사)
SETUP_PARAMS = {
    "BOTTOM_CATCH": {"target": 0.08, "stop": 0.05},
    "BREAKOUT": {"target": 0.08, "stop": 0.04},
}


def load_ohlcv(path: str):
    out = []
    for row in csv.reader(open(path, encoding="utf-8-sig")):
        if not row or not row[0] or row[0] == "date":
            continue
        try:
            d, o, h, l, c = row[0], float(row[3]), float(row[4]), float(row[5]), float(row[6])
        except (ValueError, IndexError):
            continue
        if min(o, h, l, c) > 0:
            out.append((d, o, h, l, c))
    out.sort(key=lambda r: r[0])
    return out


def sma(xs, n, i):
    return sum(xs[i - n + 1 : i + 1]) / n if i + 1 >= n else None


def rsi(cl, n, i):
    if i < n:
        return None
    g = l = 0.0
    for k in range(i - n + 1, i + 1):
        ch = cl[k] - cl[k - 1]
        g += max(ch, 0.0)
        l += max(-ch, 0.0)
    if g + l == 0:
        return 50.0
    rs = (g / n) / ((l / n) if l > 0 else 1e-9)
    return 100 - 100 / (1 + rs)


def simulate(entry, bars, target, stop, hold):
    for k in range(min(hold, len(bars))):
        _o, h, l, c = bars[k]
        hit_s, hit_t = l <= entry * (1 - stop), h >= entry * (1 + target)
        if hit_s:  # 보수적: 같은날 둘다면 손절
            return -stop * 100, bars[k][0] if len(bars[k]) > 4 else k, k + 1
        if hit_t:
            return target * 100, k, k + 1
    if bars:
        idx = min(hold, len(bars)) - 1
        return (bars[idx][3] / entry - 1) * 100, idx, idx + 1
    return None, None, None


def main() -> int:
    files = glob.glob(os.path.join(REPO, "data", "market", "ohlcv", "kr_*_daily.csv"))
    data = {}
    for f in files:
        r = load_ohlcv(f)
        if len(r) > MA_TREND + 15:
            data[os.path.basename(f).split("kr_")[1].split("_")[0]] = r

    # 통일 레짐 — 메인 엔진과 동일한 KOSPI 기준(regime_kr). 파편화 제거.
    from regime_kr import kospi_regime_series
    regime = kospi_regime_series(REPO)

    rows = []
    for sym, r in data.items():
        cl = [x[4] for x in r]
        for i in range(MA_TREND, len(r) - 1):
            d, o, h, l, c = r[i]
            ma60, ma20, rsi14 = sma(cl, MA_TREND, i), sma(cl, MA_MID, i), rsi(cl, RSI_N, i)
            if None in (ma60, ma20, rsi14):
                continue
            prev_c = cl[i - 1]
            setup = None
            if c < ma60 and rsi14 < BOTTOM_RSI_MAX and c > o and c > prev_c:
                setup = "BOTTOM_CATCH"
            else:
                hh20 = max(x[2] for x in r[i - 19 : i + 1])
                if c > ma20 > ma60 and c >= hh20 * (1 - NEAR_HIGH_PCT) and rsi14 > BREAKOUT_RSI_MIN:
                    setup = "BREAKOUT"
            if not setup:
                continue
            bars = [(r[j][1], r[j][2], r[j][3], r[j][4]) for j in range(i + 1, min(i + 1 + HOLD + 1, len(r)))]
            if not bars:
                continue
            entry = bars[0][0]
            p = SETUP_PARAMS[setup]
            gross, exit_idx, held = simulate(entry, bars, p["target"], p["stop"], HOLD)
            if gross is None:
                continue
            net = gross - COST
            exit_date = r[i + 1 + (held - 1)][0] if held and i + 1 + (held - 1) < len(r) else ""
            rows.append(
                {
                    "signalDate": d,
                    "symbol": sym,
                    "setup": setup,
                    "regime": regime.get(d, "SIDE"),
                    "rsi14": round(rsi14, 1),
                    "distMa20Pct": round((c / ma20 - 1) * 100, 1),
                    "entry": round(entry, 2),
                    "grossPnlPct": round(gross, 3),
                    "netPnlPct": round(net, 3),
                    "outcome": "WIN" if net > 0 else "LOSS",
                    "barsHeld": held,
                    "exitDate": exit_date,
                }
            )

    rows.sort(key=lambda x: x["signalDate"])
    out = os.path.join(REPO, "reports", "lens_journal_kr.csv")
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    span = f"{rows[0]['signalDate']} ~ {rows[-1]['signalDate']}" if rows else "-"
    print(f"lens journal: {len(rows)} trades  ({span})  -> {os.path.relpath(out, REPO)}")
    by = defaultdict(list)
    for x in rows:
        by[(x["setup"], x["regime"])].append(x["netPnlPct"])
    print(f"\n{'setup':14s}{'regime':7s}{'n':>6s}{'win%':>7s}{'netAvg':>8s}")
    for k in sorted(by):
        v = by[k]
        wr = sum(1 for p in v if p > 0) / len(v) * 100
        print(f"{k[0]:14s}{k[1]:7s}{len(v):6d}{wr:6.1f}%{sum(v)/len(v):+7.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
