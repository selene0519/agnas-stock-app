"""backtest_momentum_continuation_score.py의 KR 버전. KR 유니버스로 검증."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_kr_recommendations import indicators, momentum_continuation_score, _load_ohlcv_all, _load_sector_map  # noqa: E402
from scripts.backtest_momentum_continuation_score import _tercile_bucket  # noqa: E402
from scripts.backtest_pre_rise_score import _future_closes, _multi_horizon_stats, _spearman, HORIZONS  # noqa: E402

OHLCV_ALL = _load_ohlcv_all()
SECTOR_MAP = _load_sector_map()
TERCILE_HORIZON = 20


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
        sector_mom: dict[str, list[float]] = {}
        per_symbol_ind: dict[str, dict[str, Any]] = {}
        for sym, rows in OHLCV_ALL.items():
            if sym in {"KOSPI", "KOSDAQ"}:
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
                sec = SECTOR_MAP.get(sym) or SECTOR_MAP.get(sym.lstrip("0")) or "Unknown"
                sector_mom.setdefault(sec, []).append(mom20)
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

            sec = SECTOR_MAP.get(sym) or SECTOR_MAP.get(sym.lstrip("0")) or "Unknown"
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
    path = ROOT / "docs" / "validation" / "momentum_continuation_score_validation_kr.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
