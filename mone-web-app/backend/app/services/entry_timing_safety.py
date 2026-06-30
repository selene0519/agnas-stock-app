from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any, Iterable

from app.services import trade_failure_analytics as failure_analytics
from app.services import virtual_trade_journal as vtj

PENDING_REASONS = {"INSUFFICIENT_HOLDING_PERIOD", "PENDING_EVALUATION", "NO_FUTURE_BARS_YET"}
DATA_QUALITY_REASONS = {
    "DATA_MISSING",
    "PRICE_INVALID",
    "INVALID_PRICE_PATH",
    "SYMBOL_OR_DATE_MISMATCH",
    "MISSING_ENTRY_PRICE",
    "MISSING_TARGET_OR_STOP",
}
ENTRY_TIMING_RISK_REASONS = {
    "STOP_TOO_TIGHT",
    "STOP_BEFORE_TARGET",
    "OVEREXTENDED_ENTRY",
    "MARKET_GAP",
    "HIGH_DRAWDOWN_BEFORE_SUCCESS",
    "ENTRY_TOUCHED_BUT_NO_EXIT",
    "TARGET_NOT_REACHED",
}
STOP_FAILURE_REASONS = {"STOP_TOO_TIGHT", "STOP_BEFORE_TARGET"}
GUARD_VERSION = "v1"
MIN_ACTIVATION_SAMPLE = 40
MIN_AFFECTED_SAMPLE = 8


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


def _reason(row: dict[str, Any]) -> str:
    return failure_analytics._failure_reason(row)


def _bool_value(row: dict[str, Any], field: str) -> bool | None:
    return failure_analytics._bool_value(row, field)


def _is_evaluated_outcome(row: dict[str, Any]) -> bool:
    reason = _reason(row)
    if reason in PENDING_REASONS or reason in DATA_QUALITY_REASONS:
        return False
    return failure_analytics.failure_reason_group(reason) == failure_analytics.REASON_GROUP_EVALUATED


def _return_value(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "net_pnl_pct", "returnPct", "return_pct", "pnl_pct"))


def _mfe(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "maxFavorableExcursion", "mfe_pct"))


def _mae(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "maxAdverseExcursion", "mae_pct"))


def _setup_score(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "setup_score", "setupScore"))


def _overextension_risk(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "overextension_risk", "overextensionRisk"))


def _momentum_score(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "momentum_continuation_score", "momentumContinuationScore"))


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _rate(rows: list[dict[str, Any]], field: str) -> float | None:
    return failure_analytics._rate(rows, field)


def _dimension_value(row: dict[str, Any], field: str) -> str:
    if field == "market":
        return _text(row.get("market")).lower() or "unknown"
    if field == "mode":
        return _text(row.get("mode")).lower() or "unknown"
    if field == "horizon":
        return _text(row.get("horizon")).lower() or "unknown"
    if field == "regime":
        return failure_analytics._regime(row)
    if field == "recommendationBucket":
        return failure_analytics._recommendation_bucket(row)
    if field == "riskLevel":
        return compute_entry_timing_risk(row)["entryTimingRiskLevel"]
    return _text(row.get(field)) or "unknown"


def _group_rows(rows: Iterable[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_dimension_value(row, field)].append(row)
    return groups


def _metrics(rows: list[dict[str, Any]], denominator: int | None = None) -> dict[str, Any]:
    denominator = denominator if denominator is not None else len(rows)
    returns = [value for row in rows if (value := _return_value(row)) is not None]
    mfes = [value for row in rows if (value := _mfe(row)) is not None]
    maes = [value for row in rows if (value := _mae(row)) is not None]
    stop_failure = sum(1 for row in rows if _reason(row) in STOP_FAILURE_REASONS)
    stop_too_tight = sum(1 for row in rows if _reason(row) == "STOP_TOO_TIGHT")
    stop_before_target = sum(1 for row in rows if _reason(row) == "STOP_BEFORE_TARGET")
    wins = sum(1 for row in rows if _reason(row) == "TARGET_BEFORE_STOP" or ((_return_value(row) or 0) > 0))
    return {
        "count": len(rows),
        "ratio": round(len(rows) / denominator, 4) if denominator else 0.0,
        "avgReturn": _avg(returns),
        "medianReturn": round(median(returns), 4) if returns else None,
        "winRate": round(wins / len(rows), 4) if rows else None,
        "avgMFE": _avg(mfes),
        "avgMAE": _avg(maes),
        "stopFailureTrades": stop_failure,
        "stopFailureRate": round(stop_failure / len(rows), 4) if rows else 0.0,
        "stopTooTightRate": round(stop_too_tight / len(rows), 4) if rows else 0.0,
        "stopBeforeTargetRate": round(stop_before_target / len(rows), 4) if rows else 0.0,
        "targetBeforeStopRate": _rate(rows, "targetBeforeStop"),
        "stopBeforeTargetRateByTouch": round(
            sum(1 for row in rows if _bool_value(row, "stopTouched") is True and _bool_value(row, "targetBeforeStop") is not True) / len(rows),
            4,
        )
        if rows
        else 0.0,
        "entryTouchedRate": _rate(rows, "entryTouched"),
    }


def _dimension(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    total = len(rows)
    items = []
    for value, group in _group_rows(rows, field).items():
        item = {field: value}
        item.update(_metrics(group, total))
        items.append(item)
    return sorted(items, key=lambda item: (-int(item.get("count") or 0), str(item.get(field) or "")))


def _original_action(row: dict[str, Any]) -> str:
    action = _upper(_first(row, "action", "recommendationAction", "recommendation_action", "signalAction"))
    if action:
        return action
    bucket = _upper(_first(row, "decision_bucket", "decisionBucket", "newEntryDecision", "recommendationBucket"))
    if bucket in {"TODAY_ENTRY", "BUY", "STRONG_BUY", "오늘 진입"}:
        return "BUY"
    if bucket in {"CONDITIONAL_ENTRY", "WATCH_ENTRY", "WATCH", "조건부 진입", "대기 관찰"}:
        return "WATCH"
    if bucket in {"HOLD"}:
        return "HOLD"
    return bucket or "UNKNOWN"


def _adjusted_action(original_action: str, risk_level: str) -> str:
    action = _upper(original_action)
    if risk_level != "HIGH":
        return action
    if action in {"BUY", "STRONG_BUY"}:
        return "WAIT_PULLBACK"
    if action in {"WATCH", "HOLD"}:
        return "CAUTION"
    return action


def compute_entry_timing_risk(row: dict[str, Any]) -> dict[str, Any]:
    reason = _reason(row)
    score = 0
    reasons: list[str] = []
    overextension = _overextension_risk(row)
    setup = _setup_score(row)
    momentum = _momentum_score(row)
    mfe = _mfe(row)
    mae = _mae(row)

    if overextension is not None and overextension >= 66.667:
        score += 2
        reasons.append("OVEREXTENSION_RISK_HIGH")
    if reason == "OVEREXTENDED_ENTRY":
        score += 2
        reasons.append("OVEREXTENDED_ENTRY")
    if reason == "MARKET_GAP":
        score += 1
        reasons.append("MARKET_GAP")
    if mae is not None and abs(mae) >= 5.0 and (mfe is None or abs(mae) >= max(5.0, abs(mfe) * 1.2)):
        score += 2
        reasons.append("MAE_DEEPER_THAN_MFE")
    if reason in STOP_FAILURE_REASONS:
        score += 2
        reasons.append(reason)
    if momentum is not None and momentum < 33.333 and overextension is not None and overextension >= 66.667:
        score += 1
        reasons.append("LOW_MOMENTUM_WITH_OVEREXTENSION")
    if setup is not None and setup < 50 and reason in STOP_FAILURE_REASONS:
        score += 1
        reasons.append("LOW_SETUP_IN_STOP_FAILURE_GROUP")

    if score >= 4:
        level = "HIGH"
    elif score >= 2:
        level = "MEDIUM"
    else:
        level = "LOW"
    original = _original_action(row)
    adjusted = _adjusted_action(original, level)
    safety_action = "NONE" if adjusted == original else adjusted
    return {
        "entryTimingRiskScore": score,
        "entryTimingRiskLevel": level,
        "entryTimingRiskReasons": reasons,
        "recommendedSafetyAction": safety_action,
        "originalAction": original,
        "adjustedAction": adjusted,
        "actionAdjustmentReason": "; ".join(reasons) if adjusted != original else "",
        "entryTimingGuardApplied": False,
        "entryTimingGuardVersion": GUARD_VERSION,
        "entryTimingGuardMode": "diagnostic_only",
    }


def _risk_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if _reason(row) in ENTRY_TIMING_RISK_REASONS or compute_entry_timing_risk(row)["entryTimingRiskLevel"] in {"MEDIUM", "HIGH"}]


def _annotate(row: dict[str, Any]) -> dict[str, Any]:
    risk = compute_entry_timing_risk(row)
    return {
        "journalId": row.get("journal_id") or row.get("journalId") or "",
        "market": _text(row.get("market")).lower() or "unknown",
        "mode": _text(row.get("mode")).lower() or "unknown",
        "horizon": _text(row.get("horizon")).lower() or "unknown",
        "symbol": row.get("symbol") or "",
        "failureReason": _reason(row),
        "label": failure_analytics.failure_reason_label(_reason(row)),
        "avgReturn": _return_value(row),
        "avgMFE": _mfe(row),
        "avgMAE": _mae(row),
        **risk,
    }


def _risk_reason_top(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        risk = compute_entry_timing_risk(row)
        for reason in risk["entryTimingRiskReasons"]:
            counts[reason] += 1
    return [
        {"reason": reason, "count": count, "ratio": round(count / len(rows), 4) if rows else 0.0}
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]


def _before_after(evaluated: list[dict[str, Any]], affected: list[dict[str, Any]]) -> dict[str, Any]:
    affected_ids = {id(row) for row in affected}
    adjusted_rows = [row for row in evaluated if id(row) not in affected_ids]
    before = _metrics(evaluated)
    after = _metrics(adjusted_rows)
    return {
        "baseline": before,
        "diagnosticOnly": {
            **before,
            "actionDowngradeCount": 0,
            "recommendationCountChange": 0,
        },
        "activeGuard": {
            **after,
            "affectedTrades": len(affected),
            "actionDowngradeCount": len(affected),
            "recommendationCountChange": -len(affected),
        },
        "evaluatedTrades": len(evaluated),
        "affectedTrades": len(affected),
        "actionDowngradeCount": len(affected),
        "recommendationCountChange": -len(affected),
        "stopFailureRateBefore": before["stopFailureRate"],
        "stopFailureRateAfter": after["stopFailureRate"],
        "stopTooTightRateBefore": before["stopTooTightRate"],
        "stopTooTightRateAfter": after["stopTooTightRate"],
        "stopBeforeTargetRateBefore": before["stopBeforeTargetRate"],
        "stopBeforeTargetRateAfter": after["stopBeforeTargetRate"],
        "targetBeforeStopRateBefore": before["targetBeforeStopRate"],
        "targetBeforeStopRateAfter": after["targetBeforeStopRate"],
        "avgReturnBefore": before["avgReturn"],
        "avgReturnAfter": after["avgReturn"],
        "medianReturnBefore": before["medianReturn"],
        "medianReturnAfter": after["medianReturn"],
        "winRateBefore": before["winRate"],
        "winRateAfter": after["winRate"],
        "avgMFEBefore": before["avgMFE"],
        "avgMFEAfter": after["avgMFE"],
        "avgMAEBefore": before["avgMAE"],
        "avgMAEAfter": after["avgMAE"],
    }


_PROSPECTIVE_ONLY_REASONS = {"OVEREXTENSION_RISK_HIGH", "LOW_MOMENTUM_WITH_OVEREXTENSION"}


def _lookahead_bias_check(evaluated: list[dict[str, Any]], affected: list[dict[str, Any]]) -> dict[str, Any]:
    """Check whether HIGH-risk classification can be reproduced using only data
    available at the moment a live recommendation is issued (i.e. without
    maxFavorableExcursion/maxAdverseExcursion/failureReason, which only exist
    after the trade has already played out)."""
    have_prospective_fields = sum(
        1
        for row in evaluated
        if _overextension_risk(row) is not None or _momentum_score(row) is not None or _setup_score(row) is not None
    )
    reachable_without_outcome_data = 0
    for row in affected:
        risk = compute_entry_timing_risk(row)
        outcome_reasons = set(risk["entryTimingRiskReasons"]) - _PROSPECTIVE_ONLY_REASONS
        if not outcome_reasons:
            reachable_without_outcome_data += 1
    return {
        "evaluatedTradesWithProspectiveFeatureData": have_prospective_fields,
        "affectedTrades": len(affected),
        "affectedTradesReachableWithoutOutcomeData": reachable_without_outcome_data,
        "affectedTradesRequiringOutcomeData": len(affected) - reachable_without_outcome_data,
        "lookaheadBiasDetected": bool(affected) and reachable_without_outcome_data == 0,
    }


def _activation_decision(
    evaluated: list[dict[str, Any]],
    affected: list[dict[str, Any]],
    replay: dict[str, Any],
    lookahead: dict[str, Any],
) -> dict[str, Any]:
    before_stop = float(replay.get("stopFailureRateBefore") or 0)
    after_stop = float(replay.get("stopFailureRateAfter") or 0)
    before_return = replay.get("avgReturnBefore")
    after_return = replay.get("avgReturnAfter")
    reasons = []
    if lookahead.get("lookaheadBiasDetected"):
        reasons.append(
            "HIGH risk로 분류된 거래 "
            f"{lookahead.get('affectedTrades', 0)}건 전부가 maxAdverseExcursion/maxFavorableExcursion/"
            "failureReason처럼 거래가 끝난 뒤에만 알 수 있는 사후 데이터에 의존하고 있습니다 "
            "(추천 시점에 알 수 있는 overextensionRisk/momentumContinuationScore만으로는 HIGH 임계값에 "
            "도달한 거래가 0건입니다). 따라서 이 리플레이의 손절실패율/수익률 개선은 실제 사전 예측력이 "
            "아니라 이미 결과를 아는 거래를 사후에 제외한 효과이며, 라이브 추천 단계에서는 재현할 수 없습니다."
        )
    if len(evaluated) < MIN_ACTIVATION_SAMPLE:
        reasons.append("평가 완료 표본이 작아 active guard를 적용하지 않았습니다.")
    if len(affected) < MIN_AFFECTED_SAMPLE:
        reasons.append("action downgrade 후보 표본이 작아 과적합 위험이 큽니다.")
    if after_stop >= before_stop:
        reasons.append("active-guard 리플레이에서 손절 실패율 감소가 확인되지 않았습니다.")
    if before_return is not None and after_return is not None and float(after_return) < float(before_return) - 0.1:
        reasons.append("active-guard 리플레이에서 평균 수익률 악화 가능성이 있습니다.")
    if not reasons:
        reasons.append("리플레이 기준은 통과했지만 현재 구현은 추천 action을 자동 변경하지 않고 프리뷰로만 제공합니다.")
    next_step = (
        "overextensionRisk/momentumContinuationScore/setupScore를 매매일지 평가 행에 보존하고, "
        "이 prospective 피처만으로 별도의 사전 위험 점수를 새로 설계·검증한 뒤에 활성화 여부를 다시 판단하세요."
        if lookahead.get("lookaheadBiasDetected")
        else "HIGH risk action downgrade 후보를 별도 검증군으로 추적한 뒤 운영 반영 여부를 다시 판단하세요."
    )
    return {
        "guardMode": "diagnostic_only",
        "appliedGuard": False,
        "activationDecision": "diagnostic_only",
        "activationReason": " ".join(reasons),
        "recommendedNextStep": next_step,
        "shouldModifyTradingLogicNow": False,
        "lookaheadBiasCheck": lookahead,
    }


def empty_response(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
    regime: str = "all",
    recommendation_bucket: str = "all",
) -> dict[str, Any]:
    scope = {
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "sourceType": source_type,
        "journalSession": journal_session,
        "regime": regime,
        "recommendationBucket": recommendation_bucket,
    }
    empty_metrics = _metrics([])
    return {
        "status": "OK",
        "source": "",
        "scope": scope,
        "summary": {
            "totalEvaluatedTrades": 0,
            "entryTimingRiskTrades": 0,
            "entryTimingRiskRate": 0.0,
            "highRiskTrades": 0,
            "highRiskRate": 0.0,
            "stopFailureTrades": 0,
            "stopFailureRate": 0.0,
            "avgMFE": None,
            "avgMAE": None,
            "medianReturn": None,
            "avgReturn": None,
            "winRate": None,
            "targetBeforeStopRate": None,
            "stopBeforeTargetRate": 0.0,
            "stopTooTightRate": 0.0,
            "entryTouchedRate": None,
            "actionDowngradeCandidateCount": 0,
        },
        "riskBreakdown": [],
        "beforeAfterReplay": {
            "baseline": empty_metrics,
            "diagnosticOnly": {**empty_metrics, "actionDowngradeCount": 0, "recommendationCountChange": 0},
            "activeGuard": {**empty_metrics, "affectedTrades": 0, "actionDowngradeCount": 0, "recommendationCountChange": 0},
        },
        "appliedGuard": False,
        "guardMode": "diagnostic_only",
        "guardVersion": GUARD_VERSION,
        "activationDecision": "diagnostic_only",
        "activationReason": "분석 가능한 평가 완료 거래가 아직 없습니다.",
        "lookaheadBiasCheck": {
            "evaluatedTradesWithProspectiveFeatureData": 0,
            "affectedTrades": 0,
            "affectedTradesReachableWithoutOutcomeData": 0,
            "affectedTradesRequiringOutcomeData": 0,
            "lookaheadBiasDetected": False,
        },
        "affectedTrades": [],
        "marketBreakdown": [],
        "modeBreakdown": [],
        "horizonBreakdown": [],
        "affectedMarketBreakdown": [],
        "affectedModeBreakdown": [],
        "affectedHorizonBreakdown": [],
        "affectedRegimeBreakdown": [],
        "recommendedNextStep": "평가 완료 거래가 쌓이면 진입 타이밍 위험군을 다시 검증하세요.",
        "shouldModifyTradingLogicNow": False,
        "note": "Entry timing safety is a diagnostic action-downgrade preview. It does not change _final_score, ranking, filters, EV, candidates, or entry/target/stop formulas.",
    }


def build_entry_timing_diagnostics(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
    regime: str = "all",
    recommendation_bucket: str = "all",
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
        regime_filter = _text(regime).lower()
        if regime_filter and regime_filter != "all":
            rows = [row for row in rows if failure_analytics._regime(row).lower() == regime_filter]
        bucket_filter = _text(recommendation_bucket).lower()
        if bucket_filter and bucket_filter != "all":
            rows = [row for row in rows if failure_analytics._recommendation_bucket(row).lower() == bucket_filter]
    except Exception as exc:
        out = empty_response(market, mode, horizon, source_type, journal_session, regime, recommendation_bucket)
        out["warning"] = f"entry timing diagnostics source unavailable: {exc}"
        return out

    evaluated = [row for row in rows if _is_evaluated_outcome(row)]
    if not evaluated:
        return empty_response(market, mode, horizon, source_type, journal_session, regime, recommendation_bucket)

    risk_rows = _risk_rows(evaluated)
    high_rows = [row for row in evaluated if compute_entry_timing_risk(row)["entryTimingRiskLevel"] == "HIGH"]
    affected = [row for row in high_rows if compute_entry_timing_risk(row)["adjustedAction"] != compute_entry_timing_risk(row)["originalAction"]]
    stop_failure = [row for row in evaluated if _reason(row) in STOP_FAILURE_REASONS]
    metrics = _metrics(evaluated)
    replay = _before_after(evaluated, affected)
    lookahead = _lookahead_bias_check(evaluated, affected)
    decision = _activation_decision(evaluated, affected, replay, lookahead)
    summary = {
        "totalEvaluatedTrades": len(evaluated),
        "entryTimingRiskTrades": len(risk_rows),
        "entryTimingRiskRate": round(len(risk_rows) / len(evaluated), 4) if evaluated else 0.0,
        "highRiskTrades": len(high_rows),
        "highRiskRate": round(len(high_rows) / len(evaluated), 4) if evaluated else 0.0,
        "stopFailureTrades": len(stop_failure),
        "stopFailureRate": metrics["stopFailureRate"],
        "avgMFE": metrics["avgMFE"],
        "avgMAE": metrics["avgMAE"],
        "medianReturn": metrics["medianReturn"],
        "avgReturn": metrics["avgReturn"],
        "winRate": metrics["winRate"],
        "targetBeforeStopRate": metrics["targetBeforeStopRate"],
        "stopBeforeTargetRate": metrics["stopBeforeTargetRate"],
        "stopTooTightRate": metrics["stopTooTightRate"],
        "entryTouchedRate": metrics["entryTouchedRate"],
        "actionDowngradeCandidateCount": len(affected),
    }
    return {
        "status": "OK",
        "source": vtj._relative(vtj.EVALUATION_CSV),
        "scope": empty_response(market, mode, horizon, source_type, journal_session, regime, recommendation_bucket)["scope"],
        "summary": summary,
        "riskBreakdown": _dimension(evaluated, "riskLevel"),
        "beforeAfterReplay": replay,
        **decision,
        "guardVersion": GUARD_VERSION,
        "affectedTrades": [_annotate(row) for row in affected[:25]],
        "marketBreakdown": _dimension(evaluated, "market"),
        "modeBreakdown": _dimension(evaluated, "mode"),
        "horizonBreakdown": _dimension(evaluated, "horizon"),
        "affectedMarketBreakdown": _dimension(affected, "market"),
        "affectedModeBreakdown": _dimension(affected, "mode"),
        "affectedHorizonBreakdown": _dimension(affected, "horizon"),
        "affectedRegimeBreakdown": _dimension(affected, "regime"),
        "riskReasonTop": _risk_reason_top(high_rows or risk_rows),
        "shouldModifyTradingLogicNow": False,
        "note": "Entry timing safety is a diagnostic action-downgrade preview. It does not change _final_score, ranking, filters, EV, candidates, or entry/target/stop formulas.",
    }
