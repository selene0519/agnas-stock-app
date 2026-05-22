from __future__ import annotations

from typing import Any


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        text = str(value).replace("%", "").replace(",", "").strip()
        if text == "" or text.lower() in {"nan", "none", "nat"}:
            return default
        return float(text)
    except Exception:
        return default


def _event_very_high(value: Any) -> bool:
    text = str(value or "").strip()
    return text in {"매우 높음", "very_high", "VERY_HIGH", "high_event_risk"} or "FOMC" in text or "CPI" in text


def evaluate_market_hardblock(market_context: dict[str, Any]) -> dict[str, Any]:
    ctx = market_context or {}
    reasons: list[str] = []
    severity = 0

    if _num(ctx.get("vix_change_pct", ctx.get("vix_pct"))) >= 8:
        severity += 2
        reasons.append("VIX 급등")
    if _num(ctx.get("kosdaq_change_pct", ctx.get("kosdaq_pct"))) <= -2.0:
        severity += 2
        reasons.append("코스닥 급락")
    if _num(ctx.get("nasdaq_future_change_pct", ctx.get("nasdaq_futures_pct"))) <= -1.5:
        severity += 2
        reasons.append("나스닥 선물 급락")
    if _num(ctx.get("sp500_future_change_pct", ctx.get("sp500_futures_pct"))) <= -1.2:
        severity += 2
        reasons.append("S&P500 선물 급락")
    if _num(ctx.get("usdkrw_change_pct", ctx.get("usdkrw_pct"))) >= 0.7:
        severity += 1
        reasons.append("원달러 급등")
    if _num(ctx.get("us10y_change_pct", ctx.get("us10y_pct"))) >= 1.2:
        severity += 1
        reasons.append("미국 10년물 급등")
    if _num(ctx.get("dollar_index_change_pct", ctx.get("dxy_pct"))) >= 0.8:
        severity += 1
        reasons.append("달러지수 급등")

    down_ratio = _num(ctx.get("candidate_down_ratio"), 0.0)
    if down_ratio > 1:
        down_ratio = down_ratio / 100
    if down_ratio >= 0.85:
        severity += 4
        reasons.append("후보군 하락 비율 85% 이상")
    elif down_ratio >= 0.75:
        severity += 3
        reasons.append("후보군 하락 비율 75% 이상")
    elif down_ratio >= 0.60:
        severity += 1
        reasons.append("후보군 하락 비율 60% 이상")

    if _event_very_high(ctx.get("event_risk_level") or ctx.get("schedule_risk_level") or ctx.get("event_type")):
        severity += 2
        reasons.append("일정 리스크 매우 높음")

    if severity >= 5:
        level = "매우 강함"
    elif severity >= 3:
        level = "강함"
    elif severity >= 1:
        level = "주의"
    else:
        level = "없음"

    return {
        "market_hardblock": level in {"강함", "매우 강함"},
        "hardblock_level": level,
        "hardblock_reasons": reasons,
        "new_buy_blocked": level in {"강함", "매우 강함"},
    }
