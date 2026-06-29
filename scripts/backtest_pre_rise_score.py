"""
setup_score()(scripts/generate_kr_recommendations.py)가 진짜 미래 수익률과 상관이
있는지 검증한다 — 8중 필터를 통과한 후보만 보는 게 아니라 전체 유니버스에 대해,
"이 점수가 높을수록 앞으로 더 오르는가"를 직접 테스트하는 표준적인 팩터 검증.

중요: 이 스크립트는 가중치를 이 결과에 맞춰 다시 튜닝하지 않는다(과적합 방지). 가중치는
generate_kr_recommendations.py의 setup_score()에 도메인 논리로 먼저 정해뒀고, 여기서는
그 점수가 신호로서 유효한지만 사후에 확인한다.

2026-06-29 갱신: 전체 점수 하나의 Spearman만 보면 정보가 너무 압축된다는 피드백을 반영해
(1) 버킷별로 따로 보고 (2) 10일 하나가 아니라 3/5/10/20일을 같이 본다 — 셋업류 신호는
모멘텀류보다 더 늦게(예: 5~20일 구간에서) 효과가 나타날 수 있어서다.

방법: cutoff(5거래일 간격) x 전체 US 유니버스에 대해
- cutoff까지의 OHLCV만으로 setup_score 계산 (미래 데이터 누출 없음)
- cutoff 이후 3/5/10/20거래일 종가 기준 forward return + 구간 내 최대 역행(MAE) 계산
- 버킷별·기간별 평균 수익률·승률 + 전체 점수 기준 Spearman 순위상관(10일 기준, 비교용)

출력: docs/validation/pre_rise_score_validation_us.json
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

from scripts.generate_kr_recommendations import indicators, setup_score, recommendation_bucket  # noqa: E402
from scripts.generate_us_recommendations import _load_us_ohlcv, _load_us_sector_map  # noqa: E402
from scripts.backtest_band_calibration import _slice_rows, _cutoff_dates  # noqa: E402

OHLCV_ALL = _load_us_ohlcv()
SECTOR_MAP = _load_us_sector_map()
HORIZONS = (3, 5, 10, 20)
SPEARMAN_HORIZON = 10  # 기존 단일 지표와의 비교용


def _future_closes(rows: list[dict], cutoff: str) -> list[float]:
    future = [r for r in rows if str(r.get("date") or "")[:10] > cutoff]
    return [float(r.get("close") or 0) for r in future if r.get("close")]


def _multi_horizon_stats(base_close: float, future_closes: list[float]) -> dict[int, dict[str, float | None]]:
    out: dict[int, dict[str, float | None]] = {}
    for h in HORIZONS:
        if len(future_closes) < h or base_close <= 0:
            out[h] = {"return": None, "mae": None}
            continue
        window = future_closes[:h]
        end_close = window[-1]
        ret = (end_close - base_close) / base_close * 100
        worst = min(window)
        mae = (worst - base_close) / base_close * 100  # 음수일수록 더 깊은 역행
        out[h] = {"return": round(ret, 3), "mae": round(mae, 3)}
    return out


def _spearman(samples: list[dict], key: str, target: str) -> float | None:
    xs = [s[key] for s in samples if s.get(target) is not None]
    ys = [s[target] for s in samples if s.get(target) is not None]
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
            future_closes = _future_closes(rows, cutoff)
            if len(future_closes) < min(HORIZONS):
                continue
            base_close = past[-1].get("close")
            base_close = float(base_close) if base_close else current
            mh = _multi_horizon_stats(base_close, future_closes)
            if mh[SPEARMAN_HORIZON]["return"] is None:
                continue

            sc = setup_score(ind)
            bucket, _ = recommendation_bucket(ind, sc)

            sample: dict[str, Any] = {
                "symbol": sym, "cutoff": cutoff, "bucket": bucket,
                "totalScore": sc["totalScore"],
                "accumulationScore": sc["accumulationScore"],
                "convergenceScore": sc["convergenceScore"],
                "pullbackScore": sc["pullbackScore"],
                "sectorLeadScore": sc["sectorLeadScore"],
                "overextensionRisk": sc["overextensionRisk"],
            }
            for h in HORIZONS:
                sample[f"return_{h}d"] = mh[h]["return"]
                sample[f"mae_{h}d"] = mh[h]["mae"]
            samples.append(sample)

    if not samples:
        print("샘플 없음")
        return

    # 1) 기존 비교 지표: 전체 점수 기준 10일 Spearman (이전 결과와 직접 비교용)
    factor_corr = {
        key: _spearman(samples, key, "return_10d")
        for key in ("totalScore", "accumulationScore", "convergenceScore", "pullbackScore",
                    "sectorLeadScore", "overextensionRisk")
    }

    # 2) 버킷별 x 기간별 성과
    by_bucket: dict[str, Any] = {}
    for bucket in sorted({s["bucket"] for s in samples}):
        rows_b = [s for s in samples if s["bucket"] == bucket]
        entry: dict[str, Any] = {"n": len(rows_b), "byHorizon": {}}
        for h in HORIZONS:
            rets = [s[f"return_{h}d"] for s in rows_b if s[f"return_{h}d"] is not None]
            maes = [s[f"mae_{h}d"] for s in rows_b if s[f"mae_{h}d"] is not None]
            wins = [r for r in rets if r > 0]
            entry["byHorizon"][f"{h}d"] = {
                "n": len(rets),
                "avgReturnPct": round(sum(rets) / len(rets), 3) if rets else None,
                "winRate": round(len(wins) / len(rets), 4) if rets else None,
                "avgMaxAdverseExcursionPct": round(sum(maes) / len(maes), 3) if maes else None,
            }
        by_bucket[bucket] = entry

    out = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "cutoffDates": len(cutoffs),
        "horizonsTested": list(HORIZONS),
        "sampleCount": len(samples),
        "totalScoreSpearmanAt10d": factor_corr,
        "byBucket": by_bucket,
    }

    path = ROOT / "docs" / "validation" / "pre_rise_score_validation_us.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
