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


def ensemble_score_v2(
    final_score: float | None,
    regime: str,
    rr_actual: float | None,
    market: str,
    mode: str,
    horizon: str,
    repo_root: Path,
    *,
    upside_score: float | None = None,
    risk_score: float | None = None,
    momentum_score: float | None = None,
    entry_score: float | None = None,
    rr_score: float | None = None,
    quality_score: float | None = None,
    news_risk_penalty: float | None = None,
) -> dict[str, Any]:
    """
    5개 독립 모델 앙상블 점수 계산.

    M1 전략 가중  — 현재 finalScore (전략·기간별 가중합)
    M2 리스크 중심 — riskScore·rrScore·qualityScore 중심
    M3 모멘텀 중심 — momentumScore·upsideScore·entryScore 중심
    M4 밸류·진입  — entryScore·rrScore·riskScore 중심
    M5 레짐 강화  — M1 × regime_factor²  (레짐 민감도 강화)

    Returns
    -------
    ensembleScore, calibratedWinRate, calibratedAvgPnl, calibrationCount,
    modelScores (M1~M5 개별 점수)
    """
    if final_score is None:
        return {
            "ensembleScore": None, "calibratedWinRate": None,
            "calibratedAvgPnl": None, "calibrationCount": 0,
            "modelScores": None,
        }

    regime_factor = _REGIME_FACTORS.get(regime, 1.0)
    rr_actual_safe = max(0.5, rr_actual or 1.5)
    news_penalty = min(max(news_risk_penalty or 0.0, 0.0), 30.0)

    def _s(v: float | None, fallback: float = 50.0) -> float:
        return max(0.0, min(100.0, float(v))) if v is not None else fallback

    us = _s(upside_score)
    rs = _s(risk_score)
    ms = _s(momentum_score)
    es = _s(entry_score)
    rrs = _s(rr_score)
    qs = _s(quality_score)

    # M1: finalScore 그대로 사용 (전략 가중합)
    m1 = max(0.0, min(100.0, float(final_score)))

    # M2: 리스크·손익비 중심 (보수형 관점)
    m2 = rs * 0.40 + rrs * 0.30 + qs * 0.20 + es * 0.10 - news_penalty * 0.05
    m2 = max(0.0, min(100.0, m2))

    # M3: 모멘텀·상승 여력 중심 (공격형 관점)
    m3 = ms * 0.35 + us * 0.35 + es * 0.20 + rs * 0.10 - news_penalty * 0.05
    m3 = max(0.0, min(100.0, m3))

    # M4: 진입·가치 중심 (타이밍 관점)
    m4 = es * 0.35 + rrs * 0.30 + rs * 0.20 + qs * 0.15 - news_penalty * 0.05
    m4 = max(0.0, min(100.0, m4))

    # M5: 레짐 강화 (시장 상황 민감형)
    m5 = m1 * (regime_factor ** 2)
    m5 = max(0.0, min(100.0, m5))

    # 손익비 보정 계수 (1.5 기준, 3.0 이상 최대)
    rr_boost = min(max((rr_actual_safe - 1.0) / 2.0, 0.0), 1.0)

    # 5모델 가중 평균 (레짐 기반 동적 가중치)
    if regime == "BEAR":
        # 약세장: 리스크·레짐 모델 비중 높임
        weights = [0.20, 0.35, 0.10, 0.15, 0.20]
    elif regime == "BULL":
        # 강세장: 모멘텀·M1 비중 높임
        weights = [0.30, 0.15, 0.30, 0.15, 0.10]
    else:
        weights = [0.25, 0.20, 0.25, 0.20, 0.10]

    raw_ensemble = (
        m1 * weights[0] + m2 * weights[1] + m3 * weights[2]
        + m4 * weights[3] + m5 * weights[4]
    )
    # 손익비 보정 최대 +5점
    ensemble = max(0.0, min(100.0, raw_ensemble + rr_boost * 5.0))

    # 보정 테이블 (백테스트 데이터 있을 때만 활용)
    cal = load_calibration(market, mode, horizon, repo_root)
    table = cal.get("table", {})
    global_stats = cal.get("global", {})
    bin_key = f"{_bin_label(ensemble)}|{regime}"
    bucket = table.get(bin_key) or {}
    fallback_bucket = table.get(f"{_bin_label(ensemble)}|SIDE") or {}
    primary_count = bucket.get("count", 0)
    count = primary_count or fallback_bucket.get("count", 0)

    if regime == "BEAR" and primary_count == 0:
        calib_win = None
        calib_pnl = None
    else:
        calib_win_raw = bucket.get("winRate") or fallback_bucket.get("winRate") or global_stats.get("winRate")
        calib_pnl_raw = bucket.get("avgPnl") or fallback_bucket.get("avgPnl") or global_stats.get("avgPnl")
        calib_win = round(calib_win_raw, 1) if calib_win_raw is not None else None
        calib_pnl = round(calib_pnl_raw, 3) if calib_pnl_raw is not None else None

    return {
        "ensembleScore": round(ensemble, 1),
        "calibratedWinRate": calib_win,
        "calibratedAvgPnl": calib_pnl,
        "calibrationCount": count,
        "modelScores": {
            "m1_strategy": round(m1, 1),
            "m2_risk": round(m2, 1),
            "m3_momentum": round(m3, 1),
            "m4_value": round(m4, 1),
            "m5_regime": round(m5, 1),
        },
    }


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

    # ensembleScore: 점수(50%) + 레짐(30%) + 손익비(20%) — 항상 계산
    regime_factor = _REGIME_FACTORS.get(regime, 1.0)
    rr_factor = min(max((rr_actual or 1.5) / 3.0, 0.3), 1.0)
    raw = (final_score / 100) * 0.5 + (regime_factor - 0.6) / 0.6 * 0.3 + rr_factor * 0.2
    ensemble = max(0.0, min(100.0, raw * 100))

    primary_count = bucket.get("count", 0)   # fallback 제외, 해당 레짐 실측 건수만
    count = primary_count or fallback.get("count", 0)  # 표시용 (fallback 포함)

    # BEAR 레짐: 백테스트에서 진입 자체가 없어 실측 버킷이 비어 있음 → 승률 null 반환 (오해 방지)
    if regime == "BEAR" and primary_count == 0:
        return {
            "ensembleScore": round(ensemble, 1),
            "calibratedWinRate": None,
            "calibratedAvgPnl": None,
            "calibrationCount": 0,
        }

    calib_win = bucket.get("winRate") or fallback.get("winRate") or global_stats.get("winRate", 20.0)
    calib_pnl = bucket.get("avgPnl") or fallback.get("avgPnl") or global_stats.get("avgPnl", 0.0)

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
