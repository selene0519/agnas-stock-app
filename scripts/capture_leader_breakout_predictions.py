#!/usr/bin/env python3
"""Capture leader-breakout candidates into the prediction ledger for live proof.

Past backtesting (train/OOS, cost-adjusted trade-sim) is done: the leader
breakout cleared PF 1.6-2.2. Further re-backtesting on the same 2014-2026 data
only risks overfitting. The honest remaining test is the FUTURE, so this feeds
each day's leader-breakout candidates into reports/lens_prediction_ledger_kr.csv
(setup=LEADER_BREAKOUT), where the existing settle + promote scripts settle them
against real forward prices and only promote if the LIVE record clears the same
fixed bar (n>=12, PF>1, win>=50%). Survivorship-bias-free, look-ahead-free.

KR only for now (mirrors the existing KR settle/promote infra). US candidates
would need a parallel US ledger/settle to be added.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = os.path.join(REPO, "reports", "leader_breakout_candidates_kr.json")
LEDGER = os.path.join(REPO, "reports", "lens_prediction_ledger_kr.csv")
FIELDS = ["predictionId", "captureDate", "symbol", "name", "setup", "regime",
          "entry", "stop", "target", "rsi14", "distMa20Pct", "calibrationGate",
          "sizeMultiplier", "validationWindowDays", "status", "exitDate",
          "grossPnlPct", "netPnlPct", "outcome"]
WINDOW = 20


def _existing_ids() -> set[str]:
    if not os.path.exists(LEDGER):
        return set()
    try:
        return {r.get("predictionId", "") for r in csv.DictReader(open(LEDGER, encoding="utf-8-sig"))}
    except Exception:
        return set()


def main() -> int:
    if not os.path.exists(CANDIDATES):
        print("leader-breakout capture: no candidate file yet")
        return 0
    doc = json.loads(open(CANDIDATES, encoding="utf-8").read())
    if doc.get("status") != "OK":
        print(f"leader-breakout capture: status {doc.get('status')} -> nothing to capture")
        return 0
    as_of = str(doc.get("asOf") or "")
    cands = doc.get("candidates") or []
    have = _existing_ids()
    new_rows = []
    for c in cands:
        sym = str(c.get("symbol") or "")
        pid = hashlib.sha1(f"LEADER_BREAKOUT|{sym}|{as_of}".encode()).hexdigest()[:16]
        if pid in have:
            continue
        new_rows.append({
            "predictionId": pid, "captureDate": as_of, "symbol": sym, "name": sym,
            "setup": "LEADER_BREAKOUT", "regime": "BULL",
            "entry": c.get("entry"), "stop": c.get("stop"), "target": c.get("target"),
            "rsi14": "", "distMa20Pct": "", "calibrationGate": "VALIDATED_TRADESIM",
            "sizeMultiplier": 1.0, "validationWindowDays": WINDOW,
            "status": "PENDING", "exitDate": "", "grossPnlPct": "", "netPnlPct": "", "outcome": "",
        })
    if new_rows:
        is_new = not os.path.exists(LEDGER)
        with open(LEDGER, "a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if is_new:
                w.writeheader()
            for r in new_rows:
                w.writerow(r)
    print(f"leader-breakout capture: {as_of}, {len(cands)} candidate(s), +{len(new_rows)} new ledger row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
