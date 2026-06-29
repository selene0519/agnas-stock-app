"""backtest_pre_rise_score.py의 KR 버전. US와 같은 방법(버킷별 x 3/5/10/20일), KR 유니버스로 검증."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_kr_recommendations import indicators, setup_score, recommendation_bucket, _load_ohlcv_all  # noqa: E402
from scripts.backtest_pre_rise_score import _future_closes, _multi_horizon_stats, _spearman, HORIZONS, SPEARMAN_HORIZON  # noqa: E402

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

    factor_corr = {
        key: _spearman(samples, key, "return_10d")
        for key in ("totalScore", "accumulationScore", "convergenceScore", "pullbackScore",
                    "sectorLeadScore", "overextensionRisk")
    }

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
    path = ROOT / "docs" / "validation" / "pre_rise_score_validation_kr.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
