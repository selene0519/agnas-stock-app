"""
self_correction_v2.py — 과거 검증 결과를 집계해 보정 파라미터를 생성한다 (7-D/7-E)

핵심 원칙:
- 개별 추천 점수에 직접 감점하지 않는다.
- market/mode/horizon 단위로 결과를 집계해 보정 파라미터만 생성한다.
- sampleCount < 30 → 보정 미적용 (confidence=0 표시).
- 개별 weight 조정 최대 ±1.5, 전체 합 최대 ±8.
- entryAggressiveness ±0.5, targetMultiplier ±0.2, stopAtrMultiplier ±0.3.

사용법:
    from app.engine.self_correction_v2 import build_correction_params, apply_correction
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.engine import correction_store, outcome_analyzer
from app.engine.quant_scanner import round_to_kr_tick

# ── 킬스위치 & 적용 강도 (환경변수) ───────────────────────────────────────
# SELF_CORRECTION_ENABLED=false → 전체 보정 비활성화
# CORRECTION_STRENGTH=0.25/0.5/1.0 → 보정 폭 배율 (기본 1.0)
def _correction_enabled() -> bool:
    return os.environ.get("SELF_CORRECTION_ENABLED", "true").lower() not in {"false", "0", "no", "off"}

def _correction_strength() -> float:
    try:
        val = float(os.environ.get("CORRECTION_STRENGTH", "1.0"))
        return max(0.0, min(1.0, val))
    except Exception:
        return 1.0

# ── 안전장치 상수 ──────────────────────────────────────────────────────────
_MIN_SAMPLES       = 30     # 이 미만이면 보정 안 함
_MIN_CONFIDENCE    = 0.3    # 이 미만이면 보정 파라미터 무시
_MAX_WEIGHT_SINGLE = 1.5    # 개별 weight 조정 최대 ±1.5
_MAX_WEIGHT_TOTAL  = 8.0    # 전체 weight 조정 합산 최대 ±8
_MAX_ENTRY_ADJ     = 0.5    # entryAggressiveness 최대 ±0.5
_MAX_TARGET_ADJ    = 0.2    # targetMultiplier 최대 ±0.2
_MAX_STOP_ADJ      = 0.3    # stopAtrMultiplier 최대 ±0.3
_MAX_DIST_ADJ      = 2.0    # maxDistanceToEntryPct 최대 ±2.0
_MAX_RR_ADJ        = 0.2    # minRiskRewardRatio 최대 ±0.2


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _reports_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "reports"


def _load_validation_results(market: str) -> list[dict[str, Any]]:
    """
    검증 결과를 여러 소스에서 로드한다.
    1. virtual_validation_results.csv (settled 결과)
    2. mone_v36_final_trade_validation_{market}_YYYYMMDD.csv (dated 결과)
    """
    rows: list[dict[str, Any]] = []
    reports = _reports_dir()

    # 소스 1: virtual_validation_results.csv (signal_ledger 기반)
    vvr_path = reports / "virtual_validation_results.csv"
    if vvr_path.exists():
        try:
            for enc in ("utf-8-sig", "utf-8", "cp949"):
                try:
                    with vvr_path.open("r", encoding=enc, newline="") as f:
                        for row in csv.DictReader(f):
                            mkt = str(row.get("market") or "").lower()
                            if mkt and mkt != market:
                                continue
                            _status_up = str(row.get("status") or "").upper()
                            if _status_up not in {"SETTLED", "EXPIRED", "CLOSED", "WIN", "LOSS"}:
                                continue
                            # 필드 매핑
                            is_exec = str(row.get("isExecuted") or "").lower() in {"true", "1"}
                            target_hit = str(row.get("targetHit") or "").lower() in {"true", "1"}
                            stop_hit = str(row.get("stopHit") or "").lower() in {"true", "1"}
                            result_str = str(row.get("result") or "").upper()
                            row.setdefault("executionStatus", "체결" if is_exec else "미체결")
                            # result 필드 우선 사용
                            if result_str in {"WIN", "TARGET", "TARGET_HIT"}:
                                row.setdefault("exitStatus", "목표도달")
                            elif result_str in {"LOSS", "STOP", "STOP_HIT", "STOP_FIRST"}:
                                row.setdefault("exitStatus", "손절")
                            elif target_hit and not stop_hit:
                                row.setdefault("exitStatus", "목표도달")
                            elif stop_hit:
                                row.setdefault("exitStatus", "손절")
                            else:
                                row.setdefault("exitStatus", "기간종료")
                            row.setdefault("netPnlPct", row.get("returnPct", ""))
                            row.setdefault("grossPnlPct", row.get("returnPct", ""))
                            rows.append(row)
                    break
                except UnicodeDecodeError:
                    continue
        except Exception:
            pass

    # 소스 2: 날짜별 dated validation CSV
    for path in sorted(reports.glob(f"mone_v36_final_trade_validation_{market}_*_????????.csv")):
        try:
            for enc in ("utf-8-sig", "utf-8", "cp949"):
                try:
                    with path.open("r", encoding=enc, newline="") as f:
                        for row in csv.DictReader(f):
                            if str(row.get("validationStatus") or "").upper() == "PENDING":
                                continue
                            rows.append(row)
                    break
                except UnicodeDecodeError:
                    continue
        except Exception:
            pass

    return rows


def _load_recommendation_csvs(market: str) -> list[dict[str, Any]]:
    """reports/mone_v36_final_recommendations_{market}_*.csv 전체 로드."""
    rows: list[dict[str, Any]] = []
    for path in _reports_dir().glob(f"mone_v36_final_recommendations_{market}_*.csv"):
        try:
            for enc in ("utf-8-sig", "utf-8", "cp949"):
                try:
                    with path.open("r", encoding=enc, newline="") as f:
                        rows.extend(list(csv.DictReader(f)))
                    break
                except UnicodeDecodeError:
                    continue
        except Exception:
            pass
    return rows


def _group_by_combo(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        mkt = str(row.get("market") or "kr").lower()
        mode = str(row.get("mode") or "balanced").lower()
        horizon = str(row.get("horizon") or "swing").lower()
        key = f"{mkt}_{mode}_{horizon}"
        groups.setdefault(key, []).append(row)
    return groups


def _compute_confidence(sample_count: int) -> float:
    if sample_count < _MIN_SAMPLES:
        return 0.0
    if sample_count >= 100:
        return 0.9
    return round(0.3 + (sample_count - 30) / 70 * 0.6, 3)


def _build_weight_adjustments(reason_counts: dict[str, int], total: int) -> dict[str, float]:
    if total == 0:
        return {}
    adj: dict[str, float] = {}

    def pct(code: str) -> float:
        return reason_counts.get(code, 0) / total

    # chartScore: NEWS_RISK 많으면 뉴스 페널티 강화
    news_pct = pct("NEWS_RISK_UNDERWEIGHTED")
    if news_pct > 0.15:
        adj["newsPenalty"] = _clamp(news_pct * 3.0, -_MAX_WEIGHT_SINGLE, _MAX_WEIGHT_SINGLE)

    # riskPenalty: 변동성/진입 과도 시 강화
    vol_pct = pct("VOLATILITY_TOO_HIGH") + pct("ENTRY_TOO_AGGRESSIVE") * 0.5
    if vol_pct > 0.2:
        adj["riskPenalty"] = _clamp(vol_pct * 2.5, -_MAX_WEIGHT_SINGLE, _MAX_WEIGHT_SINGLE)

    # qualityScore: DATA_STALE 많으면 품질 가중치 하향
    stale_pct = pct("DATA_STALE")
    if stale_pct > 0.2:
        adj["qualityScore"] = _clamp(-stale_pct * 2.0, -_MAX_WEIGHT_SINGLE, _MAX_WEIGHT_SINGLE)

    # 전체 합산 ±8 상한
    total_adj = sum(abs(v) for v in adj.values())
    if total_adj > _MAX_WEIGHT_TOTAL:
        scale = _MAX_WEIGHT_TOTAL / total_adj
        adj = {k: round(v * scale, 3) for k, v in adj.items()}

    return {k: round(v, 3) for k, v in adj.items()}


def _build_price_adjustments(reason_counts: dict[str, int], total: int) -> dict[str, float]:
    if total == 0:
        return {"entryAggressiveness": 0.0, "targetMultiplier": 0.0, "stopAtrMultiplier": 0.0}

    def pct(code: str) -> float:
        return reason_counts.get(code, 0) / total

    entry_adj  = 0.0
    target_adj = 0.0
    stop_adj   = 0.0

    # MISS_ENTRY_TOO_LOW → 진입가 더 공격적으로 (높게)
    miss_pct = pct("MISS_ENTRY_TOO_LOW")
    if miss_pct > 0.2:
        entry_adj += miss_pct * 0.8

    # ENTRY_TOO_AGGRESSIVE → 진입가 보수적으로 (낮게)
    aggr_pct = pct("ENTRY_TOO_AGGRESSIVE")
    if aggr_pct > 0.15:
        entry_adj -= aggr_pct * 0.6

    # TARGET_TOO_FAR → targetMultiplier 낮춤
    far_pct = pct("TARGET_TOO_FAR")
    if far_pct > 0.2:
        target_adj -= far_pct * 0.5

    # TARGET_TOO_CLOSE → targetMultiplier 높임
    close_pct = pct("TARGET_TOO_CLOSE")
    if close_pct > 0.2:
        target_adj += close_pct * 0.4

    # STOP_TOO_TIGHT → stopAtrMultiplier 높임
    tight_pct = pct("STOP_TOO_TIGHT")
    if tight_pct > 0.15:
        stop_adj += tight_pct * 0.8

    # VOLATILITY_TOO_HIGH → stopAtrMultiplier 높임 (더 여유 있게)
    vol_pct = pct("VOLATILITY_TOO_HIGH")
    if vol_pct > 0.15:
        stop_adj += vol_pct * 0.5

    return {
        "entryAggressiveness": _clamp(round(entry_adj, 3),  -_MAX_ENTRY_ADJ,  _MAX_ENTRY_ADJ),
        "targetMultiplier":    _clamp(round(target_adj, 3), -_MAX_TARGET_ADJ, _MAX_TARGET_ADJ),
        "stopAtrMultiplier":   _clamp(round(stop_adj, 3),   -_MAX_STOP_ADJ,   _MAX_STOP_ADJ),
    }


def _build_filter_adjustments(reason_counts: dict[str, int], total: int) -> dict[str, float]:
    if total == 0:
        return {"maxDistanceToEntryPct": 0.0, "minRiskRewardRatio": 0.0}

    def pct(code: str) -> float:
        return reason_counts.get(code, 0) / total

    dist_adj = 0.0
    rr_adj   = 0.0

    # MISS_ENTRY_TOO_LOW 많으면 maxDistance 상향 (더 멀리 있어도 허용)
    if pct("MISS_ENTRY_TOO_LOW") > 0.25:
        dist_adj += pct("MISS_ENTRY_TOO_LOW") * 2.0

    # ENTRY_TOO_AGGRESSIVE 많으면 maxDistance 하향 (더 가깝게만 허용)
    if pct("ENTRY_TOO_AGGRESSIVE") > 0.2:
        dist_adj -= pct("ENTRY_TOO_AGGRESSIVE") * 1.5

    # GOOD_SIGNAL_WEAK_EXIT 많으면 RR 기준 낮춤 (진입은 했는데 출구 미흡)
    if pct("GOOD_SIGNAL_WEAK_EXIT") > 0.2:
        rr_adj -= pct("GOOD_SIGNAL_WEAK_EXIT") * 0.15

    return {
        "maxDistanceToEntryPct": _clamp(round(dist_adj, 3), -_MAX_DIST_ADJ, _MAX_DIST_ADJ),
        "minRiskRewardRatio":    _clamp(round(rr_adj, 3),   -_MAX_RR_ADJ,   _MAX_RR_ADJ),
    }


def build_correction_params(market: str = "kr") -> dict[str, Any]:
    """
    validation CSV들을 읽어 market/mode/horizon별 보정 파라미터를 계산하고
    correction_store에 저장한다.

    Returns
    -------
    새로 저장된 params 딕셔너리
    """
    all_rows = _load_validation_results(market)
    rec_rows = _load_recommendation_csvs(market)

    # 검증 결과와 추천을 symbol+generatedAt로 매칭
    rec_index: dict[str, dict[str, Any]] = {}
    for r in rec_rows:
        sym = str(r.get("symbol") or "")
        gen = str(r.get("generatedAt") or "")[:16]
        mode = str(r.get("mode") or "")
        horizon = str(r.get("horizon") or "")
        if sym:
            rec_index[f"{sym}_{gen}_{mode}_{horizon}"] = r

    # 각 validation row에 outcomeReason 부여
    analyzed: list[dict[str, Any]] = []
    for row in all_rows:
        sym = str(row.get("symbol") or "")
        gen = str(row.get("generatedAt") or "")[:16]
        mode = str(row.get("mode") or "")
        horizon = str(row.get("horizon") or "")
        rec = rec_index.get(f"{sym}_{gen}_{mode}_{horizon}", row)
        reason = outcome_analyzer.classify_outcome(rec, row)
        analyzed.append({**row, "outcomeReason": reason})

    # market/mode/horizon별로 그룹화
    groups = _group_by_combo(analyzed)
    old_params = correction_store.load_params()
    old_version = int(old_params.get("version", 0))

    markets_dict: dict[str, Any] = {}
    for key, rows in groups.items():
        sample_count = len(rows)
        confidence = _compute_confidence(sample_count)

        counts = outcome_analyzer.reason_counts(rows)
        top_failures = outcome_analyzer.top_failure_reasons(rows)

        # 학습 제외 샘플(DATA_STALE) 제거 후 집계
        learnable = [r for r in rows if r.get("outcomeReason") != "DATA_STALE"]
        learnable_count = len(learnable)
        learnable_counts = outcome_analyzer.reason_counts(learnable)

        weight_adj  = _build_weight_adjustments(learnable_counts, learnable_count)
        price_adj   = _build_price_adjustments(learnable_counts, learnable_count)
        filter_adj  = _build_filter_adjustments(learnable_counts, learnable_count)

        parts = key.split("_", 2)
        mkt   = parts[0] if len(parts) > 0 else market
        mode  = parts[1] if len(parts) > 1 else "balanced"
        hor   = parts[2] if len(parts) > 2 else "swing"

        markets_dict[key] = {
            "market": mkt,
            "mode": mode,
            "horizon": hor,
            "sampleCount": sample_count,
            "learnableSampleCount": learnable_count,
            "confidence": confidence,
            "weightAdjustments": weight_adj if confidence >= _MIN_CONFIDENCE else {},
            "priceAdjustments": price_adj if confidence >= _MIN_CONFIDENCE else {
                "entryAggressiveness": 0.0, "targetMultiplier": 0.0, "stopAtrMultiplier": 0.0,
            },
            "filterAdjustments": filter_adj if confidence >= _MIN_CONFIDENCE else {
                "maxDistanceToEntryPct": 0.0, "minRiskRewardRatio": 0.0,
            },
            "topFailureReasons": top_failures,
            "reasonCounts": counts,
            "appliedAt": datetime.now(timezone.utc).isoformat(),
        }

    new_params = {
        "version": old_version + 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "market": market,
        "totalSamples": len(all_rows),
        "markets": markets_dict,
    }
    correction_store.save_params(new_params)
    return new_params


def apply_correction(
    score_components: dict[str, float],
    entry: float,
    target: float,
    stop: float,
    market: str,
    mode: str,
    horizon: str,
) -> dict[str, Any]:
    """
    현재 보정 파라미터를 로드해 점수/가격에 적용한다.

    Returns
    -------
    {
        "adjustedScores": {...},
        "adjustedEntry": float,
        "adjustedTarget": float,
        "adjustedStop": float,
        "correctionApplied": bool,
        "correctionConfidence": float,
        "correctionSummary": str,
        "appliedCorrectionVersion": int,
    }
    """
    version = correction_store.load_params().get("version", 0)

    # 킬스위치: SELF_CORRECTION_ENABLED=false → 즉시 원래 값 반환
    if not _correction_enabled():
        return {
            "adjustedScores": score_components,
            "adjustedEntry": entry,
            "adjustedTarget": target,
            "adjustedStop": stop,
            "correctionApplied": False,
            "correctionConfidence": 0.0,
            "correctionSummary": "보정 비활성화 (SELF_CORRECTION_ENABLED=false)",
            "appliedCorrectionVersion": version,
        }

    strength = _correction_strength()
    params = correction_store.load_correction(market, mode, horizon)
    confidence = float(params.get("confidence") or 0.0)

    if confidence < _MIN_CONFIDENCE or int(params.get("sampleCount", 0)) < _MIN_SAMPLES:
        return {
            "adjustedScores": score_components,
            "adjustedEntry": entry,
            "adjustedTarget": target,
            "adjustedStop": stop,
            "correctionApplied": False,
            "correctionConfidence": confidence,
            "correctionSummary": f"보정 미적용 (샘플부족 또는 낮은 신뢰도 confidence={confidence:.2f})",
            "appliedCorrectionVersion": version,
        }

    # 점수 보정 (strength 배율 적용)
    adjusted_scores = dict(score_components)
    weight_adj = params.get("weightAdjustments") or {}
    for comp, delta in weight_adj.items():
        if comp in adjusted_scores:
            adjusted_scores[comp] = round(
                _clamp(adjusted_scores[comp] + delta * 10 * strength, 0, 100), 2
            )

    # 가격 보정 (strength 배율 적용)
    price_adj = params.get("priceAdjustments") or {}
    entry_delta  = float(price_adj.get("entryAggressiveness", 0.0)) * strength
    target_delta = float(price_adj.get("targetMultiplier", 0.0)) * strength
    stop_delta   = float(price_adj.get("stopAtrMultiplier", 0.0)) * strength

    adj_entry  = entry  * (1 + entry_delta * 0.01) if entry else entry
    adj_target = target * (1 + target_delta)        if target else target
    adj_stop   = stop   * (1 - stop_delta * 0.1)   if stop else stop

    top_reasons = params.get("topFailureReasons") or []
    summary = (
        f"보정 적용 (confidence={confidence:.2f}, strength={strength:.2f}, "
        f"주요실패={','.join(top_reasons[:3])})"
    )

    def _price_round(p: float | None, fallback: float) -> float:
        if not p:
            return fallback
        return float(round_to_kr_tick(p)) if market == "kr" else round(p, 2)

    adj_entry_out  = _price_round(adj_entry, entry)
    adj_target_out = _price_round(adj_target, target)
    adj_stop_out   = _price_round(adj_stop, stop)

    rr_actual = None
    if adj_entry_out and adj_stop_out and adj_target_out and adj_entry_out > 0:
        reward_pct = (adj_target_out - adj_entry_out) / adj_entry_out * 100.0
        risk_pct   = abs((adj_entry_out - adj_stop_out) / adj_entry_out * 100.0)
        if risk_pct > 0:
            rr_actual = round(reward_pct / risk_pct, 2)

    return {
        "adjustedScores": adjusted_scores,
        "adjustedEntry": adj_entry_out,
        "adjustedTarget": adj_target_out,
        "adjustedStop": adj_stop_out,
        "adjustedRrActual": rr_actual,
        "correctionApplied": True,
        "correctionConfidence": confidence,
        "correctionStrength": strength,
        "correctionSummary": summary,
        "appliedCorrectionVersion": version,
    }
