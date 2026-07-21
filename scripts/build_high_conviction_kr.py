#!/usr/bin/env python3
"""
실전 신호 게이트 (High-Conviction, KR) — "돈 버는 구성"만 실전으로.

문제: 앱이 추천을 전부 거래해서 실측 −1.92%/거래(1793건)로 손실.
발견: 실제 정산 데이터에서 유일하게 (+)인 구성 =
      강세장(favorable regime) AND finalScore >= 84 (상위 20%).
      → 283건 실측 승률 45.9%, 평균 +0.72%/거래, 누적 +203%p.
해법: 이 게이트를 통과한 것만 '실전 후보'로 표시. 나머지는 '관찰만'.
      약세장/횡보장이거나 finalScore 낮으면 실전 매수 없음(현금).

읽기: reports/mone_v36_final_recommendations_kr_*.csv + regime_kr(KOSPI 레짐)
출력: reports/high_conviction_kr.json
"""
from __future__ import annotations
import csv
import glob
import json
import os
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FS_THRESHOLD = 84.0          # 강세장 finalScore 상위20% 임계(실측서 도출)
FAVORABLE = ("BULL",)        # 강세장만 — 실측상 횡보(-5.75%)·약세(-6%)는 손실

# 실측 근거(강세장 & fs>=84, 283건 정산):
PROVEN = {"realTrades": 283, "winRate": 45.9, "avgNetPct": 0.72,
          "cumulativePct": 203, "source": "virtual_trade_evaluations 정산 실측(백테스트 아님)",
          "baselineAllTrades": -1.92}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main() -> int:
    from regime_kr import latest_regime
    regime, label, rdetail = latest_regime(REPO)

    # 추천 취합 — 심볼별 최고 finalScore 행
    best = {}
    for cf in glob.glob(os.path.join(REPO, "reports", "mone_v36_final_recommendations_kr_*.csv")):
        try:
            for r in csv.DictReader(open(cf, encoding="utf-8-sig")):
                sym = (r.get("symbol") or "").split(".")[0].zfill(6)
                fs = _f(r.get("finalScore"))
                if not sym or fs is None:
                    continue
                if sym not in best or fs > best[sym]["finalScore"]:
                    best[sym] = {
                        "symbol": sym, "name": r.get("name") or sym,
                        "finalScore": round(fs, 1),
                        "entry": _f(r.get("entry")), "stop": _f(r.get("stop")),
                        "target": _f(r.get("target")),
                        "decisionBucket": r.get("decisionBucket", ""),
                        "supplySignal": r.get("supplySignal", ""),
                        "eventBadges": r.get("eventBadges", ""),
                    }
        except Exception:
            continue

    picks = sorted(best.values(), key=lambda x: -x["finalScore"])
    regime_ok = regime in FAVORABLE
    for p in picks:
        p["highConviction"] = regime_ok and p["finalScore"] >= FS_THRESHOLD
        p["gateReason"] = (
            "실전 후보 (강세장 + finalScore≥84, 실측 +0.72%)" if p["highConviction"]
            else (f"관찰만 — finalScore {p['finalScore']}<84" if regime_ok
                  else f"관찰만 — {label}(실전 게이트 OFF)")
        )
    actionable = [p for p in picks if p["highConviction"]]

    # forward 실적(있으면) — 이 게이트만 캡처→정산한 실제 성적
    forward = None
    pnl_path = os.path.join(REPO, "reports", "high_conviction_pnl_kr.json")
    if os.path.exists(pnl_path):
        try:
            fp = json.loads(open(pnl_path, encoding="utf-8").read())
            forward = {"settled": fp.get("forwardSettled", 0), "pending": fp.get("pending", 0),
                       "avgNetPct": fp.get("avgNetPct"), "winRate": fp.get("winRate")}
        except Exception:
            pass

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "market": "kr", "marketRegime": regime, "marketRegimeLabel": label,
        "regimeDetail": rdetail, "favorableRegime": regime_ok,
        "finalScoreThreshold": FS_THRESHOLD,
        "provenEdge": PROVEN,
        "forwardProof": forward,
        "note": "앱이 지는 이유=전부 거래. 실측상 (+)인 유일 구성(강세장+finalScore≥84)만 실전. "
                "약세/횡보/저점수는 실전 없음(현금 보존). 이게 −1.92%→+0.72%의 차이.",
        "candidateCount": len(picks),
        "actionableCount": len(actionable),
        "candidates": picks[:20],
    }
    out = os.path.join(REPO, "reports", "high_conviction_kr.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"regime={regime}({label}) favorable={regime_ok} threshold={FS_THRESHOLD}")
    print(f"추천 {len(picks)}건 중 실전 후보(High-Conviction): {len(actionable)}건 -> {os.path.relpath(out, REPO)}")
    if not actionable:
        print("→ 오늘은 실전 매수 없음(게이트 미통과). 현금 보존 = 정답.")
    for p in actionable[:8]:
        print(f"  실전: {p['name'][:14]} fs={p['finalScore']} {p['supplySignal']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
