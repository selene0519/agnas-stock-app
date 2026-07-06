"""
Context-Aware Candlestick Pattern Detector v1.

Unlike geometric_patterns.py which reads multi-day swing structure, this
module detects 1–3 candle Japanese candlestick signals and gates them
through the market context already established by pattern_engine.py.

Design principle — context first:
  1. Determine which DIRECTION is meaningful given the current market flow
     (structure + phase + primary pattern + risk).
  2. Run only the compatible detectors for that direction.
  3. Score each hit by how well it fits the context and location.
  4. Return the single strongest, contextually-relevant match.

Public API:
    detect_contextual(rows, atr20, *, market_structure, trend_phase,
                      primary_pattern, risk_status) → dict | None

Return schema:
    {
        "pattern":    str,           # e.g. "MORNING_STAR"
        "direction":  "BULLISH" | "BEARISH",
        "fit":        float,         # 0.0–1.0 context-alignment score
        "reason":     str,           # human-readable Korean explanation
        "candidates": list[str],     # all patterns that fired this bar
    }
"""
from __future__ import annotations

from typing import Any


# ── Candle anatomy helpers ────────────────────────────────────────────────────

def _body(o: float, c: float) -> float:
    return abs(c - o)


def _range(h: float, l: float) -> float:
    return max(h - l, 1e-9)


def _lower_wick(o: float, h: float, l: float, c: float) -> float:
    return min(o, c) - l


def _upper_wick(o: float, h: float, l: float, c: float) -> float:
    return h - max(o, c)


def _body_ratio(o: float, h: float, l: float, c: float) -> float:
    return _body(o, c) / _range(h, l)


def _mid(o: float, c: float) -> float:
    return (o + c) / 2.0


def _is_bull(o: float, c: float) -> bool:
    return c >= o


def _is_bear(o: float, c: float) -> bool:
    return c < o


def _unpack3(rows: list[dict]) -> tuple | None:
    """Unpack last 3 candles → (o1,h1,l1,c1, o2,h2,l2,c2, o3,h3,l3,c3) or None."""
    if len(rows) < 3:
        return None
    try:
        r1, r2, r3 = rows[-3], rows[-2], rows[-1]
        return (
            float(r1["open"]), float(r1["high"]), float(r1["low"]), float(r1["close"]),
            float(r2["open"]), float(r2["high"]), float(r2["low"]), float(r2["close"]),
            float(r3["open"]), float(r3["high"]), float(r3["low"]), float(r3["close"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _unpack2(rows: list[dict]) -> tuple | None:
    """Unpack last 2 candles → (o1,h1,l1,c1, o2,h2,l2,c2) or None."""
    if len(rows) < 2:
        return None
    try:
        r1, r2 = rows[-2], rows[-1]
        return (
            float(r1["open"]), float(r1["high"]), float(r1["low"]), float(r1["close"]),
            float(r2["open"]), float(r2["high"]), float(r2["low"]), float(r2["close"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


# ── Bullish pattern detectors ─────────────────────────────────────────────────

def _detect_morning_star(rows: list[dict], atr20: float) -> dict | None:
    """
    Morning Star (샛별): 3-candle bullish reversal.
    C1: large bearish (body > 0.5 × atr20)
    C2: small body / doji (body < 0.4 × C1 body) — indecision
    C3: large bullish closing above midpoint of C1
    """
    d = _unpack3(rows)
    if not d:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2, o3, h3, l3, c3 = d

    if not _is_bear(o1, c1):
        return None
    b1 = _body(o1, c1)
    if b1 < 0.5 * atr20:
        return None
    if _body(o2, c2) > 0.4 * b1:
        return None
    if not _is_bull(o3, c3):
        return None
    if c3 < _mid(o1, c1):
        return None

    return {
        "pattern": "MORNING_STAR",
        "direction": "BULLISH",
        "reason": (
            "큰 음봉 → 불확실 소형봉 → 큰 양봉의 샛별 패턴. "
            "하락 추세 바닥에서 매수세 전환을 알리는 강한 반전 신호입니다."
        ),
    }


def _detect_bullish_engulfing(rows: list[dict], atr20: float) -> dict | None:
    """
    Bullish Engulfing (음을양병): C1 bearish, C2 bullish fully engulfs C1.
    Marubozu variant (포병): if C2 body ratio > 0.65 (near-zero wicks).
    """
    d = _unpack2(rows)
    if not d:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2 = d

    if not (_is_bear(o1, c1) and _is_bull(o2, c2)):
        return None
    if not (c2 > o1 and o2 < c1):
        return None

    if _body_ratio(o2, h2, l2, c2) > 0.65:
        return {
            "pattern": "BULLISH_ENGULFING_MARUBOZU",
            "direction": "BULLISH",
            "reason": (
                "음봉을 완전히 삼킨 강한 포병형 양봉(음을양병+포병). "
                "매수세가 매도세를 압도한 강력한 전환 신호입니다."
            ),
        }
    return {
        "pattern": "BULLISH_ENGULFING",
        "direction": "BULLISH",
        "reason": (
            "음봉을 감싸는 장악형 양봉(음을양병). "
            "전일 매도세를 뒤집는 하락 전환 신호입니다."
        ),
    }


def _detect_hammer_confirm(rows: list[dict], atr20: float) -> dict | None:
    """
    Hammer + confirmation candle (핀버+확인봉).
    C1: lower wick > 2× body, upper wick < body, body > 0.08 × atr20
    C2: closes above C1 close (confirms rejection of lows)
    """
    d = _unpack2(rows)
    if not d:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2 = d

    bd1 = _body(o1, c1)
    if bd1 < 0.08 * atr20:
        return None
    if _lower_wick(o1, h1, l1, c1) < 2.0 * bd1:
        return None
    if _upper_wick(o1, h1, l1, c1) > bd1:
        return None
    if c2 <= c1:
        return None

    return {
        "pattern": "HAMMER_CONFIRM",
        "direction": "BULLISH",
        "reason": (
            "하단 긴 꼬리의 핀버(망치) 이후 확인 양봉 출현. "
            "하단 지지가 강하게 유지되고 매수세가 재진입했습니다."
        ),
    }


def _detect_spike_reversal(rows: list[dict], atr20: float) -> dict | None:
    """
    Spike Low + recovery (스파이크로+핀버): sudden intraday dive that recovers.
    C1: lower wick spike from body base > 1.5 × atr20
    C2: closes at or above C1 open (full recovery)
    """
    d = _unpack2(rows)
    if not d:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2 = d

    spike = min(o1, c1) - l1
    if spike < 1.5 * atr20:
        return None
    if c2 < o1:
        return None

    return {
        "pattern": "SPIKE_REVERSAL",
        "direction": "BULLISH",
        "reason": (
            f"하방 스파이크(급락 {spike:.0f}) 후 시가 수준으로 빠르게 회복. "
            "하단 매수세가 강력하여 추가 하락보다 반등 가능성이 높습니다."
        ),
    }


def _detect_three_inside_up(rows: list[dict], atr20: float) -> dict | None:
    """
    Three Inside Up (삼강법 유사): large bear → bullish harami → confirming bull.
    C1: large bearish (body > 0.5 × atr20)
    C2: bullish, body inside C1 body (harami)
    C3: bullish, closes above C1 open
    """
    d = _unpack3(rows)
    if not d:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2, o3, h3, l3, c3 = d

    if not _is_bear(o1, c1):
        return None
    if _body(o1, c1) < 0.5 * atr20:
        return None
    if not _is_bull(o2, c2):
        return None
    if not (o2 > c1 and c2 < o1):  # inside C1 body
        return None
    if not (_is_bull(o3, c3) and c3 > o1):
        return None

    return {
        "pattern": "THREE_INSIDE_UP",
        "direction": "BULLISH",
        "reason": (
            "큰 음봉 → 내부 양봉(하라미) → 강한 확인 양봉의 삼강법 패턴. "
            "매수세 전환이 단계적으로 확인된 신뢰도 높은 반전 신호입니다."
        ),
    }


# ── Bearish pattern detectors ─────────────────────────────────────────────────

def _detect_evening_star(rows: list[dict], atr20: float) -> dict | None:
    """
    Evening Star (저녁별): 3-candle bearish reversal.
    C1: large bullish (body > 0.5 × atr20)
    C2: small body (body < 0.4 × C1 body) — gap or near gap
    C3: large bearish closing below midpoint of C1
    """
    d = _unpack3(rows)
    if not d:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2, o3, h3, l3, c3 = d

    if not _is_bull(o1, c1):
        return None
    b1 = _body(o1, c1)
    if b1 < 0.5 * atr20:
        return None
    if _body(o2, c2) > 0.4 * b1:
        return None
    if not _is_bear(o3, c3):
        return None
    if c3 > _mid(o1, c1):
        return None

    return {
        "pattern": "EVENING_STAR",
        "direction": "BEARISH",
        "reason": (
            "큰 양봉 → 불확실 소형봉 → 큰 음봉의 저녁별 패턴. "
            "상승 추세 고점에서 매도세 전환을 알리는 강한 반전 경고입니다."
        ),
    }


def _detect_three_black_crows(rows: list[dict], atr20: float) -> dict | None:
    """
    Three Black Crows (흑삼병): 3 consecutive strong bearish candles,
    each opening inside prior body and closing progressively lower.
    """
    d = _unpack3(rows)
    if not d:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2, o3, h3, l3, c3 = d

    for o, c in [(o1, c1), (o2, c2), (o3, c3)]:
        if not _is_bear(o, c) or _body(o, c) < 0.4 * atr20:
            return None
    if not (c2 < c1 and c3 < c2):
        return None
    if not (c1 < o2 <= o1 and c2 < o3 <= o2):
        return None

    return {
        "pattern": "THREE_BLACK_CROWS",
        "direction": "BEARISH",
        "reason": (
            "3개 연속 강한 음봉(흑삼병). 매도세가 지속적으로 강화되고 있어 "
            "하락 추세 가속 경고입니다."
        ),
    }


def _detect_bearish_engulfing(rows: list[dict], atr20: float) -> dict | None:
    """
    Bearish Engulfing (두브러리): C1 bullish, C2 bearish fully engulfs C1.
    Marubozu variant (흑포병): body ratio > 0.65.
    """
    d = _unpack2(rows)
    if not d:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2 = d

    if not (_is_bull(o1, c1) and _is_bear(o2, c2)):
        return None
    if not (c2 < o1 and o2 > c1):
        return None

    if _body_ratio(o2, h2, l2, c2) > 0.65:
        return {
            "pattern": "BEARISH_ENGULFING_MARUBOZU",
            "direction": "BEARISH",
            "reason": (
                "양봉을 완전히 삼킨 강한 흑포병형 음봉(두브러리+흑포병). "
                "매도세가 매수세를 압도한 강력한 전환 경고입니다."
            ),
        }
    return {
        "pattern": "BEARISH_ENGULFING",
        "direction": "BEARISH",
        "reason": (
            "양봉을 감싸는 장악형 음봉(두브러리). "
            "전일 매수세를 뒤집는 상승 전환 경고입니다."
        ),
    }


def _detect_shooting_star_confirm(rows: list[dict], atr20: float) -> dict | None:
    """
    Shooting Star + confirmation (유성형+확인봉).
    C1: upper wick > 2× body, lower wick < body, body > 0.08 × atr20
    C2: closes below C1 close (confirms rejection of highs)
    """
    d = _unpack2(rows)
    if not d:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2 = d

    bd1 = _body(o1, c1)
    if bd1 < 0.08 * atr20:
        return None
    if _upper_wick(o1, h1, l1, c1) < 2.0 * bd1:
        return None
    if _lower_wick(o1, h1, l1, c1) > bd1:
        return None
    if c2 >= c1:
        return None

    return {
        "pattern": "SHOOTING_STAR_CONFIRM",
        "direction": "BEARISH",
        "reason": (
            "상단 긴 꼬리의 유성형 이후 확인 음봉 출현. "
            "상단 저항 매도세가 강하게 재확인된 하락 전환 신호입니다."
        ),
    }


def _detect_dark_cloud_cover(rows: list[dict], atr20: float) -> dict | None:
    """
    Dark Cloud Cover (그늘그개):
    C1: large bullish (body > 0.5 × atr20)
    C2: opens above C1 high, bearish, closes below midpoint of C1
    """
    d = _unpack2(rows)
    if not d:
        return None
    o1, h1, l1, c1, o2, h2, l2, c2 = d

    if not _is_bull(o1, c1):
        return None
    if _body(o1, c1) < 0.5 * atr20:
        return None
    if o2 <= h1:
        return None
    if not _is_bear(o2, c2):
        return None
    if c2 >= _mid(o1, c1):
        return None

    return {
        "pattern": "DARK_CLOUD_COVER",
        "direction": "BEARISH",
        "reason": (
            "갭 상승 출발 후 전일 양봉 중간 이하로 밀린 먹구름형(그늘그개). "
            "상단 매도 압력이 강해 상승 추세가 꺾일 위험이 있습니다."
        ),
    }


# ── Detector registry ─────────────────────────────────────────────────────────

_BULLISH_DETECTORS = [
    _detect_morning_star,
    _detect_bullish_engulfing,
    _detect_hammer_confirm,
    _detect_spike_reversal,
    _detect_three_inside_up,
]

_BEARISH_DETECTORS = [
    _detect_evening_star,
    _detect_three_black_crows,
    _detect_bearish_engulfing,
    _detect_shooting_star_confirm,
    _detect_dark_cloud_cover,
]


# ── Context-to-direction mapping ──────────────────────────────────────────────

# (market_structure, trend_phase) → preferred direction
_STRUCTURE_PHASE_DIR: dict[tuple[str, str], str] = {
    ("TREND_UP",           "PULLBACK"):            "BULLISH",  # 눌림목 복귀 확인
    ("TREND_UP",           "RETEST"):              "BULLISH",  # 돌파 후 재테스트 확인
    ("TREND_UP",           "NORMAL"):              "BOTH",
    ("TREND_UP",           "EXTENDED"):            "BEARISH",  # 과열 → 반전 경고
    ("TREND_DOWN",         "STRUCTURE_BREAKDOWN"): "BEARISH",  # 붕괴 지속 확인
    ("TREND_DOWN",         "STALLED"):             "BOTH",     # 잠시 멈춤 → 방향 불명
    ("BREAKOUT_CANDIDATE", "NORMAL"):              "BULLISH",  # 돌파 직전 확인
    ("BREAKOUT_CANDIDATE", "RETEST"):              "BULLISH",
    ("RANGE",              "STALLED"):             "BOTH",
    ("RANGE_DRIFT",        "STALLED"):             "BOTH",
    ("DISTRIBUTION_WATCH", "EXTENDED"):            "BEARISH",
    ("DISTRIBUTION_WATCH", "STALLED"):             "BEARISH",
    ("DISTRIBUTION_WATCH", "NORMAL"):              "BEARISH",
}

# primary_pattern → direction override (takes precedence over structure/phase)
_PRIMARY_PATTERN_DIR: dict[str, str] = {
    "trend_up_pullback":         "BULLISH",
    "horizontal_support_rebound":"BULLISH",
    "range_bottom_rebound":      "BULLISH",
    "resistance_breakout":       "BULLISH",
    "breakout_retest":           "BULLISH",
    "volume_turnaround":         "BULLISH",
    "relative_strength":         "BULLISH",
    "downtrend_bounce_trap":     "BEARISH",
    "distribution_zone":         "BEARISH",
    "overheated_chase_risk":     "BEARISH",
    "false_breakout_risk":       "BEARISH",
    "structure_breakdown_risk":  "BEARISH",
    "resistance_chase_risk":     "BEARISH",
    "overheated_pullback_risk":  "BEARISH",
    "zombie_breakout":           "BEARISH",
}

# risk_status → direction override (strongest override — checked first)
_RISK_DIR: dict[str, str] = {
    "STRUCTURE_BREAKDOWN":   "BEARISH",
    "MOMENTUM_COLLAPSE":     "BEARISH",
    "FAKE_BREAKOUT":         "BEARISH",
    "OVERHEATED_EXTENSION":  "BEARISH",
}


def _expected_direction(
    structure: str, phase: str, primary: str, risk: str
) -> str:
    """
    Determine which signal direction is contextually meaningful right now.
    Priority: risk > primary_pattern > (structure, phase).
    """
    if risk in _RISK_DIR:
        return _RISK_DIR[risk]
    if primary in _PRIMARY_PATTERN_DIR:
        return _PRIMARY_PATTERN_DIR[primary]
    return _STRUCTURE_PHASE_DIR.get((structure, phase), "BOTH")


def _fit_score(direction: str, expected: str) -> float:
    """0.0–1.0: how well the pattern direction fits the market context."""
    if expected == "BOTH":
        return 0.65   # neutral context: moderate fit
    return 1.0 if direction == expected else 0.15   # counter-context: very low


# ── Public API ────────────────────────────────────────────────────────────────

def detect_contextual(
    rows: list[dict],
    atr20: float,
    *,
    market_structure: str = "",
    trend_phase: str = "",
    primary_pattern: str = "",
    risk_status: str = "",
) -> dict[str, Any] | None:
    """
    Detect the single most contextually relevant candlestick pattern.

    Algorithm:
      1. Infer the expected signal direction from the full market context.
      2. Run aligned detectors first, opposite-direction detectors after
         (to catch rare counter-context reversal signals at extremes).
      3. Score each hit by context fit.
      4. Return the best hit whose fit ≥ 0.3 (suppress counter-context noise).

    Returns None when no pattern fires or all candidates score below threshold.
    """
    if not rows or len(rows) < 3 or not atr20 or atr20 <= 0:
        return None

    expected = _expected_direction(market_structure, trend_phase, primary_pattern, risk_status)

    # Aligned detectors run first for priority ordering
    if expected == "BULLISH":
        ordered = _BULLISH_DETECTORS + _BEARISH_DETECTORS
    elif expected == "BEARISH":
        ordered = _BEARISH_DETECTORS + _BULLISH_DETECTORS
    else:
        ordered = _BULLISH_DETECTORS + _BEARISH_DETECTORS

    hits: list[dict] = []
    for detector in ordered:
        try:
            result = detector(rows, atr20)
        except Exception:
            result = None
        if result:
            fit = _fit_score(result["direction"], expected)
            hits.append({**result, "fit": round(fit, 2)})

    if not hits:
        return None

    # Sort: best fit first; ties broken by alignment with expected direction
    hits.sort(key=lambda h: (-h["fit"], 0 if h["direction"] == expected else 1))
    best = hits[0]

    if best["fit"] < 0.3:
        return None

    best["candidates"] = [h["pattern"] for h in hits]
    return best
