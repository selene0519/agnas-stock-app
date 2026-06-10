"""
Pattern Strategy Engine v1 — action mapper.

Maps (marketStructure, trendPhase, riskStatus) → final Action.
Structure describes WHAT the market is doing;
Action prescribes WHAT the investor should do.
They can and should diverge (e.g., TREND_UP + EXTENDED → WAIT_PULLBACK).
"""
from __future__ import annotations

from .types import Action, MarketStructure, RiskStatus, TrendPhase, BLOCKED_ACTIONS


def map_action(
    structure:  MarketStructure,
    phase:      TrendPhase,
    risk:       RiskStatus,
) -> Action:
    """Return the recommended action given structure + phase + risk."""

    # ── Risk overrides always win ─────────────────────────────────────────
    if risk == RiskStatus.DATA_QUALITY_RISK:
        return Action.RISK_CHECK
    if risk == RiskStatus.STRUCTURE_BREAKDOWN:
        return Action.AVOID_BUY
    if risk == RiskStatus.MOMENTUM_COLLAPSE:
        return Action.WATCH_ONLY
    if risk == RiskStatus.FAKE_BREAKOUT:
        return Action.AVOID_BUY
    if risk == RiskStatus.OVERHEATED_EXTENSION:
        return Action.WAIT_PULLBACK

    # ── Phase-specific actions ────────────────────────────────────────────
    if phase == TrendPhase.STRUCTURE_BREAKDOWN:
        return Action.AVOID_BUY
    if phase == TrendPhase.PULLBACK_RISK:
        return Action.WATCH_ONLY
    if phase == TrendPhase.STALLED:
        return Action.HOLD_CASH
    if phase == TrendPhase.EXTENDED:
        # Without risk flag → wait for pullback before entering
        return Action.WAIT_PULLBACK

    # ── Structure-based actions ────────────────────────────────────────────
    if structure == MarketStructure.TREND_DOWN:
        return Action.AVOID_BUY

    if structure == MarketStructure.DISTRIBUTION_WATCH:
        return Action.WATCH_ONLY

    if structure == MarketStructure.RANGE_DRIFT:
        return Action.WATCH_ONLY

    if structure == MarketStructure.RANGE:
        if phase == TrendPhase.PULLBACK:
            return Action.WATCH_ONLY
        return Action.HOLD_CASH

    if structure == MarketStructure.BREAKOUT_CANDIDATE:
        if risk == RiskStatus.LOW_ACTIVITY_BREAKOUT:
            return Action.WATCH_ONLY
        if phase == TrendPhase.RETEST:
            return Action.SCALE_IN
        return Action.SCALE_IN

    if structure == MarketStructure.TREND_UP:
        if phase == TrendPhase.NORMAL:
            return Action.SCALE_IN
        if phase == TrendPhase.RETEST:
            return Action.SCALE_IN
        if phase == TrendPhase.PULLBACK:
            return Action.SCALE_IN
        if phase == TrendPhase.PULLBACK_RISK:
            return Action.WATCH_ONLY
        return Action.WAIT_PULLBACK

    return Action.HOLD_CASH


def is_blocked(action: Action) -> bool:
    return action in BLOCKED_ACTIONS
