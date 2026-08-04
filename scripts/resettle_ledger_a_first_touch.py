#!/usr/bin/env python3
"""원장 A를 선착순 청산 규칙으로 재정산한다.

배경 (2026-07-29):
`mone_v65_api_stabilizer`가 창 **전체**를 훑어 target_hit/stop_hit 플래그를
모은 뒤 마지막에 판정하고 있었다. 2일차에 목표를 찍고 9일차에 손절을 찍으면
STOP_FIRST(손실)로 기록된다 — 실제로는 2일차에 익절되어 포지션이 없는데도.

  실측: STOP_FIRST 110건 중 **46건(41.8%)이 목표 먼저**였다.
  선착순 재판정 시 정산 663건: 평균 -5.015% -> -3.826%, 승률 15.4% -> 22.3%.

판정 로직은 이미 고쳤다(선착순). 이 스크립트는 **과거 행**을 같은 규칙으로
다시 계산한다.

⚠️ **원장 B(`virtual_trade_evaluations.csv`)는 대상이 아니다.** 그쪽
`_find_exit`는 처음부터 선착순이라 이 버그가 없다. 엣지 판정·게이트는 B를
쓰므로 그 수치는 이 재정산으로 바뀌지 않는다. A는 화면 표시 분모다.

안전장치:
  * 기본이 dry-run이다. `--apply`를 줘야 파일을 쓴다.
  * 쓰기 전에 원본을 `.bak.<타임스탬프>`로 남긴다.
  * 바뀐 행을 전부 `reports/resettlement_audit.json`에 기록한다.
  * `validationRule`을 `first_touch_v2`로 표시해 어느 행이 재정산됐는지 남긴다.
  * PENDING·OHLCV 없음·필드 부족은 **건드리지 않는다.**

판정은 `settle_pending_validations._settle_from_ohlcv`를 **그대로 재사용**한다.
이 레포엔 손절가를 세 군데서 따로 계산하다 어긋난 전례가 있어 두 번째 산식을
만들지 않는다.

실행: python scripts/resettle_ledger_a_first_touch.py           # dry-run
      python scripts/resettle_ledger_a_first_touch.py --apply
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from settle_pending_validations import (  # noqa: E402
    _num, _settle_from_ohlcv, _window_cutoff,
)

LEDGER = ROOT / "reports" / "virtual_validation_results.csv"
AUDIT = ROOT / "reports" / "resettlement_audit.json"
RULE_TAG = "first_touch_v2"

# 앱이 정의한 진입 창(mone_v65_api_stabilizer:2433 `entry_window`). 이걸 안 주면
# 검증 창 전체에서 진입을 인정해 **미체결이어야 할 것이 체결로 잡힌다**
# (실측: NOT_EXECUTED -> STOP 52건이 그 때문이었다).
ENTRY_WINDOW_BARS = {"short": 2, "swing": 3, "mid": 4}

# 손대지 않을 상태 — 아직 안 끝났거나 정산 대상이 아닌 것들.
UNTOUCHED_RESULTS = {"PENDING", "DATA_PENDING", "INVALID_SYMBOL", ""}

# **원장이 쓰던 대문자 어휘를 유지한다.** 판정 함수는 소문자를 돌려주는데,
# 그대로 쓰면 값이 그대로인 행까지 전부 "변경"으로 잡혀(실측 834행 중 808행)
# 감사가 불가능해진다. 어휘를 바꾸는 것과 판정을 고치는 것은 다른 작업이다.
_LABEL = {
    "target_hit": "TARGET",
    "stop_hit": "STOP",          # 같은 날 동시 도달이면 아래에서 STOP_FIRST로
    "close_exit": "HOLDING_EVAL",
    "NOT_EXECUTED": "NOT_EXECUTED",
}


def _to_ledger_label(settled: dict) -> str:
    raw = str(settled.get("result") or "")
    if raw == "stop_hit" and settled.get("sameDayTie"):
        # STOP_FIRST는 이제 "같은 날 둘 다 닿아 순서를 알 수 없음"만 뜻한다.
        return "STOP_FIRST"
    return _LABEL.get(raw, raw)


def _read_rows() -> tuple[list[dict], list[str]]:
    with LEDGER.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [dict(r) for r in reader]
        fields = list(reader.fieldnames or [])
    return rows, fields


def _mean(vals: list[float]) -> float:
    return round(statistics.fmean(vals), 4) if vals else 0.0


def _win_rate(vals: list[float]) -> float:
    return round(sum(1 for v in vals if v > 0) / len(vals) * 100, 2) if vals else 0.0


def run(apply: bool) -> dict:
    rows, fields = _read_rows()
    changes: list[dict] = []
    # 변경을 **두 종류로 나눈다.** 안 나누면 817행이 뭉뚱그려져 감사가 안 된다.
    #   judgment: 청산 판정(라벨)이 바뀐 행 — 선착순 수정의 실제 효과
    #   costOnly: 판정은 같고 비용만 반영된 행 — 스태빌라이저가 **총수익**을
    #             기록하고 있었다(비용 미차감). 정산 경로는 순수익을 쓴다.
    kinds = {"judgment": 0, "costOnly": 0}
    skipped = {"pending": 0, "noFields": 0, "noOhlcv": 0, "unchanged": 0,
               "executionFlip": 0}
    before: list[float] = []
    after: list[float] = []

    for row in rows:
        old_result = str(row.get("result") or "").strip()
        old_ret = _num(row.get("returnPct"))
        if old_ret is not None:
            before.append(old_ret)

        if old_result in UNTOUCHED_RESULTS:
            skipped["pending"] += 1
            if old_ret is not None:
                after.append(old_ret)
            continue

        market = str(row.get("market") or "").lower()
        symbol = str(row.get("symbol") or "").strip()
        entry = _num(row.get("entryPrice"))
        stop = _num(row.get("stopPrice"))
        target = _num(row.get("targetPrice"))
        created = str(row.get("createdAt") or "")[:10]
        due = str(row.get("validationDueDate") or "")[:10]
        if not (symbol and entry and stop and target and created and due):
            skipped["noFields"] += 1
            if old_ret is not None:
                after.append(old_ret)
            continue

        horizon = str(row.get("horizon") or "swing").lower()
        cutoff = _window_cutoff(horizon, due)
        settled = _settle_from_ohlcv(market, symbol, entry, stop, target, created, cutoff,
                                     entry_window_bars=ENTRY_WINDOW_BARS.get(horizon, 3))
        if not settled:
            skipped["noOhlcv"] += 1
            if old_ret is not None:
                after.append(old_ret)
            continue

        new_result = _to_ledger_label(settled)

        # **체결 여부는 절대 뒤집지 않는다.**
        # 진입 창을 어떻게 세느냐에 따라 체결/미체결이 양방향으로 흔들리는데
        # (실측: STOP->NOT_EXECUTED 67건, NOT_EXECUTED->STOP 52건),
        # 어느 쪽이 맞는지 확인할 근거가 없다. 기록된 역사를 근거 없이
        # 내 재구성으로 갈아치우는 셈이 된다.
        # 반면 **청산 판정**은 원본도 "체결됨"으로 합의한 행에서만 고치므로
        # 검증 가능하다 — 이 스크립트가 고치는 건 그것뿐이다.
        was_exec = old_result != "NOT_EXECUTED"
        now_exec = new_result != "NOT_EXECUTED"
        if was_exec != now_exec:
            skipped["executionFlip"] += 1
            if old_ret is not None:
                after.append(old_ret)
            continue

        new_ret = settled.get("returnPct")
        if new_ret is not None:
            after.append(float(new_ret))
        elif old_ret is not None:
            after.append(old_ret)

        # 둘 다 None(NOT_EXECUTED)이면 "같다"로 봐야 한다. 예전 조건은
        # non-None을 요구해서 값이 없는 행 82개를 매번 "변경"으로 보고했다 —
        # 없는 변화를 보고하는 감시 도구는 있으나 마나다.
        if old_ret is None and new_ret is None:
            same_ret = True
        else:
            same_ret = (old_ret is not None and new_ret is not None
                        and abs(float(new_ret) - old_ret) < 0.005)
        if new_result == old_result and same_ret:
            skipped["unchanged"] += 1
            row["validationRule"] = RULE_TAG
            continue

        kind = "judgment" if new_result != old_result else "costOnly"
        kinds[kind] += 1
        changes.append({
            "changeKind": kind,
            "predictionId": row.get("predictionId") or row.get("﻿predictionId"),
            "market": market, "symbol": symbol,
            "mode": row.get("mode"), "horizon": row.get("horizon"),
            "createdAt": created,
            "old": {"result": old_result, "returnPct": old_ret,
                    "exitPrice": _num(row.get("exitPrice"))},
            "new": {"result": new_result, "returnPct": new_ret,
                    "exitPrice": settled.get("exitPrice"),
                    "exitDate": settled.get("exitDate")},
        })

        row["result"] = new_result
        if new_ret is not None:
            row["returnPct"] = new_ret
        if settled.get("exitPrice") is not None:
            row["exitPrice"] = settled["exitPrice"]
        row["targetHit"] = "true" if new_result in {"TARGET"} else "false"
        row["stopHit"] = "true" if new_result in {"STOP", "STOP_FIRST"} else "false"
        row["validationRule"] = RULE_TAG
        if "exitDate" in fields and settled.get("exitDate"):
            row["exitDate"] = settled["exitDate"]
        # status가 승/패를 담고 있으면 부호에 맞춘다. CLOSED 같은 생애주기
        # 값은 손대지 않는다 — 이 컬럼은 원래 두 가지를 섞어 쓰고 있다.
        status = str(row.get("status") or "").upper()
        if status in {"WIN", "LOSS"} and new_ret is not None:
            row["status"] = "WIN" if float(new_ret) > 0 else "LOSS"

    summary = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "applied": apply,
        "ledger": str(LEDGER.relative_to(ROOT)),
        "rule": RULE_TAG,
        "totalRows": len(rows),
        "changedRows": len(changes),
        "changeKinds": kinds,
        "skipped": skipped,
        "beforeMeanPct": _mean(before),
        "afterMeanPct": _mean(after),
        "beforeWinRatePct": _win_rate(before),
        "afterWinRatePct": _win_rate(after),
        "scopeNote": ("원장 B(virtual_trade_evaluations)는 대상이 아니다 — 그쪽 _find_exit는 "
                      "처음부터 선착순이라 이 버그가 없다. 엣지 판정·게이트는 B를 쓰므로 "
                      "그 수치는 이 재정산으로 바뀌지 않는다."),
        "changes": changes,
    }

    if apply and changes:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = LEDGER.with_suffix(f".csv.bak.{stamp}")
        shutil.copy2(LEDGER, backup)
        summary["backup"] = str(backup.relative_to(ROOT))
        if "validationRule" not in fields:
            fields.append("validationRule")
        with LEDGER.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="실제로 원장을 고친다 (기본은 dry-run)")
    args = ap.parse_args()

    s = run(args.apply)
    mode = "적용" if args.apply else "DRY-RUN"
    print(f"=== 원장 A 재정산 ({mode}) ===")
    k = s["changeKinds"]
    print(f"  전체 {s['totalRows']}행 · 변경 {s['changedRows']}행")
    print(f"    ├ 청산 판정이 바뀜 {k['judgment']}행  (선착순 수정의 실제 효과)")
    print(f"    └ 비용만 반영     {k['costOnly']}행  (기존 원장은 총수익 기록)")
    print(f"  건너뜀: {s['skipped']}")
    print(f"\n  평균손익  {s['beforeMeanPct']:+.3f}%  ->  {s['afterMeanPct']:+.3f}%"
          f"   ({s['afterMeanPct'] - s['beforeMeanPct']:+.3f}%p)")
    print(f"  승률      {s['beforeWinRatePct']:.1f}%  ->  {s['afterWinRatePct']:.1f}%")
    if s.get("backup"):
        print(f"  백업: {s['backup']}")
    print(f"  감사 기록: {AUDIT.relative_to(ROOT)}")
    if not args.apply:
        print("\n  (dry-run입니다. 실제 적용은 --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
