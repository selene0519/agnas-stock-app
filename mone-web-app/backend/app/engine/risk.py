from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.engine import correction, data_quality, session
from app.engine.symbols import display_name, normalize_market, normalize_symbol
from app.services import data_loader as data
from app.services import final_engine

MODE_ALIASES = {
    "보수": "conservative",
    "균형": "balanced",
    "공격": "aggressive",
    "conservative": "conservative",
    "balanced": "balanced",
    "aggressive": "aggressive",
}

HORIZON_ALIASES = {
    "단기": "short",
    "스윙": "swing",
    "장기": "mid",
    "short": "short",
    "swing": "swing",
    "mid": "mid",
    "long": "mid",
}

TERM_TEXT = {
    "short": "단기: 1~3일 청산 목표",
    "swing": "스윙: 1~3주 보유 목표",
    "mid": "장기: 1~3개월 호흡 매매",
}

CAPITAL_WEIGHT = {"conservative": 0.12, "balanced": 0.18, "aggressive": 0.25}


def _mode(value: Any) -> str:
    text = str(value or "balanced").strip()
    return MODE_ALIASES.get(text, MODE_ALIASES.get(text.lower(), "balanced"))


def _horizon(value: Any) -> str:
    text = str(value or "swing").strip()
    return HORIZON_ALIASES.get(text, HORIZON_ALIASES.get(text.lower(), "swing"))


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").replace(",", "").replace("원", "").replace("$", "").replace("%", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _percent(value: Any) -> float:
    parsed = _number(value)
    return float(parsed or 0.0)


def _risk_reward(entry: float, stop: float, target: float) -> float:
    downside = max(entry - stop, 0.0)
    upside = max(target - entry, 0.0)
    return round(upside / downside, 2) if downside else 0.0


def _fundamental_missing_map(market: str) -> dict[str, str]:
    try:
        payload = data.company_analysis(market)
        rows = payload.get("items") or payload.get("rows") or []
    except Exception:
        return {}

    missing: dict[str, str] = {}
    missing_words = ("API 미연결", "CSV 누락", "데이터 없음", "업데이트 대기", "NO_DATA", "PARTIAL", "없음", "N/A")
    for row in rows:
        symbol = normalize_symbol(row.get("symbol") or row.get("code") or row.get("ticker"), market)
        if not symbol:
            continue
        text = " ".join(str(value) for value in row.values())
        if any(word in text for word in missing_words):
            missing[symbol] = "데이터 결손 리스크 보유"
    return missing


def _event_badges(row: dict[str, Any]) -> list[str]:
    raw = []
    for key in ("eventBadges", "eventBadgesText", "newsKeywords", "newsKeyword", "disclosureKeyword"):
        value = row.get(key)
        if isinstance(value, list):
            raw.extend(str(item) for item in value)
        elif value:
            raw.extend(re.split(r"[,/|·]", str(value)))
    badges = [item.strip() for item in raw if item and item.strip()]
    if badges:
        return badges[:3]
    reason = str(row.get("warningReason") or row.get("warning_reason") or "")
    if "공시" in reason:
        return ["공시 리스크"]
    if "거래량" in reason:
        return ["거래량 이상"]
    return []


def _prepare_candidate(
    row: dict[str, Any],
    market: str,
    mode: str,
    horizon: str,
    cash: float,
    missing_fundamentals: dict[str, str],
    correction_summary: dict[str, Any],
) -> dict[str, Any] | None:
    symbol = normalize_symbol(row.get("symbol") or row.get("code") or row.get("ticker"), market)
    if not symbol:
        return None

    name = display_name(symbol, row.get("name"), market)
    data_status = str(row.get("dataStatus") or "PARTIAL").upper()
    price_status = str(row.get("priceDataStatus") or row.get("dataStatus") or "PARTIAL").upper()
    entry = _number(row.get("entry") or row.get("entryPrice") or row.get("recommendedEntry") or row.get("currentPrice"))
    current = _number(row.get("currentPrice") or row.get("current_price") or row.get("basePrice"))
    stop = _number(row.get("stop") or row.get("stopLoss"))
    target = _number(row.get("target") or row.get("targetPrice"))

    if not entry or not current:
        return None

    if mode == "conservative":
        stop = round(entry * 0.985, 2)
    elif not stop:
        stop = round(entry * 0.97, 2)
    if not target:
        target = round(entry * (1.045 if mode != "aggressive" else 1.07), 2)

    rr = _risk_reward(entry, stop, target)
    warnings = []
    original_warning = row.get("warning_reason") or row.get("warningReason")
    if original_warning:
        warnings.append(str(original_warning))

    fundamental_missing = symbol in missing_fundamentals
    if fundamental_missing and mode in {"conservative", "balanced"}:
        return None
    if fundamental_missing:
        warnings.append(missing_fundamentals[symbol])

    if mode == "conservative":
        if data_status in {"PARTIAL", "STALE", "NO_DATA", "ERROR"} or price_status in {"STALE", "NO_DATA", "ERROR"}:
            return None
        if rr < 2.0:
            return None

    if mode == "balanced" and price_status in {"STALE", "NO_DATA", "ERROR"}:
        return None

    if mode == "aggressive":
        warnings.append("테마성 수급 과열 추정, 철저한 분할 진입 요망")

    probability = _percent(
        row.get("winProbability")
        or row.get("probability")
        or row.get("probabilityText")
        or row.get("probSwing")
        or row.get("probShort")
        or row.get("probMid")
    )

    recommended_cash = max(cash, 0.0) * CAPITAL_WEIGHT.get(mode, 0.18)
    recommended_shares = int(recommended_cash // entry) if entry > 0 else 0

    prepared = {
        **row,
        "symbol": symbol,
        "code": symbol,
        "name": name,
        "label": f"{name} ({symbol})" if market == "kr" else f"{name} · {symbol}",
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "termText": TERM_TEXT[horizon],
        "currentPrice": current,
        "currentPriceText": row.get("currentPriceText") or data.format_price(current, market),
        "entry": entry,
        "entryText": row.get("entryText") or data.format_price(entry, market),
        "stop": stop,
        "stopText": data.format_price(stop, market),
        "target": target,
        "targetText": row.get("targetText") or data.format_price(target, market),
        "riskReward": rr,
        "riskRewardText": f"{rr}x",
        "winProbability": probability,
        "probabilityText": f"{probability:.1f}%",
        "dataStatus": data_status,
        "priceDataStatus": price_status,
        "fundamentalMissing": fundamental_missing,
        "eventBadgesText": _event_badges(row),
        "warning_reason": " · ".join(dict.fromkeys(warnings)),
        "recommendedShares": recommended_shares,
        "recommendedSharesText": f"{recommended_shares:,}주" if recommended_shares > 0 else "예수금 부족",
    }
    return correction.apply_penalty(prepared, correction_summary)


def candidates(
    market: str = "kr",
    strategy: str = "balanced",
    term: str = "swing",
    cash: float = 0.0,
    limit: int = 30,
) -> dict[str, Any]:
    normalized_market = normalize_market(market)
    mode = _mode(strategy)
    horizon = _horizon(term)
    quality = data_quality.data_quality(normalized_market)
    correction_state = correction.correction_summary(normalized_market, mode, horizon)
    missing_fundamentals = _fundamental_missing_map(normalized_market)

    payload = final_engine.final_recommendations(normalized_market, mode, horizon, max(limit * 3, 30))
    rows = payload.get("items") or []
    items = []
    for row in rows:
        candidate = _prepare_candidate(row, normalized_market, mode, horizon, cash, missing_fundamentals, correction_state)
        if candidate is not None:
            items.append(candidate)
        if len(items) >= limit:
            break

    return {
        "status": "OK",
        "market": normalized_market,
        "strategy": mode,
        "term": horizon,
        "termText": TERM_TEXT[horizon],
        "priceSession": quality.get("priceSession"),
        "dataStatus": quality.get("dataStatus"),
        "killSwitch": quality.get("killSwitch"),
        "reviewMode": quality.get("reviewMode"),
        "session": quality.get("session"),
        "dataQuality": quality,
        "selfCorrection": correction_state,
        "count": len(items),
        "items": items,
        "generatedAt": datetime.now(session.KST).isoformat(),
    }
