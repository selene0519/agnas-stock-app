#!/usr/bin/env python3
"""시장 x 전략 x 기간별로 손절/목표 밴드를 탐색한다 — **홀드아웃 검증 포함**.

목표: "손실은 적고 수익은 큰" 밴드를 찾되, **같은 데이터로 고르고 같은
데이터로 자랑하지 않는다.** 추천 시점을 날짜순으로 갈라 앞쪽(train)에서만
고르고 뒤쪽(test)에서 확인한다. test가 train을 확인하지 못하면 그 값은
쓰면 안 된다 — 과적합이라는 뜻이다.

고정하는 것 / 바꾸는 것:
  고정  종목 선택, 진입가, 추천일, 진입 창(앱 정의 short2/swing3/mid4)
  변경  손절폭, 목표폭
따라서 **선택 스킬은 그대로 두고 청산 설계만** 비교한다.

비용: 왕복 기준을 쓴다(매수+매도). 원장 A의 0.09%는 "편도"를 왕복에 한 번만
뺀 값이라 낙관적이다 — 여기서는 그 실수를 재현하지 않는다.

청산: 선착순. 같은 날 목표·손절 동시 도달은 보수적으로 손절.
      (`settle_pending_validations._settle_from_ohlcv` 재사용)

실행: python scripts/optimize_exit_bands.py [--min-trades 20]
쓰기: reports/exit_band_optimization.json
"""
from __future__ import annotations

import argparse
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
from settle_pending_validations import (  # noqa: E402
    OHLCV_DIR, _num, _read_csv, _settle_from_ohlcv, _sym_norm, _window_cutoff,
)

LEDGER = ROOT / "reports" / "virtual_validation_results.csv"
OUT = ROOT / "reports" / "exit_band_optimization.json"

# 왕복 비용(%). 원장 B의 구조를 따른다: 매수 슬리피지 + 매도 슬리피지 + 세금·수수료.
ROUND_TRIP_COST = {"kr": 0.41, "us": 0.30}
ENTRY_WINDOW_BARS = {"short": 2, "swing": 3, "mid": 4}

STOPS = [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0]
TARGETS = [3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0]

TRAIN_SHARE = 0.6          # 앞 60%로 고르고 뒤 40%로 확인


def _load_trades() -> list[dict]:
    bars_cache: dict[tuple, list] = {}
    out = []
    with LEDGER.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            market = str(r.get("market") or "").lower()
            symbol = str(r.get("symbol") or "").strip()
            mode = str(r.get("mode") or "").lower()
            horizon = str(r.get("horizon") or "swing").lower()
            created = str(r.get("createdAt") or "")[:10]
            due = str(r.get("validationDueDate") or "")[:10]
            entry = _num(r.get("entryPrice"))
            if not (market and symbol and created and due and entry and mode):
                continue
            key = (market, symbol)
            if key not in bars_cache:
                bars_cache[key] = _read_csv(
                    OHLCV_DIR / f"{market}_{_sym_norm(symbol, market)}_daily.csv")
            if not bars_cache[key]:
                continue
            out.append({"market": market, "symbol": symbol, "mode": mode,
                        "horizon": horizon, "created": created,
                        "cutoff": _window_cutoff(horizon, due), "entry": entry,
                        "bars": bars_cache[key]})
    return out


def _sim(t: dict, stop_pct: float, target_pct: float) -> float | None:
    entry = t["entry"]
    res = _settle_from_ohlcv(
        t["market"], t["symbol"], entry,
        entry * (1 - stop_pct / 100), entry * (1 + target_pct / 100),
        t["created"], t["cutoff"],
        entry_window_bars=ENTRY_WINDOW_BARS.get(t["horizon"], 3),
    )
    if not res or res.get("returnPct") is None:
        return None
    # `_settle_from_ohlcv`가 편도 비용을 이미 뺐다. 왕복이 되도록 차액을 더 뺀다.
    from settle_pending_validations import COST_PCT
    already = COST_PCT.get(t["market"], COST_PCT["kr"])
    extra = max(0.0, ROUND_TRIP_COST.get(t["market"], 0.41) - already)
    return float(res["returnPct"]) - extra


def _stats(v: list[float]) -> dict:
    if not v:
        return {"n": 0}
    wins = [x for x in v if x > 0]
    losses = [x for x in v if x <= 0]
    aw = statistics.fmean(wins) if wins else 0.0
    al = statistics.fmean(losses) if losses else 0.0
    return {
        "n": len(v),
        "meanPct": round(statistics.fmean(v), 3),
        "winRatePct": round(len(wins) / len(v) * 100, 1),
        "avgWinPct": round(aw, 2),
        "avgLossPct": round(al, 2),
        "payoff": round(aw / abs(al), 2) if al else None,
    }


def run(min_trades: int) -> dict:
    trades = _load_trades()
    cells: dict[tuple, list] = {}
    for t in trades:
        cells.setdefault((t["market"], t["mode"], t["horizon"]), []).append(t)

    results = []
    for (market, mode, horizon), group in sorted(cells.items()):
        group.sort(key=lambda x: x["created"])
        split = int(len(group) * TRAIN_SHARE)
        train, test = group[:split], group[split:]
        if len(train) < min_trades or len(test) < max(5, min_trades // 2):
            results.append({"market": market, "mode": mode, "horizon": horizon,
                            "status": "SAMPLE_TOO_SMALL",
                            "trainN": len(train), "testN": len(test)})
            continue

        grid = []
        for sp in STOPS:
            for tp in TARGETS:
                tr = [v for v in (_sim(t, sp, tp) for t in train) if v is not None]
                if len(tr) < min_trades:
                    continue
                grid.append({"stopPct": -sp, "targetPct": tp, "train": _stats(tr)})
        if not grid:
            results.append({"market": market, "mode": mode, "horizon": horizon,
                            "status": "NO_VALID_GRID"})
            continue

        best = max(grid, key=lambda g: g["train"]["meanPct"])
        sp, tp = -best["stopPct"], best["targetPct"]
        te = [v for v in (_sim(t, sp, tp) for t in test) if v is not None]
        best["test"] = _stats(te)

        # 현재 밴드(원장에 기록된 실제 폭)의 같은 기간 성적 — 비교 기준.
        cur = []
        for t in test:
            r = _settle_from_ohlcv(t["market"], t["symbol"], t["entry"],
                                   None, None, t["created"], t["cutoff"],
                                   entry_window_bars=ENTRY_WINDOW_BARS.get(t["horizon"], 3))
            if r and r.get("returnPct") is not None:
                cur.append(float(r["returnPct"]))
        results.append({
            "market": market, "mode": mode, "horizon": horizon, "status": "OK",
            "trainN": len(train), "testN": len(test),
            "bestOnTrain": {"stopPct": best["stopPct"], "targetPct": best["targetPct"]},
            "trainStats": best["train"], "testStats": best["test"],
            "noBandBaselineTest": _stats(cur),
            # train에서 좋았던 게 test에서도 (+)인가 = 과적합 아닌가
            "confirmedOutOfSample": bool(best["test"].get("n") and
                                         best["test"]["meanPct"] > 0),
        })

    ok = [r for r in results if r.get("status") == "OK"]
    confirmed = [r for r in ok if r["confirmedOutOfSample"]]
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "method": ("추천 시점 날짜순 60/40 분할. train에서 평균손익 최대인 밴드를 고르고 "
                   "test에서 확인. 종목선택·진입가·진입창은 고정, 손절/목표만 변경."),
        "roundTripCostPct": ROUND_TRIP_COST,
        "entryWindowBars": ENTRY_WINDOW_BARS,
        "gridStops": [-s for s in STOPS], "gridTargets": TARGETS,
        "minTrades": min_trades,
        "cells": results,
        "cellsEvaluated": len(ok),
        "cellsConfirmedOutOfSample": len(confirmed),
        "caveat": ("표본 구간이 KOSPI -24%인 한 국면뿐이다. test가 확인해도 "
                   "그건 '같은 하락 국면 안에서 유지됐다'는 뜻이지 상승장에서 "
                   "통한다는 뜻이 아니다."),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-trades", type=int, default=20)
    args = ap.parse_args()
    d = run(args.min_trades)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== 밴드 탐색 (60/40 홀드아웃) ===")
    print(f"왕복비용 {d['roundTripCostPct']}  ·  진입창 {d['entryWindowBars']}\n")
    print(f"{'시장':<4}{'전략':<13}{'기간':<7}{'train':>6}{'test':>6}"
          f"{'손절%':>7}{'목표%':>7}{'train평균':>10}{'test평균':>10}{'test승률':>9}{'페이오프':>9}  확인")
    for r in d["cells"]:
        if r.get("status") != "OK":
            print(f"{r['market']:<4}{r['mode']:<13}{r['horizon']:<7}  {r.get('status')}")
            continue
        b, tr, te = r["bestOnTrain"], r["trainStats"], r["testStats"]
        mark = "✓" if r["confirmedOutOfSample"] else "✗ 과적합"
        print(f"{r['market']:<4}{r['mode']:<13}{r['horizon']:<7}{r['trainN']:>6}{r['testN']:>6}"
              f"{b['stopPct']:>7.0f}{b['targetPct']:>7.0f}{tr['meanPct']:>10.2f}"
              f"{te.get('meanPct', 0):>10.2f}{te.get('winRatePct', 0):>9.1f}"
              f"{str(te.get('payoff')):>9}  {mark}")
    print(f"\n셀 {d['cellsEvaluated']}개 중 홀드아웃 확인 {d['cellsConfirmedOutOfSample']}개")
    print(d["caveat"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
