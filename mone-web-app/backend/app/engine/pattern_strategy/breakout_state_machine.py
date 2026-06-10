"""
Pattern Strategy Engine v1 — breakout state machine.

Rules:
  • baseBreakout is set on the FIRST valid breakout and never overwritten.
  • extensionBreakouts accumulate subsequent breakout levels above baseBreakout.
  • 2+ extensionBreakouts → OVERHEATED_EXTENSION risk signal.
  • A very strong breakout is NOT failed — it becomes TREND_UP + EXTENDED.
  • Failed breakout: close drops back below baseBreakout with volume.
"""
from __future__ import annotations

from typing import Any


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _date(row: dict) -> str:
    return str(row.get("date", ""))


def run(
    rows: list[dict],
    ind: dict[str, Any],
    params: dict[str, Any],
    existing_base: dict | None = None,
    existing_extensions: list[dict] | None = None,
) -> tuple[dict, list[dict], bool]:
    """
    Returns (baseBreakout, extensionBreakouts, is_failed_breakout).

    existing_base / existing_extensions allow incremental updates when the
    caller caches state across calls (not required — pass None for fresh run).
    """
    bo_params  = params.get("breakout", {})
    buf_atr    = bo_params.get("breakoutBufferAtr", 0.3)
    min_vr     = bo_params.get("minVolumeRatio", 1.2)
    overheat_n = bo_params.get("extensionOverheatCount", 2)
    confirm_d  = bo_params.get("confirmMaxDays", 10)

    atr20      = ind.get("atr20")
    range_high = ind.get("rangeHigh")

    base: dict       = existing_base or {}
    extensions: list = list(existing_extensions or [])

    if not rows or not atr20 or not range_high:
        return base, extensions, False

    # Sliding window scan for breakout events in the last confirmMaxDays * 3 rows
    scan_rows = rows[-(confirm_d * 3):]

    def _vol_ratio(row: dict, look: list[dict]) -> float:
        idx = look.index(row) if row in look else -1
        prev_vols = [_f(r.get("volume")) for r in look[max(0, idx - 20):idx] if _f(r.get("volume"))]
        if not prev_vols:
            return 0.0
        avg = sum(prev_vols) / len(prev_vols)
        today_v = _f(row.get("volume")) or 0.0
        return today_v / avg if avg > 0 else 0.0

    breakout_threshold = range_high + buf_atr * atr20

    for i, row in enumerate(scan_rows):
        close = _f(row.get("close"))
        if close is None:
            continue
        vr = _vol_ratio(row, scan_rows)

        # ── Valid breakout candidate ────────────────────────────────────────
        if close > breakout_threshold and vr >= min_vr:
            level = round(close, 2)
            date  = _date(row)

            if not base:
                # First valid breakout → lock as baseBreakout
                base = {
                    "level":       level,
                    "date":        date,
                    "volumeRatio": round(vr, 3),
                    "confirmed":   False,
                    "rangeHigh":   round(range_high, 2),
                }
            else:
                base_level = base.get("level", 0)
                # Confirm base if price is holding above it within confirmMaxDays
                if not base.get("confirmed"):
                    base["confirmed"] = True

                # New higher breakout level → extensionBreakout
                if level > base_level * 1.005:  # 0.5% above base to avoid noise
                    # Only add if not already in extensions
                    existing_levels = {e.get("level", 0) for e in extensions}
                    if not any(abs(level - el) / el < 0.005 for el in existing_levels):
                        extensions.append({
                            "level":       level,
                            "date":        date,
                            "volumeRatio": round(vr, 3),
                            "confirmed":   False,
                        })

    # Keep only last overheat_n * 3 extensions for memory efficiency
    if len(extensions) > overheat_n * 4:
        extensions = extensions[-(overheat_n * 4):]

    # ── Failed breakout detection ──────────────────────────────────────────
    # Close returned below baseBreakout with volume in the most recent rows
    is_failed = False
    if base:
        last_close = ind.get("close")
        last_vr    = ind.get("volumeRatio20") or 0.0
        base_level = base.get("level", 0)
        if last_close and last_close < base_level and last_vr >= min_vr:
            is_failed = True

    return base, extensions, is_failed
