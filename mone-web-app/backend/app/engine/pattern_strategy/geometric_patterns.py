"""
Pattern Strategy Engine v1 — geometric chart pattern detector (Phase 1, 10 core patterns).

Classic price-action patterns (double top/bottom, head & shoulders, triangles,
flags, wedges) detected from swing highs/lows. These are additive to the
indicator-driven patterns in pattern_engine.py — they do not change
marketStructure/action/Action, only annotate the result with a geometric
pattern name + a staged status (never a direct BUY/SELL signal):

    bullish: WATCH -> BREAKOUT_CANDIDATE -> BUY_ZONE -> BLOCKED
    bearish: RISK_WATCH -> AVOID -> BLOCKED

Public API: detect_all(rows, atr20, volume_ratio20) -> dict | None
"""
from __future__ import annotations

from typing import Any

_PIVOT_WINDOW   = 3     # bars on each side required to confirm a swing point
_LOOKBACK       = 70    # bars of history considered for pattern geometry
_MIN_SEPARATION = 5     # min bars between two pivots of the same kind


def _f(val: Any) -> float | None:
    try:
        v = float(val)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def _series(rows: list[dict]) -> tuple[list[float | None], list[float | None], list[float | None]]:
    highs  = [_f(r.get("high")) for r in rows]
    lows   = [_f(r.get("low")) for r in rows]
    closes = [_f(r.get("close")) for r in rows]
    return highs, lows, closes


def _pivot_highs(highs: list[float | None], window: int = _PIVOT_WINDOW) -> list[int]:
    n = len(highs)
    out: list[int] = []
    for i in range(window, n - window):
        seg = highs[i - window:i + window + 1]
        if highs[i] is None or any(v is None for v in seg):
            continue
        if highs[i] == max(seg) and seg.count(highs[i]) == 1:
            out.append(i)
    return out


def _pivot_lows(lows: list[float | None], window: int = _PIVOT_WINDOW) -> list[int]:
    n = len(lows)
    out: list[int] = []
    for i in range(window, n - window):
        seg = lows[i - window:i + window + 1]
        if lows[i] is None or any(v is None for v in seg):
            continue
        if lows[i] == min(seg) and seg.count(lows[i]) == 1:
            out.append(i)
    return out


def _line_fit(idxs: list[int], values: list[float | None]) -> dict | None:
    """Straight line through the first and last pivot in idxs."""
    if len(idxs) < 2:
        return None
    i0, i1 = idxs[0], idxs[-1]
    v0, v1 = values[i0], values[i1]
    if v0 is None or v1 is None or i1 == i0:
        return None
    slope = (v1 - v0) / (i1 - i0)
    return {"slope": slope, "i0": i0, "v0": v0}


def _line_value_at(line: dict, idx: int) -> float:
    return line["v0"] + line["slope"] * (idx - line["i0"])


def _bullish_stage(close: float, trigger: float, atr20: float | None, vol_ratio: float | None, invalidation: float | None) -> str:
    if invalidation is not None and close <= invalidation:
        return "BLOCKED"
    if close > trigger:
        if atr20 and vol_ratio and vol_ratio >= 1.3 and close <= trigger + 1.2 * atr20:
            return "BUY_ZONE"
        return "BREAKOUT_CANDIDATE"
    return "WATCH"


def _bearish_stage(close: float, trigger: float, atr20: float | None, invalidation: float | None) -> str | None:
    if invalidation is not None and close >= invalidation:
        return None  # broken back above the pattern — no longer a bearish risk
    if close < trigger:
        if atr20 and close <= trigger - 1.5 * atr20:
            return "BLOCKED"
        return "AVOID"
    return "RISK_WATCH"


# ── Reversal patterns ───────────────────────────────────────────────────────

def detect_double_bottom(highs, lows, closes, atr20, vol_ratio) -> dict | None:
    low_idx = _pivot_lows(lows)
    if len(low_idx) < 2:
        return None
    i1, i2 = low_idx[-2], low_idx[-1]
    if i2 - i1 < _MIN_SEPARATION:
        return None
    l1, l2 = lows[i1], lows[i2]
    if not l1 or not l2 or abs(l2 - l1) / l1 > 0.035:
        return None
    between = [h for h in highs[i1:i2 + 1] if h is not None]
    if not between:
        return None
    neckline = max(between)
    if neckline <= max(l1, l2) * 1.02:
        return None
    close = closes[-1]
    if close is None:
        return None
    invalidation = min(l1, l2) - 0.3 * (atr20 or 0)
    stage = _bullish_stage(close, neckline, atr20, vol_ratio, invalidation)
    return {
        "pattern": "DOUBLE_BOTTOM", "direction": "BULLISH", "stage": stage,
        "trigger": round(neckline, 2), "invalidation": round(invalidation, 2),
        "reason": f"두 저점({l1:.0f}, {l2:.0f})이 비슷한 수준에서 형성된 더블바텀 후보입니다. 넥라인 {neckline:.0f} 돌파 시 매수 후보로 전환됩니다.",
    }


def detect_double_top(highs, lows, closes, atr20, vol_ratio) -> dict | None:
    hi_idx = _pivot_highs(highs)
    if len(hi_idx) < 2:
        return None
    i1, i2 = hi_idx[-2], hi_idx[-1]
    if i2 - i1 < _MIN_SEPARATION:
        return None
    h1, h2 = highs[i1], highs[i2]
    if not h1 or not h2 or abs(h2 - h1) / h1 > 0.035:
        return None
    between = [l for l in lows[i1:i2 + 1] if l is not None]
    if not between:
        return None
    neckline = min(between)
    if neckline >= min(h1, h2) * 0.98:
        return None
    close = closes[-1]
    if close is None:
        return None
    invalidation = max(h1, h2) + 0.3 * (atr20 or 0)
    stage = _bearish_stage(close, neckline, atr20, invalidation)
    if stage is None:
        return None
    return {
        "pattern": "DOUBLE_TOP", "direction": "BEARISH", "stage": stage,
        "trigger": round(neckline, 2), "invalidation": round(invalidation, 2),
        "reason": f"두 고점({h1:.0f}, {h2:.0f})이 비슷한 수준에서 형성된 더블탑 경계 구간입니다. 넥라인 {neckline:.0f} 이탈 시 리스크가 커집니다.",
    }


def detect_head_and_shoulders(highs, lows, closes, atr20, vol_ratio) -> dict | None:
    hi_idx = _pivot_highs(highs)
    if len(hi_idx) < 3:
        return None
    i1, i2, i3 = hi_idx[-3], hi_idx[-2], hi_idx[-1]
    h1, head, h3 = highs[i1], highs[i2], highs[i3]
    if not h1 or not head or not h3:
        return None
    if not (head > h1 * 1.02 and head > h3 * 1.02):
        return None
    if abs(h1 - h3) / h1 > 0.06:
        return None
    t1 = [l for l in lows[i1:i2 + 1] if l is not None]
    t2 = [l for l in lows[i2:i3 + 1] if l is not None]
    if not t1 or not t2:
        return None
    neckline = min(min(t1), min(t2))
    close = closes[-1]
    if close is None:
        return None
    invalidation = h3 + 0.3 * (atr20 or 0)
    stage = _bearish_stage(close, neckline, atr20, invalidation)
    if stage is None:
        return None
    return {
        "pattern": "HEAD_AND_SHOULDERS", "direction": "BEARISH", "stage": stage,
        "trigger": round(neckline, 2), "invalidation": round(invalidation, 2),
        "reason": f"왼쪽 어깨·머리·오른쪽 어깨 구조가 형성된 헤드앤숄더 경계 구간입니다. 넥라인 {neckline:.0f} 이탈 시 하락 위험이 커집니다.",
    }


def detect_inverse_head_and_shoulders(highs, lows, closes, atr20, vol_ratio) -> dict | None:
    lo_idx = _pivot_lows(lows)
    if len(lo_idx) < 3:
        return None
    i1, i2, i3 = lo_idx[-3], lo_idx[-2], lo_idx[-1]
    l1, head, l3 = lows[i1], lows[i2], lows[i3]
    if not l1 or not head or not l3:
        return None
    if not (head < l1 * 0.98 and head < l3 * 0.98):
        return None
    if abs(l1 - l3) / l1 > 0.06:
        return None
    p1 = [h for h in highs[i1:i2 + 1] if h is not None]
    p2 = [h for h in highs[i2:i3 + 1] if h is not None]
    if not p1 or not p2:
        return None
    neckline = min(max(p1), max(p2))
    close = closes[-1]
    if close is None:
        return None
    invalidation = l3 - 0.3 * (atr20 or 0)
    stage = _bullish_stage(close, neckline, atr20, vol_ratio, invalidation)
    return {
        "pattern": "INVERSE_HEAD_AND_SHOULDERS", "direction": "BULLISH", "stage": stage,
        "trigger": round(neckline, 2), "invalidation": round(invalidation, 2),
        "reason": f"왼쪽 어깨·머리·오른쪽 어깨 구조가 뒤집힌 역헤드앤숄더 후보입니다. 넥라인 {neckline:.0f} 돌파 시 매수 후보로 전환됩니다.",
    }


# ── Continuation patterns: triangles ────────────────────────────────────────

def detect_ascending_triangle(highs, lows, closes, atr20, vol_ratio) -> dict | None:
    n = len(closes)
    hi_idx = _pivot_highs(highs)[-4:]
    lo_idx = _pivot_lows(lows)[-4:]
    res = _line_fit(hi_idx, highs)
    sup = _line_fit(lo_idx, lows)
    if not res or not sup:
        return None
    close = closes[-1]
    if not close or close <= 0:
        return None
    res_pct, sup_pct = res["slope"] / close, sup["slope"] / close
    if abs(res_pct) > 0.0015 or sup_pct < 0.0015:
        return None
    resistance_now = _line_value_at(res, n - 1)
    support_now = _line_value_at(sup, n - 1)
    invalidation = support_now - 0.5 * (atr20 or 0)
    stage = _bullish_stage(close, resistance_now, atr20, vol_ratio, invalidation)
    return {
        "pattern": "ASCENDING_TRIANGLE", "direction": "BULLISH", "stage": stage,
        "trigger": round(resistance_now, 2), "invalidation": round(invalidation, 2),
        "reason": f"저항선은 평평하게 유지되고 저점은 점진적으로 높아지고 있어 상승 삼각형 후보입니다. 저항 {resistance_now:.0f} 돌파를 확인하세요.",
    }


def detect_descending_triangle(highs, lows, closes, atr20, vol_ratio) -> dict | None:
    n = len(closes)
    hi_idx = _pivot_highs(highs)[-4:]
    lo_idx = _pivot_lows(lows)[-4:]
    res = _line_fit(hi_idx, highs)
    sup = _line_fit(lo_idx, lows)
    if not res or not sup:
        return None
    close = closes[-1]
    if not close or close <= 0:
        return None
    res_pct, sup_pct = res["slope"] / close, sup["slope"] / close
    if abs(sup_pct) > 0.0015 or res_pct > -0.0015:
        return None
    resistance_now = _line_value_at(res, n - 1)
    support_now = _line_value_at(sup, n - 1)
    invalidation = resistance_now + 0.5 * (atr20 or 0)
    stage = _bearish_stage(close, support_now, atr20, invalidation)
    if stage is None:
        return None
    return {
        "pattern": "DESCENDING_TRIANGLE", "direction": "BEARISH", "stage": stage,
        "trigger": round(support_now, 2), "invalidation": round(invalidation, 2),
        "reason": f"지지선은 평평하게 유지되고 저항은 점진적으로 낮아지고 있어 하락 삼각형 경계 구간입니다. 지지 {support_now:.0f} 이탈 시 위험이 커집니다.",
    }


# ── Continuation patterns: flags ────────────────────────────────────────────

def detect_bull_flag(highs, lows, closes, atr20, vol_ratio) -> dict | None:
    lo_idx = _pivot_lows(lows)
    hi_idx = _pivot_highs(highs)
    if not lo_idx or not hi_idx:
        return None
    pole_start_i = lo_idx[-1]
    pole_top_candidates = [i for i in hi_idx if i > pole_start_i]
    if not pole_top_candidates:
        return None
    pole_top_i = pole_top_candidates[0]
    pole_start, pole_top = lows[pole_start_i], highs[pole_top_i]
    if not pole_start or not pole_top:
        return None
    if (pole_top - pole_start) / pole_start < 0.08 or pole_top_i - pole_start_i > 15:
        return None
    consolidation = closes[pole_top_i:]
    if len(consolidation) < 3:
        return None
    cons_high = max(h for h in highs[pole_top_i:] if h is not None)
    cons_low  = min(l for l in lows[pole_top_i:] if l is not None)
    if (cons_high - cons_low) / pole_top > 0.07:
        return None  # consolidation too wide to be a tight flag
    close = closes[-1]
    if close is None:
        return None
    invalidation = cons_low - 0.3 * (atr20 or 0)
    stage = _bullish_stage(close, cons_high, atr20, vol_ratio, invalidation)
    return {
        "pattern": "BULL_FLAG", "direction": "BULLISH", "stage": stage,
        "trigger": round(cons_high, 2), "invalidation": round(invalidation, 2),
        "reason": f"강한 상승(깃대) 이후 좁은 구간에서 조정 중인 불 플래그 후보입니다. 깃대 상단 {cons_high:.0f} 돌파 시 매수 후보로 전환됩니다.",
    }


def detect_bear_flag(highs, lows, closes, atr20, vol_ratio) -> dict | None:
    hi_idx = _pivot_highs(highs)
    lo_idx = _pivot_lows(lows)
    if not hi_idx or not lo_idx:
        return None
    pole_start_i = hi_idx[-1]
    pole_bottom_candidates = [i for i in lo_idx if i > pole_start_i]
    if not pole_bottom_candidates:
        return None
    pole_bottom_i = pole_bottom_candidates[0]
    pole_start, pole_bottom = highs[pole_start_i], lows[pole_bottom_i]
    if not pole_start or not pole_bottom:
        return None
    if (pole_start - pole_bottom) / pole_start < 0.08 or pole_bottom_i - pole_start_i > 15:
        return None
    cons_high = max(h for h in highs[pole_bottom_i:] if h is not None)
    cons_low  = min(l for l in lows[pole_bottom_i:] if l is not None)
    if pole_bottom <= 0 or (cons_high - cons_low) / pole_bottom > 0.07:
        return None
    close = closes[-1]
    if close is None:
        return None
    invalidation = cons_high + 0.3 * (atr20 or 0)
    stage = _bearish_stage(close, cons_low, atr20, invalidation)
    if stage is None:
        return None
    return {
        "pattern": "BEAR_FLAG", "direction": "BEARISH", "stage": stage,
        "trigger": round(cons_low, 2), "invalidation": round(invalidation, 2),
        "reason": f"급락(깃대) 이후 좁은 구간에서 약한 반등 중인 베어 플래그 경계 구간입니다. 깃대 하단 {cons_low:.0f} 이탈 시 하락이 재개될 수 있습니다.",
    }


# ── Continuation/reversal patterns: wedges ──────────────────────────────────

def detect_falling_wedge_breakout(highs, lows, closes, atr20, vol_ratio) -> dict | None:
    n = len(closes)
    hi_idx = _pivot_highs(highs)[-4:]
    lo_idx = _pivot_lows(lows)[-4:]
    res = _line_fit(hi_idx, highs)
    sup = _line_fit(lo_idx, lows)
    if not res or not sup:
        return None
    close = closes[-1]
    if not close or close <= 0:
        return None
    res_pct, sup_pct = res["slope"] / close, sup["slope"] / close
    if not (res_pct < 0 and sup_pct < 0 and res_pct > sup_pct):
        return None  # both falling, but must be converging (resistance falls slower)
    resistance_now = _line_value_at(res, n - 1)
    support_now = _line_value_at(sup, n - 1)
    start_width = highs[hi_idx[0]] - lows[lo_idx[0]] if highs[hi_idx[0]] and lows[lo_idx[0]] else None
    end_width = resistance_now - support_now
    if start_width is None or start_width <= 0 or end_width > start_width * 0.8:
        return None  # not narrowing enough
    invalidation = support_now - 0.3 * (atr20 or 0)
    stage = _bullish_stage(close, resistance_now, atr20, vol_ratio, invalidation)
    return {
        "pattern": "FALLING_WEDGE_BREAKOUT", "direction": "BULLISH", "stage": stage,
        "trigger": round(resistance_now, 2), "invalidation": round(invalidation, 2),
        "reason": f"하락하는 두 추세선이 좁아지는 하락 쐐기 후보입니다. 상단 추세선 {resistance_now:.0f} 돌파 시 매수 후보로 전환됩니다.",
    }


def detect_rising_wedge_breakdown(highs, lows, closes, atr20, vol_ratio) -> dict | None:
    n = len(closes)
    hi_idx = _pivot_highs(highs)[-4:]
    lo_idx = _pivot_lows(lows)[-4:]
    res = _line_fit(hi_idx, highs)
    sup = _line_fit(lo_idx, lows)
    if not res or not sup:
        return None
    close = closes[-1]
    if not close or close <= 0:
        return None
    res_pct, sup_pct = res["slope"] / close, sup["slope"] / close
    if not (res_pct > 0 and sup_pct > 0 and sup_pct > res_pct):
        return None  # both rising, but must be converging (support rises faster)
    resistance_now = _line_value_at(res, n - 1)
    support_now = _line_value_at(sup, n - 1)
    start_width = highs[hi_idx[0]] - lows[lo_idx[0]] if highs[hi_idx[0]] and lows[lo_idx[0]] else None
    end_width = resistance_now - support_now
    if start_width is None or start_width <= 0 or end_width > start_width * 0.8:
        return None
    invalidation = resistance_now + 0.3 * (atr20 or 0)
    stage = _bearish_stage(close, support_now, atr20, invalidation)
    if stage is None:
        return None
    return {
        "pattern": "RISING_WEDGE_BREAKDOWN", "direction": "BEARISH", "stage": stage,
        "trigger": round(support_now, 2), "invalidation": round(invalidation, 2),
        "reason": f"상승하는 두 추세선이 좁아지는 상승 쐐기 경계 구간입니다. 하단 추세선 {support_now:.0f} 이탈 시 하락 위험이 커집니다.",
    }


_DETECTORS = [
    detect_double_bottom,
    detect_double_top,
    detect_head_and_shoulders,
    detect_inverse_head_and_shoulders,
    detect_ascending_triangle,
    detect_descending_triangle,
    detect_bull_flag,
    detect_bear_flag,
    detect_falling_wedge_breakout,
    detect_rising_wedge_breakdown,
]

_ACTIONABLE_STAGES = {"BUY_ZONE", "AVOID", "BLOCKED", "BREAKOUT_CANDIDATE"}


def detect_all(rows: list[dict], atr20: float | None, volume_ratio20: float | None) -> dict[str, Any] | None:
    """
    Run all Phase-1 geometric pattern detectors and return the single most
    relevant match (actionable stage > watch stage, then by recency of the
    underlying pivots). Returns None if nothing matched.

    Result keys: pattern, direction, stage, trigger, invalidation, reason, candidates
    """
    if not rows or len(rows) < 20:
        return None
    work = rows[-_LOOKBACK:] if len(rows) > _LOOKBACK else rows
    if len(work) < 2 * _PIVOT_WINDOW + _MIN_SEPARATION + 2:
        return None
    highs, lows, closes = _series(work)

    matches: list[dict] = []
    for detector in _DETECTORS:
        try:
            result = detector(highs, lows, closes, atr20, volume_ratio20)
        except Exception:
            result = None
        if result:
            matches.append(result)

    if not matches:
        return None

    matches.sort(key=lambda m: 0 if m["stage"] in _ACTIONABLE_STAGES else 1)
    best = matches[0]
    best["candidates"] = [m["pattern"] for m in matches]
    return best
