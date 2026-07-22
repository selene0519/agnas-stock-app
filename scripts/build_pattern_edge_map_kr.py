#!/usr/bin/env python3
"""Build reports/pattern_edge_map_kr.json: a rigorous per-pattern, per-regime
edge tier used by app.services.pattern_edge_map (and thus by serving).

Grading is deliberately conservative so that survivorship drift can never
masquerade as an edge:
  - Geometric patterns: from the train/OOS trade-simulation harness
    (reports/regime_pattern_execution_kr.json). PROVEN only if the pattern
    cleared the promotion gate (qualified); WEAK if OOS expectancy is positive
    but it did not qualify; NONE otherwise.
  - Engine/candlestick patterns: from run_walkforward forward returns, scored
    as EXCESS over the survivorship-biased regime baseline (the current listed
    universe drifts ~+2%/20d, so raw returns overstate everything). WEAK only
    if the excess clears +1.0 percentage point; NONE otherwise. No PROVEN tier
    for engine patterns because they lack a train/OOS trade simulation.

Requires FinanceDataReader-free inputs: the two committed harness reports plus
local OHLCV for the baseline. Run after the harnesses regenerate.
"""
from __future__ import annotations

import glob
import json
import os

import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OHLCV = os.path.join(REPO, "data", "market", "ohlcv")
GEO_REPORT = os.path.join(REPO, "reports", "regime_pattern_execution_kr.json")
ENGINE_REPORT = os.path.join(REPO, "reports", "pattern_walkforward_kr.json")
OUT = os.path.join(REPO, "reports", "pattern_edge_map_kr.json")

ENGINE_EXCESS_WEAK_PP = 1.0
MIN_GEO_N = 15
MIN_ENGINE_N = 100


def _load_close(path):
    d = pd.read_csv(path, encoding="utf-8-sig")
    d["dt"] = pd.to_datetime(d["date"], errors="coerce")
    d = d.dropna(subset=["dt"]).sort_values("dt")
    return d.set_index("dt")["close"].astype(float)


def _regime_baseline_20d():
    k = _load_close(os.path.join(OHLCV, "kr_KOSPI_daily.csv"))
    ma20 = k.rolling(20).mean()
    rising = ma20 > ma20.shift(5)
    reg = pd.Series("SIDE", index=k.index)
    reg[(k > ma20) & rising] = "BULL"
    reg[(k < ma20) & (~rising)] = "BEAR"
    frames = []
    for f in glob.glob(os.path.join(OHLCV, "kr_*_daily.csv")):
        if any(x in f for x in ("KOSPI", "KOSDAQ", "USDKRW")):
            continue
        c = _load_close(f)
        if len(c) < 300:
            continue
        f20 = (c.shift(-20) / c - 1) * 100
        frames.append(pd.DataFrame({"reg": reg.reindex(c.index), "f20": f20}).dropna())
    a = pd.concat(frames)
    return {r: float(a[a["reg"] == r]["f20"].mean()) for r in ("BULL", "SIDE", "BEAR")}


def main() -> int:
    base = _regime_baseline_20d()
    emap = {
        "version": "pattern-edge-map-v1", "market": "kr",
        "baseline20dPct": {k: round(v, 3) for k, v in base.items()},
        "method": "geometric=train/OOS trade-sim qualified; engine=excess over survivorship baseline",
        "patterns": {},
    }

    geo = json.load(open(GEO_REPORT, encoding="utf-8"))
    for regm, block in (geo.get("regimePatternSummary") or {}).items():
        for key, st in block.items():
            if ":CONFIRMED" in key:
                continue
            pat = key.replace(":BUY_ZONE", "")
            oos = st.get("outOfSample", {})
            n = oos.get("sampleCount") or 0
            ev = oos.get("avgNetReturn")
            if n < MIN_GEO_N:
                continue
            q = bool(st.get("qualified"))
            tier = "PROVEN" if q else ("WEAK" if (ev or 0) > 0 else "NONE")
            emap["patterns"].setdefault(pat, {})[regm] = {
                "source": "geo_tradesim", "tier": tier, "qualified": q,
                "oosN": n, "oosEvPct": round((ev or 0) * 100, 3),
            }

    try:
        eng = json.load(open(ENGINE_REPORT, encoding="utf-8"))
        for regm in ("BULL", "SIDE", "BEAR"):
            for pat, st in (eng.get("regimeSummary") or {}).get(regm, {}).items():
                n = st.get("sampleCount") or 0
                if n < MIN_ENGINE_N:
                    continue
                excess = (st.get("avgReturn") or 0) * 100 - base.get(regm, 0)
                tier = "WEAK" if excess > ENGINE_EXCESS_WEAK_PP else "NONE"
                emap["patterns"].setdefault(pat, {})[regm] = {
                    "source": "engine_excess", "tier": tier,
                    "excessPct": round(excess, 3), "n": n,
                }
    except Exception as exc:
        print(f"[edge-map] engine report skipped: {exc}")

    json.dump(emap, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    tiers: dict[str, int] = {}
    for regs in emap["patterns"].values():
        for v in regs.values():
            tiers[v["tier"]] = tiers.get(v["tier"], 0) + 1
    print(f"[edge-map] {len(emap['patterns'])} patterns -> {OUT}")
    print(f"[edge-map] tier counts: {tiers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
