from __future__ import annotations

from typing import Any

from app.services import trade_failure_analytics as failure_analytics

SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}


def _num(value: Any) -> float | None:
    try:
        n = float(value)
    except Exception:
        return None
    return n if n == n else None


def _severity(ratio: float | None, count: int = 0, high: float = 0.25, medium: float = 0.12) -> str:
    value = float(ratio or 0.0)
    if value >= high or count >= 30:
        return "high"
    if value >= medium or count >= 10:
        return "medium"
    return "low"


def _reason_map(analytics: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("failureReason") or ""): item
        for item in analytics.get("failureReasons") or []
        if item.get("failureReason")
    }


def _combined_reason(reason_rows: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    count = sum(int(row.get("count") or 0) for row in reason_rows)
    denominator = int(summary.get("evaluatedTrades") or summary.get("totalTrades") or 0)
    ratio = round(count / denominator, 4) if denominator else 0.0
    values = [row for row in reason_rows if row]

    def avg_field(field: str) -> float | None:
        weighted = [
            (float(row[field]), int(row.get("count") or 0))
            for row in values
            if _num(row.get(field)) is not None and int(row.get("count") or 0) > 0
        ]
        total = sum(weight for _, weight in weighted)
        if not total:
            return None
        return round(sum(value * weight for value, weight in weighted) / total, 4)

    return {
        "count": count,
        "ratio": ratio,
        "avgReturn": avg_field("avgReturn"),
        "avgMFE": avg_field("avgMFE"),
        "avgMAE": avg_field("avgMAE"),
    }


def _evidence(
    row: dict[str, Any],
    summary: dict[str, Any],
    relevant_rates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    count = int(row.get("count") or 0)
    total = int(summary.get("totalTrades") or 0)
    evaluated = int(summary.get("evaluatedTrades") or 0)
    ratio = _num(row.get("ratio")) or 0.0
    return {
        "count": count,
        "ratio": ratio,
        "conditionRate": ratio,
        "overallRatio": round(count / total, 4) if total else 0.0,
        "ratioBasis": "condition",
        "overallRatioBasis": "totalTrades",
        "totalTrades": total,
        "evaluatedTrades": evaluated,
        "relevantRates": {
            "entryTouchedRate": summary.get("entryTouchedRate"),
            "targetTouchedRate": summary.get("targetTouchedRate"),
            "targetBeforeStopRate": summary.get("targetBeforeStopRate"),
            "stopBeforeTargetRate": summary.get("stopBeforeTargetRate"),
            "entryNotTouchedRate": summary.get("entryNotTouchedRate"),
            **(relevant_rates or {}),
        },
        "avgReturn": row.get("avgReturn"),
        "avgMFE": row.get("avgMFE"),
        "avgMAE": row.get("avgMAE"),
    }


def _priority(
    *,
    issue_type: str,
    title: str,
    summary_text: str,
    affected_area: str,
    evidence: dict[str, Any],
    recommendation: str,
    safe_next_step: str,
    severity: str | None = None,
) -> dict[str, Any]:
    ratio = _num(evidence.get("ratio")) or 0.0
    count = int(evidence.get("count") or 0)
    return {
        "rank": 0,
        "severity": severity or _severity(ratio, count),
        "issueType": issue_type,
        "title": title,
        "summary": summary_text,
        "affectedArea": affected_area,
        "evidence": evidence,
        "recommendation": recommendation,
        "safeNextStep": safe_next_step,
        "shouldModifyTradingLogicNow": False,
    }


def _sort_and_rank(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(
        items,
        key=lambda item: (
            -SEVERITY_WEIGHT.get(str(item.get("severity")), 0),
            -float(item.get("evidence", {}).get("ratio") or 0.0),
            -int(item.get("evidence", {}).get("count") or 0),
            str(item.get("issueType") or ""),
        ),
    )
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
    return ranked


def empty_response(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
    regime: str = "all",
    recommendation_bucket: str = "all",
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
            "regime": regime,
            "recommendationBucket": recommendation_bucket,
        },
        "summary": {
            "totalTrades": 0,
            "evaluatedTrades": 0,
            "priorityCount": 0,
            "highSeverityCount": 0,
            "topIssueType": None,
            "diagnosticOnly": True,
            "shouldModifyTradingLogicNow": False,
        },
        "priorities": [],
        "note": "Improvement priorities are diagnostic only. They identify what to validate next and do not change recommendation logic.",
    }


def build_improvement_priorities(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
    regime: str = "all",
    recommendation_bucket: str = "all",
) -> dict[str, Any]:
    try:
        analytics = failure_analytics.build_failure_analytics(
            market=market,
            mode=mode,
            horizon=horizon,
            source_type=source_type,
            journal_session=journal_session,
            regime=regime,
            recommendation_bucket=recommendation_bucket,
        )
    except Exception as exc:
        out = empty_response(market, mode, horizon, source_type, journal_session, regime, recommendation_bucket)
        out["warning"] = f"improvement priority source unavailable: {exc}"
        return out

    summary = analytics.get("summary") or {}
    total = int(summary.get("totalTrades") or 0)
    evaluated = int(summary.get("evaluatedTrades") or 0)
    if total <= 0 and evaluated <= 0:
        return empty_response(market, mode, horizon, source_type, journal_session, regime, recommendation_bucket)

    by_reason = _reason_map(analytics)
    priorities: list[dict[str, Any]] = []

    entry = by_reason.get("ENTRY_NOT_TOUCHED")
    if entry and int(entry.get("count") or 0) > 0:
        priorities.append(_priority(
            issue_type="ENTRY_PRICE_TOO_DEEP",
            title="진입가 미도달 비율 높음",
            summary_text="가상 매매 평가에서 진입가를 터치하지 못한 사례가 누적되고 있습니다.",
            affected_area="entryPrice",
            evidence=_evidence(entry, summary),
            recommendation="진입가가 지나치게 보수적인지 점검 필요",
            safe_next_step="최근 미체결 표본의 추천 시점 가격, entry gap, 호가/변동성 조건을 검증하세요.",
        ))

    stop = by_reason.get("STOP_BEFORE_TARGET")
    if stop and int(stop.get("count") or 0) > 0:
        priorities.append(_priority(
            issue_type="STOP_BEFORE_TARGET_HIGH",
            title="손절 선도달 비율 높음",
            summary_text="목표가보다 손절가에 먼저 닿은 평가가 의미 있게 관측됩니다.",
            affected_area="candidateSelection/risk",
            evidence=_evidence(stop, summary),
            recommendation="후보 선정 신호, 과열 진입, 손절 위치를 점검 필요",
            safe_next_step="손절 선도달 표본을 setup bucket과 overextension 진단별로 나눠 원인을 확인하세요.",
        ))

    target_not_reached = by_reason.get("TARGET_NOT_REACHED")
    if target_not_reached and int(target_not_reached.get("count") or 0) > 0:
        priorities.append(_priority(
            issue_type="TARGET_TOO_FAR_OR_MOMENTUM_WEAK",
            title="목표가 미도달 비율 높음",
            summary_text="진입 이후 목표가까지 이어지지 못하고 시간 종료 또는 약한 흐름으로 남는 사례가 있습니다.",
            affected_area="targetPrice/momentum",
            evidence=_evidence(target_not_reached, summary),
            recommendation="목표가가 과도하거나 모멘텀이 약한 후보가 포함되는지 점검 필요",
            safe_next_step="목표 미도달 표본의 MFE, 보유기간, momentum_continuation_score 분포를 비교하세요.",
        ))

    direction = by_reason.get("DIRECTION_FAILED")
    if direction and int(direction.get("count") or 0) > 0:
        priorities.append(_priority(
            issue_type="WEAK_CANDIDATE_SIGNAL",
            title="방향성 실패 비율 높음",
            summary_text="추천 방향과 실제 평가 방향이 어긋난 표본이 관측됩니다.",
            affected_area="scoringSignal",
            evidence=_evidence(direction, summary),
            recommendation="_final_score 구성 피처와 후보 선정 신호 진단 필요",
            safe_next_step="_final_score를 바꾸지 말고, 실패 표본의 표시용 진단 피처와 시장 regime 분포를 먼저 점검하세요.",
        ))

    data = _combined_reason([row for key, row in by_reason.items() if key in {"DATA_MISSING", "PRICE_INVALID"}], summary)
    if data["count"] > 0:
        priorities.append(_priority(
            issue_type="DATA_QUALITY_PROBLEM",
            title="데이터 품질 문제",
            summary_text="평가가 데이터 부족 또는 가격 오류로 제한된 사례가 있습니다.",
            affected_area="dataQuality",
            evidence=_evidence(data, summary),
            recommendation="가격/결과 데이터 수집 품질 점검 필요",
            safe_next_step="누락된 OHLCV/가격 컬럼과 평가 지연 상태가 특정 market 또는 source에 집중되는지 확인하세요.",
            severity=_severity(data["ratio"], data["count"], high=0.15, medium=0.07),
        ))

    target_before_stop_rate = _num(summary.get("targetBeforeStopRate"))
    avg_mae = _num(summary.get("avgMAE"))
    if target_before_stop_rate is not None and avg_mae is not None and target_before_stop_rate < 0.25 and avg_mae <= -5.0:
        priorities.append(_priority(
            issue_type="HIGH_DRAWDOWN_BEFORE_SUCCESS",
            title="진입 후 역행폭 과대",
            summary_text="목표가 선도달률은 낮고 평균 MAE가 깊어, 진입 후 불리한 움직임이 크게 나타납니다.",
            affected_area="timing/risk",
            evidence=_evidence(
                {
                    "count": evaluated or total,
                    "ratio": round(1.0 - target_before_stop_rate, 4),
                    "avgReturn": None,
                    "avgMFE": summary.get("avgMFE"),
                    "avgMAE": summary.get("avgMAE"),
                },
                summary,
                {"drawdownBasis": "targetBeforeStopRate_low_and_avgMAE_deep"},
            ),
            recommendation="진입 타이밍 또는 과열 위험 필터 점검 필요",
            safe_next_step="로직 변경 전에 손실 표본의 entryTouchDate 이후 MAE 진행과 overextension_risk 분포를 검증하세요.",
            severity=_severity(1.0 - target_before_stop_rate, evaluated or total, high=0.75, medium=0.55),
        ))

    avg_mfe = _num(summary.get("avgMFE"))
    target_touched_rate = _num(summary.get("targetTouchedRate"))
    if avg_mfe is not None and target_touched_rate is not None and avg_mfe >= 4.0 and target_touched_rate < 0.35:
        priorities.append(_priority(
            issue_type="MISSED_PROFIT_CAPTURE",
            title="수익 구간 포착 실패",
            summary_text="평균 MFE는 높지만 목표가 터치율이 낮아, 수익 구간을 충분히 확정하지 못했을 가능성이 있습니다.",
            affected_area="exitDesign",
            evidence=_evidence(
                {
                    "count": evaluated or total,
                    "ratio": round(1.0 - target_touched_rate, 4),
                    "avgReturn": None,
                    "avgMFE": summary.get("avgMFE"),
                    "avgMAE": summary.get("avgMAE"),
                },
                summary,
                {"profitCaptureBasis": "avgMFE_high_and_targetTouchedRate_low"},
            ),
            recommendation="목표가/분할익절/보유기간 기준 점검 필요",
            safe_next_step="목표가 산식 변경 전, 높은 MFE 표본에서 targetTouchDate와 holdingDays를 사람이 검토하세요.",
            severity=_severity(1.0 - target_touched_rate, evaluated or total, high=0.75, medium=0.55),
        ))

    ranked = _sort_and_rank(priorities)
    return {
        "status": "OK",
        "source": analytics.get("source", ""),
        "scope": analytics.get("scope") or empty_response(market, mode, horizon, source_type, journal_session, regime, recommendation_bucket)["scope"],
        "summary": {
            "totalTrades": total,
            "evaluatedTrades": evaluated,
            "priorityCount": len(ranked),
            "highSeverityCount": sum(1 for item in ranked if item.get("severity") == "high"),
            "topIssueType": ranked[0]["issueType"] if ranked else None,
            "diagnosticOnly": True,
            "shouldModifyTradingLogicNow": False,
        },
        "priorities": ranked,
        "failureSummary": summary,
        "note": "Improvement priorities are diagnostic only. They identify what to validate next and do not change recommendation logic.",
    }
