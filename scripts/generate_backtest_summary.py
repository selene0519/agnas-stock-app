"""data/backtest/walk_forward_results.csv → reports/backtest_summary.json"""
import csv
import json
import math
from pathlib import Path
from collections import defaultdict
from datetime import datetime

REPO_ROOT = Path(__file__).parents[1]

def main():
    result_path = REPO_ROOT / "data" / "backtest" / "walk_forward_results.csv"
    if not result_path.exists():
        print("백테스트 결과 없음")
        return

    rows = []
    with open(result_path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("result") in ("win", "loss", "hold_loss"):
                rows.append(r)

    if not rows:
        print("유효한 결과 없음")
        return

    by_horizon = defaultdict(list)
    for r in rows:
        by_horizon[r["horizon"]].append(r)

    summary = {
        "generatedAt": datetime.now().isoformat(),
        "horizons": {},
        "overall": {},
    }

    horizon_days_map = {"short": 5, "swing": 10, "mid": 20}

    for horizon, hrs in by_horizon.items():
        wins = [r for r in hrs if r["result"] == "win"]
        rets = [float(r.get("netReturnPct", 0)) for r in hrs]
        n = len(hrs)
        avg_r = sum(rets) / n if n else 0
        std_r = math.sqrt(sum((r - avg_r) ** 2 for r in rets) / (n - 1)) if n > 1 else 0
        days = horizon_days_map.get(horizon, 10)
        sharpe = (avg_r / std_r * math.sqrt(252 / days)) if std_r > 0 else 0

        summary["horizons"][horizon] = {
            "n": n,
            "winRate": round(len(wins) / n * 100, 1) if n else 0,
            "avgNetReturn": round(avg_r, 3),
            "sharpe": round(sharpe, 2),
            "maxDrawdown": round(min(rets), 3) if rets else 0,
            "costApplied": "0.09% (수수료+슬리피지)",
        }

    all_rets = [float(r.get("netReturnPct", 0)) for r in rows]
    all_wins = [r for r in rows if r["result"] == "win"]
    summary["overall"] = {
        "n": len(rows),
        "winRate": round(len(all_wins) / len(rows) * 100, 1) if rows else 0,
        "avgNetReturn": round(sum(all_rets) / len(all_rets), 3) if all_rets else 0,
        "dateRange": f"{min(r['test_date'] for r in rows)} ~ {max(r['test_date'] for r in rows)}" if rows else "",
    }

    out = REPO_ROOT / "reports" / "backtest_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {out}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
