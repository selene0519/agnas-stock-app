"""backtest_pre_rise_score.py의 KR 버전. US와 같은 방법, KR 유니버스로 검증."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_kr_recommendations import indicators, pre_rise_score, _load_ohlcv_all  # noqa: E402
from scripts.backtest_pre_rise_score import _forward_return, _quantile_bucket, FORWARD_DAYS  # noqa: E402

OHLCV_ALL = _load_ohlcv_all()


def _slice_rows(rows: list[dict], cutoff: str) -> list[dict]:
    return [r for r in rows if str(r.get("date") or "")[:10] <= cutoff]


def _cutoff_dates() -> list[str]:
    all_dates = sorted({str(r.get("date") or "")[:10] for rows in OHLCV_ALL.values() for r in rows})
    if len(all_dates) < 100:
        return []
    usable = all_dates[60:-30]
    return usable[::5]


def main() -> None:
    cutoffs = _cutoff_dates()
    samples: list[dict[str, Any]] = []

    for cutoff in cutoffs:
        for sym, rows in OHLCV_ALL.items():
            if sym in {"KOSPI", "KOSDAQ"}:
                continue
            past = _slice_rows(rows, cutoff)
            if len(past) < 60:
                continue
            ind = indicators(past)
            current = ind.get("latest")
            if not current or current <= 0:
                continue
            fwd = _forward_return(rows, cutoff, FORWARD_DAYS)
            if fwd is None:
                continue
            pr = pre_rise_score(ind)
            samples.append({
                "symbol": sym, "forwardReturnPct": round(fwd, 3),
                "totalScore": pr["totalScore"],
                "accumulationScore": pr["accumulationScore"],
                "convergenceScore": pr["convergenceScore"],
                "pullbackScore": pr["pullbackScore"],
            })

    def _bucket_stats(key: str) -> dict[str, Any]:
        vals = sorted(s[key] for s in samples)
        n = len(vals)
        q1, q2 = vals[n // 3], vals[2 * n // 3]
        buckets: dict[str, list[float]] = {"low": [], "mid": [], "high": []}
        for s in samples:
            buckets[_quantile_bucket(s[key], q1, q2)].append(s["forwardReturnPct"])
        return {b: {"n": len(r), "avgForwardReturnPct": round(sum(r) / len(r), 3) if r else None} for b, r in buckets.items()}

    def _spearman(key: str) -> float | None:
        xs = [s[key] for s in samples]
        ys = [s["forwardReturnPct"] for s in samples]
        n = len(xs)
        if n < 10:
            return None

        def _rank(vals):
            order = sorted(range(len(vals)), key=lambda i: vals[i])
            ranks = [0.0] * len(vals)
            for r, i in enumerate(order):
                ranks[i] = r
            return ranks

        rx, ry = _rank(xs), _rank(ys)
        mx, my = sum(rx) / n, sum(ry) / n
        cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
        vx = sum((x - mx) ** 2 for x in rx)
        vy = sum((y - my) ** 2 for y in ry)
        return round(cov / (vx * vy) ** 0.5, 4) if vx > 0 and vy > 0 else None

    out = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "cutoffDates": len(cutoffs), "forwardDays": FORWARD_DAYS, "sampleCount": len(samples),
        "factors": {
            key: {"spearmanRankCorrelation": _spearman(key), "byTercile": _bucket_stats(key)}
            for key in ("totalScore", "accumulationScore", "convergenceScore", "pullbackScore")
        },
    }
    path = ROOT / "reports" / "pre_rise_score_validation_kr.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
