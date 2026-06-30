from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any, Iterable

from app.services import trade_failure_analytics as failure_analytics
from app.services import virtual_trade_journal as vtj

STOP_FAILURE_REASONS = {"STOP_TOO_TIGHT", "STOP_BEFORE_TARGET"}
COMPARISON_REASONS = {
    "TARGET_BEFORE_STOP",
    "TARGET_NOT_REACHED",
    "ENTRY_NOT_TOUCHED",
    "ENTRY_TOUCHED_BUT_NO_EXIT",
    "OVEREXTENDED_ENTRY",
    "MARKET_GAP",
    "MISSED_PROFIT_CAPTURE",
    "HIGH_DRAWDOWN_BEFORE_SUCCESS",
}

MIN_PATCH_SAMPLE_SIZE = 40
MIN_CAUSE_SAMPLE_SIZE = 8


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _upper(value: Any) -> str:
    return _text(value).upper()


def _raw(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_recommendation")
    if isinstance(raw, dict):
        return raw
    return failure_analytics._raw(row)


def _first(row: dict[str, Any], *keys: str) -> Any:
    raw = _raw(row)
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return ""


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        n = float(str(value).replace(",", "").replace("%", ""))
    except Exception:
        return None
    return n if math.isfinite(n) else None


def _bool_value(row: dict[str, Any], field: str) -> bool | None:
    return failure_analytics._bool_value(row, field)


def _reason(row: dict[str, Any]) -> str:
    return failure_analytics._failure_reason(row)


def _is_evaluated_outcome(row: dict[str, Any]) -> bool:
    reason = _reason(row)
    return failure_analytics.failure_reason_group(reason) == failure_analytics.REASON_GROUP_EVALUATED


def _is_stop_failure(row: dict[str, Any]) -> bool:
    return _reason(row) in STOP_FAILURE_REASONS


def _return_value(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "net_pnl_pct", "returnPct", "return_pct", "pnl_pct"))


def _mfe(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "maxFavorableExcursion", "mfe_pct"))


def _mae(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "maxAdverseExcursion", "mae_pct"))


def _holding_days(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "holdingDays", "bars_held"))


def _setup_score(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "setup_score", "setupScore"))


def _overextension_risk(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "overextension_risk", "overextensionRisk"))


def _momentum_score(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "momentum_continuation_score", "momentumContinuationScore"))


def _final_score(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "finalScore", "final_score", "finalRankScore", "_final_score"))


def _holding_bucket(row: dict[str, Any]) -> str:
    return failure_analytics._holding_bucket(row)


def _recommendation_bucket(row: dict[str, Any]) -> str:
    return failure_analytics._recommendation_bucket(row)


def _regime(row: dict[str, Any]) -> str:
    return failure_analytics._regime(row)


def _tercile(value: float | None, *, inverted: bool = False) -> str:
    if value is None:
        return "unknown"
    if value < 33.333:
        bucket = "low"
    elif value < 66.667:
        bucket = "mid"
    else:
        bucket = "high"
    if inverted:
        return {"low": "high", "mid": "mid", "high": "low"}[bucket]
    return bucket


def _dimension_value(row: dict[str, Any], field: str) -> str:
    if field == "market":
        return _text(row.get("market")).lower() or "unknown"
    if field == "mode":
        return _text(row.get("mode")).lower() or "unknown"
    if field == "horizon":
        return _text(row.get("horizon")).lower() or "unknown"
    if field == "holdingDaysBucket":
        return _holding_bucket(row)
    if field == "recommendationBucket":
        return _recommendation_bucket(row)
    if field == "regime":
        return _regime(row)
    if field == "overextensionRisk":
        return _tercile(_overextension_risk(row))
    if field == "setupScore":
        return _tercile(_setup_score(row))
    if field == "momentumContinuation":
        return _tercile(_momentum_score(row))
    if field == "entryTouched":
        value = _bool_value(row, "entryTouched")
        return "true" if value is True else "false" if value is False else "unknown"
    if field == "marketGap":
        return "true" if _reason(row) == "MARKET_GAP" else "false"
    if field == "overextendedEntry":
        return "true" if _reason(row) == "OVEREXTENDED_ENTRY" else "false"
    if field == "stopTooTight":
        return "true" if _reason(row) == "STOP_TOO_TIGHT" else "false"
    return _text(row.get(field)) or "unknown"


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _rate(rows: list[dict[str, Any]], field: str) -> float | None:
    return failure_analytics._rate(rows, field)


def _metrics(rows: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    denominator = total if total is not None else len(rows)
    returns = [value for row in rows if (value := _return_value(row)) is not None]
    mfes = [value for row in rows if (value := _mfe(row)) is not None]
    maes = [value for row in rows if (value := _mae(row)) is not None]
    holding_days = [value for row in rows if (value := _holding_days(row)) is not None]
    stop_rows = [row for row in rows if _is_stop_failure(row)]
    stop_too_tight = sum(1 for row in rows if _reason(row) == "STOP_TOO_TIGHT")
    stop_before_target = sum(1 for row in rows if _reason(row) == "STOP_BEFORE_TARGET")
    wins = sum(1 for row in rows if _reason(row) == "TARGET_BEFORE_STOP" or ((_return_value(row) or 0) > 0))
    return {
        "count": len(rows),
        "ratio": round(len(rows) / denominator, 4) if denominator else 0.0,
        "stopFailureTrades": len(stop_rows),
        "stopFailureRate": round(len(stop_rows) / len(rows), 4) if rows else 0.0,
        "stopTooTightCount": stop_too_tight,
        "stopTooTightRate": round(stop_too_tight / len(rows), 4) if rows else 0.0,
        "stopBeforeTargetCount": stop_before_target,
        "stopBeforeTargetRate": round(stop_before_target / len(rows), 4) if rows else 0.0,
        "avgReturn": _avg(returns),
        "medianReturn": round(median(returns), 4) if returns else None,
        "winRate": round(wins / len(rows), 4) if rows else None,
        "avgMFE": _avg(mfes),
        "avgMAE": _avg(maes),
        "avgHoldingDays": _avg(holding_days),
        "targetBeforeStopRate": _rate(rows, "targetBeforeStop"),
        "stopTouchedRate": _rate(rows, "stopTouched"),
        "entryTouchedRate": _rate(rows, "entryTouched"),
    }


def _group_rows(rows: Iterable[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_dimension_value(row, field)].append(row)
    return groups


def _dimension(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    items = []
    total = len(rows)
    for value, group in _group_rows(rows, field).items():
        item = {field: value}
        item.update(_metrics(group, total))
        items.append(item)
    return sorted(items, key=lambda item: (-float(item.get("stopFailureRate") or 0), -int(item.get("count") or 0), str(item.get(field) or "")))


def _mean_score(rows: list[dict[str, Any]], getter) -> float | None:
    values = [value for row in rows if (value := getter(row)) is not None]
    return _avg(values)


def _comparison(stop_rows: list[dict[str, Any]], non_stop_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "stopFailureGroup": {
            **_metrics(stop_rows),
            "avgSetupScore": _mean_score(stop_rows, _setup_score),
            "avgOverextensionRisk": _mean_score(stop_rows, _overextension_risk),
            "avgMomentumContinuationScore": _mean_score(stop_rows, _momentum_score),
            "avgFinalScore": _mean_score(stop_rows, _final_score),
        },
        "nonStopFailureGroup": {
            **_metrics(non_stop_rows),
            "avgSetupScore": _mean_score(non_stop_rows, _setup_score),
            "avgOverextensionRisk": _mean_score(non_stop_rows, _overextension_risk),
            "avgMomentumContinuationScore": _mean_score(non_stop_rows, _momentum_score),
            "avgFinalScore": _mean_score(non_stop_rows, _final_score),
        },
    }


def _top_item(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    candidates = [item for item in items if str(item.get(key) or "") not in {"unknown", "false"} and int(item.get("count") or 0) >= MIN_CAUSE_SAMPLE_SIZE]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-float(item.get("stopFailureRate") or 0), -int(item.get("stopFailureTrades") or 0)))[0]


def _cause_candidates(
    evaluated_rows: list[dict[str, Any]],
    stop_rows: list[dict[str, Any]],
    dimensions: dict[str, list[dict[str, Any]]],
    comparison: dict[str, Any],
) -> list[dict[str, Any]]:
    total = len(evaluated_rows)
    stop_total = len(stop_rows)
    candidates: list[dict[str, Any]] = []

    overext = _top_item(dimensions.get("byOverextensionRisk", []), "overextensionRisk")
    overext_reason_count = sum(1 for row in stop_rows if _reason(row) == "OVEREXTENDED_ENTRY")
    if overext and (overext.get("overextensionRisk") == "high" or overext_reason_count > 0):
        candidates.append({
            "causeType": "OVEREXTENSION_RISK_HIGH",
            "title": "과열 진입 연관성",
            "summary": "손절 실패가 과열 위험 high 또는 OVEREXTENDED_ENTRY 표본과 함께 나타나는지 점검해야 합니다.",
            "evidence": {
                "count": int(overext.get("count") or 0),
                "stopFailureTrades": int(overext.get("stopFailureTrades") or 0),
                "stopFailureRate": overext.get("stopFailureRate"),
                "overextendedEntryStopFailures": overext_reason_count,
            },
        })

    market_gap_count = sum(1 for row in stop_rows if _reason(row) == "MARKET_GAP")
    gap_item = _top_item(dimensions.get("byMarketGap", []), "marketGap")
    if market_gap_count > 0 or (gap_item and float(gap_item.get("stopFailureRate") or 0) >= 0.35):
        candidates.append({
            "causeType": "MARKET_GAP_RISK",
            "title": "갭 변동 위험",
            "summary": "갭 변동 표본에서 손절 실패가 반복되는지 확인이 필요합니다.",
            "evidence": {
                "marketGapStopFailures": market_gap_count,
                "stopFailureRate": gap_item.get("stopFailureRate") if gap_item else None,
            },
        })

    for field, cause_type, title in (
        ("byMode", "MODE_SPECIFIC_STOP_FAILURE", "특정 모드 집중"),
        ("byMarket", "MARKET_SPECIFIC_STOP_FAILURE", "특정 시장 집중"),
    ):
        item = _top_item(dimensions.get(field, []), field[2].lower() + field[3:] if field.startswith("by") else field)
        if item and float(item.get("stopFailureRate") or 0) >= max(0.35, (stop_total / total if total else 0) * 1.25):
            dim_name = next((key for key in item.keys() if key not in {"count", "ratio", "stopFailureTrades", "stopFailureRate", "stopTooTightCount", "stopTooTightRate", "stopBeforeTargetCount", "stopBeforeTargetRate", "avgReturn", "medianReturn", "winRate", "avgMFE", "avgMAE", "avgHoldingDays", "targetBeforeStopRate", "stopTouchedRate", "entryTouchedRate"}), "segment")
            candidates.append({
                "causeType": cause_type,
                "title": title,
                "summary": f"{dim_name}={item.get(dim_name)} 구간의 손절 실패율이 상대적으로 높습니다.",
                "evidence": {
                    "segment": item.get(dim_name),
                    "count": item.get("count"),
                    "stopFailureRate": item.get("stopFailureRate"),
                },
            })

    stop_cmp = comparison.get("stopFailureGroup") or {}
    non_stop_cmp = comparison.get("nonStopFailureGroup") or {}
    stop_mfe = stop_cmp.get("avgMFE")
    stop_mae = stop_cmp.get("avgMAE")
    if stop_mfe is not None and stop_mae is not None and stop_mfe > 0 and abs(float(stop_mae)) >= max(5.0, float(stop_mfe)):
        candidates.append({
            "causeType": "ENTRY_TIMING_TOO_EARLY",
            "title": "진입 타이밍 역행폭",
            "summary": "MFE는 양수지만 MAE가 더 깊어 진입 직후 역행폭 검증이 필요합니다.",
            "evidence": {"avgMFE": stop_mfe, "avgMAE": stop_mae},
        })

    stop_setup = stop_cmp.get("avgSetupScore")
    non_stop_setup = non_stop_cmp.get("avgSetupScore")
    stop_momentum = stop_cmp.get("avgMomentumContinuationScore")
    non_stop_momentum = non_stop_cmp.get("avgMomentumContinuationScore")
    if (
        stop_setup is not None
        and non_stop_setup is not None
        and stop_setup + 5 < non_stop_setup
    ) or (
        stop_momentum is not None
        and non_stop_momentum is not None
        and stop_momentum + 5 < non_stop_momentum
    ):
        candidates.append({
            "causeType": "WEAK_CANDIDATE_QUALITY",
            "title": "후보 품질 약화",
            "summary": "손절 실패 그룹의 setup/momentum 진단 점수가 비손절 그룹보다 낮습니다.",
            "evidence": {
                "avgSetupScoreStop": stop_setup,
                "avgSetupScoreNonStop": non_stop_setup,
                "avgMomentumStop": stop_momentum,
                "avgMomentumNonStop": non_stop_momentum,
            },
        })

    if stop_total >= MIN_CAUSE_SAMPLE_SIZE and not candidates:
        candidates.append({
            "causeType": "STOP_BAND_DESIGN_WEAK",
            "title": "손절 설계 추가 검증",
            "summary": "과열/갭/시장/모드로 명확히 설명되지 않는 손절 실패가 남아 있습니다. 산식 변경 전 추가 백테스트가 필요합니다.",
            "evidence": {"stopFailureTrades": stop_total, "stopFailureRate": round(stop_total / total, 4) if total else 0.0},
        })

    return candidates[:5]


def _patch_decision(total: int, stop_count: int, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    stop_rate = stop_count / total if total else 0.0
    if total < MIN_PATCH_SAMPLE_SIZE:
        reason = "평가 완료 표본이 작아 운영 로직 변경 대신 진단만 제공합니다."
    elif stop_rate < 0.2:
        reason = "손절 실패율이 운영 로직 변경 임계값보다 낮아 진단만 제공합니다."
    elif not candidates:
        reason = "원인 후보가 명확하지 않아 과적합을 피하기 위해 운영 패치를 적용하지 않았습니다."
    else:
        reason = "원인 후보는 관측되었지만 before/after 검증 없이 추천 action downgrade를 적용하지 않았습니다."
    return {
        "appliedPatch": False,
        "patchType": "diagnostic_only",
        "patchReason": reason,
        "shouldModifyTradingLogicNow": False,
        "backtest": {
            "available": False,
            "reason": "현재 변경은 진단 엔진/API/UI 추가이며 추천 후보 제외, action 변경, 가격 산식 변경을 수행하지 않았습니다.",
            "beforeAfter": None,
            "recommendationCountChange": 0,
            "actionDowngradeCount": 0,
            "affectedTradeCount": 0,
        },
    }


def empty_response(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
) -> dict[str, Any]:
    return {
        "status": "OK",
        "source": "",
        "scope": {
            "market": market,
            "mode": mode,
            "horizon": horizon,
            "sourceType": source_type,
            "journalSession": journal_session,
        },
        "summary": {
            "totalEvaluatedTrades": 0,
            "stopFailureTrades": 0,
            "stopFailureRate": 0.0,
            "stopTooTightCount": 0,
            "stopTooTightRate": 0.0,
            "stopBeforeTargetCount": 0,
            "stopBeforeTargetRate": 0.0,
            "avgMFE": None,
            "avgMAE": None,
            "targetBeforeStopRate": None,
            "stopTouchedRate": None,
        },
        "dimensions": {
            "byMarket": [],
            "byMode": [],
            "byHorizon": [],
            "byHoldingDaysBucket": [],
            "byRegime": [],
            "byRecommendationBucket": [],
            "byOverextensionRisk": [],
            "bySetupScore": [],
            "byMomentumContinuation": [],
        },
        "comparison": _comparison([], []),
        "causeCandidates": [],
        "patch": _patch_decision(0, 0, []),
        "appliedPatch": False,
        "patchType": "diagnostic_only",
        "patchReason": "분석 가능한 평가 완료 거래가 아직 없습니다.",
        "shouldModifyTradingLogicNow": False,
        "note": "Stop-loss diagnostics use evaluated-only virtual trade rows and do not change recommendation logic.",
    }


def build_stop_loss_diagnostics(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
) -> dict[str, Any]:
    try:
        vtj._ensure()
        rows = vtj._filter_rows(
            vtj._merge_evaluations(vtj._read_journal_rows()),
            market,
            mode,
            horizon,
            source_type,
            journal_session,
            "all",
        )
        if vtj._session_filter(journal_session) == "ALL":
            rows = [row for row in rows if vtj._is_trade_evaluation_session(row)]
    except Exception as exc:
        out = empty_response(market, mode, horizon, source_type, journal_session)
        out["warning"] = f"stop-loss diagnostics source unavailable: {exc}"
        return out

    evaluated = [row for row in rows if _is_evaluated_outcome(row)]
    if not evaluated:
        return empty_response(market, mode, horizon, source_type, journal_session)

    stop_rows = [row for row in evaluated if _is_stop_failure(row)]
    non_stop_rows = [row for row in evaluated if not _is_stop_failure(row)]
    stop_too_tight = sum(1 for row in stop_rows if _reason(row) == "STOP_TOO_TIGHT")
    stop_before_target = sum(1 for row in stop_rows if _reason(row) == "STOP_BEFORE_TARGET")
    dimensions = {
        "byMarket": _dimension(evaluated, "market"),
        "byMode": _dimension(evaluated, "mode"),
        "byHorizon": _dimension(evaluated, "horizon"),
        "byHoldingDaysBucket": _dimension(evaluated, "holdingDaysBucket"),
        "byRegime": _dimension(evaluated, "regime"),
        "byRecommendationBucket": _dimension(evaluated, "recommendationBucket"),
        "byOverextensionRisk": _dimension(evaluated, "overextensionRisk"),
        "bySetupScore": _dimension(evaluated, "setupScore"),
        "byMomentumContinuation": _dimension(evaluated, "momentumContinuation"),
        "byEntryTouched": _dimension(evaluated, "entryTouched"),
        "byMarketGap": _dimension(evaluated, "marketGap"),
        "byOverextendedEntry": _dimension(evaluated, "overextendedEntry"),
        "byStopTooTight": _dimension(evaluated, "stopTooTight"),
    }
    comparison = _comparison(stop_rows, non_stop_rows)
    candidates = _cause_candidates(evaluated, stop_rows, dimensions, comparison)
    patch = _patch_decision(len(evaluated), len(stop_rows), candidates)

    mfes = [value for row in evaluated if (value := _mfe(row)) is not None]
    maes = [value for row in evaluated if (value := _mae(row)) is not None]
    summary = {
        "totalEvaluatedTrades": len(evaluated),
        "stopFailureTrades": len(stop_rows),
        "stopFailureRate": round(len(stop_rows) / len(evaluated), 4) if evaluated else 0.0,
        "stopTooTightCount": stop_too_tight,
        "stopTooTightRate": round(stop_too_tight / len(evaluated), 4) if evaluated else 0.0,
        "stopBeforeTargetCount": stop_before_target,
        "stopBeforeTargetRate": round(stop_before_target / len(evaluated), 4) if evaluated else 0.0,
        "avgMFE": _avg(mfes),
        "avgMAE": _avg(maes),
        "targetBeforeStopRate": _rate(evaluated, "targetBeforeStop"),
        "stopTouchedRate": _rate(evaluated, "stopTouched"),
        "overextensionAssociationRate": next((item.get("stopFailureRate") for item in dimensions["byOverextensionRisk"] if item.get("overextensionRisk") == "high"), None),
        "marketGapAssociationRate": next((item.get("stopFailureRate") for item in dimensions["byMarketGap"] if item.get("marketGap") == "true"), None),
    }
    return {
        "status": "OK",
        "source": vtj._relative(vtj.EVALUATION_CSV),
        "scope": empty_response(market, mode, horizon, source_type, journal_session)["scope"],
        "summary": summary,
        "dimensions": dimensions,
        "comparison": comparison,
        "causeCandidates": candidates,
        "patch": patch,
        "appliedPatch": patch["appliedPatch"],
        "patchType": patch["patchType"],
        "patchReason": patch["patchReason"],
        "shouldModifyTradingLogicNow": patch["shouldModifyTradingLogicNow"],
        "note": "Stop-loss diagnostics use evaluated-only virtual trade rows and do not change recommendation logic.",
    }
