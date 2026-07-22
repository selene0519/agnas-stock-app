#!/usr/bin/env python3
"""Paper -> live promotion gate for KR bear-rebound lens setups.

Reads the survivorship-free settled paper journal (reports/lens_live_journal_kr.csv,
written by settle_lens_predictions_kr.py) and decides, per setup x regime, whether
the LIVE forward evidence has cleared a fixed, pre-declared bar. Only setups that
clear it should ever be promoted from paper-only to real recommendations.

Promotion criteria (fixed before reading results, same bar the walk-forward
harness uses so paper and backtest agree):
  - sampleCount   >= 12   (enough independent settled trades to be informative)
  - profitFactor  >  1.0  (winners outweigh losers after costs)
  - winRate       >= 50%  (not carried by a few outliers)
  - avgNetPnlPct  >  0    (positive expectancy)

This never promotes anything on its own; it emits an auditable verdict to
reports/lens_promotion_status_kr.json for a human to act on. Absence of data is
NEVER a pass.
"""
from __future__ import annotations

import csv
import json
import os
from collections import defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOURNAL = os.path.join(REPO, "reports", "lens_live_journal_kr.csv")
OUT = os.path.join(REPO, "reports", "lens_promotion_status_kr.json")

MIN_SAMPLES = 12
MIN_PROFIT_FACTOR = 1.0
MIN_WIN_RATE = 0.50
MIN_AVG_NET = 0.0


def _num(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _rows():
    if not os.path.exists(JOURNAL):
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with open(JOURNAL, encoding=enc, newline="") as fh:
                return [dict(r) for r in csv.DictReader(fh)]
        except Exception:
            continue
    return []


def _evaluate(trades):
    nets = [n for t in trades if (n := _num(t.get("netPnlPct"))) is not None]
    n = len(nets)
    if n == 0:
        return {"sampleCount": 0, "status": "NO_DATA"}
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    win_rate = len(wins) / n
    avg_net = sum(nets) / n
    reasons = []
    if n < MIN_SAMPLES:
        reasons.append(f"SAMPLES_{n}_BELOW_{MIN_SAMPLES}")
    if pf <= MIN_PROFIT_FACTOR:
        reasons.append("PROFIT_FACTOR_NOT_ABOVE_1")
    if win_rate < MIN_WIN_RATE:
        reasons.append("WIN_RATE_BELOW_50")
    if avg_net <= MIN_AVG_NET:
        reasons.append("NON_POSITIVE_EXPECTANCY")
    return {
        "sampleCount": n,
        "winRatePct": round(win_rate * 100, 1),
        "profitFactor": round(pf, 2),
        "avgNetPnlPct": round(avg_net, 3),
        "status": "PROMOTE" if not reasons else "STAY_PAPER",
        "blockingReasons": reasons,
    }


def main() -> int:
    rows = _rows()
    groups = defaultdict(list)
    for r in rows:
        setup = str(r.get("setup") or "UNKNOWN").upper()
        regime = str(r.get("regime") or "UNKNOWN").upper()
        groups[f"{regime}|{setup}"].append(r)

    verdicts = {key: _evaluate(trades) for key, trades in sorted(groups.items())}
    promotable = [k for k, v in verdicts.items() if v.get("status") == "PROMOTE"]
    payload = {
        "version": "lens-promotion-v1",
        "market": "kr",
        "source": os.path.relpath(JOURNAL, REPO).replace("\\", "/"),
        "criteria": {
            "minSamples": MIN_SAMPLES, "minProfitFactor": MIN_PROFIT_FACTOR,
            "minWinRate": MIN_WIN_RATE, "minAvgNetPnlPct": MIN_AVG_NET,
        },
        "totalSettledTrades": len(rows),
        "promotable": promotable,
        "verdicts": verdicts,
        "note": "Paper-only forward evidence. Absence of data is never a pass. A human promotes; this is an auditable gate, not an automatic action.",
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    if not rows:
        print("promote: no settled paper trades yet (predictions still maturing) -> nothing promotable")
    else:
        print(f"promote: {len(rows)} settled trades, {len(promotable)} setup(s) clear the bar: {promotable or '(none)'}")
    print(f"  -> {os.path.relpath(OUT, REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
