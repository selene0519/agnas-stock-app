from __future__ import annotations

import json
import math
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BACKEND_DIR = ROOT / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.backtest_band_calibration import _slice_rows  # noqa: E402
from scripts.generate_kr_recommendations import (  # noqa: E402
    _final_score,
    _load_ohlcv_all,
    _load_sector_map,
    _sub_scores,
    indicators,
    momentum_continuation_score,
    setup_score,
)
from scripts.generate_us_recommendations import _load_us_ohlcv, _load_us_sector_map  # noqa: E402

HORIZONS = (3, 5, 10, 20)
FEATURES = (
    "setup_score",
    "overextension_risk",
    "momentum_continuation_score",
    "final_score_balanced_swing",
    "upside_score",
    "risk_score",
    "momentum_score",
    "entry_score",
    "rr_score",
    "quality_score",
    "news_risk_penalty",
)
BENCHMARKS = {
    "kr": {"KOSPI", "KOSDAQ", "KS11", "KQ11", "^KS11", "^KQ11"},
    "us": {"SPY", "QQQ", "DIA", "SP500", "^GSPC"},
}


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _rank(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=lambda idx: vals[idx])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(rows: list[dict[str, Any]], feature: str, target: str) -> float | None:
    pairs = [(_num(row.get(feature)), _num(row.get(target))) for row in rows]
    clean = [(x, y) for x, y in pairs if x is not None and y is not None]
    if len(clean) < 10:
        return None
    xs = [p[0] for p in clean]
    ys = [p[1] for p in clean]
    rx = _rank(xs)
    ry = _rank(ys)
    mx = statistics.fmean(rx)
    my = statistics.fmean(ry)
    cov = sum((rx[i] - mx) * (ry[i] - my) for i in range(len(rx)))
    vx = sum((x - mx) ** 2 for x in rx)
    vy = sum((y - my) ** 2 for y in ry)
    if vx <= 0 or vy <= 0:
        return None
    return round(cov / math.sqrt(vx * vy), 4)


def _cutoff_dates(ohlcv_all: dict[str, list[dict[str, Any]]]) -> list[str]:
    all_dates = sorted({str(row.get("date") or "")[:10] for rows in ohlcv_all.values() for row in rows if row.get("date")})
    if len(all_dates) < 100:
        return []
    return all_dates[60:-30:5]


def _future_window(rows: list[dict[str, Any]], cutoff: str, horizon: int) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for row in rows:
        if str(row.get("date") or "")[:10] <= cutoff:
            continue
        close = _num(row.get("close"))
        high = _num(row.get("high")) or close
        low = _num(row.get("low")) or close
        if close is None or high is None or low is None:
            continue
        out.append({"close": close, "high": high, "low": low})
        if len(out) >= horizon:
            break
    return out


def _forward_stats(base_close: float, rows: list[dict[str, Any]], cutoff: str) -> dict[str, float | None]:
    stats: dict[str, float | None] = {}
    for horizon in HORIZONS:
        window = _future_window(rows, cutoff, horizon)
        if len(window) < horizon or base_close <= 0:
            stats[f"return_{horizon}d"] = None
            stats[f"mae_{horizon}d"] = None
            stats[f"mfe_{horizon}d"] = None
            continue
        end_close = window[-1]["close"]
        high = max(row["high"] for row in window)
        low = min(row["low"] for row in window)
        stats[f"return_{horizon}d"] = round((end_close - base_close) / base_close * 100.0, 4)
        stats[f"mae_{horizon}d"] = round((low - base_close) / base_close * 100.0, 4)
        stats[f"mfe_{horizon}d"] = round((high - base_close) / base_close * 100.0, 4)
    return stats


def _median(values: Iterable[float]) -> float | None:
    vals = [v for v in values if math.isfinite(v)]
    return statistics.median(vals) if vals else None


def _regime_for_cutoff(market: str, cutoff: str, ohlcv_all: dict[str, list[dict[str, Any]]]) -> str:
    symbols = [s for s in BENCHMARKS[market] if s in ohlcv_all] or list(ohlcv_all.keys())
    dist_values: list[float] = []
    mom_values: list[float] = []
    for symbol in symbols:
        past = _slice_rows(ohlcv_all.get(symbol, []), cutoff)
        if len(past) < 25:
            continue
        ind = indicators(past)
        dist = _num(ind.get("distanceToMa20"))
        mom = _num(ind.get("recentMomentum5"))
        if dist is not None:
            dist_values.append(dist)
        if mom is not None:
            mom_values.append(mom)
        if len(dist_values) >= 80 and symbol not in BENCHMARKS[market]:
            break
    dist_med = _median(dist_values)
    mom_med = _median(mom_values)
    if dist_med is None or mom_med is None:
        return "RANGE"
    if dist_med > 0 and mom_med > 0:
        return "BULL"
    if dist_med < -2.0 or mom_med < -2.0:
        return "BEAR"
    return "RANGE"


def _sector_gap(symbol: str, ind_by_symbol: dict[str, dict[str, Any]], sector_map: dict[str, str]) -> float | None:
    own = _num(ind_by_symbol.get(symbol, {}).get("recentMomentum20"))
    if own is None:
        return None
    sector = sector_map.get(symbol, "Unknown")
    peers = [
        _num(ind.get("recentMomentum20"))
        for peer, ind in ind_by_symbol.items()
        if sector_map.get(peer, "Unknown") == sector
    ]
    peer_vals = [v for v in peers if v is not None]
    if len(peer_vals) < 3:
        return None
    return statistics.fmean(peer_vals) - own


def _feature_values(symbol: str, ind: dict[str, Any], ind_by_symbol: dict[str, dict[str, Any]], sector_map: dict[str, str]) -> dict[str, float | None]:
    sub = _sub_scores(ind)
    gap = _sector_gap(symbol, ind_by_symbol, sector_map)
    setup = setup_score(ind, supply_row=None, sector_lead_gap=gap)
    momentum = momentum_continuation_score(ind, supply_row=None, sector_lead_gap=gap)
    return {
        "setup_score": _num(setup.get("totalScore")),
        "overextension_risk": _num(setup.get("overextensionRisk")),
        "momentum_continuation_score": _num(momentum.get("totalScore")),
        "final_score_balanced_swing": _num(_final_score(ind, "balanced", "swing")),
        "upside_score": _num(sub.get("upsideScore")),
        "risk_score": _num(sub.get("riskScore")),
        "momentum_score": _num(sub.get("momentumScore")),
        "entry_score": _num(sub.get("entryScore")),
        "rr_score": _num(sub.get("rrScore")),
        "quality_score": _num(sub.get("qualityScore")),
        "news_risk_penalty": _num(sub.get("newsRiskPenalty")),
    }


def _tercile_name(index: int, total: int) -> str:
    if index < total / 3:
        return "low"
    if index >= total * 2 / 3:
        return "high"
    return "mid"


def _tercile_stats(rows: list[dict[str, Any]], feature: str, horizon: int) -> dict[str, Any]:
    valid = [
        row for row in rows
        if _num(row.get(feature)) is not None and _num(row.get(f"return_{horizon}d")) is not None
    ]
    valid.sort(key=lambda row: float(row[feature]))
    buckets = {"low": [], "mid": [], "high": []}
    for idx, row in enumerate(valid):
        buckets[_tercile_name(idx, len(valid))].append(row)
    out: dict[str, Any] = {}
    for name, bucket_rows in buckets.items():
        returns = [float(row[f"return_{horizon}d"]) for row in bucket_rows if _num(row.get(f"return_{horizon}d")) is not None]
        maes = [float(row[f"mae_{horizon}d"]) for row in bucket_rows if _num(row.get(f"mae_{horizon}d")) is not None]
        mfes = [float(row[f"mfe_{horizon}d"]) for row in bucket_rows if _num(row.get(f"mfe_{horizon}d")) is not None]
        out[name] = {
            "sample_count": len(returns),
            "avg_return_pct": round(statistics.fmean(returns), 4) if returns else None,
            "median_return_pct": round(statistics.median(returns), 4) if returns else None,
            "win_rate": round(sum(1 for value in returns if value > 0) / len(returns), 4) if returns else None,
            "avg_mae_pct": round(statistics.fmean(maes), 4) if maes else None,
            "avg_mfe_pct": round(statistics.fmean(mfes), 4) if mfes else None,
        }
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    features: dict[str, Any] = {}
    for feature in FEATURES:
        horizons: dict[str, Any] = {}
        for horizon in HORIZONS:
            horizons[f"{horizon}d"] = {
                "sample_count": sum(
                    1 for row in rows
                    if _num(row.get(feature)) is not None and _num(row.get(f"return_{horizon}d")) is not None
                ),
                "spearman": spearman(rows, feature, f"return_{horizon}d"),
                "terciles": _tercile_stats(rows, feature, horizon),
            }
        features[feature] = horizons
    return {"sample_count": len(rows), "features": features}


def collect_samples(market: str) -> tuple[list[dict[str, Any]], int]:
    if market == "kr":
        ohlcv_all = _load_ohlcv_all()
        sector_map = _load_sector_map()
    else:
        ohlcv_all = _load_us_ohlcv()
        sector_map = _load_us_sector_map()
    cutoffs = _cutoff_dates(ohlcv_all)
    samples: list[dict[str, Any]] = []
    for cutoff in cutoffs:
        regime = _regime_for_cutoff(market, cutoff, ohlcv_all)
        ind_by_symbol: dict[str, dict[str, Any]] = {}
        for symbol, rows in ohlcv_all.items():
            if symbol in BENCHMARKS[market]:
                continue
            past = _slice_rows(rows, cutoff)
            if len(past) < 60:
                continue
            ind = indicators(past)
            latest = _num(ind.get("latest"))
            if latest is None or latest <= 0:
                continue
            if len(_future_window(rows, cutoff, max(HORIZONS))) < min(HORIZONS):
                continue
            ind_by_symbol[symbol] = ind
        for symbol, ind in ind_by_symbol.items():
            rows = ohlcv_all[symbol]
            base_close = _num(_slice_rows(rows, cutoff)[-1].get("close")) or _num(ind.get("latest"))
            if base_close is None or base_close <= 0:
                continue
            sample = {
                "market": market,
                "symbol": symbol,
                "cutoff": cutoff,
                "regime": regime,
                **_feature_values(symbol, ind, ind_by_symbol, sector_map),
                **_forward_stats(base_close, rows, cutoff),
            }
            samples.append(sample)
    return samples, len(cutoffs)


def build_report(market: str) -> dict[str, Any]:
    samples, cutoff_count = collect_samples(market)
    by_regime = {
        regime: summarize([row for row in samples if row.get("regime") == regime])
        for regime in sorted({str(row.get("regime") or "UNKNOWN") for row in samples})
    }
    return {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "market": market,
        "purpose": "diagnostic_only_not_operational_scoring_basis",
        "leakagePolicy": "features use OHLCV at or before cutoff; returns/MAE/MFE use bars after cutoff",
        "operationPolicy": "do not wire these results into _final_score, ranking, filters, or EV without a separate approved review",
        "horizons": list(HORIZONS),
        "cutoffCount": cutoff_count,
        "sampleCount": len(samples),
        "overall": summarize(samples),
        "byRegime": by_regime,
    }


def main() -> None:
    out_dir = ROOT / "docs" / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    for market in ("kr", "us"):
        report = build_report(market)
        path = out_dir / f"oos_signal_validation_{market}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{market}: samples={report['sampleCount']} cutoffs={report['cutoffCount']} -> {path}")


if __name__ == "__main__":
    main()
