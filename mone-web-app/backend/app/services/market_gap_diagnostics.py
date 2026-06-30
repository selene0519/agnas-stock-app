from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any, Iterable

from app.services import trade_failure_analytics as failure_analytics
from app.services import virtual_trade_journal as vtj

MIN_CAUSE_SAMPLE_SIZE = 8
MIN_PATCH_SAMPLE_SIZE = 40
MARKET_CONCENTRATION_RATIO = 2.0


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


def _reason(row: dict[str, Any]) -> str:
    return failure_analytics._failure_reason(row)


def _is_evaluated_outcome(row: dict[str, Any]) -> bool:
    return failure_analytics.failure_reason_group(_reason(row)) == failure_analytics.REASON_GROUP_EVALUATED


def _is_market_gap(row: dict[str, Any]) -> bool:
    return _reason(row) == "MARKET_GAP"


def _is_next_open(row: dict[str, Any]) -> bool:
    return _text(row.get("entry_type")).upper() == "NEXT_OPEN"


def _return_value(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "net_pnl_pct", "returnPct", "return_pct", "pnl_pct"))


def _entry_price(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "entry_price", "entry"))


def _fill_price(row: dict[str, Any]) -> float | None:
    return _num(_first(row, "fill_price"))


def _gap_pct(row: dict[str, Any]) -> float | None:
    """% deviation of the actual fill price from the recommended entry price.
    Only meaningful for NEXT_OPEN entries (the price action between signal close and next open)."""
    entry = _entry_price(row)
    fill = _fill_price(row)
    if entry is None or fill is None or entry == 0:
        return None
    return round((fill - entry) / entry * 100, 4)


def _gap_direction(row: dict[str, Any]) -> str:
    gap = _gap_pct(row)
    if gap is None:
        return "unknown"
    if gap <= -2:
        return "gap_down(<=-2%)"
    if gap < 0:
        return "shallow_down(-2~0%)"
    if gap == 0:
        return "flat(0%)"
    if gap < 2:
        return "shallow_up(0~2%)"
    return "gap_up(>=2%)"


def _holding_bucket(row: dict[str, Any]) -> str:
    return failure_analytics._holding_bucket(row)


def _regime(row: dict[str, Any]) -> str:
    return failure_analytics._regime(row)


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
    if field == "entryType":
        return _text(row.get("entry_type")).upper() or "unknown"
    if field == "gapDirection":
        return _gap_direction(row)
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
    gap_rows = [row for row in rows if _is_market_gap(row)]
    returns = [value for row in rows if (value := _return_value(row)) is not None]
    gaps = [value for row in rows if (value := _gap_pct(row)) is not None]
    wins = sum(1 for row in rows if _reason(row) == "TARGET_BEFORE_STOP" or ((_return_value(row) or 0) > 0))
    return {
        "count": len(rows),
        "ratio": round(len(rows) / denominator, 4) if denominator else 0.0,
        "marketGapTrades": len(gap_rows),
        "marketGapRate": round(len(gap_rows) / len(rows), 4) if rows else 0.0,
        "avgReturn": _avg(returns),
        "medianReturn": round(median(returns), 4) if returns else None,
        "winRate": round(wins / len(rows), 4) if rows else None,
        "avgGapPct": _avg(gaps),
        "medianGapPct": round(median(gaps), 4) if gaps else None,
    }


def _dimension(rows: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    total = len(rows)
    items = []
    for value, group in _group_rows(rows, field).items():
        item = {field: value}
        item.update(_metrics(group, total))
        items.append(item)
    return sorted(items, key=lambda item: (-float(item.get("marketGapRate") or 0), -int(item.get("count") or 0), str(item.get(field) or "")))


def _comparison(gap_rows: list[dict[str, Any]], non_gap_next_open: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "marketGapGroup": _metrics(gap_rows),
        "nonGapNextOpenGroup": _metrics(non_gap_next_open),
    }


def _top_item(items: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    candidates = [item for item in items if str(item.get(key) or "") not in {"unknown"} and int(item.get("count") or 0) >= MIN_CAUSE_SAMPLE_SIZE]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-float(item.get("marketGapRate") or 0), -int(item.get("marketGapTrades") or 0)))[0]


def _cause_candidates(
    next_open_rows: list[dict[str, Any]],
    gap_rows: list[dict[str, Any]],
    dimensions: dict[str, list[dict[str, Any]]],
    comparison: dict[str, Any],
) -> list[dict[str, Any]]:
    total = len(next_open_rows)
    gap_total = len(gap_rows)
    candidates: list[dict[str, Any]] = []

    by_market = dimensions.get("byMarket", [])
    market_lookup = {item.get("market"): item for item in by_market}
    kr_item = market_lookup.get("kr")
    us_item = market_lookup.get("us")
    if (
        kr_item
        and us_item
        and int(kr_item.get("count") or 0) >= MIN_CAUSE_SAMPLE_SIZE
        and int(us_item.get("count") or 0) >= MIN_CAUSE_SAMPLE_SIZE
        and float(us_item.get("marketGapRate") or 0) > 0
        and float(kr_item.get("marketGapRate") or 0) >= float(us_item.get("marketGapRate") or 0) * MARKET_CONCENTRATION_RATIO
    ):
        candidates.append({
            "causeType": "KR_MARKET_GAP_CONCENTRATION",
            "title": "KR 시장 갭 위험 집중",
            "summary": "전일 종가 기준 NEXT_OPEN 진입에서 KR의 갭 실패율이 US보다 뚜렷하게 높습니다. 국장 시가 변동성이 더 크게 반영되는 것으로 보입니다.",
            "evidence": {
                "krGapRate": kr_item.get("marketGapRate"),
                "usGapRate": us_item.get("marketGapRate"),
                "krCount": kr_item.get("count"),
                "usCount": us_item.get("count"),
            },
        })

    gap_cmp = comparison.get("marketGapGroup") or {}
    avg_gap = gap_cmp.get("avgGapPct")
    median_gap = gap_cmp.get("medianGapPct")
    if avg_gap is not None and gap_total >= MIN_CAUSE_SAMPLE_SIZE:
        direction_item = _top_item(dimensions.get("byGapDirection", []), "gapDirection")
        if direction_item and "down" in str(direction_item.get("gapDirection") or ""):
            candidates.append({
                "causeType": "GAP_DOWN_DOMINANT",
                "title": "하락 갭 비중 높음",
                "summary": "갭 실패 표본에서 시초가가 추천 진입가보다 낮게 출발하는 하락 갭 비중이 높습니다. 전일 종가 기준 진입가가 다음날 변동을 따라가지 못하는 패턴입니다.",
                "evidence": {"avgGapPct": avg_gap, "medianGapPct": median_gap},
            })
        elif avg_gap < 0:
            candidates.append({
                "causeType": "GAP_DOWN_DOMINANT",
                "title": "하락 갭 비중 높음",
                "summary": "갭 실패 표본의 평균 갭 방향이 하락 쪽으로 치우쳐 있습니다.",
                "evidence": {"avgGapPct": avg_gap, "medianGapPct": median_gap},
            })

    for field, cause_type, title in (
        ("byMode", "MODE_SPECIFIC_GAP_FAILURE", "특정 모드 집중"),
        ("byHorizon", "HORIZON_SPECIFIC_GAP_FAILURE", "특정 horizon 집중"),
    ):
        item = _top_item(dimensions.get(field, []), field[2].lower() + field[3:])
        baseline_rate = (gap_total / total) if total else 0.0
        if item and float(item.get("marketGapRate") or 0) >= max(0.1, baseline_rate * 1.5):
            dim_name = field[2].lower() + field[3:]
            candidates.append({
                "causeType": cause_type,
                "title": title,
                "summary": f"{dim_name}={item.get(dim_name)} 구간의 갭 실패율이 상대적으로 높습니다.",
                "evidence": {
                    "segment": item.get(dim_name),
                    "count": item.get("count"),
                    "marketGapRate": item.get("marketGapRate"),
                },
            })

    if gap_total >= MIN_CAUSE_SAMPLE_SIZE and not candidates:
        candidates.append({
            "causeType": "GAP_PATTERN_UNCLEAR",
            "title": "갭 실패 원인 불분명",
            "summary": "시장/방향만으로는 명확히 설명되지 않는 갭 실패 표본이 남아 있습니다. 추가 분석이 필요합니다.",
            "evidence": {"marketGapTrades": gap_total, "marketGapRate": round(gap_total / total, 4) if total else 0.0},
        })

    return candidates[:5]


def _patch_decision(total: int, gap_count: int, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    rate = gap_count / total if total else 0.0
    if total < MIN_PATCH_SAMPLE_SIZE:
        reason = "NEXT_OPEN 표본이 작아 운영 로직 변경 대신 진단만 제공합니다."
    elif rate < 0.1:
        reason = "갭 실패율이 운영 로직 변경 임계값보다 낮아 진단만 제공합니다."
    elif not candidates:
        reason = "원인 후보가 명확하지 않아 과적합을 피하기 위해 운영 패치를 적용하지 않았습니다."
    else:
        reason = "원인 후보는 관측되었지만 before/after 검증 없이 추천 제외나 action downgrade를 적용하지 않았습니다."
    return {
        "appliedPatch": False,
        "patchType": "diagnostic_only",
        "patchReason": reason,
        "shouldModifyTradingLogicNow": False,
        "backtest": {
            "available": False,
            "reason": "현재 변경은 진단 엔진/API 추가이며 추천 후보 제외, action 변경, 진입가 산식 변경을 수행하지 않았습니다.",
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
            "nextOpenTrades": 0,
            "marketGapTrades": 0,
            "marketGapRate": 0.0,
            "avgGapPct": None,
            "avgReturnGapGroup": None,
            "avgReturnNonGapGroup": None,
        },
        "dimensions": {
            "byMarket": [],
            "byMode": [],
            "byHorizon": [],
            "byHoldingDaysBucket": [],
            "byRegime": [],
            "byEntryType": [],
            "byGapDirection": [],
        },
        "comparison": _comparison([], []),
        "causeCandidates": [],
        "patch": _patch_decision(0, 0, []),
        "appliedPatch": False,
        "patchType": "diagnostic_only",
        "patchReason": "분석 가능한 평가 완료 거래가 아직 없습니다.",
        "shouldModifyTradingLogicNow": False,
        "note": "Market-gap diagnostics use evaluated-only virtual trade rows (NEXT_OPEN entries) and do not change recommendation logic, candidate filters, or entry price formulas.",
    }


def build_market_gap_diagnostics(
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
        out["warning"] = f"market-gap diagnostics source unavailable: {exc}"
        return out

    evaluated = [row for row in rows if _is_evaluated_outcome(row)]
    next_open_rows = [row for row in evaluated if _is_next_open(row)]
    if not next_open_rows:
        return empty_response(market, mode, horizon, source_type, journal_session)

    gap_rows = [row for row in next_open_rows if _is_market_gap(row)]
    non_gap_rows = [row for row in next_open_rows if not _is_market_gap(row)]
    dimensions = {
        "byMarket": _dimension(next_open_rows, "market"),
        "byMode": _dimension(next_open_rows, "mode"),
        "byHorizon": _dimension(next_open_rows, "horizon"),
        "byHoldingDaysBucket": _dimension(next_open_rows, "holdingDaysBucket"),
        "byRegime": _dimension(next_open_rows, "regime"),
        "byEntryType": _dimension(evaluated, "entryType"),
        "byGapDirection": _dimension(gap_rows, "gapDirection"),
    }
    comparison = _comparison(gap_rows, non_gap_rows)
    candidates = _cause_candidates(next_open_rows, gap_rows, dimensions, comparison)
    patch = _patch_decision(len(next_open_rows), len(gap_rows), candidates)

    summary = {
        "totalEvaluatedTrades": len(evaluated),
        "nextOpenTrades": len(next_open_rows),
        "marketGapTrades": len(gap_rows),
        "marketGapRate": round(len(gap_rows) / len(next_open_rows), 4) if next_open_rows else 0.0,
        "avgGapPct": comparison["marketGapGroup"]["avgGapPct"],
        "avgReturnGapGroup": comparison["marketGapGroup"]["avgReturn"],
        "avgReturnNonGapGroup": comparison["nonGapNextOpenGroup"]["avgReturn"],
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
        "note": "Market-gap diagnostics use evaluated-only virtual trade rows (NEXT_OPEN entries) and do not change recommendation logic, candidate filters, or entry price formulas.",
    }
