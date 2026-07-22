"""Fail-closed trade-plan router for different market regimes.

This module converts the *observable* inputs already present in a candidate
(price structure, supply/volume, and event risk) into a compact plan.  It is
intentionally not a return forecaster: a missing or contradictory input moves
the result to WATCH/CASH_ONLY instead of inventing a precise entry.
"""

from __future__ import annotations

import math
from typing import Any


_BULL = {"BULL", "RISK_ON", "UPTREND", "BROADENING"}
_BEAR = {"BEAR", "RISK_OFF", "DOWNTREND", "CONTRACTION", "SHOCK"}
_SIDE = {"SIDE", "NEUTRAL", "RANGE", "TRANSITIONAL", "INFLATIONARY"}
_NEGATIVE_SUPPLY = {"SELL_PRESSURE", "DISTRIBUTION", "NEGATIVE"}
_POSITIVE_SUPPLY = {"STRONG_BUY", "INST_BUY", "ACCUMULATION", "POSITIVE"}


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _regime_key(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in _BULL:
        return "BULL"
    if text in _BEAR:
        return "BEAR"
    if text in _SIDE:
        return "SIDE"
    return "UNKNOWN"


def _price(value: float | None) -> float | None:
    return round(value, 2) if value is not None and value > 0 else None


def _entry_zone(entry: float | None, atr: float | None, width_multiplier: float) -> dict[str, float | None]:
    """Return a small ATR-aware zone; it never claims tick-level precision."""
    if entry is None or entry <= 0:
        return {"low": None, "high": None}
    width = (atr * 0.25 if atr is not None and atr > 0 else entry * 0.003) * width_multiplier
    return {"low": _price(max(0.01, entry - width)), "high": _price(entry + width * 0.6)}


def build_trade_plan(
    item: dict[str, Any],
    *,
    market: str,
    mode: str,
    horizon: str,
    regime: str | None = None,
) -> dict[str, Any]:
    """Build a conservative regime-specific plan from a recommendation item.

    `READY` means that the structural gate is satisfied, not that the trade is
    profitable or that it bypasses portfolio/performance gates elsewhere.
    """
    indicators = item.get("indicators") if isinstance(item.get("indicators"), dict) else {}
    actual_regime = _regime_key(regime or item.get("regime") or item.get("marketRegime"))
    normalized_mode = str(mode or "balanced").lower()
    normalized_horizon = str(horizon or "swing").lower()
    mode_size_multiplier = {"conservative": 0.60, "balanced": 1.00, "aggressive": 1.15}.get(normalized_mode, 1.00)
    horizon_size_multiplier = {"short": 0.75, "swing": 1.00, "mid": 0.85, "long": 0.70}.get(normalized_horizon, 1.00)
    entry_width_multiplier = {"conservative": 0.75, "balanced": 1.00, "aggressive": 1.20}.get(normalized_mode, 1.00)
    entry = _num(item.get("entry")) or _num(item.get("currentPrice"))
    stop = _num(item.get("stop"))
    target = _num(item.get("target"))
    atr = _num(indicators.get("atr14"))
    rsi = _num(indicators.get("rsi14"))
    bb_percent_b = _num(indicators.get("bbPercentB"))
    distance_ma20 = _num(indicators.get("distanceToMa20"))
    ma20 = _num(indicators.get("ma20"))
    volume_ratio = _num(indicators.get("volumeRatio20"))
    event_risk = max(
        value
        for value in (_num(item.get("newsRiskPenalty")), _num(item.get("eventRiskScore")), 0.0)
        if value is not None
    )
    supply = str(item.get("supplySignal") or "").strip().upper()
    risk_flags = {str(flag).upper() for flag in (item.get("riskFlags") or [])}

    reasons: list[str] = []
    status = "WATCH"
    strategy = "UNCLASSIFIED"
    risk_multiplier = 0.0

    if entry is None:
        reasons.append("MISSING_ENTRY_PRICE")
    if atr is None or atr <= 0:
        reasons.append("MISSING_ATR")
    if event_risk >= 10 or "NEWS_DISCLOSURE_RISK" in risk_flags:
        reasons.append("EVENT_OR_DISCLOSURE_RISK")
    if supply in _NEGATIVE_SUPPLY:
        reasons.append("NEGATIVE_SUPPLY")

    hard_block = bool({"MISSING_ENTRY_PRICE", "MISSING_ATR", "EVENT_OR_DISCLOSURE_RISK"} & set(reasons))
    if actual_regime == "BULL":
        strategy = "TREND_PULLBACK"
        if rsi is None or not 40 <= rsi <= 70:
            reasons.append("PULLBACK_RSI_NOT_CONFIRMED")
        if distance_ma20 is None or not -4.0 <= distance_ma20 <= 3.0:
            reasons.append("PULLBACK_DISTANCE_NOT_CONFIRMED")
        if volume_ratio is None or volume_ratio < 0.8:
            reasons.append("VOLUME_NOT_CONFIRMED")
        if not hard_block and supply not in _NEGATIVE_SUPPLY and not {
            "PULLBACK_RSI_NOT_CONFIRMED", "PULLBACK_DISTANCE_NOT_CONFIRMED", "VOLUME_NOT_CONFIRMED"
        } & set(reasons):
            status, risk_multiplier = "READY", 1.0
    elif actual_regime == "SIDE":
        strategy = "RANGE_MEAN_REVERSION"
        if rsi is None or rsi > 42:
            reasons.append("RANGE_OVERSOLD_NOT_CONFIRMED")
        if bb_percent_b is None or bb_percent_b > 0.30:
            reasons.append("BOLLINGER_ENTRY_NOT_CONFIRMED")
        if entry is not None and target is not None and ma20 is not None and ma20 > entry:
            # A range plan takes the nearer of the previous target and the mean.
            target = min(target, ma20)
        elif entry is not None and ma20 is not None and ma20 > entry:
            target = ma20
        else:
            reasons.append("MEAN_REVERSION_TARGET_UNAVAILABLE")
        if not hard_block and supply not in _NEGATIVE_SUPPLY and not {
            "RANGE_OVERSOLD_NOT_CONFIRMED", "BOLLINGER_ENTRY_NOT_CONFIRMED", "MEAN_REVERSION_TARGET_UNAVAILABLE"
        } & set(reasons):
            status, risk_multiplier = "READY", 0.5
    elif actual_regime == "BEAR":
        strategy = "BEAR_RALLY_SCALP"
        if rsi is None or rsi > 32:
            reasons.append("BEAR_RALLY_OVERSOLD_NOT_CONFIRMED")
        if bb_percent_b is None or bb_percent_b > 0.15:
            reasons.append("BEAR_RALLY_BOLLINGER_NOT_CONFIRMED")
        if supply not in _POSITIVE_SUPPLY:
            reasons.append("BEAR_RALLY_SUPPLY_NOT_CONFIRMED")
        if not hard_block and not {
            "BEAR_RALLY_OVERSOLD_NOT_CONFIRMED", "BEAR_RALLY_BOLLINGER_NOT_CONFIRMED", "BEAR_RALLY_SUPPLY_NOT_CONFIRMED"
        } & set(reasons):
            status, risk_multiplier = "READY", 0.25
        else:
            status = "CASH_ONLY"
    else:
        strategy = "UNCLASSIFIED"
        reasons.append("MARKET_REGIME_UNAVAILABLE")

    if entry is None or stop is None or stop <= 0 or stop >= entry:
        reasons.append("INVALID_STOP")
    if entry is None or target is None or target <= entry:
        reasons.append("INVALID_TARGET")

    if hard_block or supply in _NEGATIVE_SUPPLY or {"INVALID_STOP", "INVALID_TARGET"} & set(reasons):
        status = "CASH_ONLY" if actual_regime == "BEAR" else "WATCH"
        risk_multiplier = 0.0
    elif status == "WATCH" and event_risk >= 6:
        reasons.append("ELEVATED_EVENT_RISK")

    zone = _entry_zone(entry, atr, entry_width_multiplier)
    return {
        "version": "regime-plan-v1",
        "market": str(market or "").lower(),
        "mode": normalized_mode,
        "horizon": normalized_horizon,
        "regime": actual_regime,
        "status": status,
        "strategy": strategy,
        "manualReviewRequired": True,
        "riskFractionMultiplier": round(risk_multiplier * mode_size_multiplier * horizon_size_multiplier, 3),
        "riskSizingProfile": {
            "modeMultiplier": mode_size_multiplier,
            "horizonMultiplier": horizon_size_multiplier,
            "entryZoneWidthMultiplier": entry_width_multiplier,
        },
        "entry": _price(entry),
        "entryZone": zone,
        "stop": _price(stop),
        "target": _price(target),
        "reasonCodes": sorted(set(reasons)),
        "evidence": {
            "rsi14": _price(rsi),
            "bbPercentB": _price(bb_percent_b),
            "distanceToMa20": _price(distance_ma20),
            "volumeRatio20": _price(volume_ratio),
            "eventRisk": _price(event_risk),
            "supplySignal": supply or None,
        },
    }
