"""
ensemble_calibrator.py — 백테스트 거래 기록 기반 앙상블 보정 모델

목적:
  - walk-forward 백테스트 결과(600+ 거래)로 (점수구간, 레짐) → (실제 승률, 평균 PnL) 매핑
  - apply_quant_overlay에서 ensembleScore / calibratedWinRate로 활용
  - 매월 백테스트 실행 시 자동 갱신

공식:
  ensembleScore = 0.5 * normalizedScore + 0.3 * regimeFactor + 0.2 * rrFactor
  calibratedWinRate = 백테스트 실측 승률 (점수구간 × 레짐 교차표)
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


_SCORE_BINS = [(0, 50), (50, 55), (55, 60), (60, 65), (65, 70), (70, 100)]
_REGIME_FACTORS = {"BULL": 1.2, "SIDE": 1.0, "BEAR": 0.6}
_CACHE: dict[str, Any] = {}


def _bin_label(score: float) -> str:
    for lo, hi in _SCORE_BINS:
        if lo <= score < hi:
            return f"{lo}-{hi}"
    return "70-100"


def build_calibration_table(
    trade_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    거래 기록으로 (점수구간, 레짐) 교차 보정 테이블 생성.
    """
    buckets: dict[str, list[float]] = {}
    for rec in trade_records:
        score = rec.get("finalScore")
        regime = str(rec.get("regime") or "SIDE")
        if score is None:
            continue
        pnl = rec.get("netPnlPct")
        filled = rec.get("executionStatus") == "체결"
        if not filled:
            continue
        key = f"{_bin_label(float(score))}|{regime}"
        if pnl is not None:
            buckets.setdefault(key, []).append(float(pnl))

    table: dict[str, dict] = {}
    for key, pnls in buckets.items():
        wins = [p for p in pnls if p > 0]
        table[key] = {
            "count": len(pnls),
            "winRate": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            "avgPnl": round(sum(pnls) / len(pnls), 3) if pnls else 0,
            "avgWin": round(sum(wins) / len(wins), 3) if wins else 0,
            "lossPct": round((len(pnls) - len(wins)) / len(pnls) * 100, 1) if pnls else 100,
        }

    # 전체 평균 (fallback용)
    all_pnls = [p for pnls in buckets.values() for p in pnls]
    all_wins = [p for p in all_pnls if p > 0]
    global_stats = {
        "count": len(all_pnls),
        "winRate": round(len(all_wins) / len(all_pnls) * 100, 1) if all_pnls else 0,
        "avgPnl": round(sum(all_pnls) / len(all_pnls), 3) if all_pnls else 0,
    }

    return {"table": table, "global": global_stats, "bins": [f"{l}-{h}" for l, h in _SCORE_BINS]}


def save_calibration(
    trade_records: list[dict[str, Any]],
    market: str,
    mode: str,
    horizon: str,
    repo_root: Path,
) -> Path:
    """보정 테이블을 JSON으로 저장."""
    cal = build_calibration_table(trade_records)
    cal["market"] = market
    cal["mode"] = mode
    cal["horizon"] = horizon
    cal["recordCount"] = len(trade_records)
    path = repo_root / "reports" / f"ensemble_calibration_{market}_{mode}_{horizon}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, indent=2)
    return path


def load_calibration(
    market: str,
    mode: str,
    horizon: str,
    repo_root: Path,
) -> dict[str, Any]:
    """보정 테이블 로드 (메모리 캐시)."""
    key = f"{market}_{mode}_{horizon}"
    if key in _CACHE:
        return _CACHE[key]
    path = repo_root / "reports" / f"ensemble_calibration_{market}_{mode}_{horizon}.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    _CACHE[key] = data
    return data


def ensemble_score(
    final_score: float | None,
    regime: str,
    rr_actual: float | None,
    market: str,
    mode: str,
    horizon: str,
    repo_root: Path,
) -> dict[str, Any]:
    """
    앙상블 점수와 실증 기반 승률 반환.

    Returns
    -------
    {
        "ensembleScore": float (0~100),
        "calibratedWinRate": float (%),
        "calibratedAvgPnl": float (%),
        "calibrationCount": int,    # 해당 버킷 샘플 수
    }
    """
    if final_score is None:
        return {"ensembleScore": None, "calibratedWinRate": None, "calibratedAvgPnl": None, "calibrationCount": 0}

    cal = load_calibration(market, mode, horizon, repo_root)
    table = cal.get("table", {})
    global_stats = cal.get("global", {})

    bin_key = f"{_bin_label(final_score)}|{regime}"
    bucket = table.get(bin_key) or {}
    fallback = table.get(f"{_bin_label(final_score)}|SIDE") or {}

    calib_win = bucket.get("winRate") or fallback.get("winRate") or global_stats.get("winRate", 20.0)
    calib_pnl = bucket.get("avgPnl") or fallback.get("avgPnl") or global_stats.get("avgPnl", 0.0)
    count = bucket.get("count", fallback.get("count", 0))

    # ensembleScore: 점수(50%) + 레짐(30%) + 손익비(20%)
    regime_factor = _REGIME_FACTORS.get(regime, 1.0)
    rr_factor = min(max((rr_actual or 1.5) / 3.0, 0.3), 1.0)
    raw = (final_score / 100) * 0.5 + (regime_factor - 0.6) / 0.6 * 0.3 + rr_factor * 0.2
    ensemble = max(0.0, min(100.0, raw * 100))

    return {
        "ensembleScore": round(ensemble, 1),
        "calibratedWinRate": round(calib_win, 1),
        "calibratedAvgPnl": round(calib_pnl, 3),
        "calibrationCount": count,
    }


def run_ensemble_calibration(market: str = "kr", repo_root: Path | None = None) -> dict[str, Any]:
    """
    전체 walk-forward 백테스트를 실행해 9개 콤보 모두 보정 테이블 저장.
    보통 월 1회 GitHub Actions에서 실행.
    """
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[4]

    from app.engine.walkforward_backtest import run_walkforward

    results: list[dict] = []
    for mode in ("conservative", "balanced", "aggressive"):
        for horizon in ("short", "swing", "mid"):
            res = run_walkforward(market=market, mode=mode, horizon=horizon)
            records = res.get("tradeRecords", [])
            if records:
                path = save_calibration(records, market, mode, horizon, repo_root)
                stats = res.get("correctedStats", {})
                results.append({
                    "combo": f"{market}_{mode}_{horizon}",
                    "records": len(records),
                    "winRate": stats.get("winRate"),
                    "avgPnl": stats.get("avgNetPnlPct"),
                    "savedTo": str(path),
                })

    return {"status": "OK", "market": market, "combos": results}
