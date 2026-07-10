"""
build_live_calibration.py — 라이브 VTJ 실측으로 '통합' 롤링 보정 JSON 생성.

score×regime 신호는 combo(mode×horizon)를 가로질러 공통이고, per-combo로 쪼개면
반감기 30일 하에서 effN<2로 붕괴한다(검증됨). 그래서 shadow에서 통과한 방식대로
**전 combo 통합 풀** 단일 테이블을 만든다:
  - virtual_trade_evaluations.csv × virtual_trade_journal.csv 조인 (정산된 거래)
  - live_calibrator.build_live_calibration (recency 감쇠 + prior shrinkage)
  - prior global = 백테스트 9개 combo global 평균(~47%, 온전한 앵커)
  - reports/live_calibration_kr.json 저장

일일 정산(mone-settle-validations) 후 실행하면 게이트가 신선한 실측 승률을 사용.
실행: python scripts/build_live_calibration.py [--market kr]
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mone-web-app" / "backend"))
from app.engine.live_calibrator import build_live_calibration, save_live_calibration  # noqa: E402


def _load(p: Path) -> list[dict]:
    for e in ("utf-8-sig", "cp949", "utf-8"):
        try:
            with open(p, encoding=e, newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            continue
    return []


def _ff(x):
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None


def _backtest_prior_global(market: str) -> float:
    """백테스트 9 combo global 승률 평균을 shrinkage prior 앵커로 사용."""
    wrs = []
    for mode in ("conservative", "balanced", "aggressive"):
        for horizon in ("short", "swing", "mid"):
            p = ROOT / "reports" / f"ensemble_calibration_{market}_{mode}_{horizon}.json"
            if p.exists():
                try:
                    w = json.load(open(p, encoding="utf-8")).get("global", {}).get("winRate")
                    if w is not None:
                        wrs.append(float(w))
                except Exception:
                    pass
    return round(sum(wrs) / len(wrs), 1) if wrs else 45.0


def run(market: str = "kr") -> dict:
    ev = _load(ROOT / "data" / "virtual_trade_evaluations.csv")
    jr = {r["journal_id"]: r for r in _load(ROOT / "data" / "virtual_trade_journal.csv")}
    recs = []
    for r in ev:
        net = _ff(r.get("net_pnl_pct"))
        if net is None:
            continue
        j = jr.get(r.get("journal_id"))
        if not j or (j.get("market") or "kr").lower() != market:
            continue
        fs = _ff(j.get("final_rank_score"))
        d = (j.get("as_of_date") or j.get("generated_at") or "")[:10]
        if fs is None or not d:
            continue
        recs.append({"finalScore": fs, "regime": j.get("market_regime_at_signal", ""), "netPnlPct": net, "date": d})

    prior_wr = _backtest_prior_global(market)
    cal = build_live_calibration(
        recs, as_of=date.today(),
        prior_table={"table": {}, "global": {"winRate": prior_wr}},
    )
    # 통합 단일 테이블: reports/live_calibration_{market}.json
    cal = {**cal, "market": market, "source": "live_vtj_rolling_pooled", "priorGlobal": prior_wr}
    path = ROOT / "reports" / f"live_calibration_{market}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, indent=2)
    return {
        "status": "OK", "market": market, "records": len(recs), "priorGlobal": prior_wr,
        "globalWinRate": cal["global"]["winRate"], "buckets": len(cal["table"]),
        "savedTo": path.name, "table": cal["table"],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="kr")
    args = ap.parse_args()
    res = run(args.market)
    print(f"records={res['records']}  priorGlobal={res['priorGlobal']}%  globalWR(recency)={res['globalWinRate']}%  buckets={res['buckets']}  → {res['savedTo']}\n")
    for k, v in sorted(res["table"].items()):
        print(f"  {k:14s} winRate(shrunk)={v['winRate']:5.1f}  raw={v['rawWinRate']:5.1f}  effN={v['effN']:5.1f}  prior={v['priorWinRate']:5.1f}")
    print(f"\n{res['status']}")
