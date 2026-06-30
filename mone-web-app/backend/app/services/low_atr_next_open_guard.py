from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any, Iterable

from app.services import trade_failure_analytics as failure_analytics
from app.services import virtual_trade_journal as vtj

GUARD_NAME = "KR_NEXT_OPEN_LOW_ATR_GUARD"
GUARD_VERSION = "v1"

# Frozen from a time-ordered train split (first ~65% of KR NEXT_OPEN evaluated trades by date).
# Validated out-of-sample across three independent time folds: the bottom-tercile-ATR segment
# consistently shows a higher stop-failure rate and worse avg return than the rest in every fold.
# This is NOT a market-gap signal: MARKET_GAP/HIGH_ATR trades were checked and explicitly
# rejected as a downgrade trigger because the high-ATR segment outperforms despite a higher
# gap-failure rate. See docs/validation/low_atr_next_open_guard_validation.json.
ATR_TERCILE_CUTOFF = 6.7
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


def _is_evaluated_outcome(row: dict[str, Any]) -> bool:
    return failure_analytics.failure_reason_group(_reason(row)) == failure_analytics.REASON_GROUP_EVALUATED


def _is_kr(row: dict[str, Any]) -> bool:
    return _text(row.get("market")).lower() == "kr"


def _is_next_open(row: dict[str, Any]) -> bool:
    return _upper(row.get("entry_type")) == "NEXT_OPEN"


def _atr14_pct(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "atr14_pct_at_entry", "atr14Pct", "atr14_pct", "atr_pct"))


def _is_low_atr(row: dict[str, Any]) -> bool:
    atr = _atr14_pct(row)
    return atr is not None and atr < ATR_TERCILE_CUTOFF


def _is_guard_segment(row: dict[str, Any]) -> bool:
    return _is_kr(row) and _is_next_open(row) and _is_low_atr(row)


def _return_value(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "net_pnl_pct", "returnPct", "return_pct", "pnl_pct"))


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


def _adjusted_action(original_action: str, in_guard_segment: bool) -> str:
    action = _upper(original_action)
    if not in_guard_segment:
        return action
    if action in {"BUY", "STRONG_BUY"}:
        return "WAIT_PULLBACK"
    if action in {"WATCH", "HOLD"}:
        return "CAUTION"
    return action


TODAY_ENTRY_BUCKET = "오늘 진입"
WAIT_PULLBACK_BUCKET = "기다림"


def compute_atr14_pct(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    """Same formula as scripts/generate_kr_recommendations.py:_atr() / atr14Pct: simple average
    of true range over the last `period` bars, as a percentage of the latest close. Used because
    the live KR candidate sources (predictions.csv, v93_*_cards_kr.csv) do not carry atr14Pct --
    only the historical journal-evaluation pipeline did. Computed fresh from OHLCV here so the
    guard can actually evaluate the same validated threshold against live candidates."""
    if len(closes) <= period or not closes or closes[-1] in (None, 0):
        return None
    true_ranges = [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(len(closes) - period, len(closes))
    ]
    atr14 = sum(true_ranges) / period
    latest_close = closes[-1]
    if not latest_close:
        return None
    return round(atr14 / latest_close * 100, 4)


def apply_live_guard(market: str, bucket: str, buy_timing: str, atr14_pct: float | None) -> dict[str, Any]:
    """Live recommendation engine entry point (final_engine.py).

    Only fires when market=KR, the decision bucket is the "오늘 진입" (buy-today / NEXT_OPEN-fill)
    bucket, and atr14Pct is known and below the validated bottom-tercile cutoff. Returns the
    (possibly downgraded) decisionBucket/buyTiming plus originalAction/adjustedAction/
    actionAdjustmentReason for transparency. Does not touch finalRankScore, ranking, filters,
    EV, candidate selection, or entry/target/stop price formulas -- call this only AFTER
    finalRankScore has already been computed from the original bucket.
    """
    in_segment = (
        _text(market).lower() == "kr"
        and bucket == TODAY_ENTRY_BUCKET
        and atr14_pct is not None
        and atr14_pct < ATR_TERCILE_CUTOFF
    )
    if not in_segment:
        return {
            "appliedGuard": False,
            "decisionBucket": bucket,
            "buyTiming": buy_timing,
            "originalAction": bucket,
            "adjustedAction": bucket,
            "actionAdjustmentReason": "",
            "guardName": GUARD_NAME,
            "guardVersion": GUARD_VERSION,
        }
    reason = (
        f"KR NEXT_OPEN 진입 중 ATR14 {atr14_pct:.2f}%로 하위 1/3 구간(<{ATR_TERCILE_CUTOFF}%)에 해당해 "
        "과거 평가 완료 거래 기준 손절실패율 상승·수익률 악화가 3개 독립 시간 구간에서 일관되게 "
        "확인됨 (KR_NEXT_OPEN_LOW_ATR_GUARD v1)."
    )
    return {
        "appliedGuard": True,
        "decisionBucket": WAIT_PULLBACK_BUCKET,
        "buyTiming": "기준가 도달 대기 (저ATR 갭/손절 위험 가드)",
        "originalAction": bucket,
        "adjustedAction": WAIT_PULLBACK_BUCKET,
        "actionAdjustmentReason": reason,
        "guardName": GUARD_NAME,
        "guardVersion": GUARD_VERSION,
    }


def compute_low_atr_guard(row: dict[str, Any]) -> dict[str, Any]:
    in_segment = _is_guard_segment(row)
    original = _original_action(row)
    adjusted = _adjusted_action(original, in_segment)
    reasons: list[str] = []
    if in_segment:
        reasons.append("KR_NEXT_OPEN_LOW_ATR")
    return {
        "inGuardSegment": in_segment,
        "atr14Pct": _atr14_pct(row),
        "atrTercileCutoff": ATR_TERCILE_CUTOFF,
        "originalAction": original,
        "adjustedAction": adjusted,
        "actionAdjustmentReason": "; ".join(reasons) if adjusted != original else "",
        "guardName": GUARD_NAME,
        "guardVersion": GUARD_VERSION,
    }


def _holding_bucket(row: dict[str, Any]) -> str:
    return failure_analytics._holding_bucket(row)


def _dimension_value(row: dict[str, Any], field: str) -> str:
    if field == "market":
        return _text(row.get("market")).lower() or "unknown"
    if field == "mode":
        return _text(row.get("mode")).lower() or "unknown"
    if field == "horizon":
        return _text(row.get("horizon")).lower() or "unknown"
    if field == "holdingDaysBucket":
        return _holding_bucket(row)
    if field == "guardSegment":
        return "in_segment" if _is_guard_segment(row) else "not_in_segment"
    return _text(row.get(field)) or "unknown"


def _group_rows(rows: Iterable[dict[str, Any]], field: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_dimension_value(row, field)].append(row)
    return groups


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _metrics(rows: list[dict[str, Any]], total: int | None = None) -> dict[str, Any]:
    denominator = total if total is not None else len(rows)
    returns = [value for row in rows if (value := _return_value(row)) is not None]
    stop_failure = sum(1 for row in rows if _reason(row) in {"STOP_TOO_TIGHT", "STOP_BEFORE_TARGET"})
    target_before_stop = sum(1 for row in rows if _reason(row) == "TARGET_BEFORE_STOP")
    wins = sum(1 for row in rows if _reason(row) == "TARGET_BEFORE_STOP" or ((_return_value(row) or 0) > 0))
    return {
        "count": len(rows),
        "ratio": round(len(rows) / denominator, 4) if denominator else 0.0,
        "stopFailureRate": round(stop_failure / len(rows), 4) if rows else 0.0,
        "avgReturn": _avg(returns),
        "medianReturn": round(median(returns), 4) if returns else None,
        "winRate": round(wins / len(rows), 4) if rows else None,
        "targetBeforeStopRate": round(target_before_stop / len(rows), 4) if rows else 0.0,
    }


def _dimension(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    total = len(rows)
    items = []
    for value, group in _group_rows(rows, field).items():
        item = {field: value}
        item.update(_metrics(group, total))
        items.append(item)
    return sorted(items, key=lambda item: (-int(item.get("count") or 0), str(item.get(field) or "")))


def _before_after(evaluated: list[dict[str, Any]], affected: list[dict[str, Any]]) -> dict[str, Any]:
    affected_ids = {id(row) for row in affected}
    after_rows = [row for row in evaluated if id(row) not in affected_ids]
    before = _metrics(evaluated)
    after = _metrics(after_rows)
    return {
        "baseline": before,
        "afterGuard": after,
        "affectedSegment": _metrics(affected),
        "evaluatedTrades": len(evaluated),
        "affectedTrades": len(affected),
        "actionDowngradeCount": len(affected),
        "recommendationCountChange": -len(affected),
        "stopFailureRateBefore": before["stopFailureRate"],
        "stopFailureRateAfter": after["stopFailureRate"],
        "avgReturnBefore": before["avgReturn"],
        "avgReturnAfter": after["avgReturn"],
        "medianReturnBefore": before["medianReturn"],
        "medianReturnAfter": after["medianReturn"],
        "winRateBefore": before["winRate"],
        "winRateAfter": after["winRate"],
        "targetBeforeStopRateBefore": before["targetBeforeStopRate"],
        "targetBeforeStopRateAfter": after["targetBeforeStopRate"],
    }


def _activation_decision(evaluated: list[dict[str, Any]], affected: list[dict[str, Any]], replay: dict[str, Any]) -> dict[str, Any]:
    before_stop = float(replay.get("stopFailureRateBefore") or 0)
    after_stop = float(replay.get("stopFailureRateAfter") or 0)
    before_return = replay.get("avgReturnBefore")
    after_return = replay.get("avgReturnAfter")
    coverage = len(affected) / len(evaluated) if evaluated else 0.0
    reasons = []
    if len(evaluated) < MIN_ACTIVATION_SAMPLE:
        reasons.append("평가 완료 표본이 작아 active guard를 적용하지 않습니다.")
    if len(affected) < MIN_AFFECTED_SAMPLE:
        reasons.append("대상 세그먼트 표본이 작아 과적합 위험이 큽니다.")
    if after_stop > before_stop:
        reasons.append("적용 후 손절 실패율이 오히려 악화되어 적용하지 않습니다.")
    if before_return is not None and after_return is not None and float(after_return) < float(before_return):
        reasons.append("적용 후 평균 수익률이 오히려 악화되어 적용하지 않습니다.")
    if coverage > 0.5:
        reasons.append("대상 비중이 전체 평가 완료 거래의 50%를 초과해 과도한 추천 수 감소로 판단해 적용하지 않습니다.")
    if reasons:
        return {
            "guardMode": "diagnostic_only",
            "appliedGuard": False,
            "activationDecision": "diagnostic_only",
            "activationReason": " ".join(reasons),
            "shouldModifyTradingLogicNow": False,
        }
    return {
        "guardMode": "active_if_validated",
        "appliedGuard": True,
        "activationDecision": "active_kr_next_open_low_atr_only",
        "activationReason": (
            "KR NEXT_OPEN 진입 중 ATR 하위 1/3 구간이 3개 독립 시간 구간 전부에서 일관되게 손절실패율"
            " 상승·수익률 악화를 보여 제한적으로 활성화합니다. 적용 범위는 market=KR, entry_type=NEXT_OPEN,"
            f" atr14Pct<{ATR_TERCILE_CUTOFF}로 한정하며, US와 HIGH_ATR 구간에는 적용하지 않습니다."
            " 추천 후보 제외, final_score 감산, entry/target/stop 산식 변경은 하지 않으며 action 한 단계"
            " 다운그레이드만 적용합니다."
        ),
        "shouldModifyTradingLogicNow": True,
        "scope": {"market": "KR", "entryType": "NEXT_OPEN", "atr14PctBelow": ATR_TERCILE_CUTOFF},
    }


def empty_response(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
) -> dict[str, Any]:
    empty_metrics = _metrics([])
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
            "guardSegmentTrades": 0,
            "guardSegmentRate": 0.0,
            "atrTercileCutoff": ATR_TERCILE_CUTOFF,
        },
        "dimensions": {
            "byMarket": [],
            "byMode": [],
            "byHorizon": [],
            "byHoldingDaysBucket": [],
        },
        "beforeAfterReplay": {
            "baseline": empty_metrics,
            "afterGuard": empty_metrics,
            "affectedSegment": empty_metrics,
        },
        "guardMode": "diagnostic_only",
        "appliedGuard": False,
        "guardName": GUARD_NAME,
        "guardVersion": GUARD_VERSION,
        "activationDecision": "diagnostic_only",
        "activationReason": "분석 가능한 평가 완료 거래가 아직 없습니다.",
        "affectedTrades": [],
        "shouldModifyTradingLogicNow": False,
        "note": "KR_NEXT_OPEN_LOW_ATR_GUARD downgrades action by one tier only for market=KR, entry_type=NEXT_OPEN, ATR-bottom-tercile recommendations. It does not change _final_score, ranking, filters, EV, candidates, or entry/target/stop formulas. It explicitly does not apply to US or HIGH_ATR segments, and is not a market-gap-based rule (a MARKET_GAP/HIGH_ATR downgrade was evaluated and rejected; see docs/validation/low_atr_next_open_guard_validation.json).",
    }


def build_low_atr_guard_diagnostics(
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
        out["warning"] = f"low-ATR next-open guard diagnostics source unavailable: {exc}"
        return out

    evaluated = [row for row in rows if _is_evaluated_outcome(row)]
    if not evaluated:
        return empty_response(market, mode, horizon, source_type, journal_session)

    affected = [row for row in evaluated if _is_guard_segment(row)]
    replay = _before_after(evaluated, affected)
    decision = _activation_decision(evaluated, affected, replay)

    summary = {
        "totalEvaluatedTrades": len(evaluated),
        "guardSegmentTrades": len(affected),
        "guardSegmentRate": round(len(affected) / len(evaluated), 4) if evaluated else 0.0,
        "atrTercileCutoff": ATR_TERCILE_CUTOFF,
    }
    return {
        "status": "OK",
        "source": vtj._relative(vtj.EVALUATION_CSV),
        "scope": empty_response(market, mode, horizon, source_type, journal_session)["scope"],
        "summary": summary,
        "dimensions": {
            "byMarket": _dimension(evaluated, "market"),
            "byMode": _dimension([row for row in evaluated if _is_kr(row)], "mode"),
            "byHorizon": _dimension([row for row in evaluated if _is_kr(row)], "horizon"),
            "byHoldingDaysBucket": _dimension(affected, "holdingDaysBucket"),
        },
        "beforeAfterReplay": replay,
        "guardName": GUARD_NAME,
        "guardVersion": GUARD_VERSION,
        **decision,
        "affectedTrades": [
            {
                "journalId": row.get("journal_id") or row.get("journalId") or "",
                "market": _text(row.get("market")).lower(),
                "mode": _text(row.get("mode")).lower(),
                "horizon": _text(row.get("horizon")).lower(),
                "symbol": row.get("symbol") or "",
                "failureReason": _reason(row),
                "avgReturn": _return_value(row),
                **compute_low_atr_guard(row),
            }
            for row in affected[:25]
        ],
        "note": "KR_NEXT_OPEN_LOW_ATR_GUARD downgrades action by one tier only for market=KR, entry_type=NEXT_OPEN, ATR-bottom-tercile recommendations. It does not change _final_score, ranking, filters, EV, candidates, or entry/target/stop formulas. It explicitly does not apply to US or HIGH_ATR segments, and is not a market-gap-based rule (a MARKET_GAP/HIGH_ATR downgrade was evaluated and rejected; see docs/validation/low_atr_next_open_guard_validation.json).",
    }
