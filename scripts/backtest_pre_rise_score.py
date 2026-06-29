"""
Pre-Rise Score(scripts/generate_kr_recommendations.py의 pre_rise_score())가 진짜 미래
수익률과 상관이 있는지 검증한다 — 8중 필터를 통과한 후보만 보는 게 아니라 전체 유니버스에
대해, "이 점수가 높을수록 앞으로 N일간 더 오르는가"를 직접 테스트하는 표준적인 팩터 검증.

중요: 이 스크립트는 가중치를 이 결과에 맞춰 다시 튜닝하지 않는다(과적합 방지). 가중치는
generate_kr_recommendations.py의 pre_rise_score()에 도메인 논리로 먼저 정해뒀고, 여기서는
그 점수가 신호로서 유효한지만 사후에 확인한다.

방법: 105개 historical cutoff(주 1회 간격) x 전체 US 유니버스에 대해
- cutoff까지의 OHLCV만으로 pre_rise_score 계산 (미래 데이터 누출 없음)
- cutoff 이후 10거래일 종가 기준 순수 forward return 계산
- score를 3분위로 나눠 분위별 평균 forward return 비교 + Spearman 순위상관

출력: reports/pre_rise_score_validation_us.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BACKEND_DIR = ROOT / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.generate_kr_recommendations import indicators, pre_rise_score  # noqa: E402
from scripts.generate_us_recommendations import _load_us_ohlcv, _load_us_sector_map  # noqa: E402
from scripts.backtest_band_calibration import _slice_rows, _cutoff_dates  # noqa: E402

OHLCV_ALL = _load_us_ohlcv()
SECTOR_MAP = _load_us_sector_map()
FORWARD_DAYS = 10


def _forward_return(rows: list[dict], cutoff: str, days: int) -> float | None:
    future = [r for r in rows if str(r.get("date") or "")[:10] > cutoff]
    if len(future) < days:
        return None
    base_rows = [r for r in rows if str(r.get("date") or "")[:10] <= cutoff]
    if not base_rows:
        return None
    base_close = float(base_rows[-1].get("close") or 0)
    target_close = float(future[days - 1].get("close") or 0)
    if base_close <= 0 or target_close <= 0:
        return None
    return (target_close - base_close) / base_close * 100


def _quantile_bucket(value: float, q1: float, q2: float) -> str:
    if value <= q1:
        return "low"
    if value >= q2:
        return "high"
    return "mid"


def main() -> None:
    cutoffs = _cutoff_dates()
    samples: list[dict[str, Any]] = []

    for cutoff in cutoffs:
        for sym, rows in OHLCV_ALL.items():
            if sym in {"SPY", "QQQ", "DIA"}:
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
                "symbol": sym, "cutoff": cutoff, "forwardReturnPct": round(fwd, 3),
                "totalScore": pr["totalScore"],
                "accumulationScore": pr["accumulationScore"],
                "convergenceScore": pr["convergenceScore"],
                "pullbackScore": pr["pullbackScore"],
                "sectorLeadScore": pr["sectorLeadScore"],
                "alreadyMovedPenalty": pr["alreadyMovedPenalty"],
            })

    if not samples:
        print("샘플 없음")
        return

    def _bucket_stats(key: str) -> dict[str, Any]:
        vals = sorted(s[key] for s in samples)
        n = len(vals)
        q1 = vals[n // 3]
        q2 = vals[2 * n // 3]
        buckets: dict[str, list[float]] = {"low": [], "mid": [], "high": []}
        for s in samples:
            b = _quantile_bucket(s[key], q1, q2)
            buckets[b].append(s["forwardReturnPct"])
        return {
            b: {"n": len(rets), "avgForwardReturnPct": round(sum(rets) / len(rets), 3) if rets else None}
            for b, rets in buckets.items()
        }

    def _spearman(key: str) -> float | None:
        xs = [s[key] for s in samples]
        ys = [s["forwardReturnPct"] for s in samples]
        n = len(xs)
        if n < 10:
            return None

        def _rank(vals: list[float]) -> list[float]:
            order = sorted(range(len(vals)), key=lambda i: vals[i])
            ranks = [0.0] * len(vals)
            for r, i in enumerate(order):
                ranks[i] = r
            return ranks

        rx, ry = _rank(xs), _rank(ys)
        mean_x, mean_y = sum(rx) / n, sum(ry) / n
        cov = sum((rx[i] - mean_x) * (ry[i] - mean_y) for i in range(n))
        var_x = sum((x - mean_x) ** 2 for x in rx)
        var_y = sum((y - mean_y) ** 2 for y in ry)
        if var_x <= 0 or var_y <= 0:
            return None
        return round(cov / (var_x * var_y) ** 0.5, 4)

    out = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "cutoffDates": len(cutoffs),
        "forwardDays": FORWARD_DAYS,
        "sampleCount": len(samples),
        "factors": {},
    }
    for key in ("totalScore", "accumulationScore", "convergenceScore", "pullbackScore",
                "sectorLeadScore", "alreadyMovedPenalty"):
        out["factors"][key] = {
            "spearmanRankCorrelation": _spearman(key),
            "byTercile": _bucket_stats(key),
        }

    path = ROOT / "reports" / "pre_rise_score_validation_us.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
