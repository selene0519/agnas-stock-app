from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from statistics import median
from typing import Any, Iterable

from app.services import virtual_trade_journal as vtj

FAILURE_REASON_LABELS = {
    "ENTRY_NOT_TOUCHED": "진입가 미도달",
    "TARGET_BEFORE_STOP": "목표가 선도달",
    "STOP_BEFORE_TARGET": "손절 선도달",
    "TARGET_NOT_REACHED": "목표가 미도달",
    "DIRECTION_FAILED": "방향성 실패",
    "DATA_MISSING": "데이터 부족",
    "PRICE_INVALID": "가격 오류",
    "UNKNOWN": "원인 미분류",
}

DATA_ISSUE_REASONS = {"DATA_MISSING", "PRICE_INVALID"}
DATA_ISSUE_STATUSES = {"DATA_PENDING", "DATA_INVALID"}
EVALUATED_STATUSES = {"EVALUATED", "CANCELLED"}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _upper(value: Any) -> str:
    return _text(value).upper()


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        n = float(str(value).replace(",", "").replace("%", ""))
    except Exception:
        return None
    return n if math.isfinite(n) else None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in {"1", "true", "t", "yes", "y"}


def _bool_value(row: dict[str, Any], field: str) -> bool | None:
    value = _first(row, field)
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = _text(value).lower()
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    return None


def _raw(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("raw_recommendation")
    if isinstance(raw, dict):
        return raw
    raw_json = row.get("raw_recommendation_json")
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            parsed = json.loads(raw_json)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


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


def _failure_reason(row: dict[str, Any]) -> str:
    reason = _upper(_first(row, "failureReason", "failure_reason", "outcome"))
    if not reason or reason in {"NONE", "NAN"}:
        return "UNKNOWN"
    if reason == "STOP_HIT":
        return "STOP_BEFORE_TARGET"
    if reason == "TARGET_HIT":
        return "TARGET_BEFORE_STOP"
    if reason.startswith("TIME_EXIT"):
        return "TARGET_NOT_REACHED"
    if reason.startswith("DATA"):
        return "DATA_MISSING"
    return reason


def _holding_bucket(row: dict[str, Any]) -> str:
    entry_touched = _bool_value(row, "entryTouched")
    if _failure_reason(row) == "ENTRY_NOT_TOUCHED" or entry_touched is False:
        return "entry_not_touched"
    days = _safe_float(_first(row, "holdingDays", "bars_held"))
    if days is None:
        return "unknown"
    if days <= 3:
        return "0-3d"
    if days <= 10:
        return "4-10d"
    if days <= 30:
        return "11-30d"
    return "31d+"


def _setup_bucket(row: dict[str, Any]) -> str:
    setup = _safe_float(_first(row, "setup_score", "setupScore"))
    if setup is None:
        return "unknown"
    if setup >= 75:
        return "setup_high"
    if setup >= 50:
        return "setup_mid"
    return "setup_low"


def _recommendation_bucket(row: dict[str, Any]) -> str:
    value = _first(row, "recommendation_bucket", "decision_bucket", "decisionBucket", "newEntryDecision")
    return _text(value) or "unknown"


def _regime(row: dict[str, Any]) -> str:
    return _text(_first(row, "regime_at_entry", "market_regime_at_signal", "marketRegime")) or "UNKNOWN"


def _return_value(row: dict[str, Any]) -> float | None:
    return _safe_float(_first(row, "net_pnl_pct", "returnPct", "return_pct", "pnl_pct"))


def _mfe(row: dict[str, Any]) -> float | None:
    return _safe_float(_first(row, "maxFavorableExcursion", "mfe_pct"))


def _mae(row: dict[str, Any]) -> float | None:
    return _safe_float(_first(row, "maxAdverseExcursion", "mae_pct"))


def _holding_days(row: dict[str, Any]) -> float | None:
    return _safe_float(_first(row, "holdingDays", "bars_held"))


def _is_data_issue(row: dict[str, Any]) -> bool:
    return _failure_reason(row) in DATA_ISSUE_REASONS or _upper(row.get("status")) in DATA_ISSUE_STATUSES


def _is_classified(row: dict[str, Any]) -> bool:
    return _upper(row.get("status")) in EVALUATED_STATUSES | DATA_ISSUE_STATUSES or bool(_text(_first(row, "failureReason", "failure_reason")))


def _metric(rows: list[dict[str, Any]], denominator: int) -> dict[str, Any]:
    returns = [v for row in rows if (v := _return_value(row)) is not None]
    mfes = [v for row in rows if (v := _mfe(row)) is not None]
    maes = [v for row in rows if (v := _mae(row)) is not None]
    holding_days = [v for row in rows if (v := _holding_days(row)) is not None]
    wins = sum(1 for row in rows if _failure_reason(row) == "TARGET_BEFORE_STOP" or _upper(row.get("outcome")) == "TARGET_HIT" or ((_return_value(row) or 0) > 0))

    def avg(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    count = len(rows)
    return {
        "count": count,
        "ratio": round(count / denominator, 4) if denominator else 0.0,
        "avgReturn": avg(returns),
        "medianReturn": round(median(returns), 4) if returns else None,
        "winRate": round(wins / count, 4) if count else None,
        "avgMFE": avg(mfes),
        "avgMAE": avg(maes),
        "avgHoldingDays": avg(holding_days),
        "entryTouchedRate": _rate(rows, "entryTouched"),
        "targetTouchedRate": _rate(rows, "targetTouched"),
        "stopTouchedRate": _rate(rows, "stopTouched"),
        "targetBeforeStopRate": _rate(rows, "targetBeforeStop"),
    }


def _rate(rows: list[dict[str, Any]], field: str) -> float | None:
    if not rows:
        return None
    known = [_bool_value(row, field) for row in rows]
    known = [value for value in known if value is not None]
    if not known:
        return None
    return round(sum(1 for value in known if value) / len(known), 4)


def _group_rows(rows: Iterable[dict[str, Any]], fields: tuple[str, ...]) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        values = []
        for field in fields:
            if field == "market":
                values.append(_text(row.get("market")).lower() or "unknown")
            elif field == "mode":
                values.append(_text(row.get("mode")).lower() or "unknown")
            elif field == "horizon":
                values.append(_text(row.get("horizon")).lower() or "unknown")
            elif field == "holdingDaysBucket":
                values.append(_holding_bucket(row))
            elif field == "failureReason":
                values.append(_failure_reason(row))
            elif field == "recommendationBucket":
                values.append(_recommendation_bucket(row))
            elif field == "setupBucket":
                values.append(_setup_bucket(row))
            elif field == "regime":
                values.append(_regime(row))
            else:
                values.append(_text(row.get(field)) or "unknown")
        groups[tuple(values)].append(row)
    return groups


def _dimension_items(rows: list[dict[str, Any]], fields: tuple[str, ...], denominator: int) -> list[dict[str, Any]]:
    items = []
    for key, group in _group_rows(rows, fields).items():
        item = {field: value for field, value in zip(fields, key)}
        item.update(_metric(group, denominator))
        if "failureReason" in item:
            item["label"] = FAILURE_REASON_LABELS.get(str(item["failureReason"]), "원인 미분류")
        items.append(item)
    return sorted(items, key=lambda item: (-int(item["count"]), str(item.get("failureReason") or ""), str(item)))


def empty_response(market: str = "all", mode: str = "all", horizon: str = "all", source_type: str = "all", journal_session: str = "all") -> dict[str, Any]:
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
            "totalTrades": 0,
            "evaluatedTrades": 0,
            "entryTouchedTrades": 0,
            "targetBeforeStopTrades": 0,
            "stopBeforeTargetTrades": 0,
            "entryNotTouchedTrades": 0,
            "dataIssueTrades": 0,
            "topFailureReasons": [],
            "avgMFE": None,
            "avgMAE": None,
            "entryTouchedRate": None,
            "targetBeforeStopRate": None,
            "stopBeforeTargetRate": None,
            "entryNotTouchedRate": None,
        },
        "failureReasons": [],
        "groups": [],
        "breakdowns": {
            "byMarket": [],
            "byMode": [],
            "byHorizon": [],
            "byHoldingDaysBucket": [],
            "byRecommendationBucket": [],
            "bySetupBucket": [],
            "byRegime": [],
        },
        "labels": FAILURE_REASON_LABELS,
        "note": "Failure analytics are diagnostic only and are not applied to recommendation ranking.",
    }


def build_failure_analytics(
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
        out["warning"] = f"failure analytics source unavailable: {exc}"
        return out

    classified = [row for row in rows if _is_classified(row)]
    if not rows and not classified:
        return empty_response(market, mode, horizon, source_type, journal_session)

    denominator = len(classified) or len(rows)
    failure_counts = Counter(_failure_reason(row) for row in classified)
    entry_touched = sum(1 for row in classified if _bool_value(row, "entryTouched") is True)
    target_before_stop = sum(1 for row in classified if _bool_value(row, "targetBeforeStop") is True)
    stop_before_target = sum(1 for row in classified if _bool_value(row, "stopTouched") is True and _bool_value(row, "targetBeforeStop") is not True)
    entry_not_touched = sum(1 for row in classified if _failure_reason(row) == "ENTRY_NOT_TOUCHED" or _bool_value(row, "entryTouched") is False)
    has_entry_touch_basis = any(_bool_value(row, "entryTouched") is not None or _failure_reason(row) == "ENTRY_NOT_TOUCHED" for row in classified)
    has_stop_touch_basis = any(_bool_value(row, "stopTouched") is not None or _bool_value(row, "targetBeforeStop") is not None for row in classified)
    data_issues = sum(1 for row in classified if _is_data_issue(row))
    mfes = [v for row in classified if (v := _mfe(row)) is not None]
    maes = [v for row in classified if (v := _mae(row)) is not None]

    top_failure_reasons = [
        {
            "failureReason": reason,
            "label": FAILURE_REASON_LABELS.get(reason, "원인 미분류"),
            "count": count,
            "ratio": round(count / denominator, 4) if denominator else 0.0,
        }
        for reason, count in failure_counts.most_common(5)
    ]

    summary = {
        "totalTrades": len(rows),
        "evaluatedTrades": sum(1 for row in rows if _upper(row.get("status")) in EVALUATED_STATUSES),
        "entryTouchedTrades": entry_touched,
        "targetBeforeStopTrades": target_before_stop,
        "stopBeforeTargetTrades": stop_before_target,
        "entryNotTouchedTrades": entry_not_touched,
        "dataIssueTrades": data_issues,
        "topFailureReasons": top_failure_reasons,
        "avgMFE": round(sum(mfes) / len(mfes), 4) if mfes else None,
        "avgMAE": round(sum(maes) / len(maes), 4) if maes else None,
        "entryTouchedRate": _rate(classified, "entryTouched"),
        "targetBeforeStopRate": _rate(classified, "targetBeforeStop"),
        "stopBeforeTargetRate": round(stop_before_target / denominator, 4) if denominator and has_stop_touch_basis else None,
        "entryNotTouchedRate": round(entry_not_touched / denominator, 4) if denominator and has_entry_touch_basis else None,
    }

    out = empty_response(market, mode, horizon, source_type, journal_session)
    out.update(
        {
            "source": vtj._relative(vtj.EVALUATION_CSV),
            "summary": summary,
            "failureReasons": _dimension_items(classified, ("failureReason",), denominator),
            "groups": _dimension_items(
                classified,
                ("market", "mode", "horizon", "holdingDaysBucket", "failureReason", "recommendationBucket", "setupBucket", "regime"),
                denominator,
            ),
            "breakdowns": {
                "byMarket": _dimension_items(classified, ("market", "failureReason"), denominator),
                "byMode": _dimension_items(classified, ("mode", "failureReason"), denominator),
                "byHorizon": _dimension_items(classified, ("horizon", "failureReason"), denominator),
                "byHoldingDaysBucket": _dimension_items(classified, ("holdingDaysBucket", "failureReason"), denominator),
                "byRecommendationBucket": _dimension_items(classified, ("recommendationBucket", "failureReason"), denominator),
                "bySetupBucket": _dimension_items(classified, ("setupBucket", "failureReason"), denominator),
                "byRegime": _dimension_items(classified, ("regime", "failureReason"), denominator),
            },
        }
    )
    return out
