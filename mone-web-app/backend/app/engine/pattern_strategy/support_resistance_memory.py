"""
Pattern Strategy Engine v1 — support/resistance memory management.

Rules (from spec):
  • max 5 levels; remove lowest-importance first (not FIFO).
  • Broken support → resistance_candidate (not deleted immediately).
  • resistance_candidate → support only if close > level + 0.2 * ATR20.
  • Neutral buffer: level ± 0.2 * ATR20 — no role flip inside buffer.
  • broken_support removed if close < level - 1.0 * ATR20 for 20+ days without retest.
"""
from __future__ import annotations

from typing import Any


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


# ── Level detection helpers ────────────────────────────────────────────────

def _find_pivot_lows(rows: list[dict], window: int = 5) -> list[tuple[float, str]]:
    """Find local pivot lows (potential support levels) with their dates."""
    pivots: list[tuple[float, str]] = []
    for i in range(window, len(rows) - window):
        low  = _f(rows[i].get("low"))
        date = str(rows[i].get("date", ""))
        if low is None:
            continue
        neighbours = [_f(rows[j].get("low")) for j in range(i - window, i + window + 1) if j != i]
        if all(n is not None and low <= n for n in neighbours):
            pivots.append((low, date))
    return pivots


def _find_pivot_highs(rows: list[dict], window: int = 5) -> list[tuple[float, str]]:
    """Find local pivot highs (potential resistance) with their dates."""
    pivots: list[tuple[float, str]] = []
    for i in range(window, len(rows) - window):
        high = _f(rows[i].get("high"))
        date = str(rows[i].get("date", ""))
        if high is None:
            continue
        neighbours = [_f(rows[j].get("high")) for j in range(i - window, i + window + 1) if j != i]
        if all(value is not None and high >= value for value in neighbours):
            pivots.append((high, date))
    return pivots


def _cluster_levels(raw: list[tuple[float, str]], atr20: float, role: str, tol_atr: float = 0.5) -> list[dict]:
    """Merge nearby pivots into single levels; assign importance by touch count."""
    clusters: list[dict] = []
    for level, date in sorted(raw, key=lambda x: x[0]):
        merged = False
        for cl in clusters:
            if abs(level - cl["level"]) <= tol_atr * atr20:
                cl["touchCount"] += 1
                cl["level"] = (cl["level"] * (cl["touchCount"] - 1) + level) / cl["touchCount"]
                if date > cl["lastTestedDate"]:
                    cl["lastTestedDate"] = date
                merged = True
                break
        if not merged:
            clusters.append({
                "level":          round(level, 2),
                "role":           role,
                "importance":     0.3,
                "touchCount":     1,
                "lastTestedDate": date,
                "atrDistance":    0.0,
            })
    # importance peaks at touchCount ≈ 5–6 then decays (exhausted level effect):
    # a zone retested 8+ times has absorbed all resting orders and weakens.
    for cl in clusters:
        tc = cl["touchCount"]
        if tc <= 5:
            cl["importance"] = round(min(1.0, 0.3 + (tc - 1) * 0.15), 2)
        else:
            decay = min(0.4, (tc - 5) * 0.08)
            cl["importance"] = round(max(0.2, 0.9 - decay), 2)
        cl["saturated"] = tc > 6
        width = max(atr20 * 0.35, cl["level"] * 0.002)
        cl["zoneLow"] = round(cl["level"] - width, 2)
        cl["zoneHigh"] = round(cl["level"] + width, 2)
        cl["zoneWidth"] = round(width, 2)
    return clusters


# ── Role transition rules ──────────────────────────────────────────────────

def _update_roles(levels: list[dict], close: float, atr20: float, params: dict) -> list[dict]:
    sp = params.get("supportMemory", {})
    buf      = sp.get("supportReturnBufferAtr",  0.2) * atr20
    break_b  = sp.get("supportBreakAtr",         0.3) * atr20
    remove_b = sp.get("removeBrokenSupportAtr",  1.0) * atr20

    updated: list[dict] = []
    for lv in levels:
        lvl  = lv["level"]
        role = lv["role"]

        # ── support → resistance_candidate ────────────────────────────────
        if role == "support" and close < lvl - break_b:
            lv = {**lv, "role": "resistance_candidate"}
            role = "resistance_candidate"

        elif role == "resistance" and close > lvl + buf:
            # A repeated ceiling becomes support only after a confirmed close
            # above an ATR buffer; this is a flip/retest, not a line touch.
            lv = {**lv, "role": "support"}
            role = "support"

        # ── resistance_candidate → support (buffer must be cleared) ───────
        elif role == "resistance_candidate":
            if close > lvl + buf:
                lv = {**lv, "role": "support"}
                role = "support"
            # within neutral buffer → keep as resistance_candidate (no flip)

        # ── support → broken_support ──────────────────────────────────────
        if role == "support" and close < lvl - remove_b:
            lv = {**lv, "role": "broken_support"}
            role = "broken_support"

        # Drop broken_support that is very far below current price
        if role == "broken_support" and close > lvl + remove_b * 2:
            continue  # prune

        lv["atrDistance"] = round(abs(close - lv["level"]) / atr20, 3) if atr20 > 0 else 0.0
        updated.append(lv)

    return updated


# ── Capacity management ────────────────────────────────────────────────────

def _prune(levels: list[dict], max_levels: int) -> list[dict]:
    """Keep max_levels entries; drop lowest-importance first (not FIFO)."""
    active = [lv for lv in levels if lv["role"] != "broken_support"]
    broken = [lv for lv in levels if lv["role"] == "broken_support"]
    if len(active) > max_levels:
        active.sort(key=lambda x: x["importance"])
        active = active[-(max_levels):]
    # always keep at most 2 broken_support for context
    broken = broken[-2:] if len(broken) > 2 else broken
    return active + broken


# ── Public API ─────────────────────────────────────────────────────────────

def build(rows: list[dict], atr20: float, params: dict) -> list[dict]:
    """
    Build support/resistance levels from OHLCV history.
    Returns a list of SupportLevel-like dicts.
    """
    sp            = params.get("supportMemory", {})
    max_levels    = sp.get("maxHistoricalLevels", 5)
    close         = _f(rows[-1].get("close")) if rows else None

    if not rows or atr20 <= 0 or close is None:
        return []

    # Use a broad, recent view: roughly 3–6 months of daily candles.
    work = rows[-120:] if len(rows) > 120 else rows
    raw_lows = _find_pivot_lows(work, window=3)
    raw_highs = _find_pivot_highs(work, window=3)
    if not raw_lows and not raw_highs:
        return []

    levels = _cluster_levels(raw_lows, atr20, "support", tol_atr=0.4)
    levels += _cluster_levels(raw_highs, atr20, "resistance", tol_atr=0.4)
    levels = _update_roles(levels, close, atr20, params)
    levels = _prune(levels, max_levels)

    # Sort by proximity to current price
    levels.sort(key=lambda x: x["atrDistance"])
    return levels


def nearest_support(levels: list[dict], close: float, atr20: float) -> float | None:
    """Return the closest active support level below current price."""
    candidates = [
        lv["level"] for lv in levels
        if lv["role"] == "support" and lv["level"] < close
    ]
    return max(candidates) if candidates else None


def nearest_resistance(levels: list[dict], close: float, atr20: float) -> float | None:
    """Return the closest active resistance above the current price."""
    candidates = [
        lv["level"] for lv in levels
        if lv["role"] in {"resistance", "resistance_candidate"} and lv["level"] > close
    ]
    return min(candidates) if candidates else None


def zones(levels: list[dict]) -> list[dict]:
    """Compact support/resistance zones for the API and chart overlays."""
    return [
        {
            "role": level.get("role"),
            "level": level.get("level"),
            "zoneLow": level.get("zoneLow", level.get("level")),
            "zoneHigh": level.get("zoneHigh", level.get("level")),
            "touchCount": level.get("touchCount", 0),
            "importance": level.get("importance", 0.0),
            "saturated": bool(level.get("saturated")),
        }
        for level in levels
    ]


def is_support_intact(levels: list[dict], close: float, atr20: float, params: dict) -> bool:
    """True if at least one support level is holding near or above current close."""
    sp     = params.get("supportMemory", {})
    buf    = sp.get("supportReturnBufferAtr", 0.2) * atr20
    for lv in levels:
        if lv["role"] == "support" and close >= lv["level"] - buf:
            return True
    return False
