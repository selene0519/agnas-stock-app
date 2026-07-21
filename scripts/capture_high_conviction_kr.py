#!/usr/bin/env python3
"""
실전 게이트 forward 증명 1/2 — 캡처.

실전 신호 게이트(high_conviction_kr.json)가 '실전 매수'로 낸 종목을 forward 예측
원장에 기록한다. settle이 만기 정산 → 게이트가 진짜 (+)를 내는지 forward로 증명.
(임계값 84가 in-sample에서 뽑혀 낙관일 수 있어, forward 실측이 최종 판정.)

- highConviction=True만 캡처. 오늘 약세장이면 0건(정상, 현금 보존).
- 멱등: predictionId(symbol+date) 중복 skip.
읽기: reports/high_conviction_kr.json
쓰기(append): reports/high_conviction_ledger_kr.csv
"""
from __future__ import annotations
import csv
import hashlib
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOW = 10
FIELDS = ["predictionId", "captureDate", "symbol", "name", "finalScore",
          "entry", "stop", "target", "regime", "validationWindowDays", "status"]


def main() -> int:
    src = os.path.join(REPO, "reports", "high_conviction_kr.json")
    if not os.path.exists(src):
        print("high_conviction_kr.json 없음 — build_high_conviction_kr.py 먼저 실행")
        return 1
    rep = json.load(open(src, encoding="utf-8"))
    as_of = rep.get("regimeDetail", {}).get("asOf") or rep.get("generatedAt", "")[:10]
    regime = rep.get("marketRegime", "")
    actionable = [c for c in rep.get("candidates", []) if c.get("highConviction")]

    ledger = os.path.join(REPO, "reports", "high_conviction_ledger_kr.csv")
    existing = set()
    if os.path.exists(ledger):
        for r in csv.DictReader(open(ledger, encoding="utf-8-sig")):
            existing.add(r.get("predictionId"))

    new = []
    for c in actionable:
        pid = hashlib.sha1(f"{c['symbol']}|{as_of}".encode()).hexdigest()[:16]
        if pid in existing:
            continue
        new.append({"predictionId": pid, "captureDate": as_of, "symbol": c["symbol"],
                    "name": c.get("name", c["symbol"]), "finalScore": c.get("finalScore"),
                    "entry": c.get("entry") or c.get("close"), "stop": c.get("stop"),
                    "target": c.get("target"), "regime": regime,
                    "validationWindowDays": WINDOW, "status": "PENDING"})

    is_new = not os.path.exists(ledger)
    with open(ledger, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if is_new:
            w.writeheader()
        w.writerows(new)
    print(f"실전 게이트 캡처 asOf={as_of} regime={regime}: +{len(new)}건 (기존 {len(existing)})")
    if not new and not actionable:
        print("→ 실전 후보 0건(약세장/저점수) = 캡처 없음, 현금 보존 유지")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
