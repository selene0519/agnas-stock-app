#!/usr/bin/env python3
"""
실전 게이트 forward 증명 2/2 — 정산 + 실적 요약.

high_conviction_ledger_kr.csv의 PENDING을 만기(10거래일) 도래 시 실제 OHLCV로 정산
(target/stop 절대가 터치, 보수적 손절, 비용 0.5%, 룩어헤드無) → 게이트의 진짜 forward
실적을 reports/high_conviction_pnl_kr.json에 요약. 이게 +0.72%가 실제로 유지되는지의
최종 판정(백테스트 아님, in-sample 편향 없는 forward).

읽기: reports/high_conviction_ledger_kr.csv, data/market/ohlcv/kr_*_daily.csv
쓰기: 원장 갱신 + reports/high_conviction_pnl_kr.json
"""
from __future__ import annotations
import csv
import json
import os
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COST = 0.5
LEDGER_FIELDS = ["predictionId", "captureDate", "symbol", "name", "finalScore",
                 "entry", "stop", "target", "regime", "validationWindowDays", "status",
                 "exitDate", "netPnlPct", "outcome"]


def load_ohlcv(symbol):
    path = os.path.join(REPO, "data", "market", "ohlcv", f"kr_{symbol}_daily.csv")
    if not os.path.exists(path):
        return []
    out = []
    for x in csv.reader(open(path, encoding="utf-8-sig")):
        if not x or not x[0] or x[0] == "date":
            continue
        try:
            out.append((x[0], float(x[3]), float(x[4]), float(x[5]), float(x[6])))
        except (ValueError, IndexError):
            continue
    out.sort(key=lambda r: r[0])
    return out


def settle_one(r):
    bars = load_ohlcv(r["symbol"])
    if not bars:
        return None
    after = [b for b in bars if b[0] > r["captureDate"]]
    window = int(r.get("validationWindowDays") or 10)
    if len(after) < window:
        return None  # 만기 전
    try:
        entry, stop, target = float(r["entry"]), float(r["stop"]), float(r["target"])
    except (TypeError, ValueError):
        return None
    for k in range(min(window, len(after))):
        _d, _o, h, l, _c = after[k]
        if l <= stop:
            return (round((stop / entry - 1) * 100 - COST, 3), after[k][0])
        if h >= target:
            return (round((target / entry - 1) * 100 - COST, 3), after[k][0])
    idx = min(window, len(after)) - 1
    return (round((after[idx][4] / entry - 1) * 100 - COST, 3), after[idx][0])


def main() -> int:
    ledger = os.path.join(REPO, "reports", "high_conviction_ledger_kr.csv")
    rows = list(csv.DictReader(open(ledger, encoding="utf-8-sig"))) if os.path.exists(ledger) else []
    settled_now = 0
    for r in rows:
        if str(r.get("status")) == "SETTLED":
            continue
        res = settle_one(r)
        if not res:
            continue
        net, exit_date = res
        r["status"] = "SETTLED"; r["netPnlPct"] = net; r["exitDate"] = exit_date
        r["outcome"] = "WIN" if net > 0 else "LOSS"
        settled_now += 1
    if rows:
        with open(ledger, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in LEDGER_FIELDS})

    settled = [r for r in rows if r.get("status") == "SETTLED" and r.get("netPnlPct") not in (None, "")]
    pnls = [float(r["netPnlPct"]) for r in settled]
    pending = sum(1 for r in rows if r.get("status") != "SETTLED")
    summary = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "forwardSettled": len(pnls),
        "pending": pending,
        "winRate": round(sum(1 for p in pnls if p > 0) / len(pnls) * 100, 1) if pnls else None,
        "avgNetPct": round(sum(pnls) / len(pnls), 3) if pnls else None,
        "cumulativePct": round(sum(pnls), 1) if pnls else 0,
        "provenBacktest": {"avgNetPct": 0.72, "note": "in-sample 임계 도출분(낙관 가능)"},
        "note": "forward 실측(캡처→정산). 표본 쌓일수록 +0.72% 유지 여부 판정. 지금 0이면 아직 실전신호 없었음(약세장).",
    }
    out = os.path.join(REPO, "reports", "high_conviction_pnl_kr.json")
    json.dump(summary, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"실전 게이트 정산: +{settled_now} settled, forward 누적 {len(pnls)}건 "
          f"평균 {summary['avgNetPct']}% (pending {pending}) -> {os.path.relpath(out, REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
