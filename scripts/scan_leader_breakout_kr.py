#!/usr/bin/env python3
"""Leader base-breakout scanner for KR, gated by the US market backdrop.

Deep-data walk-forward (2014-2026, train+OOS) showed this is the strongest,
most robust long edge measured for KR: an O'Neil/Minervini-style leader
breakout works ONLY when the US backdrop is risk-on.

  Universe filter (leader):  close>MA50>MA150 and price in the top 25% of its
                             250-day range and 60-day return beating KOSPI.
  Trigger:                   new 20-day high with volume >= 1.5x its 50d avg.
  Macro gate:                SPY above its 50-day MA (US uptrend). When the US
                             is below MA50 the same setup was essentially dead
                             (fwd-20d +0.2% vs +4.5%), so no candidates are
                             emitted -> status US_BACKDROP_UNFAVORABLE.

Output: reports/leader_breakout_candidates_kr.json (research/paper only, not a
live buy recommendation). Feed to the paper-accumulation loop for live proof
before any promotion.
"""
from __future__ import annotations

import csv
import glob
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OHLCV = os.path.join(REPO, "data", "market", "ohlcv")
OUT = os.path.join(REPO, "reports", "leader_breakout_candidates_kr.json")


def _series(path):
    rows = []
    try:
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            try:
                rows.append((r.get("date", "")[:10],
                             float(r["high"]), float(r["low"]),
                             float(r["close"]), float(r.get("volume") or 0)))
            except (ValueError, KeyError, TypeError):
                continue
    except FileNotFoundError:
        return []
    rows = [x for x in rows if x[0] and x[3] > 0]
    rows.sort(key=lambda x: x[0])
    return rows


def _ma(vals, n, i):
    return sum(vals[i - n + 1:i + 1]) / n if i + 1 >= n else None


def main() -> int:
    spy = _series(os.path.join(OHLCV, "us_SPY_daily.csv"))
    kospi = _series(os.path.join(OHLCV, "kr_KOSPI_daily.csv"))
    if len(spy) < 60 or len(kospi) < 70:
        json.dump({"status": "NO_DATA", "market": "kr"}, open(OUT, "w", encoding="utf-8"))
        print("leader-breakout: NO_DATA")
        return 0

    spy_close = [x[3] for x in spy]
    us_ma50 = _ma(spy_close, 50, len(spy_close) - 1)
    us_favorable = us_ma50 is not None and spy_close[-1] > us_ma50
    as_of = kospi[-1][0]

    kospi_close = [x[3] for x in kospi]
    k_ret60 = (kospi_close[-1] / kospi_close[-61] - 1) if len(kospi_close) > 61 else 0.0

    candidates = []
    scanned = 0
    for path in sorted(glob.glob(os.path.join(OHLCV, "kr_*_daily.csv"))):
        sym = os.path.basename(path)[3:-10]
        if sym in ("KOSPI", "KOSDAQ") or sym.startswith("USD"):
            continue
        s = _series(path)
        if len(s) < 260 or s[-1][0] != as_of:
            continue
        scanned += 1
        close = [x[3] for x in s]
        high = [x[1] for x in s]
        low = [x[2] for x in s]
        vol = [x[4] for x in s]
        i = len(s) - 1
        ma50, ma150 = _ma(close, 50, i), _ma(close, 150, i)
        if ma50 is None or ma150 is None:
            continue
        hi250, lo250 = max(close[-250:]), min(close[-250:])
        posr = (close[i] - lo250) / (hi250 - lo250) if hi250 > lo250 else 0
        ret60 = close[i] / close[i - 60] - 1 if close[i - 60] else 0
        v50 = _ma(vol, 50, i) or 0
        hi20_prev = max(high[i - 20:i])
        leader = close[i] > ma50 > ma150 and posr > 0.75 and ret60 > k_ret60
        trigger = close[i] >= hi20_prev and v50 > 0 and vol[i] >= 1.5 * v50
        if not (leader and trigger):
            continue
        entry = close[i]
        stop = min(low[-10:])                 # recent swing low
        if stop >= entry:
            continue
        target = entry + 2.0 * (entry - stop)  # 2R
        candidates.append({
            "symbol": sym, "asOf": as_of,
            "entry": round(entry, 2), "stop": round(stop, 2), "target": round(target, 2),
            "rrRatio": round((target - entry) / (entry - stop), 2),
            "ret60Pct": round(ret60 * 100, 2), "posRange250": round(posr, 3),
            "volRatio50": round(vol[i] / v50, 2),
            "setup": "LEADER_BREAKOUT",
        })

    candidates.sort(key=lambda c: -c["ret60Pct"])
    status = "OK" if us_favorable else "US_BACKDROP_UNFAVORABLE"
    payload = {
        "version": "leader-breakout-v1", "market": "kr", "asOf": as_of,
        "status": status,
        "usBackdrop": {"favorable": us_favorable,
                       "spyClose": round(spy_close[-1], 2),
                       "spyMa50": round(us_ma50, 2) if us_ma50 else None,
                       "rule": "SPY > 50d MA"},
        "validatedEdge": {"fwd20dPctWhenUsUp": 4.47, "fwd20dPctWhenUsDown": 0.20,
                          "basis": "deep 2014-2026 train+OOS, forward-return (not cost/trade-sim)"},
        "scanned": scanned,
        # When the US backdrop is unfavorable the edge is gone -> emit no buys.
        "candidates": candidates if us_favorable else [],
        "heldForUnfavorableBackdrop": [] if us_favorable else candidates,
        "note": "Research/paper only. Leader breakouts are only traded on a risk-on US backdrop; feed to the paper loop for live proof before promotion.",
    }
    json.dump(payload, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    n = len(candidates) if us_favorable else 0
    print(f"leader-breakout: US {'favorable' if us_favorable else 'UNFAVORABLE'} "
          f"({as_of}), scanned {scanned}, {n} candidate(s) -> {os.path.relpath(OUT, REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
