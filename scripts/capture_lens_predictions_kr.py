#!/usr/bin/env python3
"""
Lens forward prediction capture (KR) — 자가보정 라이브화 1/2.

렌즈 스크리너 산출물(regime_lens_candidates_kr.json)의 오늘자 후보를 forward 예측 원장
(reports/lens_prediction_ledger_kr.csv)에 append 한다. 이후 settle_lens_predictions_kr.py가
만기 도래분을 실현손익으로 정산 → 라이브 렌즈 저널을 만들고, 자가보정이 생존편향 없는
실측으로 점진 전환된다.

- ACTIVE/SUPPRESSED 후보를 모두 캡처한다(억제가 옳았는지도 실측으로 검증하려고).
- 멱등: predictionId(symbol+captureDate+setup) 중복이면 skip.
- 이 스크립트는 OHLCV/시세를 새로 안 부른다. 스크리너 결과만 읽는다.

읽기: reports/regime_lens_candidates_kr.json
쓰기(append): reports/lens_prediction_ledger_kr.csv
"""
from __future__ import annotations
import csv
import hashlib
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATION_WINDOW_DAYS = 10

FIELDS = [
    "predictionId", "captureDate", "symbol", "name", "setup", "regime",
    "entry", "stop", "target", "rsi14", "distMa20Pct",
    "calibrationGate", "sizeMultiplier", "validationWindowDays", "status",
]


def _pid(symbol: str, date: str, setup: str) -> str:
    return hashlib.sha1(f"{symbol}|{date}|{setup}".encode("utf-8")).hexdigest()[:16]


def main() -> int:
    src = os.path.join(REPO, "reports", "regime_lens_candidates_kr.json")
    if not os.path.exists(src):
        print("regime_lens_candidates_kr.json 없음 — 먼저 screen_regime_lens_kr.py 실행")
        return 1
    report = json.load(open(src, encoding="utf-8"))
    as_of = report.get("asOfDate", "")
    regime = report.get("marketRegime", "")
    cands = report.get("candidates", [])

    ledger = os.path.join(REPO, "reports", "lens_prediction_ledger_kr.csv")
    existing = set()
    if os.path.exists(ledger):
        for r in csv.DictReader(open(ledger, encoding="utf-8-sig")):
            existing.add(r.get("predictionId"))

    new_rows = []
    for c in cands:
        pid = _pid(c["symbol"], as_of, c["setup"])
        if pid in existing:
            continue
        new_rows.append({
            "predictionId": pid,
            "captureDate": as_of,
            "symbol": c["symbol"],
            "name": c.get("name", c["symbol"]),
            "setup": c["setup"],
            "regime": regime,
            "entry": c.get("entryRef"),
            "stop": c.get("stop"),
            "target": c.get("target"),
            "rsi14": c.get("rsi14"),
            "distMa20Pct": c.get("distMa20Pct"),
            "calibrationGate": c.get("calibrationGate", ""),
            "sizeMultiplier": c.get("sizeMultiplier", 0),
            "validationWindowDays": VALIDATION_WINDOW_DAYS,
            "status": "PENDING",
        })

    is_new = not os.path.exists(ledger)
    with open(ledger, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if is_new:
            w.writeheader()
        w.writerows(new_rows)

    print(f"capture asOf={as_of} regime={regime}: +{len(new_rows)}건 (기존 {len(existing)}건) -> {os.path.relpath(ledger, REPO)}")
    for r in new_rows:
        print(f"  {r['symbol']} {r['setup']} gate={r['calibrationGate']} entry={r['entry']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
