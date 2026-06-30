from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any, Iterable

from app.services import trade_failure_analytics as failure_analytics
from app.services import virtual_trade_journal as vtj

MIN_CAUSE_SAMPLE_SIZE = 8
MIN_PATCH_SAMPLE_SIZE = 40
ENTRY_WINDOW_SHORTER_RATIO = 0.8
TREND_MOMENTUM_GAP = 3.0
ENTRY_DEPTH_GAP_PCT = 2.0


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


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
    return failure_analytics.failure_reason_group(_reason(row)) == failure_analytics.REASON_GROUP_EVALUATED


def _is_entry_not_touched(row: dict[str, Any]) -> bool:
    return _reason(row) == "ENTRY_NOT_TOUCHED"


def _return_value(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "net_pnl_pct", "returnPct", "return_pct", "pnl_pct"))


def _entry_price(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "entry_price", "entry"))


def _current_price_at_signal(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "current_price_at_signal", "currentPrice"))


def _entry_depth_pct(row: dict[str, Any]) -> float | None:
    """% distance of the recommended entry price from the price at signal time.
    Negative = entry set below signal price (a pullback is required to fill)."""
    entry = _entry_price(row)
    current = _current_price_at_signal(row)
    if entry is None or current is None or current == 0:
        return None
    return round((entry - current) / current * 100, 4)


def _entry_window_days(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "entry_window_days"))


def _momentum5(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "momentum5_at_entry"))


def _distance_to_ma20(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "distance_to_ma20_at_entry"))


def _rsi(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "rsi_at_entry"))


def _ma_full_align(row: dict[str, Any]) -> bool | None:
    raw = _text(_first(row, "ma_full_align_at_entry")).lower()
    if raw in {"true", "1"}:
        return True
    if raw in {"false", "0"}:
        return False
    return None


def _holding_bucket(row: dict[str, Any]) -> str:
    return failure_analytics._holding_bucket(row)


def _regime(row: dict[str, Any]) -> str:
    return failure_analytics._regime(row)


def _entry_window_bucket(row: dict[str, Any]) -> str:
    days = _entry_window_days(row)
    if days is None:
        return "unknown"
    if days <= 3:
        return "short(<=3d)"
    if days <= 6:
        return "mid(4-6d)"
    return "long(7d+)"


def _entry_depth_bucket(row: dict[str, Any]) -> str:
    depth = _entry_depth_pct(row)
    if depth is None:
        return "unknown"
    if depth <= -3:
        return "deep_pullback(<=-3%)"
    if depth < 0:
        return "shallow_pullback(-3~0%)"
    if depth == 0:
        return "at_signal_price(0%)"
    return "above_signal_price(>0%)"


def _trend_strength_bucket(row: dict[str, Any]) -> str:
    momentum = _momentum5(row)
    aligned = _ma_full_align(row)
    if momentum is None:
        return "unknown"
    if momentum >= 10 and aligned is True:
        return "strong"
    if momentum < 0:
        return "weak"
    return "mid"


def _dimension_value(row: dict[str, Any], field: str) -> str:
    if field == "market":
        return _text(row.get("market")).lower() or "unknown"
    if field == "mode":
        return _text(row.get("mode")).lower() or "unknown"
    if field == "horizon":
        return _text(row.get("horizon")).lower() or "unknown"
    if field == "holdingDaysBucket":
        return _holding_bucket(row)
    if field == "regime":
        return _regime(row)
    if field == "entryWindowBucket":
        return _entry_window_bucket(row)
    if field == "entryDepthBucket":
        return _entry_depth_bucket(row)
    if field == "trendStrength":
        return _trend_strength_bucket(row)
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
    not_touched = sum(1 for row in rows if _is_entry_not_touched(row))
    depths = [value for row in rows if (value := _entry_depth_pct(row)) is not None]
    windows = [value for row in rows if (value := _entry_window_days(row)) is not None]
    momenta = [value for row in rows if (value := _momentum5(row)) is not None]
    distances = [value for row in rows if (value := _distance_to_ma20(row)) is not None]
    rsis = [value for row in rows if (value := _rsi(row)) is not None]
    aligned = [value for row in rows if (value := _ma_full_align(row)) is not None]
    returns = [value for row in rows if (value := _return_value(row)) is not None]
    return {
        "count": len(rows),
        "ratio": round(len(rows) / denominator, 4) if denominator else 0.0,
        "entryNotTouchedTrades": not_touched,
        "entryNotTouchedRate": round(not_touched / len(rows), 4) if rows else 0.0,
        "avgEntryDepthPct": _avg(depths),
        "medianEntryDepthPct": round(median(depths), 4) if depths else None,
        "avgEntryWindowDays": _avg(windows),
        "avgMomentum5": _avg(momenta),
        "avgDistanceToMa20": _avg(distances),
        "avgRsi": _avg(rsis),
        "maFullAlignRate": round(sum(1 for v in aligned if v) / len(aligned), 4) if aligned else None,
        "avgReturn": _avg(returns),
    }


def _dimension(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    total = len(rows)
    items = []
    for value, group in _group_rows(rows, field).items():
        item = {field: value}
        item.update(_metrics(group, total))
        items.append(item)
    return sorted(items, key=lambda item: (-float(item.get("entryNotTouchedRate") or 0), -int(item.get("count") or 0), str(item.get(field) or "")))


def _comparison(not_touched: list[dict[str, Any]], touched: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "entryNotTouchedGroup": _metrics(not_touched),
        "entryTouchedGroup": _metrics(touched),
    }


def _top_item(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    candidates = [item for item in items if str(item.get(key) or "") != "unknown" and int(item.get("count") or 0) >= MIN_CAUSE_SAMPLE_SIZE]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-float(item.get("entryNotTouchedRate") or 0), -int(item.get("entryNotTouchedTrades") or 0)))[0]


def _cause_candidates(
    evaluated: list[dict[str, Any]],
    not_touched: list[dict[str, Any]],
    dimensions: dict[str, list[dict[str, Any]]],
    comparison: dict[str, Any],
) -> list[dict[str, Any]]:
    total = len(evaluated)
    not_touched_total = len(not_touched)
    candidates: list[dict[str, Any]] = []

    nt_cmp = comparison.get("entryNotTouchedGroup") or {}
    t_cmp = comparison.get("entryTouchedGroup") or {}

    nt_window = nt_cmp.get("avgEntryWindowDays")
    t_window = t_cmp.get("avgEntryWindowDays")
    if not_touched_total >= MIN_CAUSE_SAMPLE_SIZE and nt_window is not None and t_window and float(nt_window) <= float(t_window) * ENTRY_WINDOW_SHORTER_RATIO:
        candidates.append({
            "causeType": "ENTRY_WINDOW_TOO_SHORT",
            "title": "진입 대기 기간 부족",
            "summary": "진입가 미도달 표본의 평균 entry_window_days가 진입 성공 표본보다 뚜렷하게 짧습니다. 체결 대기 기간이 짧아 미도달로 끝났을 가능성이 있습니다.",
            "evidence": {"avgEntryWindowDaysNotTouched": nt_window, "avgEntryWindowDaysTouched": t_window, "sampleSize": not_touched_total},
        })

    nt_depth = nt_cmp.get("avgEntryDepthPct")
    t_depth = t_cmp.get("avgEntryDepthPct")
    if not_touched_total >= MIN_CAUSE_SAMPLE_SIZE and nt_depth is not None and t_depth is not None and float(nt_depth) <= float(t_depth) - ENTRY_DEPTH_GAP_PCT:
        candidates.append({
            "causeType": "ENTRY_PRICE_TOO_CONSERVATIVE",
            "title": "진입가 과도 보수",
            "summary": "진입가 미도달 표본의 진입가가 신호 시점 가격보다 평균적으로 더 깊게 설정되어 있습니다 (더 큰 눌림목을 요구).",
            "evidence": {"avgEntryDepthPctNotTouched": nt_depth, "avgEntryDepthPctTouched": t_depth, "sampleSize": not_touched_total},
        })

    nt_momentum = nt_cmp.get("avgMomentum5")
    t_momentum = t_cmp.get("avgMomentum5")
    nt_align = nt_cmp.get("maFullAlignRate")
    t_align = t_cmp.get("maFullAlignRate")
    momentum_gap = (
        nt_momentum is not None and t_momentum is not None and float(nt_momentum) >= float(t_momentum) + TREND_MOMENTUM_GAP
    )
    align_gap = (
        nt_align is not None and t_align is not None and float(nt_align) >= float(t_align) + 0.1
    )
    if not_touched_total >= MIN_CAUSE_SAMPLE_SIZE and (momentum_gap or align_gap):
        candidates.append({
            "causeType": "STRONG_TREND_RAN_WITHOUT_PULLBACK",
            "title": "강한 추세 종목이 눌림 없이 이탈",
            "summary": "진입가 미도달 표본은 신호 시점 모멘텀/이평 정배열이 평균적으로 더 강합니다. 눌림목을 기다리다 강한 추세 종목을 놓쳤을 가능성이 있습니다.",
            "evidence": {
                "avgMomentum5NotTouched": nt_momentum,
                "avgMomentum5Touched": t_momentum,
                "maFullAlignRateNotTouched": nt_align,
                "maFullAlignRateTouched": t_align,
            },
        })

    for field, cause_type, title in (
        ("byMode", "MODE_SPECIFIC_ENTRY_MISS", "특정 모드 집중"),
        ("byMarket", "MARKET_SPECIFIC_ENTRY_MISS", "특정 시장 집중"),
        ("byHorizon", "HORIZON_ENTRY_DEPTH_MISMATCH", "특정 horizon 집중"),
    ):
        item = _top_item(dimensions.get(field, []), field[2].lower() + field[3:])
        baseline_rate = (not_touched_total / total) if total else 0.0
        if item and float(item.get("entryNotTouchedRate") or 0) >= max(0.02, baseline_rate * 1.5):
            dim_name = field[2].lower() + field[3:]
            candidates.append({
                "causeType": cause_type,
                "title": title,
                "summary": f"{dim_name}={item.get(dim_name)} 구간의 진입가 미도달 비율이 상대적으로 높습니다.",
                "evidence": {
                    "segment": item.get(dim_name),
                    "count": item.get("count"),
                    "entryNotTouchedRate": item.get("entryNotTouchedRate"),
                },
            })

    if not_touched_total >= MIN_CAUSE_SAMPLE_SIZE and not candidates:
        candidates.append({
            "causeType": "ENTRY_NOT_TOUCHED_CAUSE_UNCLEAR",
            "title": "진입가 미도달 원인 불분명",
            "summary": "진입 대기 기간, 진입가 깊이, 추세 강도만으로는 명확히 설명되지 않는 진입가 미도달 표본이 남아 있습니다. 산식 변경 전 추가 분석이 필요합니다.",
            "evidence": {"entryNotTouchedTrades": not_touched_total, "entryNotTouchedRate": round(not_touched_total / total, 4) if total else 0.0},
        })

    return candidates[:5]


def _patch_decision(total: int, not_touched_count: int, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    rate = not_touched_count / total if total else 0.0
    if total < MIN_PATCH_SAMPLE_SIZE:
        reason = "평가 완료 표본이 작아 운영 로직 변경 대신 진단만 제공합니다."
    elif not_touched_count < MIN_CAUSE_SAMPLE_SIZE:
        reason = "진입가 미도달 표본 자체가 작아(8건 미만) 원인 분류의 신뢰도가 낮습니다. 진단만 제공합니다."
    elif not candidates:
        reason = "원인 후보가 명확하지 않아 과적합을 피하기 위해 진입가 산식을 변경하지 않았습니다."
    else:
        reason = "원인 후보는 관측되었지만 before/after 검증 없이 진입가 산식이나 entry_window_days를 변경하지 않았습니다."
    return {
        "appliedPatch": False,
        "patchType": "diagnostic_only",
        "patchReason": reason,
        "shouldModifyTradingLogicNow": False,
        "backtest": {
            "available": False,
            "reason": "현재 변경은 진단 엔진/API 추가이며 진입가 산식, entry_window_days, 후보 제외 로직을 수정하지 않았습니다.",
            "beforeAfter": None,
        },
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
            "entryNotTouchedTrades": 0,
            "entryNotTouchedRate": 0.0,
            "avgEntryDepthPct": None,
            "avgEntryWindowDays": None,
        },
        "dimensions": {
            "byMarket": [],
            "byMode": [],
            "byHorizon": [],
            "byHoldingDaysBucket": [],
            "byRegime": [],
            "byEntryWindowBucket": [],
            "byEntryDepthBucket": [],
            "byTrendStrength": [],
        },
        "comparison": _comparison([], []),
        "causeCandidates": [],
        "patch": _patch_decision(0, 0, []),
        "appliedPatch": False,
        "patchType": "diagnostic_only",
        "patchReason": "분석 가능한 평가 완료 거래가 아직 없습니다.",
        "shouldModifyTradingLogicNow": False,
        "note": "Entry-not-touched diagnostics use evaluated-only virtual trade rows and do not change entry price formulas, entry_window_days, or candidate filters.",
    }


def build_entry_not_touched_diagnostics(
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
        out["warning"] = f"entry-not-touched diagnostics source unavailable: {exc}"
        return out

    evaluated = [row for row in rows if _is_evaluated_outcome(row)]
    if not evaluated:
        return empty_response(market, mode, horizon, source_type, journal_session)

    not_touched = [row for row in evaluated if _is_entry_not_touched(row)]
    touched = [row for row in evaluated if not _is_entry_not_touched(row)]
    dimensions = {
        "byMarket": _dimension(evaluated, "market"),
        "byMode": _dimension(evaluated, "mode"),
        "byHorizon": _dimension(evaluated, "horizon"),
        "byHoldingDaysBucket": _dimension(evaluated, "holdingDaysBucket"),
        "byRegime": _dimension(evaluated, "regime"),
        "byEntryWindowBucket": _dimension(evaluated, "entryWindowBucket"),
        "byEntryDepthBucket": _dimension(evaluated, "entryDepthBucket"),
        "byTrendStrength": _dimension(evaluated, "trendStrength"),
    }
    comparison = _comparison(not_touched, touched)
    candidates = _cause_candidates(evaluated, not_touched, dimensions, comparison)
    patch = _patch_decision(len(evaluated), len(not_touched), candidates)

    summary = {
        "totalEvaluatedTrades": len(evaluated),
        "entryNotTouchedTrades": len(not_touched),
        "entryNotTouchedRate": round(len(not_touched) / len(evaluated), 4) if evaluated else 0.0,
        "avgEntryDepthPct": comparison["entryNotTouchedGroup"]["avgEntryDepthPct"],
        "avgEntryWindowDays": comparison["entryNotTouchedGroup"]["avgEntryWindowDays"],
        "avgEntryDepthPctTouchedBaseline": comparison["entryTouchedGroup"]["avgEntryDepthPct"],
        "avgEntryWindowDaysTouchedBaseline": comparison["entryTouchedGroup"]["avgEntryWindowDays"],
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
        "note": "Entry-not-touched diagnostics use evaluated-only virtual trade rows and do not change entry price formulas, entry_window_days, or candidate filters.",
    }
