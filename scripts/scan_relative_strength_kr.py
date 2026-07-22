#!/usr/bin/env python3
"""Cross-sectional relative-strength lens (KR + US).

Breaks out of the directional-long frame: instead of "will this stock go up?"
it ranks the whole universe by relative strength and surfaces the leaders,
because in a flat/sideways market the winners keep winning and the laggards
keep lagging even when the index goes nowhere.

Deep 2014-2026 (OOS) dispersion, top vs bottom RS quintile, fwd-20d:
  KR SIDE  +2.07% vs -1.38%  => +3.45p spread  (the sideways answer for KR)
  KR BULL  +4.22% vs +1.60%  => +2.63p
  KR BEAR  +4.09% vs +3.97%  => +0.11p  (no dispersion - correlations ~1)
  US BULL  +5.90% vs +1.24%  => +4.66p
Bear has essentially no (KR) or reversed (US) dispersion, so this lens is for
BULL/SIDE only; in BEAR the app should stay defensive, not lean on RS.

Output: reports/relative_strength_leaders_{market}.json (research/paper only).
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
TOP_N = 15


def _closes(path):
    out = []
    try:
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            try:
                out.append((r.get("date", "")[:10], float(r["close"])))
            except (ValueError, KeyError, TypeError):
                continue
    except FileNotFoundError:
        return []
    out = [x for x in out if x[0] and x[1] > 0]
    out.sort(key=lambda x: x[0])
    return out


def _regime(idx):
    c = [x[1] for x in idx]
    if len(c) < 25:
        return "UNKNOWN"
    ma20 = sum(c[-20:]) / 20
    ma20_prev = sum(c[-25:-5]) / 20
    if c[-1] > ma20 and ma20 > ma20_prev:
        return "BULL"
    if c[-1] < ma20 and ma20 < ma20_prev:
        return "BEAR"
    return "SIDE"


def _scan(market: str) -> dict:
    idx = _closes(os.path.join(OHLCV, f"{market}_{INDEX[market]}_daily.csv"))
    if len(idx) < 70:
        return {"status": "NO_DATA", "market": market}
    ic = [x[1] for x in idx]
    idx_rs = ic[-1] / ic[-61] - 1 if len(ic) > 61 else 0.0
    as_of = idx[-1][0]
    regime = _regime(idx)

    ranked = []
    for path in sorted(glob.glob(os.path.join(OHLCV, f"{market}_*_daily.csv"))):
        sym = os.path.basename(path)[len(market) + 1:-10]
        if sym in NON_STOCK or sym.startswith("USD"):
            continue
        c = _closes(path)
        if len(c) < 70 or c[-1][0] != as_of:
            continue
        cl = [x[1] for x in c]
        rs = cl[-1] / cl[-61] - 1
        ranked.append({"symbol": sym, "rs60Pct": round(rs * 100, 2),
                       "relToIndexPp": round((rs - idx_rs) * 100, 2)})
    ranked.sort(key=lambda x: -x["rs60Pct"])
    # This lens only carries an edge in BULL/SIDE; label BEAR as defensive.
    usable = regime in ("BULL", "SIDE")
    return {
        "version": "relative-strength-v1", "market": market, "asOf": as_of,
        "regime": regime,
        "status": "OK" if usable else "DEFENSIVE_BEAR_NO_DISPERSION",
        "lensNote": "Long the RS leaders, avoid the laggards. Edge in BULL/SIDE only; BEAR has ~no cross-sectional dispersion.",
        "universeCount": len(ranked),
        "leaders": ranked[:TOP_N] if usable else [],
        "laggardsToAvoid": ranked[-TOP_N:] if usable else [],
        "note": "Research/paper only.",
    }


def main() -> int:
    for market in ("kr", "us"):
        payload = _scan(market)
        out = os.path.join(REPO, "reports", f"relative_strength_leaders_{market}.json")
        json.dump(payload, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"relative-strength {market}: regime {payload.get('regime')}, "
              f"{len(payload.get('leaders', []))} leaders, status {payload.get('status')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
