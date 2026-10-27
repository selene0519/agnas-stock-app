"""One read-only recommendation path for home, detail and daily notifications."""
from __future__ import annotations

import copy
import math
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo


def _number(value: Any) -> float | None:
    try:
        number = float(str(value).replace(",", "").replace("$", "").replace("원", "").replace("%", ""))
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


@lru_cache(maxsize=128)
def _sessions(market: str, day: str) -> tuple[tuple[datetime, datetime], ...]:
    import pandas_market_calendars as calendars
    start = datetime.fromisoformat(day).date()
    schedule = calendars.get_calendar("XKRX" if market == "kr" else "NYSE").schedule(
        start_date=start, end_date=start + timedelta(days=14),
    )
    return tuple((row.market_open.to_pydatetime(), row.market_close.to_pydatetime()) for row in schedule.itertuples())


def execution_plan(item: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Preserve issued prices; never invent a forecast, a fill, or a personal allocation."""
    now = now or datetime.now(timezone.utc)
    market = str(item.get("market") or "").lower()
    generated = _timestamp(item.get("generatedAt") or item.get("generated_at"))
    entry = _number(item.get("entry") or item.get("entryPrice"))
    stop = _number(item.get("stop") or item.get("stopPrice"))
    target = _number(item.get("target") or item.get("targetPrice"))
    reasons: list[str] = []
    if not (entry and stop and target and 0 < stop < entry < target):
        reasons.append("INVALID_PRICE_PLAN")
    opens = closes = None
    if generated is None or market not in {"kr", "us"}:
        reasons.append("PLAN_TIMESTAMP_UNAVAILABLE")
    else:
        try:
            tz = ZoneInfo("Asia/Seoul" if market == "kr" else "America/New_York")
            opens, closes = next((op, cl) for op, cl in _sessions(market, generated.astimezone(tz).date().isoformat()) if cl > generated)
            if now >= closes:
                reasons.append("PLAN_EXPIRED")
            if generated > now + timedelta(minutes=5):
                reasons.append("FUTURE_PLAN_TIMESTAMP")
        except Exception:
            reasons.append("SESSION_CALENDAR_UNAVAILABLE")
    allowed = (
        item.get("publicTradeStatus") == "TRADE_CANDIDATE"
        and not item.get("isTradeBlocked") and not item.get("reviewOnly")
        and item.get("entryAllowed") is not False
    )
    if not allowed:
        reasons.append("PUBLIC_GATE_NOT_PASSED")
    if item.get("sourceStatus") == "FALLBACK":
        reasons.append("REQUESTED_PROFILE_UNAVAILABLE")
    if item.get("decisionBucket") != "오늘 진입":
        reasons.append("WAIT_FOR_NEXT_BRIEFING")
    # A published limit is an exact price, not permission to chase an arbitrary range.
    zone = {"low": entry, "high": entry}
    return {
        "version": "public-plan-v1", "status": "READY" if not reasons else "WATCH",
        "entry": entry, "stop": stop, "target": target, "entryZone": zone,
        "generatedAt": generated.isoformat() if generated else None,
        "validFrom": max(opens, generated).isoformat() if opens and generated else None,
        "validUntil": closes.isoformat() if closes else None,
        "reasonCodes": reasons,
        "entryCondition": "지정 진입가에서만 검토 · 가격 도달만으로 관찰 후보가 진입 후보로 바뀌지 않음",
        "cancelCondition": "유효기한 경과, 손절가 이탈 또는 새로운 진입 차단 발생 시 취소 · 미체결은 다음 브리핑에서 재평가",
        "monitoring": "PREMARKET_ONCE",
    }


def attach_execution_plans(payload: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        plan = execution_plan(item, now)
        item["executionPlan"] = plan
        if plan["status"] != "READY" and item.get("decisionBucket") == "오늘 진입":
            item.setdefault("decisionBucketOriginal", "오늘 진입")
            item["decisionBucket"] = "관찰"
    return payload


def preserve_published_inputs(item: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """The generator already applied profile/correction rules; a read must not apply them twice."""
    for field in ("entry", "stop", "target"):
        value = _number(row.get(field))
        item[field] = value
        item[f"{field}Price"] = value
        item[f"{field}Text"] = row.get(field) if value is not None else ""
    for field in ("finalScore", "finalRankScore", "expectedValue", "rrActual"):
        item[field] = _number(row.get(field))
    item["expectedValueText"] = f"{item['expectedValue']:+.1f}%" if item["expectedValue"] is not None else ""
    item["decisionBucket"] = row.get("decisionBucket") or "관찰"
    item["pricePlanSource"] = "PUBLISHED_RECOMMENDATION"
    for field in ("isTradeBlocked", "reviewOnly"):
        if str(row.get(field) or "").lower() in {"true", "1", "yes"}:
            item[field] = True
    if row.get("tradeBlockReason"):
        item["tradeBlockReason"] = row["tradeBlockReason"]
    item["correctionInputContractVersion"] = row.get("correctionInputContractVersion")
    item["computedFields"] = [field for field in item.get("computedFields", []) if not field.startswith("strategy_horizon_")]
    return item


def public_recommendations(market: str, mode: str, horizon: str, limit: int = 50) -> dict[str, Any]:
    from app.engine.mone_v65_api_stabilizer import _reco_file_version, _repo_root
    root = _repo_root()
    paths = [root / "reports" / name for name in (
        "strategy_win_rates.json", "self_correction_shadow.json", "quant_operating_status.json",
        f"{market}_recommendation_gen_status.json", f"kis_current_price_{market}.csv",
    )]
    signature = tuple(path.stat().st_mtime_ns if path.exists() else 0 for path in paths)
    payload = copy.deepcopy(_public_snapshot(market, mode, horizon, 50, _reco_file_version(market, mode, horizon), signature, int(time.time() // 60)))
    payload["items"] = (payload.get("items") or [])[:max(1, min(limit, 50))]
    payload["count"] = len(payload["items"])
    # Recheck expiration on every read, including reads served from the short cache.
    return attach_execution_plans(payload)


@lru_cache(maxsize=36)
def _public_snapshot(market: str, mode: str, horizon: str, limit: int, version: int, safety_version: tuple[int, ...], minute: int) -> dict[str, Any]:
    from app.engine.mone_v65_api_stabilizer import _recommendations_payload
    # No journal writes or alternate CSV fallback on a public display/notification read.
    return _recommendations_payload(market, mode, horizon, 0, limit, False, record_ledger=False)


def bind_public_detail(payload: dict[str, Any], market: str) -> dict[str, Any]:
    """Keep chart/company analysis, but bind trading instructions to the public plan."""
    profiles: dict[tuple[str, str], dict[str, Any]] = {}
    items = []
    for raw in payload.get("items") or []:
        row = dict(raw)
        mode, horizon = str(row.get("mode") or ""), str(row.get("horizon") or "")
        scope = (mode, horizon)
        try:
            if mode not in {"conservative", "balanced", "aggressive"} or horizon not in {"short", "swing", "mid"}:
                raise ValueError("unknown profile")
            if scope not in profiles:
                profiles[scope] = public_recommendations(market, mode, horizon)
            approved = next((candidate for candidate in profiles[scope].get("items", [])
                             if candidate.get("symbol") == row.get("symbol")), None)
        except Exception:
            approved = None
        if approved is not None:
            # Detailed indicators/news remain available. The public candidate owns
            # all prices, scores, gates and execution status, including denials.
            row.update(approved)
            row["isTradeBlocked"] = bool(approved.get("isTradeBlocked"))
            row["reviewOnly"] = bool(approved.get("reviewOnly"))
            row["tradeBlockStatus"] = approved.get("tradeBlockStatus") or "OK"
            row["tradeBlockReason"] = approved.get("tradeBlockReason") or ""
            for field in ("entry", "stop", "target"):
                row[f"{field}Price"] = approved.get(field)
                row[f"{field}PriceText"] = approved.get(f"{field}Text")
            row["stopLoss"] = approved.get("stop")
            row["planSource"] = "PUBLIC_RECOMMENDATION"
        else:
            row.update({"isTradeBlocked": True, "reviewOnly": True,
                        "publicTradeStatus": "NO_TRADE", "decisionBucket": "관찰",
                        "entryAllowed": False,
                        "positionPlan": {"status": "NO_POSITION", "suggestedWeightPct": 0, "suggestedShares": 0},
                        "tradeBlockReason": "현재 공개 추천에 포함되지 않은 분석 자료",
                        "planSource": "ANALYSIS_ONLY"})
            row["executionPlan"] = execution_plan(row)
        items.append(row)
    return {**payload, "items": items, "item": items[0] if items else None}
