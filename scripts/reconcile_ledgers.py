#!/usr/bin/env python3
"""두 원장의 정의를 확정하고 나란히 놓는다 — 어느 쪽이 무엇의 분모인가.

배경:
  clean window 정산 표본이 한쪽은 3건, 다른 쪽은 65건이라 20배 차이가 났다.
  2026-07-28에 승률이 9.1% vs 32.2%로 3배 어긋났던 것과 같은 계열의 혼란인데,
  그때는 **표본 구성**(리플레이 풀링) 문제였고 이번은 **원장 자체가 다른 것**이다.

실측(2026-07-29): 두 원장의 고유 예측 교집합은 854 vs 880 중 **88건뿐**이다.
같은 걸 다르게 세는 게 아니라 서로 다른 모집단을 담고 있다.

  원장A `reports/virtual_prediction_ledger.csv`  (= 추천 원장)
    캡처: `_recommendations_payload(..., limit=50)` — **서빙 경로 그대로**
    필터: 없음. 앱이 카드로 내보내는 것 전부.
    정산: settle_pending_validations.py -> virtual_validation_results.csv
    소비: update_win_rates.py -> strategy_win_rates.json (= API netWinRate, 화면 승률)
    의미: **"앱이 사용자에게 보여준 추천 전체"의 성적**

  원장B `data/virtual_trade_journal.csv`  (= VTJ 페이퍼 저널)
    캡처: 추천 리포트 CSV -> `_reject_reason` 필터 -> `_rank_key` 정렬
          -> `_unique_by_symbol`[:5]  (조합당 최대 5건, 심볼 중복 제거)
    정산: vtj.evaluate() -> virtual_trade_evaluations.csv
    소비: build_live_calibration.py, calibration_gate_shadow.py, factor_attribution.py
    의미: **"상위 5개만 골라 실제로 담았다면"의 성적**

즉 둘 다 맞고, **질문이 다르다.**
  - "추천 목록 전체에 엣지가 있나"        -> A
  - "사용자가 상위 몇 개만 샀다면 어땠나"  -> B
B가 사용자 행동에 더 가깝다 — 아무도 50종목을 사지 않는다.

**주의: "부분집합이니 B가 더 좋겠지"는 실측이 반박한다.**
  A: 승률 15.1% / 평균 -5.018%   (n=662)
  B: 승률 19.8% / 평균 -5.638%   (n=600)
상위 5개 필터는 **적중률은 올리지만 기댓값은 오히려 낮춘다.** 더 자주 맞히는
대신 틀릴 때 더 크게 잃는다는 뜻이고, 이 레포가 계속 마주친 손익 비대칭이
선택 단계에서도 그대로 나타난다. 그래서 두 수치를 같은 줄에 놓고 비교하면 안 된다.

실행: python scripts/reconcile_ledgers.py
쓰기: reports/ledger_reconciliation.json
stdlib만 사용.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "ledger_reconciliation.json"
MARKER = ROOT / "reports" / "clean_window_marker.json"

LEDGER_A = ROOT / "reports" / "virtual_prediction_ledger.csv"
RESULTS_A = ROOT / "reports" / "virtual_validation_results.csv"
JOURNAL_B = ROOT / "data" / "virtual_trade_journal.csv"
EVALS_B = ROOT / "data" / "virtual_trade_evaluations.csv"

NON_REALIZED = {"", "PENDING", "DATA_PENDING", "NOT_EXECUTED",
                "CANCELLED", "INVALID_SYMBOL", "DATA_INVALID", "EXPIRED"}


def _read(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _num(v):
    try:
        s = str(v or "").strip()
        return float(s) if s else None
    except Exception:
        return None


def _clean_window() -> str | None:
    try:
        return str(json.load(open(MARKER, encoding="utf-8")).get("cleanWindowStart") or "")[:10] or None
    except Exception:
        return None


def _key(market, symbol, mode, horizon, date) -> tuple:
    return (str(market or "").lower(), str(symbol or "").upper(),
            str(mode or "").lower(), str(horizon or "").lower(), str(date or "")[:10])


def _stats(pnls: list[float]) -> dict:
    if not pnls:
        return {"trades": 0, "winRate": None, "avgPnlPct": None}
    wins = [p for p in pnls if p > 0]
    return {"trades": len(pnls),
            "winRate": round(len(wins) / len(pnls), 4),
            "avgPnlPct": round(sum(pnls) / len(pnls), 4)}


def collect_a(since: str | None):
    keys, pnls = set(), []
    # 고유 예측 수는 **원장**에서 센다. 정산 결과 파일만 보면 아직 정산 안 된
    # 예측이 빠져 B와 비교할 때 A가 실제보다 작아 보인다.
    for r in _read(LEDGER_A):
        keys.add(_key(r.get("market"), r.get("symbol"), r.get("mode"),
                      r.get("horizon"), r.get("createdAt")))
    for r in _read(RESULTS_A):
        d = str(r.get("createdAt") or "")[:10]
        if since and d and d < since:
            continue
        if str(r.get("result") or r.get("status") or "").upper().strip() in NON_REALIZED:
            continue
        v = _num(r.get("returnPct"))
        if v is not None:
            pnls.append(v)
    return keys, pnls


def collect_b(since: str | None):
    journal = {r.get("journal_id", ""): r for r in _read(JOURNAL_B)}
    keys, pnls = set(), []
    for r in journal.values():
        if str(r.get("source_type") or "").upper() != "FORWARD_PAPER_TRADE":
            continue
        keys.add(_key(r.get("market"), r.get("symbol"), r.get("mode"), r.get("horizon"),
                      r.get("as_of_date") or r.get("captured_at")))
    for e in _read(EVALS_B):
        jr = journal.get(e.get("journal_id", ""))
        if not jr or str(jr.get("source_type") or "").upper() != "FORWARD_PAPER_TRADE":
            continue
        if str(e.get("outcome") or "").upper().strip() in ("", "PENDING"):
            continue
        d = str(jr.get("as_of_date") or jr.get("captured_at") or "")[:10]
        if since and d and d < since:
            continue
        v = _num(e.get("net_pnl_pct"))
        if v is not None:
            pnls.append(v)
    return keys, pnls


def build() -> dict:
    cw = _clean_window()
    ka, pa_all = collect_a(None)
    kb, pb_all = collect_b(None)
    _, pa_cw = collect_a(cw)
    _, pb_cw = collect_b(cw)
    overlap = ka & kb
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "cleanWindowStart": cw,
        "verdict": (
            "두 원장은 서로 다른 모집단이다. A=서빙 추천 전체(limit 50, 필터 없음), "
            "B=상위 5개 페이퍼 매매(_reject_reason + 심볼 중복제거). "
            "같은 줄에 놓고 비교하면 안 된다."
        ),
        "ledgerA": {
            "name": "추천 원장 (virtual_prediction_ledger)",
            "captures": "_recommendations_payload(limit=50) — 서빙 경로 그대로, 필터 없음",
            "question": "앱이 보여준 추천 목록 전체에 엣지가 있나",
            "consumers": ["update_win_rates.py -> strategy_win_rates.json (화면 netWinRate)",
                          "factor_attribution.py", "update_strategy_sleeve_nav.py"],
            "uniquePredictions": len(ka),
            "allTime": _stats(pa_all),
            "cleanWindow": _stats(pa_cw),
        },
        "ledgerB": {
            "name": "VTJ 페이퍼 저널 (virtual_trade_journal)",
            "captures": "추천 리포트 CSV -> _reject_reason -> _unique_by_symbol[:5] (조합당 최대 5)",
            "question": "상위 5개만 골라 담았다면 어땠나",
            "consumers": ["build_live_calibration.py", "calibration_gate_shadow.py",
                          "factor_attribution.py", "analyze_live_axes.py"],
            "uniquePredictions": len(kb),
            "allTime": _stats(pb_all),
            "cleanWindow": _stats(pb_cw),
        },
        "overlap": {
            "sharedPredictions": len(overlap),
            "onlyA": len(ka - kb),
            "onlyB": len(kb - ka),
            "note": ("교집합이 작은 것은 버그가 아니다 — B는 조합당 상위 5개만 "
                     "심볼 중복 없이 고르고, A는 최대 50개를 그대로 담는다."),
        },
        # 어느 쪽을 엣지 판정의 분모로 쓸지에 대한 권고.
        "recommendation": {
            "edgeVerdictDenominator": "ledgerB",
            "reason": (
                "엣지 판정의 목적은 '사용자가 이 앱을 따라 샀을 때의 기댓값'이다. "
                "아무도 50종목을 사지 않으므로 상위 N 부분집합(B)이 그 질문에 맞다. "
                "실측상 B는 A보다 승률이 높은데(19.8% vs 15.1%) 평균손익은 더 나쁘다"
                "(-5.638% vs -5.018%) — 상위 필터가 적중률만 올리고 기댓값은 못 올린다. "
                "따라서 'B가 부분집합이니 더 좋을 것'이라는 가정으로 읽으면 안 된다."
            ),
            "displayDenominator": "ledgerA",
            "displayReason": (
                "화면의 승률은 사용자가 보는 카드 전체를 설명해야 하므로 A가 맞다. "
                "A로 재고 B로 판정하는 이 비대칭을 문서화하지 않으면 다시 헷갈린다."
            ),
        },
    }


def main() -> int:
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== 두 원장 대조 ===")
    print(f"  clean window: {data['cleanWindowStart']}\n")
    for key in ("ledgerA", "ledgerB"):
        d = data[key]
        print(f"  [{key}] {d['name']}")
        print(f"    질문: {d['question']}")
        print(f"    고유 예측 {d['uniquePredictions']}건")
        for scope in ("allTime", "cleanWindow"):
            s = d[scope]
            if s["trades"]:
                print(f"    {scope:<11} n={s['trades']:<5} 승률 {s['winRate'] * 100:5.1f}%  "
                      f"평균 {s['avgPnlPct']:+.3f}%")
            else:
                print(f"    {scope:<11} n=0")
        print()
    o = data["overlap"]
    print(f"  교집합 {o['sharedPredictions']} / A만 {o['onlyA']} / B만 {o['onlyB']}")
    print(f"  {o['note']}\n")
    r = data["recommendation"]
    print(f"  엣지 판정 분모 = {r['edgeVerdictDenominator']}")
    print(f"  화면 표시 분모 = {r['displayDenominator']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
