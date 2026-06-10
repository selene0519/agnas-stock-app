"""
Pattern Strategy Engine v1 — pullback risk assessment.

EXTENDED → PULLBACK transition requires ALL of:
  dailyDownAtr <= normalMaxDownAtr
  volumeRatio20 <= normalMaxVolumeRatio
  MA20 / support / baseBreakout intact

If ANY fails → PULLBACK_RISK or STRUCTURE_BREAKDOWN.
RSI and disparity are necessary but NOT sufficient alone.
"""
from __future__ import annotations

from typing import Any

from .types import TrendPhase, RiskStatus


def assess(
    ind: dict[str, Any],
    current_phase: TrendPhase,
    market_structure: str,
    base_breakout: dict,
    support_levels: list[dict],
    params: dict,
) -> tuple[TrendPhase, RiskStatus]:
    """
    Returns (adjusted_trendPhase, riskStatus).
    Caller applies these on top of the structural phase.
    """
    pr     = params.get("pullbackRisk", {})
    normal_dda  = pr.get("normalMaxDownAtr",     1.2)
    risk_dda    = pr.get("riskDownAtr",          1.5)
    breakdown   = pr.get("breakdownDownAtr",     2.2)
    normal_vr   = pr.get("normalMaxVolumeRatio", 1.5)
    risk_vr     = pr.get("riskVolumeRatio",      2.0)
    ma20_break  = pr.get("ma20BreakAtr",         0.5)
    base_break  = pr.get("baseBreakAtr",         0.3)

    atr20    = ind.get("atr20") or 0.0
    dda      = ind.get("dailyDownAtr")
    vr       = ind.get("volumeRatio20") or 0.0
    rsi      = ind.get("rsi14")
    disp     = ind.get("ma20Disparity")
    close    = ind.get("close") or 0.0
    ma20     = ind.get("ma20") or 0.0
    ma10     = ind.get("ma10") or 0.0

    base_level = base_breakout.get("level", 0.0) if base_breakout else 0.0

    # ── DATA_QUALITY_RISK: ATR is unusable ────────────────────────────────
    if not atr20 or atr20 <= 0:
        return TrendPhase.STALLED, RiskStatus.DATA_QUALITY_RISK

    # ── Structural checks ─────────────────────────────────────────────────
    ma20_broken    = bool(ma20 and close < ma20 - ma20_break * atr20)
    base_broken    = bool(base_level and close < base_level - base_break * atr20)
    support_broken = not _any_support_intact(support_levels, close, atr20, params)
    two_day_dump   = bool(dda and dda > breakdown)

    # ── STRUCTURE_BREAKDOWN ────────────────────────────────────────────────
    if dda and dda > breakdown:
        return TrendPhase.STRUCTURE_BREAKDOWN, RiskStatus.STRUCTURE_BREAKDOWN
    if base_broken and ma20_broken:
        return TrendPhase.STRUCTURE_BREAKDOWN, RiskStatus.STRUCTURE_BREAKDOWN

    # ── MOMENTUM_COLLAPSE: gap-up then large wick or sudden volume dump ────
    # todayHigh >> close and volume spike = distribution
    today_high = ind.get("todayHigh") or 0.0
    gap_wick   = bool(today_high and close and atr20 and (today_high - close) > 1.5 * atr20)
    if gap_wick and vr > risk_vr:
        return TrendPhase.PULLBACK_RISK, RiskStatus.MOMENTUM_COLLAPSE

    # ── PULLBACK_RISK ──────────────────────────────────────────────────────
    if dda and dda > risk_dda:
        return TrendPhase.PULLBACK_RISK, RiskStatus.MOMENTUM_COLLAPSE
    if vr > risk_vr and dda and dda > 1.0:
        return TrendPhase.PULLBACK_RISK, RiskStatus.MOMENTUM_COLLAPSE
    if ma20_broken:
        return TrendPhase.PULLBACK_RISK, RiskStatus.STRUCTURE_BREAKDOWN

    # ── LOW_ACTIVITY_BREAKOUT: breakout on insufficient volume ─────────────
    min_vr = 1.2  # matches breakout.minVolumeRatio default
    if market_structure in ("BREAKOUT_CANDIDATE",) and vr is not None and vr < min_vr:
        return TrendPhase.RETEST, RiskStatus.LOW_ACTIVITY_BREAKOUT

    # ── OVERHEATED_EXTENSION ───────────────────────────────────────────────
    overheated = bool(rsi and rsi > 75 and disp and disp > 1.12)
    if current_phase == TrendPhase.EXTENDED or overheated:
        return TrendPhase.EXTENDED, RiskStatus.OVERHEATED_EXTENSION

    # ── NORMAL PULLBACK: all conditions pass ──────────────────────────────
    if dda is not None and dda <= normal_dda and vr <= normal_vr:
        if current_phase in (TrendPhase.EXTENDED, TrendPhase.PULLBACK, TrendPhase.PULLBACK_RISK):
            return TrendPhase.PULLBACK, RiskStatus.NONE
        return current_phase, RiskStatus.NONE

    # ── Default: no override ──────────────────────────────────────────────
    return current_phase, RiskStatus.NONE


def _any_support_intact(levels: list[dict], close: float, atr20: float, params: dict) -> bool:
    if not levels:
        return True  # No levels tracked → can't say it's broken
    sp  = params.get("supportMemory", {})
    buf = sp.get("supportReturnBufferAtr", 0.2) * atr20
    return any(
        lv["role"] == "support" and close >= lv["level"] - buf
        for lv in levels
    )
