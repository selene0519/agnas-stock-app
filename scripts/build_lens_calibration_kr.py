#!/usr/bin/env python3
"""
Regime lens self-calibration (KR) — Step 3 of the self-calibrating loop.

렌즈 저널(reports/lens_journal_kr.csv, Step 2)의 '실측값'을 recency 가중으로 읽어
(setup x regime)별 엣지를 재평가하고, 엣지가 살아있는 조합만 발동하도록 게이트한다.
= "AI 매매일지 값으로 자가보정".

- recency 가중: weight = 0.5 ** (age_days / HALFLIFE_DAYS). 최근 실측이 더 크게 반영 →
  어떤 셋업이 특정 레짐에서 최근 무너지면 자동으로 SUPPRESSED 로 전환된다(적응).
- 게이트: 유효표본(effN) >= MIN_EFF 이고 가중 net평균 >= MIN_EDGE 이면 ACTIVE.
  그 외 SUPPRESSED_LOW_EDGE / LOW_SAMPLE.
- sizeMultiplier: 엣지 세기에 비례(레퍼런스=BEAR 저점반등 +0.62%). 강할수록 크게(프레스),
  약하면 작게. 실측이 사이즈를 정한다.

읽기전용 입력: reports/lens_journal_kr.csv
출력: reports/lens_calibration_kr.json  (Step 1 스크리너가 읽어 게이트/사이즈에 사용)
"""
from __future__ import annotations
import csv
import json
import os
from collections import defaultdict
from datetime import date, datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HALFLIFE_DAYS = 180.0
MIN_EFF = 25.0        # 유효(가중) 표본 하한
MIN_EDGE = 0.05       # net 평균 %/거래 하한 (비용 후 (+)여야 발동)
REF_EDGE = 0.62       # 사이즈 배율 레퍼런스(BEAR 저점반등 실측)
REGIMES = ["BULL", "SIDE", "BEAR"]


def parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def main() -> int:
    jpath = os.path.join(REPO, "reports", "lens_journal_kr.csv")
    if not os.path.exists(jpath):
        print("lens_journal_kr.csv 없음 — 먼저 build_lens_journal_kr.py 실행", flush=True)
        return 1
    rows = list(csv.DictReader(open(jpath, encoding="utf-8-sig")))
    if not rows:
        print("빈 저널", flush=True)
        return 1

    as_of = max(parse_date(r["signalDate"]) for r in rows)

    # (setup, regime) -> 가중 통계 누적
    agg = defaultdict(lambda: {"w": 0.0, "wnet": 0.0, "wwin": 0.0, "gp": 0.0, "gl": 0.0, "n": 0})
    for r in rows:
        net = float(r["netPnlPct"])
        age = (as_of - parse_date(r["signalDate"])).days
        wt = 0.5 ** (age / HALFLIFE_DAYS)
        a = agg[(r["setup"], r["regime"])]
        a["w"] += wt
        a["wnet"] += wt * net
        a["wwin"] += wt * (1 if net > 0 else 0)
        if net > 0:
            a["gp"] += wt * net
        else:
            a["gl"] += wt * (-net)
        a["n"] += 1

    calib = {}
    for (setup, regime), a in agg.items():
        w = a["w"]
        if w <= 0:
            continue
        net_avg = a["wnet"] / w
        win_rate = a["wwin"] / w * 100
        pf = (a["gp"] / a["gl"]) if a["gl"] > 0 else 9.99
        if w < MIN_EFF:
            gate = "LOW_SAMPLE"
        elif net_avg >= MIN_EDGE:
            gate = "ACTIVE"
        else:
            gate = "SUPPRESSED_LOW_EDGE"
        size_mult = 0.0
        if gate == "ACTIVE":
            size_mult = max(0.3, min(1.5, net_avg / REF_EDGE))
        calib[f"{setup}|{regime}"] = {
            "setup": setup,
            "regime": regime,
            "rawSamples": a["n"],
            "effectiveSamples": round(w, 1),
            "recencyWeightedWinRate": round(win_rate, 1),
            "recencyWeightedNetAvgPct": round(net_avg, 3),
            "profitFactor": round(pf, 2),
            "gate": gate,
            "sizeMultiplier": round(size_mult, 2),
        }

    # 레짐별 라우팅: ACTIVE 셋업을 net평균 내림차순
    routing = {}
    for regime in REGIMES:
        active = [v for k, v in calib.items() if v["regime"] == regime and v["gate"] == "ACTIVE"]
        active.sort(key=lambda v: -v["recencyWeightedNetAvgPct"])
        routing[regime] = [v["setup"] for v in active]

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "asOfDate": as_of.isoformat(),
        "source": "reports/lens_journal_kr.csv",
        "policy": {
            "halflifeDays": HALFLIFE_DAYS,
            "minEffectiveSamples": MIN_EFF,
            "minEdgePct": MIN_EDGE,
            "refEdgePct": REF_EDGE,
        },
        "note": "AI 매매일지(렌즈 저널) 실측값 기반 자가보정. recency 가중 → 최근 실측이 게이트/사이즈를 결정. "
        "생존편향 미보정이라 라이브 VTJ 정산으로 갱신 시 더 정직해짐.",
        "activeSetupByRegime": routing,
        "calibration": calib,
    }
    out = os.path.join(REPO, "reports", "lens_calibration_kr.json")
    json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print(f"asOf={as_of}  -> {os.path.relpath(out, REPO)}")
    print(f"\n레짐별 활성 셋업(자가보정 결과): {json.dumps(routing, ensure_ascii=False)}")
    print(f"\n{'setup|regime':22s}{'effN':>7s}{'win%':>7s}{'netAvg':>8s}{'PF':>6s}{'gate':>20s}{'size':>6s}")
    for k in sorted(calib):
        v = calib[k]
        print(
            f"{k:22s}{v['effectiveSamples']:7.0f}{v['recencyWeightedWinRate']:6.1f}%"
            f"{v['recencyWeightedNetAvgPct']:+7.2f}%{v['profitFactor']:6.2f}{v['gate']:>20s}{v['sizeMultiplier']:6.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
