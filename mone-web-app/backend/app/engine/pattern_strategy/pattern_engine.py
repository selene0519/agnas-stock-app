"""
Pattern Strategy Learning Engine v1 — main orchestrator.

Public API:
    analyze(symbol, market, rows, params=None) → PatternResult dict

The engine is stateless — all state is derived from the OHLCV rows passed in.
Self-correction parameters are loaded from data/pattern_strategy_params.json
(or DEFAULT_PARAMS if the file is absent).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import indicators as ind_mod
from . import market_structure as ms_mod
from . import breakout_state_machine as bsm_mod
from . import support_resistance_memory as srm_mod
from . import pullback_risk as pr_mod
from . import action_mapper as am_mod
from . import geometric_patterns as gp_mod
from .types import (
    Action, DEFAULT_PARAMS, MarketStructure, PatternResult, RiskStatus, TrendPhase,
)


# ── Parameter loading ──────────────────────────────────────────────────────

_PARAMS_PATH = (
    Path(__file__).resolve().parents[5] / "data" / "pattern_strategy_params.json"
)


def load_params() -> dict[str, Any]:
    try:
        if _PARAMS_PATH.exists():
            raw = json.loads(_PARAMS_PATH.read_text(encoding="utf-8"))
            # Deep-merge with defaults so new keys are never missing
            merged: dict = {}
            for section, defaults in DEFAULT_PARAMS.items():
                if isinstance(defaults, dict):
                    merged[section] = {**defaults, **raw.get(section, {})}
                else:
                    merged[section] = raw.get(section, defaults)
            return merged
    except Exception:
        pass
    return dict(DEFAULT_PARAMS)


# ── Pattern classification helpers ────────────────────────────────────────

def _classify_primary(
    structure: MarketStructure,
    phase: TrendPhase,
    risk: RiskStatus,
    ind: dict,
    base_bo: dict,
    extensions: list[dict],
    support_levels: list[dict],
) -> str:
    # Risk patterns take precedence
    if risk == RiskStatus.STRUCTURE_BREAKDOWN:
        return "structure_breakdown_risk"
    if risk == RiskStatus.MOMENTUM_COLLAPSE:
        return "overheated_pullback_risk"
    if risk == RiskStatus.FAKE_BREAKOUT:
        return "false_breakout_risk"
    if risk == RiskStatus.OVERHEATED_EXTENSION:
        return "overheated_chase_risk"
    if risk == RiskStatus.LOW_ACTIVITY_BREAKOUT:
        return "zombie_breakout"
    if risk == RiskStatus.DATA_QUALITY_RISK:
        return "structure_breakdown_risk"

    # Structural patterns
    if structure == MarketStructure.TREND_UP:
        if phase == TrendPhase.EXTENDED:
            return "overheated_chase_risk"
        if phase in (TrendPhase.PULLBACK, TrendPhase.RETEST):
            # Check if we're near a support level
            close = ind.get("close", 0)
            atr20 = ind.get("atr20") or 1
            near_support = any(
                lv["role"] == "support" and abs(close - lv["level"]) <= 1.5 * atr20
                for lv in support_levels
            )
            return "trend_up_pullback" if not near_support else "horizontal_support_rebound"
        return "relative_strength"

    if structure == MarketStructure.BREAKOUT_CANDIDATE:
        if base_bo and len(extensions) == 0:
            return "resistance_breakout"
        if base_bo and extensions and phase == TrendPhase.RETEST:
            return "breakout_retest"
        return "resistance_breakout"

    if structure == MarketStructure.RANGE:
        rsi = ind.get("rsi14")
        rl  = ind.get("rangeLow")
        close = ind.get("close")
        atr20 = ind.get("atr20") or 1
        if rl and close and close <= rl + 2 * atr20:
            return "range_bottom_rebound"
        rw = ind.get("rangeWidth")
        if rw and rw < 0.05:
            return "volatility_contraction_expansion"
        return "range_bottom_rebound"

    if structure == MarketStructure.TREND_DOWN:
        return "downtrend_bounce_trap"

    if structure == MarketStructure.DISTRIBUTION_WATCH:
        return "distribution_zone"

    if structure == MarketStructure.RANGE_DRIFT:
        return "range_drift_watch"

    return "relative_strength"


def _classify_secondary(
    primary: str,
    structure: MarketStructure,
    phase: TrendPhase,
    risk: RiskStatus,
    ind: dict,
    base_bo: dict,
    extensions: list[dict],
    support_levels: list[dict],
) -> list[str]:
    secondary: list[str] = []
    close = ind.get("close", 0)
    ma20  = ind.get("ma20")
    atr20 = ind.get("atr20") or 1
    vr    = ind.get("volumeRatio20") or 0
    rsi   = ind.get("rsi14") or 50

    if base_bo and base_bo.get("confirmed") and primary != "resistance_breakout":
        secondary.append("base_breakout_held")

    if ma20 and abs(close - ma20) <= 1.0 * atr20:
        secondary.append("ma20_near")

    if vr > 1.5 and structure not in (MarketStructure.TREND_DOWN,):
        secondary.append("volume_turnaround")

    if rsi < 35 and structure != MarketStructure.TREND_DOWN:
        secondary.append("relative_strength")

    if extensions and len(extensions) >= 2 and primary not in ("overheated_chase_risk",):
        secondary.append("overheated_chase_risk")

    # Resistance chase risk: near range ceiling with high volume
    rh = ind.get("rangeHigh")
    if rh and close and atr20 and close >= rh - 1.0 * atr20 and vr > 1.5:
        secondary.append("resistance_chase_risk")

    return [s for s in secondary if s != primary][:4]


def _compute_confidence(
    primary: str,
    structure: MarketStructure,
    phase: TrendPhase,
    risk: RiskStatus,
    ind: dict,
) -> tuple[int, int]:
    """Returns (confidence_after_risk, confidence_before_risk)."""
    base = 55  # neutral starting point

    # Boost for favorable structure/phase
    if structure == MarketStructure.TREND_UP and phase in (TrendPhase.PULLBACK, TrendPhase.RETEST):
        base += 18
    elif structure == MarketStructure.BREAKOUT_CANDIDATE:
        base += 12
    elif structure == MarketStructure.RANGE:
        base -= 5

    # RSI sweet zone 40–60 → slight boost
    rsi = ind.get("rsi14") or 50
    if 40 <= rsi <= 60:
        base += 5
    elif rsi > 75 or rsi < 25:
        base -= 10

    # Volume confirmation
    vr = ind.get("volumeRatio20") or 1.0
    if vr >= 1.5:
        base += 5
    elif vr < 0.7:
        base -= 8

    before_risk = min(95, max(20, base))

    # Risk penalty
    risk_penalty = {
        RiskStatus.NONE:                 0,
        RiskStatus.LOW_ACTIVITY_BREAKOUT: -8,
        RiskStatus.OVERHEATED_EXTENSION:  -15,
        RiskStatus.FAKE_BREAKOUT:         -25,
        RiskStatus.MOMENTUM_COLLAPSE:     -23,
        RiskStatus.STRUCTURE_BREAKDOWN:   -30,
        RiskStatus.DATA_QUALITY_RISK:     -40,
    }.get(risk, 0)

    after_risk = min(95, max(10, before_risk + risk_penalty))
    return after_risk, before_risk


def _build_message(
    primary: str, risk: RiskStatus, phase: TrendPhase, ind: dict
) -> str:
    dda  = ind.get("dailyDownAtr")
    vr   = ind.get("volumeRatio20")
    rsi  = ind.get("rsi14")
    disp = ind.get("ma20Disparity")

    if risk == RiskStatus.DATA_QUALITY_RISK:
        return "ATR 데이터가 비정상입니다. 데이터 품질을 확인한 후 재판단하세요."
    if risk == RiskStatus.STRUCTURE_BREAKDOWN:
        return f"기준 지지선과 MA20이 붕괴됐습니다. 추가 하락 리스크가 높습니다."
    if risk == RiskStatus.MOMENTUM_COLLAPSE:
        parts = []
        if dda:
            parts.append(f"당일 고가 대비 {dda:.1f}ATR 하락")
        if vr:
            parts.append(f"거래량 {vr:.1f}배")
        return "급락 속도와 거래량이 커서 정상 눌림목으로 보기 어렵습니다." + (
            f" ({', '.join(parts)})" if parts else ""
        )
    if risk == RiskStatus.OVERHEATED_EXTENSION:
        return f"RSI {rsi:.0f}, MA20 이격 {((disp or 1) - 1) * 100:.1f}% 과열 상태. 눌림목 대기 권장."
    if risk == RiskStatus.FAKE_BREAKOUT:
        return "돌파 후 원점 복귀 패턴. 가짜 돌파 가능성이 있어 추격 매수를 피하세요."
    if risk == RiskStatus.LOW_ACTIVITY_BREAKOUT:
        return "거래량 없이 돌파. 신뢰도가 낮아 재테스트를 기다리는 게 안전합니다."

    if primary == "trend_up_pullback":
        return "상승 추세 중 정상 눌림목 구간. 지지선 유지 확인 후 분할 진입을 고려하세요."
    if primary == "horizontal_support_rebound":
        return "수평 지지선 근처에서 반등 패턴. 지지 확인 시 진입 기회입니다."
    if primary == "resistance_breakout":
        return "저항선 돌파 패턴. 거래량 지속 여부를 확인하며 진입하세요."
    if primary == "breakout_retest":
        return "돌파 후 재테스트 중. 기존 저항선이 지지선으로 전환됐는지 확인하세요."
    if primary == "range_bottom_rebound":
        return "박스권 하단 반등 패턴. 하단 지지 확인 후 접근하세요."
    if primary == "volatility_contraction_expansion":
        return "변동성 수축 후 확장 구간. 방향성 돌파 시 진입 기회입니다."
    if primary == "downtrend_bounce_trap":
        return "하락 추세 중 반등. 하락 추세 반등 착시일 수 있어 주의가 필요합니다."
    if primary == "volume_turnaround":
        return "거래량 동반 전환 신호. 추세 전환 가능성을 지속 모니터링하세요."
    if primary == "relative_strength":
        return "시장 대비 상대강도 우위 종목. 추세 유지 여부를 확인하세요."
    if primary == "distribution_zone":
        return "분산 국면. 매도세가 강해 신규 진입보다는 관찰 단계입니다."
    if primary == "range_drift_watch":
        return "방향성 없는 횡보. 돌파 방향을 확인 후 대응하세요."

    return "현재 패턴과 리스크를 종합적으로 검토한 후 진입 여부를 판단하세요."


# ── Public entry point ─────────────────────────────────────────────────────

def analyze(
    symbol: str,
    market: str,
    rows: list[dict],
    params: dict | None = None,
) -> dict[str, Any]:
    """
    Run the full Pattern Strategy Engine for one symbol.

    `rows` must be a list of OHLCV dicts sorted oldest-first, each with at
    minimum: date, open, high, low, close, volume.

    Returns a PatternResult-compatible dict.
    """
    p = params or load_params()
    min_rows = p.get("minOhlcvRows", 20)

    stub = _stub(symbol, market)

    if not rows or len(rows) < min_rows:
        stub["riskStatus"] = RiskStatus.DATA_QUALITY_RISK.value
        stub["message"]    = f"OHLCV 데이터가 부족합니다 ({len(rows)}행). 최소 {min_rows}행 필요."
        return stub

    # 1. Indicators
    ind = ind_mod.compute_all(rows)

    if not ind.get("atr20") or ind["atr20"] <= 0:
        stub["riskStatus"] = RiskStatus.DATA_QUALITY_RISK.value
        stub["message"]    = "ATR20이 계산되지 않았습니다. 데이터 품질을 확인하세요."
        return stub

    # 2. Market structure
    structure, range_floor, range_ceiling = ms_mod.determine(ind, p)

    # 3. Breakout state machine
    base_bo, extensions, is_failed_bo = bsm_mod.run(rows, ind, p)

    # Fake breakout detection
    risk_pre = RiskStatus.NONE
    if is_failed_bo and base_bo:
        risk_pre = RiskStatus.FAKE_BREAKOUT
        structure = MarketStructure.BREAKOUT_CANDIDATE  # keep candidate, mark fake

    # 4. Support/resistance memory
    atr20 = ind["atr20"]
    support_levels = srm_mod.build(rows, atr20, p)

    # 5. Initial trend phase from structure
    phase = _initial_phase(structure, ind, base_bo, extensions, p)

    # 6. Pullback risk assessment
    phase, risk = pr_mod.assess(ind, phase, structure.value, base_bo, support_levels, p)
    if risk_pre != RiskStatus.NONE and risk == RiskStatus.NONE:
        risk = risk_pre

    # 7. Action
    action = am_mod.map_action(structure, phase, risk)
    original_action = action  # before any external override

    # 8. Pattern classification
    primary   = _classify_primary(structure, phase, risk, ind, base_bo, extensions, support_levels)
    secondary = _classify_secondary(primary, structure, phase, risk, ind, base_bo, extensions, support_levels)

    # 8b. Geometric chart pattern (Phase 1, additive — never overrides primary/action)
    geo = gp_mod.detect_all(rows, atr20, ind.get("volumeRatio20"))
    if geo and geo["pattern"] not in secondary:
        secondary = (secondary + [geo["pattern"]])[:4]

    # 9. Confidence
    confidence, conf_before = _compute_confidence(primary, structure, phase, risk, ind)

    # 10. Message
    message = _build_message(primary, risk, phase, ind)

    return {
        "symbol":                 symbol,
        "market":                 market,
        "marketStructure":        structure.value,
        "trendPhase":             phase.value,
        "primaryPattern":         primary,
        "secondaryPatterns":      secondary,
        "riskStatus":             risk.value,
        "isBlocked":              am_mod.is_blocked(action),
        "action":                 action.value,
        "originalAction":         original_action.value,
        "confidence":             confidence,
        "confidenceBeforeRisk":   conf_before,
        "indicators": {
            "atr20":         round(atr20, 2),
            "dailyDownAtr":  ind.get("dailyDownAtr"),
            "volumeRatio20": ind.get("volumeRatio20"),
            "rsi14":         ind.get("rsi14"),
            "ma20Disparity": ind.get("ma20Disparity"),
            "ma20":          ind.get("ma20"),
            "ma10":          ind.get("ma10"),
            "close":         ind.get("close"),
            "rangeHigh":     ind.get("rangeHigh"),
            "rangeLow":      ind.get("rangeLow"),
        },
        "baseBreakout":            base_bo,
        "extensionBreakouts":      extensions,
        "historicalSupportLevels": support_levels,
        "message":                 message,
        "rangeFloor":              range_floor,
        "rangeCeiling":            range_ceiling,
        "rangeShiftCount":         0,
        "geometricPattern":          geo["pattern"] if geo else None,
        "geometricPatternDirection": geo["direction"] if geo else None,
        "geometricPatternStage":     geo["stage"] if geo else None,
        "geometricPatternTrigger":   geo["trigger"] if geo else None,
        "geometricPatternReason":    geo["reason"] if geo else None,
    }


# ── Internal helpers ───────────────────────────────────────────────────────

def _initial_phase(
    structure: MarketStructure,
    ind: dict,
    base_bo: dict,
    extensions: list[dict],
    params: dict,
) -> TrendPhase:
    """Derive initial TrendPhase from structure before pullback-risk override."""
    overheat_n = params.get("breakout", {}).get("extensionOverheatCount", 2)
    rsi        = ind.get("rsi14") or 50
    disp       = ind.get("ma20Disparity") or 1.0

    if structure in (MarketStructure.TREND_DOWN, MarketStructure.DISTRIBUTION_WATCH):
        return TrendPhase.STRUCTURE_BREAKDOWN

    if structure == MarketStructure.RANGE:
        return TrendPhase.STALLED

    if structure == MarketStructure.RANGE_DRIFT:
        return TrendPhase.STALLED

    # EXTENDED: too many extensions or very overbought
    if len(extensions) >= overheat_n or (rsi > 75 and disp > 1.1):
        return TrendPhase.EXTENDED

    if structure == MarketStructure.BREAKOUT_CANDIDATE:
        # Has base confirmed? → RETEST or NORMAL
        if base_bo and base_bo.get("confirmed"):
            return TrendPhase.RETEST
        return TrendPhase.NORMAL

    if structure == MarketStructure.TREND_UP:
        # RSI sweet zone → healthy pullback
        if 35 <= rsi <= 55 and disp and 0.95 <= disp <= 1.05:
            return TrendPhase.PULLBACK
        return TrendPhase.NORMAL

    return TrendPhase.NORMAL


def _stub(symbol: str, market: str) -> dict[str, Any]:
    return {
        "symbol":                 symbol,
        "market":                 market,
        "marketStructure":        MarketStructure.RANGE.value,
        "trendPhase":             TrendPhase.STALLED.value,
        "primaryPattern":         "structure_breakdown_risk",
        "secondaryPatterns":      [],
        "riskStatus":             RiskStatus.DATA_QUALITY_RISK.value,
        "isBlocked":              True,
        "action":                 Action.RISK_CHECK.value,
        "originalAction":         Action.RISK_CHECK.value,
        "confidence":             0,
        "confidenceBeforeRisk":   0,
        "indicators":             {},
        "baseBreakout":           {},
        "extensionBreakouts":     [],
        "historicalSupportLevels": [],
        "message":                "데이터 부족",
        "rangeFloor":             None,
        "rangeCeiling":           None,
        "rangeShiftCount":        0,
        "geometricPattern":          None,
        "geometricPatternDirection": None,
        "geometricPatternStage":     None,
        "geometricPatternTrigger":   None,
        "geometricPatternReason":    None,
    }
