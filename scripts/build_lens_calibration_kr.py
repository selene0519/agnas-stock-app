#!/usr/bin/env python3
"""
Regime lens self-calibration (KR) — 라이브 실측 우선 + 백테스트 prior 베이지안 shrinkage.

두 소스를 (setup x regime)별로 결합해 자가보정한다:
  - LIVE  : reports/lens_live_journal_kr.csv (forward 캡처→정산된 실현손익, 생존편향 없음)
  - PRIOR : reports/lens_journal_kr.csv (2년 백테스트, 생존편향 있음 → prior로만)

blended = (W_live*avg_live + K*avg_prior) / (W_live + K).
  → 라이브 표본(W_live)이 쌓일수록 라이브가 지배(생존편향 제거). 라이브 0이면 prior와 동일.
둘 다 recency 지수감쇠(반감기 HALFLIFE_DAYS). 게이트/사이즈는 blended로 결정.

게이트: 유효표본(W_live + K) >= MIN_EFF 이고 blended net평균 >= MIN_EDGE → ACTIVE.
읽기: lens_live_journal_kr.csv(있으면), lens_journal_kr.csv
출력: reports/lens_calibration_kr.json  (screen_regime_lens_kr.py가 읽음)
"""
from __future__ import annotations
import csv
import json
import os
from collections import defaultdict
from datetime import date, datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HALFLIFE_DAYS = 180.0
MIN_EFF = 25.0
MIN_EDGE = 0.05
REF_EDGE = 0.62
PRIOR_STRENGTH = 40.0  # K: 백테스트 prior의 유효표본 무게(라이브가 이만큼 쌓이면 50:50)
REGIMES = ["BULL", "SIDE", "BEAR"]


def parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def weighted_agg(path: str):
    """(setup,regime) -> {w, wnet, wwin, gp, gl, n} recency 가중."""
    agg = defaultdict(lambda: {"w": 0.0, "wnet": 0.0, "wwin": 0.0, "gp": 0.0, "gl": 0.0, "n": 0})
    if not os.path.exists(path):
        return agg, None
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    if not rows:
        return agg, None
    as_of = max(parse_date(r["signalDate"]) for r in rows)
    for r in rows:
        try:
            net = float(r["netPnlPct"])
        except (TypeError, ValueError):
            continue
        wt = 0.5 ** ((as_of - parse_date(r["signalDate"])).days / HALFLIFE_DAYS)
        a = agg[(r["setup"], r["regime"])]
        a["w"] += wt; a["wnet"] += wt * net; a["wwin"] += wt * (1 if net > 0 else 0)
        if net > 0:
            a["gp"] += wt * net
        else:
            a["gl"] += wt * (-net)
        a["n"] += 1
    return agg, as_of


def stats(a):
    w = a["w"]
    if w <= 0:
        return None
    return {
        "netAvg": a["wnet"] / w,
        "winRate": a["wwin"] / w * 100,
        "pf": (a["gp"] / a["gl"]) if a["gl"] > 0 else 9.99,
        "w": w,
        "n": a["n"],
    }


def main() -> int:
    live_agg, live_asof = weighted_agg(os.path.join(REPO, "reports", "lens_live_journal_kr.csv"))
    prior_agg, prior_asof = weighted_agg(os.path.join(REPO, "reports", "lens_journal_kr.csv"))
    if prior_asof is None and live_asof is None:
        print("저널 없음 — 먼저 build_lens_journal_kr.py 실행")
        return 1

    empty = {"w": 0, "wnet": 0, "wwin": 0, "gp": 0, "gl": 0, "n": 0}
    keys = set(live_agg) | set(prior_agg)
    calib = {}
    for (setup, regime) in keys:
        live = stats(live_agg.get((setup, regime), empty))
        prior = stats(prior_agg.get((setup, regime), empty))
        w_live = live["w"] if live else 0.0
        prior_net = prior["netAvg"] if prior else 0.0
        prior_win = prior["winRate"] if prior else 0.0
        live_net = live["netAvg"] if live else 0.0
        live_win = live["winRate"] if live else 0.0
        # 베이지안 shrinkage
        denom = w_live + PRIOR_STRENGTH
        blended_net = (w_live * live_net + PRIOR_STRENGTH * prior_net) / denom
        blended_win = (w_live * live_win + PRIOR_STRENGTH * prior_win) / denom
        live_fraction = w_live / denom
        eff = denom

        if eff < MIN_EFF:
            gate = "LOW_SAMPLE"
        elif blended_net >= MIN_EDGE:
            gate = "ACTIVE"
        else:
            gate = "SUPPRESSED_LOW_EDGE"
        size_mult = max(0.3, min(1.5, blended_net / REF_EDGE)) if gate == "ACTIVE" else 0.0

        calib[f"{setup}|{regime}"] = {
            "setup": setup, "regime": regime,
            "blendedNetAvgPct": round(blended_net, 3),
            "blendedWinRate": round(blended_win, 1),
            "gate": gate,
            "sizeMultiplier": round(size_mult, 2),
            "liveEffectiveSamples": round(w_live, 1),
            "liveRawSamples": live["n"] if live else 0,
            "liveNetAvgPct": round(live_net, 3) if live else None,
            "priorNetAvgPct": round(prior_net, 3) if prior else None,
            "priorRawSamples": prior["n"] if prior else 0,
            "liveFraction": round(live_fraction, 3),
            "profitFactor": round((live["pf"] if live else (prior["pf"] if prior else 0)), 2),
        }

    routing = {}
    for regime in REGIMES:
        active = [v for v in calib.values() if v["regime"] == regime and v["gate"] == "ACTIVE"]
        active.sort(key=lambda v: -v["blendedNetAvgPct"])
        routing[regime] = [v["setup"] for v in active]

    total_live = sum(v["liveRawSamples"] for v in calib.values())
    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "asOfDate": (live_asof or prior_asof).isoformat(),
        "sources": {"live": "reports/lens_live_journal_kr.csv", "prior": "reports/lens_journal_kr.csv"},
        "policy": {"halflifeDays": HALFLIFE_DAYS, "minEffectiveSamples": MIN_EFF,
                   "minEdgePct": MIN_EDGE, "refEdgePct": REF_EDGE, "priorStrengthK": PRIOR_STRENGTH},
        "liveSamplesTotal": total_live,
        "note": "라이브 forward 실측 우선 + 백테스트 prior shrinkage. 라이브(lens_live_journal)가 쌓일수록 "
                "생존편향 제거되고 liveFraction↑. 현재 liveSamplesTotal이 0이면 사실상 백테스트 prior.",
        "activeSetupByRegime": routing,
        "calibration": calib,
    }
    out = os.path.join(REPO, "reports", "lens_calibration_kr.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"asOf={report['asOfDate']} liveSamples={total_live} -> {os.path.relpath(out, REPO)}")
    print(f"라우팅: {json.dumps(routing, ensure_ascii=False)}")
    print(f"\n{'setup|regime':22s}{'blendNet':>9s}{'gate':>20s}{'size':>6s}{'liveN':>7s}{'liveFrac':>9s}")
    for k in sorted(calib):
        v = calib[k]
        print(f"{k:22s}{v['blendedNetAvgPct']:+8.2f}%{v['gate']:>20s}{v['sizeMultiplier']:6.2f}{v['liveRawSamples']:7d}{v['liveFraction']:9.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
