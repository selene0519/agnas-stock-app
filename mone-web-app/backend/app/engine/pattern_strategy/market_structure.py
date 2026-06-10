"""
Pattern Strategy Engine v1 — market structure determination.

Outputs one of:
  RANGE | BREAKOUT_CANDIDATE | TREND_UP | TREND_DOWN | RANGE_DRIFT | DISTRIBUTION_WATCH
"""
from __future__ import annotations

from typing import Any

from .types import MarketStructure


def _above_ma(close: float | None, ma: float | None) -> bool:
    return bool(close and ma and close > ma)


def _pct_change(a: float | None, b: float | None) -> float | None:
    if a and b and b > 0:
        return (a - b) / b
    return None


def determine(
    ind: dict[str, Any],
    params: dict[str, Any],
    range_shift_count: int = 0,
    prev_structure: str | None = None,
) -> tuple[MarketStructure, float | None, float | None]:
    """
    Returns (structure, rangeFloor, rangeCeiling).
    rangeCeiling / rangeFloor are only meaningful for RANGE / RANGE_DRIFT /
    DISTRIBUTION_WATCH; caller may receive None for trend states.
    """
    close    = ind.get("close")
    ma20     = ind.get("ma20")
    ma10     = ind.get("ma10")
    atr20    = ind.get("atr20")
    rsi14    = ind.get("rsi14")
    rh       = ind.get("rangeHigh")
    rl       = ind.get("rangeLow")
    rw       = ind.get("rangeWidth")
    disp     = ind.get("ma20Disparity")
    vol_r    = ind.get("volumeRatio20")

    bo_buf   = params.get("breakout", {}).get("breakoutBufferAtr", 0.3)
    min_vr   = params.get("breakout", {}).get("minVolumeRatio", 1.2)

    range_floor   = rl
    range_ceiling = rh

    if close is None or ma20 is None or atr20 is None:
        # Not enough data — treat as RANGE
        return MarketStructure.RANGE, range_floor, range_ceiling

    above_ma20 = _above_ma(close, ma20)
    above_ma10 = _above_ma(close, ma10)
    # MA bullish alignment: MA10 >= MA20 * 0.98 (remains valid during mild pullback)
    bullish_ma_align = bool(ma10 and ma20 and ma10 >= ma20 * 0.98)

    # ── RANGE bounds tightened when range is narrow ───────────────────────
    # range_ceiling is the 40-day high; range_floor is the 40-day low
    if rh and rl and rw is not None:
        # Very narrow range (<= 8% width) → tight box
        if rw <= 0.08:
            range_ceiling = rh
            range_floor   = rl
        # Wide range — use MA20 + ATR bands as practical bounds
        else:
            range_ceiling = rh
            range_floor   = rl

    # ── Breakout detection ─────────────────────────────────────────────────
    # Close above range_ceiling + breakoutBufferAtr * ATR20
    breakout_threshold = (rh + bo_buf * atr20) if rh and atr20 else None
    is_price_above_range = bool(breakout_threshold and close > breakout_threshold)
    has_volume = bool(vol_r and vol_r >= min_vr)

    # ── Trend assessment (slope of MA20 over lookback) ─────────────────────
    # Approximate via MA20 disparity; >1.04 = extended above, <0.97 = below
    strongly_above = bool(disp and disp >= 1.04)
    strongly_below = bool(disp and disp <= 0.97)

    # ── Distribution / drift heuristics ────────────────────────────────────
    # DISTRIBUTION_WATCH: price near top of range, volume declining
    near_ceiling = bool(rh and close and atr20 and close >= rh - 1.5 * atr20)
    low_volume   = bool(vol_r and vol_r < 0.8)

    # ── State transitions ──────────────────────────────────────────────────

    # 1. RANGE_DRIFT → DISTRIBUTION_WATCH if range has shifted 3+ times with no momentum
    if prev_structure == MarketStructure.RANGE_DRIFT and range_shift_count > 2 and not has_volume:
        return MarketStructure.DISTRIBUTION_WATCH, range_floor, range_ceiling

    # 2. RANGE_DRIFT → BREAKOUT_CANDIDATE if volume-accompanied upper breakout
    if prev_structure == MarketStructure.RANGE_DRIFT and is_price_above_range and has_volume:
        return MarketStructure.BREAKOUT_CANDIDATE, range_floor, range_ceiling

    # 3. DISTRIBUTION_WATCH exits
    if prev_structure == MarketStructure.DISTRIBUTION_WATCH:
        # Genuine breakout
        if is_price_above_range and bool(vol_r and vol_r > 3.0) and bool(
            ind.get("todayHigh") and close and ind["todayHigh"] and close >= ind["todayHigh"] * 0.98
        ):
            return MarketStructure.BREAKOUT_CANDIDATE, range_floor, range_ceiling
        # Breakdown
        if rl and close and atr20 and close < rl - 0.5 * atr20 and bool(vol_r and vol_r > 1.5):
            return MarketStructure.TREND_DOWN, None, None

    # 4. TREND_DOWN: below MA20 and MA10, declining
    if not above_ma20 and not above_ma10 and strongly_below:
        if rl and close and atr20 and close < rl - 0.5 * atr20:
            return MarketStructure.TREND_DOWN, None, None
        return MarketStructure.TREND_DOWN, None, None

    # 5. BREAKOUT_CANDIDATE: price cleared historical range ceiling (any volume).
    #    Must come before TREND_UP to correctly capture new-high breakouts.
    #    Volume quality is assessed in pullback_risk (LOW_ACTIVITY_BREAKOUT).
    if is_price_above_range:
        return MarketStructure.BREAKOUT_CANDIDATE, range_floor, range_ceiling

    # 6. TREND_UP: above MA20 OR close within 2% of MA20 (normal pullback dip)
    #    with bullish MA alignment (MA10 >= MA20 * 0.98).
    close_near_ma20 = bool(ma20 and close and close >= ma20 * 0.98)
    if (above_ma20 or close_near_ma20) and bullish_ma_align:
        return MarketStructure.TREND_UP, None, None

    # 7. Distribution: near ceiling, low volume, prev was TREND_UP or BREAKOUT
    if near_ceiling and low_volume and prev_structure in (
        MarketStructure.TREND_UP, MarketStructure.BREAKOUT_CANDIDATE
    ):
        return MarketStructure.DISTRIBUTION_WATCH, range_floor, range_ceiling

    # 8. RANGE_DRIFT: price is above MA20 but momentum is stalling
    if above_ma20 and not strongly_above and range_shift_count >= 1:
        return MarketStructure.RANGE_DRIFT, range_floor, range_ceiling

    # Default: RANGE
    return MarketStructure.RANGE, range_floor, range_ceiling
