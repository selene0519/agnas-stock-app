"""
momentum_continuation_score()(scripts/generate_kr_recommendations.py)가 진짜 미래
수익률과 상관이 있는지 검증한다. setup_score()와 정반대 철학("이미 움직인 종목이 건강하게
계속 가는지")이라 같은 방법(과거 cutoff, no look-ahead, 3/5/10/20일, Spearman + 3분위)
으로 따로 검증한다 — 두 점수를 합치치 않고 각자 따로 본다.

배경: docs/validation/pre_rise_score_validation_{kr,us}.json의 버킷 분석에서 "추격금지"
(이미 과열) 종목들이 오히려 20일 기준 최고 평균수익을 냈다 — 이 스크립트는 그 관찰을
독립된 점수·독립된 검증으로 다시 확인한다.

출력: docs/validation/momentum_continuation_score_validation_us.json,
      docs/validation/momentum_continuation_score_validation_kr.json (별도 스크립트)
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

from scripts.generate_kr_recommendations import indicators, momentum_continuation_score  # noqa: E402
from scripts.generate_us_recommendations import _load_us_ohlcv, _load_us_sector_map  # noqa: E402
from scripts.backtest_band_calibration import _slice_rows, _cutoff_dates  # noqa: E402
from scripts.backtest_pre_rise_score import _future_closes, _multi_horizon_stats, _spearman, HORIZONS  # noqa: E402

OHLCV_ALL = _load_us_ohlcv()
SECTOR_MAP = _load_us_sector_map()
TERCILE_HORIZON = 20  # 추세지속 신호는 단기보다 장기에서 의미가 나올 가능성이 큼


def _tercile_bucket(value: float, q1: float, q2: float) -> str:
    if value <= q1:
        return "low"
    if value >= q2:
        return "high"
    return "mid"


def main() -> None:
    cutoffs = _cutoff_dates()

    # 섹터 모멘텀(섹터 평균 recentMomentum20) — generate_us_recommendations.py와 같은 방식
    sector_mom_by_cutoff: dict[str, dict[str, list[float]]] = {}

    samples: list[dict[str, Any]] = []

    for cutoff in cutoffs:
        sector_mom: dict[str, list[float]] = {}
        per_symbol_ind: dict[str, dict[str, Any]] = {}
        for sym, rows in OHLCV_ALL.items():
            if sym in {"SPY", "QQQ", "DIA"}:
                continue
            past = _slice_rows(rows, cutoff)
            if len(past) < 60:
                continue
            ind = indicators(past)
            if not ind.get("latest") or ind["latest"] <= 0:
                continue
            per_symbol_ind[sym] = ind
            mom20 = ind.get("recentMomentum20")
            if mom20 is not None:
                sector_mom.setdefault(SECTOR_MAP.get(sym, "Unknown"), []).append(mom20)
        sector_avg = {sec: sum(v) / len(v) for sec, v in sector_mom.items() if len(v) >= 3}

        for sym, ind in per_symbol_ind.items():
            rows = OHLCV_ALL[sym]
            future_closes = _future_closes(rows, cutoff)
            if len(future_closes) < min(HORIZONS):
                continue
            base_close = float(ind["latest"])
            mh = _multi_horizon_stats(base_close, future_closes)
            if mh[TERCILE_HORIZON]["return"] is None:
                continue

            sec = SECTOR_MAP.get(sym, "Unknown")
            own_mom = ind.get("recentMomentum20")
            gap = (sector_avg.get(sec) - own_mom) if sec in sector_avg and own_mom is not None else None

            mc = momentum_continuation_score(ind, supply_row=None, sector_lead_gap=gap)
            sample: dict[str, Any] = {"symbol": sym, "cutoff": cutoff, "totalScore": mc["totalScore"]}
            for h in HORIZONS:
                sample[f"return_{h}d"] = mh[h]["return"]
                sample[f"mae_{h}d"] = mh[h]["mae"]
            samples.append(sample)

    if not samples:
        print("샘플 없음")
        return

    spearman_by_horizon = {f"{h}d": _spearman(samples, "totalScore", f"return_{h}d") for h in HORIZONS}

    vals = sorted(s["totalScore"] for s in samples)
    n = len(vals)
    q1, q2 = vals[n // 3], vals[2 * n // 3]
    terciles: dict[str, list[dict]] = {"low": [], "mid": [], "high": []}
    for s in samples:
        terciles[_tercile_bucket(s["totalScore"], q1, q2)].append(s)

    by_tercile: dict[str, Any] = {}
    for name, rows_t in terciles.items():
        entry: dict[str, Any] = {"n": len(rows_t), "byHorizon": {}}
        for h in HORIZONS:
            rets = [s[f"return_{h}d"] for s in rows_t if s[f"return_{h}d"] is not None]
            maes = [s[f"mae_{h}d"] for s in rows_t if s[f"mae_{h}d"] is not None]
            wins = [r for r in rets if r > 0]
            entry["byHorizon"][f"{h}d"] = {
                "n": len(rets),
                "avgReturnPct": round(sum(rets) / len(rets), 3) if rets else None,
                "winRate": round(len(wins) / len(rets), 4) if rets else None,
                "avgMaxAdverseExcursionPct": round(sum(maes) / len(maes), 3) if maes else None,
            }
        by_tercile[name] = entry

    out = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "cutoffDates": len(cutoffs),
        "horizonsTested": list(HORIZONS),
        "sampleCount": len(samples),
        "totalScoreSpearman": spearman_by_horizon,
        "byTercile": by_tercile,
    }
    path = ROOT / "docs" / "validation" / "momentum_continuation_score_validation_us.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
