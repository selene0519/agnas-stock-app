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
from . import candlestick_patterns as cs_mod
from .types import (
    Action, DEFAULT_PARAMS, GEO_PATTERN_FAMILY, MarketStructure, PatternResult,
    RiskStatus, TrendPhase,
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
    market: str = "kr",
    index_mom60: float | None = None,
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

    # MA20 disparity: extension penalty, market-aware.
    # KR is mean-reverting — extended entries stop out; walk-forward showed
    # heavy stop rates above 1.08 disparity. US is a momentum market —
    # extended names keep running, so only extreme extension is penalized
    # (the KR thresholds applied to US cut winning momentum entries).
    disp = ind.get("ma20Disparity")
    if disp:
        if market == "us":
            # Only parabolic extension is penalized — extended momentum names
            # are the top mid-horizon performers in the US; penalizing them at
            # KR thresholds cut returns without reducing the stop rate.
            if disp >= 1.25:
                base -= 10
        else:
            if disp >= 1.12:
                base -= 15   # deeply extended — chasing
            elif disp >= 1.08:
                base -= 8    # moderately extended
        if market == "us":
            # Momentum continuation zone: established uptrend, extended but
            # not extreme — this is where US mid-horizon returns come from.
            if structure == MarketStructure.TREND_UP and 1.04 <= disp < 1.12:
                base += 4
        elif 0.97 <= disp <= 1.04:
            base += 4        # near the mean — best entry zone (KR only:
                             # mean-reversion edge doesn't hold in US momentum)

    # Falling knife: fast intraday decline relative to ATR.
    # Halved for US — violent down days in US uptrends are routinely bought.
    dda = ind.get("dailyDownAtr")
    if dda and dda >= 1.5:
        base -= 5 if market == "us" else 10

    # CCI overbought: momentum already spent. KR only — same rationale as
    # the disparity split above (US momentum tolerates high CCI).
    cci = ind.get("cci20")
    if cci is not None and market != "us" and cci > 150:
        base -= 6

    # Momentum / relative strength — the strongest confidence-orthogonal
    # signal found in the walk-forward. RS = stock 60-bar momentum minus the
    # index's (passed in via index_mom60); falls back to raw momentum when the
    # index is unavailable.
    #   US (momentum market): RS discriminates +12p at 5d, orthogonal to the
    #     rest of confidence → strong reward for leaders, penalty for laggards.
    #   KR (mean-reverting short-term): raw high momentum does NOT help short
    #     term, but relative strength still helps at the 20d horizon → mild,
    #     RS-only, and only the laggard penalty (chasing is already penalized
    #     via disparity above).
    mom60 = ind.get("mom60")
    if mom60 is not None:
        rs60 = mom60 - index_mom60 if index_mom60 is not None else mom60
        if market == "us":
            if rs60 >= 0.15:
                base += 8
            elif rs60 >= 0.05:
                base += 4
            elif rs60 <= -0.15:
                base -= 8
            elif rs60 <= -0.05:
                base -= 4
        else:
            if rs60 <= -0.15:
                base -= 5   # KR laggards underperform even on reversion
            elif rs60 >= 0.10:
                base += 3   # relative leaders hold up over 20d

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


_SIZE_MULT = {
    # KR: confidence is cleanly edge-ordered (20d win 52→59% across tiers),
    # and return dispersion is wide → aggressive spread pays (+1.16p weighted
    # vs equal in the walk-forward).
    "kr": {"STRONG": 1.5, "NORMAL": 1.0, "LIGHT": 0.5, "MINIMAL": 0.25},
    # US: 20d returns are compressed and low-confidence names drift up too
    # (calibration is non-monotonic), so a steep spread mis-sizes. A gentle
    # curve keeps STRONG > LIGHT ordering without starving the winners that
    # land in low tiers.
    "us": {"STRONG": 1.25, "NORMAL": 1.0, "LIGHT": 0.75, "MINIMAL": 0.5},
}


def _position_size(confidence: int, is_blocked: bool, direction_ok: bool,
                   market: str = "kr") -> dict[str, Any]:
    """
    Confidence-tier position sizing, market-aware.

    Tier boundary is confidence 55 — the KR walk-forward jump point (<55 ≈
    50-52% 20d win, ≥55 ≈ 58-59%). Since confidence is already regime- and
    momentum-aware, the tier map captures the edge without re-deriving it.
    Blocked or direction-unconfirmed signals size to zero — sizing never
    overrides a block.

    Multipliers are relative weights (1.0 = one normal unit) for the caller to
    scale its base position by; edge-ordered, deliberately not Kelly-optimal.
    KR uses a wide spread (proven +1.16p), US a gentle one (its confidence is
    less monotonic — a steep spread there mis-sizes).
    """
    if is_blocked or not direction_ok:
        return {"tier": "NONE", "multiplier": 0.0}
    tier = ("STRONG" if confidence >= 65 else
            "NORMAL" if confidence >= 55 else
            "LIGHT"  if confidence >= 45 else "MINIMAL")
    mult = _SIZE_MULT.get(str(market).lower(), _SIZE_MULT["kr"])[tier]
    return {"tier": tier, "multiplier": mult}


# ── Public entry point ─────────────────────────────────────────────────────

def analyze(
    symbol: str,
    market: str,
    rows: list[dict],
    params: dict | None = None,
    market_regime: str = "",
    index_mom60: float | None = None,
) -> dict[str, Any]:
    """
    Run the full Pattern Strategy Engine for one symbol.

    `rows` must be a list of OHLCV dicts sorted oldest-first, each with at
    minimum: date, open, high, low, close, volume.

    `market_regime` is the index-level regime ("BULL"/"BEAR"/"SIDE", empty =
    unknown) computed from KOSPI (KR) or SPY/QQQ/DIA (US) — see
    pattern_validator.current_market_regime(). Regime-aware adjustments:
      • KR SIDE  — worst regime in walk-forward (43-49% win, 40-45% stops):
        confidence dampened.
      • US BEAR  — 5-day swing entries lost money (37-43% win): dampened.
      • Two-signal combo (geo+cs both confirmed, same direction) gets a
        bonus only in trending regimes; in SIDE the combo won just 35% (KR).

    `index_mom60` is the index's 60-bar momentum (KOSPI/SPY) at the same
    cutoff — enables relative-strength scoring (the strongest US confidence
    signal). When None, raw stock momentum is used as a fallback. Live callers
    get it from pattern_validator.current_index_momentum().

    Returns a PatternResult-compatible dict, including positionSizeTier /
    positionSizeMultiplier (confidence-tier sizing) and marketRegime.
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

    # 8b. Geometric chart pattern (additive — never overrides primary/action)
    geo = gp_mod.detect_all(rows, atr20, ind.get("volumeRatio20"), market=str(market).lower())
    if geo and geo["pattern"] not in secondary:
        secondary = (secondary + [geo["pattern"]])[:4]

    # 8c. Context-aware candlestick pattern
    #   Passes the full market context so the detector only returns signals
    #   that are meaningful for the current market flow, not just any candle shape.
    cs = cs_mod.detect_contextual(
        rows,
        atr20,
        market_structure=structure.value,
        trend_phase=phase.value,
        primary_pattern=primary,
        risk_status=risk.value,
        market=str(market).lower(),
    )

    # 9. Confidence — adjusted by candlestick and geometric confirmation
    confidence, conf_before = _compute_confidence(
        primary, structure, phase, risk, ind,
        market=str(market).lower(), index_mom60=index_mom60,
    )

    # Geometric confirmation — direction & family aware. Walk-forward pair
    # analysis (KR/US both, only market-consistent effects used):
    #   REV_BULL confirmed:  directional win +4.6p KR / +2.0p US → long boost.
    #     FALLING_WEDGE_BREAKOUT is the strongest single combo
    #     (+12.7p / +9.8p) → bigger boost.
    #   CONT_BEAR confirmed: price continues DOWN 58-59% of the time
    #     (+12.5p / +9.3p lift) → long confidence must go DOWN, not up.
    #     (The old direction-blind +4 boosted longs into falling channels.)
    #   CONT_BULL / NEUTRAL: no lift (-1.1p/-0.8p) → no adjustment.
    #     ASCENDING_TRIANGLE confirmation is chase-noise (-8.8p/-11.2p).
    #   REV_BEAR confirmed:  NEGATIVE lift (-2.5p/-3.9p) — a strong bear
    #     candle at a top pattern is usually the move already spent → no
    #     long penalty (the fall doesn't reliably follow).
    if geo and geo.get("confirmed"):
        g_fam = GEO_PATTERN_FAMILY.get(geo.get("pattern") or "", "NEUTRAL")
        if g_fam == "REV_BULL":
            boost = 6 if geo.get("pattern") == "FALLING_WEDGE_BREAKOUT" else 4
            confidence = min(95, confidence + boost)
        elif g_fam == "CONT_BEAR":
            confidence = max(10, confidence - 6)
        elif geo.get("pattern") == "RISING_CHANNEL" and str(market).lower() == "us":
            # Train/test-split mining: US rising-channel confirmed rides
            # momentum (train 61% → test 59%, n≈200) — CONT_BULL family
            # default of 0 undervalues this one US-specific combo.
            confidence = min(95, confidence + 4)

    # Bearish geometry in an actionable stage argues against a long entry
    # even when the indicator engine looks fine — KR walk-forward showed these
    # entries carry the highest stop rates. KR only: in the US the same names
    # are routinely dip-bought and rebound over the mid horizon.
    # Exception (train/test mining): DOUBLE_TOP detected in a BEAR regime is
    # noise — after a broad decline, the "top" is a rebound base, and its
    # bearish call hit only 13.9% in the validation window. Skip the penalty.
    _regime_pre = str(market_regime or "").upper()
    if (
        str(market).lower() != "us"
        and geo and geo.get("direction") == "BEARISH"
        and geo.get("stage") in ("AVOID", "BLOCKED")
        and not (geo.get("pattern") == "DOUBLE_TOP" and _regime_pre == "BEAR")
    ):
        confidence = max(10, confidence - 6)

    # Mining survivors with large samples and coherent narratives:
    # KR RANGE_DRIFT — aimless low-volume drift bleeds slowly (5-day long win
    # 39-46% in both train and test windows).
    if geo and geo.get("pattern") == "RANGE_DRIFT" and str(market).lower() != "us":
        confidence = max(10, confidence - 5)
    # US DOUBLE_BOTTOM in a BEAR regime — falling-knife catches; the bullish
    # call won only 37% in BOTH train and test windows (n=178).
    if (
        geo and geo.get("pattern") == "DOUBLE_BOTTOM"
        and str(market).lower() == "us" and _regime_pre == "BEAR"
    ):
        confidence = max(10, confidence - 5)

    # Candlestick alignment: full boost only for volume-backed confirmed
    # signals; setup-only alignment gets half weight (unconfirmed candles
    # showed no lift in the walk-forward). Counter-context penalty unchanged.
    if cs:
        fit = cs["fit"]
        if fit < 0.5:
            cs_boost = round((fit - 0.5) * 8)
        else:
            cs_boost = round((fit - 0.5) * (8 if cs.get("confirmed") else 4))
            if cs.get("confirmed"):
                cs_boost += 3
        confidence = min(95, max(10, confidence + cs_boost))

    # Two-signal combo (이미지의 ★★★★ 구조): geo + cs both confirmed AND
    # pointing the same way. Walk-forward: 51-57% directional win in trending
    # regimes, but only 35% (KR) in SIDE — a range's confirmation candles are
    # fake-breakout noise. Bonus only when the regime is actually trending.
    regime = str(market_regime or "").upper()
    combo_agree = (
        geo and cs
        and geo.get("confirmed") and cs.get("confirmed")
        and geo.get("direction") == cs.get("direction")
        and geo.get("direction") in ("BULLISH", "BEARISH")
    )
    if combo_agree and regime in ("BULL", "BEAR"):
        # Direction-aware: a confirmed BEARISH two-signal combo means price
        # likely falls — that lowers long confidence, it doesn't raise it.
        if geo.get("direction") == "BULLISH":
            confidence = min(95, confidence + 4)
        else:
            confidence = max(10, confidence - 4)

    # Regime dampening — the (market, regime) cells where the engine
    # demonstrably bleeds. KR BEAR and US SIDE are its best cells: untouched.
    if regime == "SIDE" and str(market).lower() != "us":
        confidence = max(10, confidence - 8)   # KR 횡보: 최악 국면
    elif regime == "BEAR" and str(market).lower() == "us":
        confidence = max(10, confidence - 6)   # US 하락장: 스윙 손실 구간
    elif regime == "OVERHEATED":
        # Late-stage index melt-up: mid-horizon entries here won only 39-42%
        # with 51-55% stop rates in the 2026-05/06 KR parabolic top.
        confidence = max(10, confidence - (10 if str(market).lower() != "us" else 6))

    # Support proximity (KR only): entries within 1 ATR above a holding
    # support level have a structural floor in a mean-reverting market.
    # In the US this bonus pulled in mediocre mean-reversion entries that
    # underperformed the momentum names it displaced.
    close_now = ind.get("close")
    if str(market).lower() != "us" and close_now and atr20:
        sup = srm_mod.nearest_support(support_levels, close_now, atr20)
        if sup is not None and (close_now - sup) <= 1.0 * atr20:
            confidence = min(95, confidence + 4)

    # 10. Message
    message = _build_message(primary, risk, phase, ind)

    # 11. Position sizing — confidence tier × direction gate. A geometric
    # signal that points down (bearish) is not a long entry, so it never
    # carries a long size regardless of confidence.
    is_blocked = am_mod.is_blocked(action)
    long_ok = not (geo and geo.get("direction") == "BEARISH"
                   and geo.get("stage") in ("AVOID", "BLOCKED"))
    position = _position_size(confidence, is_blocked, long_ok, market=str(market).lower())

    return {
        "symbol":                 symbol,
        "market":                 market,
        "marketStructure":        structure.value,
        "trendPhase":             phase.value,
        "primaryPattern":         primary,
        "secondaryPatterns":      secondary,
        "riskStatus":             risk.value,
        "isBlocked":              is_blocked,
        "action":                 action.value,
        "originalAction":         original_action.value,
        "confidence":             confidence,
        "confidenceBeforeRisk":   conf_before,
        "positionSizeTier":       position["tier"],
        "positionSizeMultiplier": position["multiplier"],
        "marketRegime":           regime or None,
        "indicators": {
            "atr20":         round(atr20, 2),
            "dailyDownAtr":  ind.get("dailyDownAtr"),
            "volumeRatio20": ind.get("volumeRatio20"),
            "rsi14":         ind.get("rsi14"),
            "cci20":         ind.get("cci20"),
            "mom20":         ind.get("mom20"),
            "mom60":         ind.get("mom60"),
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
        "supportResistanceZones":  srm_mod.zones(support_levels),
        "message":                 message,
        "rangeFloor":              range_floor,
        "rangeCeiling":            range_ceiling,
        "rangeShiftCount":         0,
        "geometricPattern":          geo["pattern"] if geo else None,
        "geometricPatternDirection": geo["direction"] if geo else None,
        "geometricPatternStage":     geo["stage"] if geo else None,
        "geometricPatternTrigger":   geo["trigger"] if geo else None,
        # This is a price-level risk boundary from the geometric detector, not
        # a generic percentage stop.  Consumers can therefore keep a reversal
        # trade tied to the structure that justified it.
        "geometricPatternInvalidation": geo.get("invalidation") if geo else None,
        "geometricPatternReason":    geo["reason"] if geo else None,
        "geometricPatternConfirmed": geo.get("confirmed", False) if geo else False,
        "candlestickPattern":          cs["pattern"] if cs else None,
        "candlestickPatternDirection": cs["direction"] if cs else None,
        "candlestickPatternFit":       cs["fit"] if cs else None,
        "candlestickPatternConfirmed": cs.get("confirmed", False) if cs else False,
        "candlestickPatternReason":    cs["reason"] if cs else None,
        "candlestickCandidates":       cs.get("candidates", []) if cs else [],
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
        "positionSizeTier":       "NONE",
        "positionSizeMultiplier": 0.0,
        "marketRegime":           None,
        "indicators":             {},
        "baseBreakout":           {},
        "extensionBreakouts":     [],
        "historicalSupportLevels": [],
        "supportResistanceZones":  [],
        "message":                "데이터 부족",
        "rangeFloor":             None,
        "rangeCeiling":           None,
        "rangeShiftCount":        0,
        "geometricPattern":          None,
        "geometricPatternDirection": None,
        "geometricPatternStage":     None,
        "geometricPatternTrigger":   None,
        "geometricPatternInvalidation": None,
        "geometricPatternReason":    None,
        "geometricPatternConfirmed": False,
        "candlestickPattern":          None,
        "candlestickPatternDirection": None,
        "candlestickPatternFit":       None,
        "candlestickPatternConfirmed": False,
        "candlestickPatternReason":    None,
        "candlestickCandidates":       [],
    }
