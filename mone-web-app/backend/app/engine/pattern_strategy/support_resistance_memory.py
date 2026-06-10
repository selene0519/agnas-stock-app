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


def _cluster_levels(raw: list[tuple[float, str]], atr20: float, tol_atr: float = 0.5) -> list[dict]:
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
                "role":           "support",
                "importance":     0.3,
                "touchCount":     1,
                "lastTestedDate": date,
                "atrDistance":    0.0,
            })
    # importance scales with touch count (capped at 1.0)
    for cl in clusters:
        cl["importance"] = round(min(1.0, 0.3 + (cl["touchCount"] - 1) * 0.15), 2)
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

        # ── resistance_candidate → support (buffer must be cleared) ───────
        elif role == "resistance_candidate":
            if close > lvl + buf:
                lv = {**lv, "role": "support"}
            # within neutral buffer → keep as resistance_candidate (no flip)

        # ── support → broken_support ──────────────────────────────────────
        if role == "support" and close < lvl - remove_b:
            lv = {**lv, "role": "broken_support"}

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

    raw_pivots = _find_pivot_lows(rows, window=3)
    if not raw_pivots:
        return []

    levels = _cluster_levels(raw_pivots, atr20, tol_atr=0.4)
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


def is_support_intact(levels: list[dict], close: float, atr20: float, params: dict) -> bool:
    """True if at least one support level is holding near or above current close."""
    sp     = params.get("supportMemory", {})
    buf    = sp.get("supportReturnBufferAtr", 0.2) * atr20
    for lv in levels:
        if lv["role"] == "support" and close >= lv["level"] - buf:
            return True
    return False
