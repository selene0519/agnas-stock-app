#!/usr/bin/env python3
"""Leader base-breakout scanner (KR + US), gated by the US market backdrop.

Deep 2014-2026 walk-forward (train+OOS, both markets) found this is the one
famous long setup that holds up robustly everywhere tested. Of O'Neil/Minervini
leader breakout, pullback-in-trend, Weinstein Stage-2, and Turtle/Donchian, only
the leader breakout was consistently positive across KR and US, train and OOS
(KR +2.17/+1.71p excess, US +1.57/+3.47p). Pullback / Stage-2 / Donchian were
weak or inconsistent, so they are deliberately NOT emitted.

  Leader filter:  close>MA50>MA150, price in the top 25% of its 250-day range,
                  60-day return beating the market index.
  Trigger:        new 20-day high on volume >= 1.5x its 50-day average.
  Macro gate:     SPY above its 50-day MA. For KR this is the foreign risk-on
                  backdrop (fwd-20d +2.29p vs -1.94p); for US it is the market's
                  own regime. When SPY<MA50 no candidates are emitted.

Output: reports/leader_breakout_candidates_{market}.json (research/paper only).
"""
from __future__ import annotations

import csv
import glob
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OHLCV = os.path.join(REPO, "data", "market", "ohlcv")
INDEX = {"kr": "KOSPI", "us": "SPY"}
NON_STOCK = {"KOSPI", "KOSDAQ", "SPY", "QQQ", "DIA", "IWM", "RSP", "HYG", "LQD",
             "TLT", "GLD", "SMH", "SOXX", "SOXL", "SCHD", "XLE", "XLF"}


def _series(path):
    rows = []
    try:
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            try:
                rows.append((r.get("date", "")[:10], float(r["high"]),
                             float(r["low"]), float(r["close"]), float(r.get("volume") or 0)))
            except (ValueError, KeyError, TypeError):
                continue
    except FileNotFoundError:
        return []
    rows = [x for x in rows if x[0] and x[3] > 0]
    rows.sort(key=lambda x: x[0])
    return rows


def _ma(v, n, i):
    return sum(v[i - n + 1:i + 1]) / n if i + 1 >= n else None


def _scan(market: str, us_favorable: bool) -> dict:
    idx = _series(os.path.join(OHLCV, f"{market}_{INDEX[market]}_daily.csv"))
    if len(idx) < 70:
        return {"status": "NO_DATA", "market": market}
    ic = [x[3] for x in idx]
    idx_ret60 = (ic[-1] / ic[-61] - 1) if len(ic) > 61 else 0.0
    as_of = idx[-1][0]

    cands = []
    scanned = 0
    for path in sorted(glob.glob(os.path.join(OHLCV, f"{market}_*_daily.csv"))):
        sym = os.path.basename(path)[len(market) + 1:-10]
        if sym in NON_STOCK or sym.startswith("USD"):
            continue
        s = _series(path)
        if len(s) < 260 or s[-1][0] != as_of:
            continue
        scanned += 1
        c = [x[3] for x in s]; h = [x[1] for x in s]; lo = [x[2] for x in s]; v = [x[4] for x in s]
        i = len(s) - 1
        ma50, ma150 = _ma(c, 50, i), _ma(c, 150, i)
        if ma50 is None or ma150 is None:
            continue
        hi250, lo250 = max(c[-250:]), min(c[-250:])
        posr = (c[i] - lo250) / (hi250 - lo250) if hi250 > lo250 else 0
        ret60 = c[i] / c[i - 60] - 1 if c[i - 60] else 0
        v50 = _ma(v, 50, i) or 0
        leader = c[i] > ma50 > ma150 and posr > 0.75 and ret60 > idx_ret60
        trigger = c[i] >= max(h[i - 20:i]) and v50 > 0 and v[i] >= 1.5 * v50
        if not (leader and trigger):
            continue
        entry = c[i]; stop = min(lo[-10:])
        if stop >= entry:
            continue
        cands.append({
            "symbol": sym, "asOf": as_of, "entry": round(entry, 2), "stop": round(stop, 2),
            "target": round(entry + 2.0 * (entry - stop), 2),
            "rrRatio": round((entry - stop and 2.0) or 0, 2),
            "ret60Pct": round(ret60 * 100, 2), "posRange250": round(posr, 3),
            "volRatio50": round(v[i] / v50, 2), "setup": "LEADER_BREAKOUT",
        })
    cands.sort(key=lambda c: -c["ret60Pct"])
    return {
        "version": "leader-breakout-v1", "market": market, "asOf": as_of,
        "status": "OK" if us_favorable else "US_BACKDROP_UNFAVORABLE",
        "usBackdropFavorable": us_favorable, "scanned": scanned,
        "validatedEdge": {"note": "leader breakout only holds up on SPY>MA50; deep 2014-2026 train+OOS forward-return, not cost/trade-sim"},
        "candidates": cands if us_favorable else [],
        "heldForUnfavorableBackdrop": [] if us_favorable else cands,
        "note": "Research/paper only. Feed the paper loop for live proof before promotion.",
    }


def main() -> int:
    spy = _series(os.path.join(OHLCV, "us_SPY_daily.csv"))
    us_favorable = False
    if len(spy) >= 60:
        sc = [x[3] for x in spy]
        ma50 = _ma(sc, 50, len(sc) - 1)
        us_favorable = ma50 is not None and sc[-1] > ma50
    for market in ("kr", "us"):
        payload = _scan(market, us_favorable)
        out = os.path.join(REPO, "reports", f"leader_breakout_candidates_{market}.json")
        json.dump(payload, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        n = len(payload.get("candidates", []))
        print(f"leader-breakout {market}: US {'favorable' if us_favorable else 'UNFAVORABLE'}, "
              f"scanned {payload.get('scanned', 0)}, {n} candidate(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
