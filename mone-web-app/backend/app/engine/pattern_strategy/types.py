"""
Pattern Strategy Learning Engine v1 — type definitions.

All enums, TypedDicts, and the canonical default parameter block live here.
No business logic; import freely from any sibling module.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict


# ── Enums ────────────────────────────────────────────────────────────────────

class MarketStructure(str, Enum):
    RANGE                = "RANGE"
    BREAKOUT_CANDIDATE   = "BREAKOUT_CANDIDATE"
    TREND_UP             = "TREND_UP"
    TREND_DOWN           = "TREND_DOWN"
    RANGE_DRIFT          = "RANGE_DRIFT"
    DISTRIBUTION_WATCH   = "DISTRIBUTION_WATCH"


class TrendPhase(str, Enum):
    NORMAL              = "NORMAL"
    RETEST              = "RETEST"
    EXTENDED            = "EXTENDED"
    PULLBACK            = "PULLBACK"
    PULLBACK_RISK       = "PULLBACK_RISK"
    STALLED             = "STALLED"
    STRUCTURE_BREAKDOWN = "STRUCTURE_BREAKDOWN"


class Action(str, Enum):
    BUY_NOW        = "BUY_NOW"
    SCALE_IN       = "SCALE_IN"
    WAIT_PULLBACK  = "WAIT_PULLBACK"
    WATCH_ONLY     = "WATCH_ONLY"
    AVOID_BUY      = "AVOID_BUY"
    HOLD_CASH      = "HOLD_CASH"
    RISK_CHECK     = "RISK_CHECK"


class RiskStatus(str, Enum):
    NONE                  = "NONE"
    OVERHEATED_EXTENSION  = "OVERHEATED_EXTENSION"
    MOMENTUM_COLLAPSE     = "MOMENTUM_COLLAPSE"
    LOW_ACTIVITY_BREAKOUT = "LOW_ACTIVITY_BREAKOUT"
    FAKE_BREAKOUT         = "FAKE_BREAKOUT"
    STRUCTURE_BREAKDOWN   = "STRUCTURE_BREAKDOWN"
    DATA_QUALITY_RISK     = "DATA_QUALITY_RISK"


# 12 canonical pattern names
PATTERN_NAMES = {
    "trend_up_pullback",
    "horizontal_support_rebound",
    "resistance_breakout",
    "breakout_retest",
    "range_bottom_rebound",
    "volatility_contraction_expansion",
    "false_breakout_risk",
    "resistance_chase_risk",
    "overheated_chase_risk",
    "downtrend_bounce_trap",
    "volume_turnaround",
    "relative_strength",
    # composite / derived
    "overheated_pullback_risk",
    "base_breakout_held",
    "ma20_near",
    "distribution_zone",
    "range_drift_watch",
    "zombie_breakout",
    "structure_breakdown_risk",
}


# ── TypedDicts ────────────────────────────────────────────────────────────────

class SupportLevel(TypedDict):
    level: float
    role: str           # "support" | "resistance_candidate" | "broken_support"
    importance: float   # 0.0–1.0
    touchCount: int
    lastTestedDate: str
    atrDistance: float  # distance from current close in ATR units


class BreakoutRecord(TypedDict):
    level: float
    date: str
    volumeRatio: float
    confirmed: bool     # True once price held for confirmMaxDays


class IndicatorSnapshot(TypedDict):
    atr20: float | None
    rsi14: float | None
    ma20: float | None
    ma10: float | None
    ma5: float | None
    ma20Disparity: float | None
    volumeRatio20: float | None
    dailyDownAtr: float | None
    close: float
    prevClose: float | None
    todayHigh: float | None
    todayLow: float | None
    rangeHigh: float | None   # 40-day rolling high
    rangeLow: float | None    # 40-day rolling low
    rangeWidth: float | None  # (high - low) / low


class PatternResult(TypedDict):
    symbol: str
    market: str
    marketStructure: str
    trendPhase: str
    primaryPattern: str
    secondaryPatterns: list[str]
    riskStatus: str
    isBlocked: bool
    action: str
    originalAction: str
    confidence: int
    confidenceBeforeRisk: int
    indicators: dict[str, Any]
    baseBreakout: dict[str, Any]
    extensionBreakouts: list[dict[str, Any]]
    historicalSupportLevels: list[dict[str, Any]]
    message: str
    rangeFloor: float | None
    rangeCeiling: float | None
    rangeShiftCount: int
    geometricPattern: str | None
    geometricPatternDirection: str | None
    geometricPatternStage: str | None
    geometricPatternTrigger: float | None
    geometricPatternReason: str | None
    geometricPatternConfirmed: bool
    candlestickPattern: str | None
    candlestickPatternDirection: str | None
    candlestickPatternFit: float | None
    candlestickPatternConfirmed: bool
    candlestickPatternReason: str | None
    candlestickCandidates: list[str]


# Japanese candlestick patterns (see candlestick_patterns.py).
# Context-gated: only surfaced when they align with the current market flow.
CANDLESTICK_PATTERN_NAMES = {
    # Bullish — confirmed (setup + 확인봉)
    "MORNING_STAR_PINBAR",           # 샛별 + 핀버
    "BULLISH_ENGULFING_MARUBOZU",    # 음을양병 + 포병
    "SPIKE_PINBAR",                  # 스파이크로 + 핀버
    "THREE_INSIDE_UP",               # 삼강법 (본질적으로 confirmed)
    "LION_MOUTH",                    # 사자 입: 연속하락+고거래량 핀버
    # Bullish — setup-only fallback
    "MORNING_STAR",
    "BULLISH_ENGULFING",
    "SPIKE_REVERSAL",
    "HARAMI_BULLISH",                # 강세 하라미 (2봉)
    # Bearish — confirmed (setup + 확인봉)
    "EVENING_STAR_BEAR",             # 저녁별 + 강한음봉
    "THREE_BLACK_CROWS",             # 흑삼병 (본질적으로 confirmed)
    "BEARISH_ENGULFING_DARK_CLOUD",  # 두브러리 + 그늘그개
    "SHOOTING_STAR_CONFIRM",         # 유성형 + 확인봉
    "THREE_INSIDE_DOWN",             # 역삼강법 (본질적으로 confirmed)
    # Bearish — setup-only fallback
    "EVENING_STAR",
    "BEARISH_ENGULFING",
    "SHOOTING_STAR",
    "HARAMI_BEARISH",                # 약세 하라미 (2봉)
}


# Classic geometric chart patterns (Phase 1, see geometric_patterns.py).
# Kept separate from PATTERN_NAMES above, which are the indicator-driven patterns.
GEOMETRIC_PATTERN_NAMES = {
    # Phase 1 — core 10
    "DOUBLE_BOTTOM",
    "DOUBLE_TOP",
    "HEAD_AND_SHOULDERS",
    "INVERSE_HEAD_AND_SHOULDERS",
    "ASCENDING_TRIANGLE",
    "DESCENDING_TRIANGLE",
    "BULL_FLAG",
    "BEAR_FLAG",
    "FALLING_WEDGE_BREAKOUT",
    "RISING_WEDGE_BREAKDOWN",
    # Phase 2 — practical auxiliary patterns
    "BULL_PENNANT",
    "BEAR_PENNANT",
    "SYMMETRICAL_TRIANGLE",
    "RECTANGLE_RANGE",
    "RISING_CHANNEL",
    "FALLING_CHANNEL",
    "CUP_AND_HANDLE",
    # Phase 3 — MONE-specific risk patterns
    "FAILED_BREAKOUT",
    "FAILED_BREAKDOWN",
    "DISTRIBUTION_WATCH",
    "RANGE_DRIFT",
    "OVEREXTENDED_BREAKOUT",
    "SUPPORT_FLIP_RESISTANCE",
    "RESISTANCE_FLIP_SUPPORT",
}


# Geometric pattern families — used for family-level confirmation calibration
# (walk-forward showed confirmation lift differs by family, not just pattern).
GEO_PATTERN_FAMILY: dict[str, str] = {
    "DOUBLE_BOTTOM":              "REV_BULL",
    "INVERSE_HEAD_AND_SHOULDERS": "REV_BULL",
    "FALLING_WEDGE_BREAKOUT":     "REV_BULL",
    "CUP_AND_HANDLE":             "REV_BULL",
    "FAILED_BREAKDOWN":           "REV_BULL",
    "RESISTANCE_FLIP_SUPPORT":    "REV_BULL",
    "ASCENDING_TRIANGLE":         "CONT_BULL",
    "BULL_FLAG":                  "CONT_BULL",
    "BULL_PENNANT":               "CONT_BULL",
    "RISING_CHANNEL":             "CONT_BULL",
    "DOUBLE_TOP":                 "REV_BEAR",
    "HEAD_AND_SHOULDERS":         "REV_BEAR",
    "RISING_WEDGE_BREAKDOWN":     "REV_BEAR",
    "FAILED_BREAKOUT":            "REV_BEAR",
    "SUPPORT_FLIP_RESISTANCE":    "REV_BEAR",
    "DISTRIBUTION_WATCH":         "REV_BEAR",
    "OVEREXTENDED_BREAKOUT":      "REV_BEAR",
    "DESCENDING_TRIANGLE":        "CONT_BEAR",
    "BEAR_FLAG":                  "CONT_BEAR",
    "BEAR_PENNANT":               "CONT_BEAR",
    "FALLING_CHANNEL":            "CONT_BEAR",
    "SYMMETRICAL_TRIANGLE":       "NEUTRAL",
    "RECTANGLE_RANGE":            "NEUTRAL",
    "RANGE_DRIFT":                "NEUTRAL",
}


# ── Default self-correction parameters ───────────────────────────────────────

DEFAULT_PARAMS: dict[str, Any] = {
    "pullbackRisk": {
        "normalMaxDownAtr":     1.2,
        "riskDownAtr":          1.5,
        "breakdownDownAtr":     2.2,
        "normalMaxVolumeRatio": 1.5,
        "riskVolumeRatio":      2.0,
        "ma20BreakAtr":         0.5,
        "baseBreakAtr":         0.3,
    },
    "supportMemory": {
        "supportReturnBufferAtr":  0.2,
        "supportBreakAtr":         0.3,
        "removeBrokenSupportAtr":  1.0,
        "maxHistoricalLevels":     5,
    },
    "breakout": {
        "breakoutBufferAtr":      0.3,
        "minVolumeRatio":         1.2,
        "extensionOverheatCount": 2,
        "confirmMaxDays":         10,
    },
    "minTradingValue":  500_000_000,   # KRW; 5억 이하 저유동성
    "rangeLookback":    40,            # days for range detection
    "trendLookback":    60,            # days for trend determination
    "minOhlcvRows":     20,            # minimum rows to run engine
}


BLOCKED_ACTIONS = {Action.AVOID_BUY, Action.WATCH_ONLY, Action.HOLD_CASH, Action.RISK_CHECK}
