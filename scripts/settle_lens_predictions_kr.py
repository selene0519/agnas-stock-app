#!/usr/bin/env python3
"""
Lens forward prediction settlement (KR) — 자가보정 라이브화 2/2.

lens_prediction_ledger_kr.csv 의 PENDING 예측 중 검증창(validationWindowDays)이 지난 것을
실제 OHLCV로 정산해 실현손익을 산출하고, 생존편향 없는 라이브 렌즈 저널
(reports/lens_live_journal_kr.csv)에 append 한다. 원장의 status를 SETTLED로 갱신.

- 정산 모델: 캡처일 다음 봉부터 window 봉까지, 기록된 target/stop 절대가 터치로 청산
  (같은날 둘다면 보수적 손절), 아니면 window 종료 봉 종가. 비용 왕복 COST% 차감.
- 룩어헤드 없음(캡처일 이후 봉만 사용). 아직 창이 안 지난 예측은 PENDING 유지.

읽기: reports/lens_prediction_ledger_kr.csv, data/market/ohlcv/kr_*_daily.csv
쓰기: reports/lens_prediction_ledger_kr.csv(갱신), reports/lens_live_journal_kr.csv(append)
"""
from __future__ import annotations
import csv
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COST = 0.5

LEDGER_FIELDS = [
    "predictionId", "captureDate", "symbol", "name", "setup", "regime",
    "entry", "stop", "target", "rsi14", "distMa20Pct",
    "calibrationGate", "sizeMultiplier", "validationWindowDays", "status",
    "exitDate", "grossPnlPct", "netPnlPct", "outcome",
]
JOURNAL_FIELDS = [
    "signalDate", "symbol", "setup", "regime", "rsi14", "distMa20Pct",
    "entry", "grossPnlPct", "netPnlPct", "outcome", "barsHeld", "exitDate", "source",
]


def load_ohlcv(symbol: str):
    path = os.path.join(REPO, "data", "market", "ohlcv", f"kr_{symbol}_daily.csv")
    if not os.path.exists(path):
        return []
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


def settle_one(row: dict):
    """(settled?, gross, net, outcome, barsHeld, exitDate) 반환. 미도래면 settled=False."""
    bars = load_ohlcv(row["symbol"])
    if not bars:
        return (False, None, None, None, None, None)
    cap = row["captureDate"]
    after = [b for b in bars if b[0] > cap]
    window = int(row.get("validationWindowDays") or 10)
    if len(after) < window:
        return (False, None, None, None, None, None)  # 아직 만기 전
    try:
        entry = float(row["entry"]); stop = float(row["stop"]); target = float(row["target"])
    except (TypeError, ValueError):
        return (False, None, None, None, None, None)
    gross = None; exit_date = after[min(window, len(after)) - 1][0]; held = window
    for k in range(min(window, len(after))):
        _d, _o, h, l, _c = after[k]
        hit_s = l <= stop
        hit_t = h >= target
        if hit_s:  # 보수적: 같은날 둘다면 손절
            gross = (stop / entry - 1) * 100; exit_date = after[k][0]; held = k + 1; break
        if hit_t:
            gross = (target / entry - 1) * 100; exit_date = after[k][0]; held = k + 1; break
    if gross is None:
        gross = (after[window - 1][3] / entry - 1) * 100
    net = gross - COST
    return (True, round(gross, 3), round(net, 3), "WIN" if net > 0 else "LOSS", held, exit_date)


def main() -> int:
    ledger = os.path.join(REPO, "reports", "lens_prediction_ledger_kr.csv")
    if not os.path.exists(ledger):
        print("lens_prediction_ledger_kr.csv 없음 — 먼저 capture_lens_predictions_kr.py 실행")
        return 0
    rows = list(csv.DictReader(open(ledger, encoding="utf-8-sig")))
    journal = os.path.join(REPO, "reports", "lens_live_journal_kr.csv")
    new_journal_rows = []
    settled_now = 0
    for r in rows:
        if str(r.get("status")) == "SETTLED":
            continue
        ok, gross, net, outcome, held, exit_date = settle_one(r)
        if not ok:
            continue
        r["status"] = "SETTLED"; r["grossPnlPct"] = gross; r["netPnlPct"] = net
        r["outcome"] = outcome; r["exitDate"] = exit_date
        new_journal_rows.append({
            "signalDate": r["captureDate"], "symbol": r["symbol"], "setup": r["setup"],
            "regime": r["regime"], "rsi14": r.get("rsi14"), "distMa20Pct": r.get("distMa20Pct"),
            "entry": r["entry"], "grossPnlPct": gross, "netPnlPct": net, "outcome": outcome,
            "barsHeld": held, "exitDate": exit_date, "source": "LIVE",
        })
        settled_now += 1

    # 원장 재작성
    with open(ledger, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in LEDGER_FIELDS})
    # 라이브 저널 append
    if new_journal_rows:
        is_new = not os.path.exists(journal)
        with open(journal, "a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=JOURNAL_FIELDS)
            if is_new:
                w.writeheader()
            w.writerows(new_journal_rows)

    pending = sum(1 for r in rows if r.get("status") != "SETTLED")
    print(f"settle: +{settled_now} settled, {pending} pending -> {os.path.relpath(journal, REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
