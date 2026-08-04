#!/usr/bin/env python3
"""측정이 흔들리지 않는지 기계로 확인한다.

"앱이 흔들리면 안 된다"를 감시 가능한 불변식으로 바꾼다. 세 가지를 본다.

1. **멱등성** — 이미 정산된 행을 같은 규칙으로 다시 정산했을 때 값이 바뀌면
   안 된다. 바뀐다면 정산이 실행 시점에 의존한다는 뜻이다.

2. **두 원장의 일치** — 같은 예측을 A와 B가 둘 다 담고 있으면 같은 값을
   줘야 한다. 2026-07-29 실측: 공통 60건 중 **0.5%p 이내 일치가 5건(8.3%)**,
   평균 3.0%p 차이. 오늘 고친 STOP_FIRST 버그(1.14%p)보다 크다.

3. **규칙 상수의 차이** — 위 불일치의 원인이다. 두 경로가 서로 다른 비용
   모델과 창 길이를 쓴다. 이건 버그가 아니라 **설계가 갈린 것**이라 코드로
   자동 수정할 수 없다. 대신 차이를 숫자로 드러내 결정을 미루지 못하게 한다.

     비용(국장)   A 0.09%          B 0.41% (슬리피지 0.1+0.1 + 세금수수료 0.21)
     검증창 mid   A 21+7=28일       B 60일
     진입창       A 없음            B 3/5/10일

실행: python scripts/check_measurement_stability.py
쓰기: reports/measurement_stability.json
종료코드: 불변식이 깨지면 1
"""
from __future__ import annotations

import csv
import json
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
OUT = ROOT / "reports" / "measurement_stability.json"

LEDGER_A = ROOT / "reports" / "virtual_validation_results.csv"
JOURNAL_B = ROOT / "data" / "virtual_trade_journal.csv"
EVALS_B = ROOT / "data" / "virtual_trade_evaluations.csv"

# 일치로 볼 허용 오차(%p)와, 그 기준을 넘겨도 되는 최소 일치 비율.
AGREE_TOL_PP = 0.5
MIN_AGREE_SHARE = 0.90


def _rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def _f(v) -> float | None:
    try:
        s = str(v or "").replace(",", "").strip()
        return float(s) if s else None
    except Exception:
        return None


def _key(market, symbol, mode, horizon, date) -> tuple:
    return (str(market or "").lower(), str(symbol or "").upper(),
            str(mode or "").lower(), str(horizon or "").lower(), str(date or "")[:10])


def check_idempotency() -> dict:
    """재정산 dry-run에서 판정이 하나도 안 바뀌어야 한다."""
    try:
        from resettle_ledger_a_first_touch import run as resettle_run
        s = resettle_run(apply=False)
    except Exception as exc:  # 스크립트가 없거나 깨졌으면 그것도 불안정이다
        return {"ok": False, "reason": f"재정산 실행 실패: {exc}"}
    kinds = s.get("changeKinds", {})
    judgment = int(kinds.get("judgment", 0))
    value = int(kinds.get("costOnly", 0))
    return {
        "ok": judgment == 0 and value == 0,
        "judgmentChanges": judgment,
        "valueChanges": value,
        "meanBeforePct": s.get("beforeMeanPct"),
        "meanAfterPct": s.get("afterMeanPct"),
        "note": ("이미 정산된 행을 같은 규칙으로 다시 정산했을 때 값이 바뀌면 "
                 "정산이 실행 시점에 의존한다는 뜻이다."),
    }


def check_cross_ledger() -> dict:
    """A와 B가 같은 예측에 같은 값을 주는가."""
    a: dict[tuple, tuple[float, str]] = {}
    for r in _rows(LEDGER_A):
        v = _f(r.get("returnPct"))
        if v is None:
            continue
        a[_key(r.get("market"), r.get("symbol"), r.get("mode"),
               r.get("horizon"), r.get("createdAt"))] = (v, str(r.get("result") or ""))

    j: dict[tuple, str] = {}
    for r in _rows(JOURNAL_B):
        j.setdefault(_key(r.get("market"), r.get("symbol"), r.get("mode"), r.get("horizon"),
                          r.get("as_of_date") or r.get("captured_at")),
                     str(r.get("journal_id") or ""))

    e: dict[str, tuple[float, str]] = {}
    for r in _rows(EVALS_B):
        v = _f(r.get("net_pnl_pct"))
        if v is not None:
            e[str(r.get("journal_id") or "")] = (v, str(r.get("outcome") or ""))

    shared = [(k, a[k], e[j[k]]) for k in a if k in j and j[k] in e]
    if not shared:
        return {"ok": True, "sharedTrades": 0,
                "note": "공통 예측이 없어 비교하지 못했다 — 통과가 아니라 미판정이다."}

    diffs = [av - bv for _, (av, _), (bv, _) in shared]
    agree = sum(1 for d in diffs if abs(d) < AGREE_TOL_PP)
    share = agree / len(diffs)
    return {
        "ok": share >= MIN_AGREE_SHARE,
        "sharedTrades": len(shared),
        "agreeWithinPp": AGREE_TOL_PP,
        "agreeShare": round(share, 4),
        "minAgreeShare": MIN_AGREE_SHARE,
        "meanA": round(statistics.fmean([av for _, (av, _), _ in shared]), 4),
        "meanB": round(statistics.fmean([bv for _, _, (bv, _) in shared]), 4),
        "meanDiffPp": round(statistics.fmean(diffs), 4),
        "medianDiffPp": round(statistics.median(diffs), 4),
        "note": ("같은 예측인데 값이 다르면 '엣지가 얼마인가'에 답이 두 개가 된다. "
                 "원인은 아래 ruleDivergence — 버그가 아니라 설계가 갈린 것이다."),
    }


def rule_divergence() -> dict:
    """두 경로가 실제로 쓰는 상수를 나란히 드러낸다."""
    try:
        from settle_pending_validations import COST_PCT, HORIZON_VALIDATION_DAYS
        a_cost = dict(COST_PCT)
        a_win = dict(HORIZON_VALIDATION_DAYS)
    except Exception:
        a_cost, a_win = {}, {}
    return {
        "cost": {
            "ledgerA": a_cost,
            "ledgerB": {"kr": 0.41, "us": 0.30,
                        "breakdown": "buy_slippage 0.1 + sell_slippage 0.1 + tax_commission 0.21(kr)/0.10(us)"},
            "note": "국장 기준 약 4.6배 차이. 같은 거래의 순손익이 달라진다.",
        },
        "window": {
            "ledgerA": {"validationDays": a_win, "plusBufferDays": 7, "entryWindow": None},
            "ledgerB": {"evaluationDays": {"short": 5, "swing": 20, "mid": 60},
                        "entryWindowDays": {"short": 3, "swing": 5, "mid": 10}},
            "note": "mid 기준 28일 vs 60일. 창이 길면 만기 청산 대신 목표·손절에 닿을 확률이 오른다.",
        },
        "decisionNeeded": ("어느 규칙이 '이 앱의 매매'인지는 사람이 정해야 한다. "
                           "코드로 한쪽에 맞추면 그 순간 과거 수치의 의미가 바뀐다."),
    }


def main() -> int:
    idem = check_idempotency()
    cross = check_cross_ledger()
    rules = rule_divergence()
    ok = bool(idem.get("ok")) and bool(cross.get("ok"))

    doc = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "stable": ok,
        "idempotency": idem,
        "crossLedger": cross,
        "ruleDivergence": rules,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== 측정 안정성: {'안정' if ok else '**불안정**'} ===\n")
    print(f"[멱등성] {'OK' if idem.get('ok') else '실패'}"
          f"  판정변경 {idem.get('judgmentChanges')}행 / 값변경 {idem.get('valueChanges')}행")
    print(f"[두 원장] {'OK' if cross.get('ok') else '실패'}"
          f"  공통 {cross.get('sharedTrades')}건 · 일치 {cross.get('agreeShare')} "
          f"(기준 {cross.get('minAgreeShare')})")
    if cross.get("sharedTrades"):
        print(f"          A {cross.get('meanA'):+.3f}%  vs  B {cross.get('meanB'):+.3f}%"
              f"   평균차 {cross.get('meanDiffPp'):+.3f}%p")
    if not cross.get("ok"):
        print("\n  원인(설계 차이, 자동 수정 불가):")
        print(f"    비용 국장  A {rules['cost']['ledgerA'].get('kr')}%  vs  B 0.41%")
        print(f"    창   mid   A 28일  vs  B 60일")
        print(f"    진입창     A 없음  vs  B 3/5/10일")
        print(f"  -> {rules['decisionNeeded']}")
    print(f"\n기록: {OUT.relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
