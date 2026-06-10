"""
Pattern Strategy Engine v1 — technical indicator calculations.

All functions accept a list of OHLCV row dicts
{"date", "open", "high", "low", "close", "volume"} sorted oldest-first.
They return float | None — callers must handle None (DATA_QUALITY_RISK).
"""
from __future__ import annotations

from typing import Any


def _f(val: Any) -> float | None:
    try:
        v = float(val)
        return v if v == v else None  # NaN check
    except (TypeError, ValueError):
        return None


# ── Core indicators ───────────────────────────────────────────────────────────

def compute_atr20(rows: list[dict]) -> float | None:
    """Average True Range over 20 periods (uses up to last 21 rows)."""
    work = rows[-21:] if len(rows) >= 21 else rows
    if len(work) < 2:
        return None
    trs: list[float] = []
    for i in range(1, len(work)):
        h = _f(work[i].get("high"))
        l = _f(work[i].get("low"))
        c = _f(work[i].get("close"))
        pc = _f(work[i - 1].get("close"))
        if None in (h, l, c, pc):
            continue
        tr = max(h - l, abs(h - pc), abs(l - pc))  # type: ignore[operator]
        trs.append(tr)
    if not trs:
        return None
    atr = sum(trs[-20:]) / len(trs[-20:])
    return atr if atr > 0 else None


def compute_rsi14(rows: list[dict]) -> float | None:
    """RSI over 14 periods (Wilder smoothing)."""
    closes: list[float] = [v for r in rows if (v := _f(r.get("close"))) is not None]
    if len(closes) < 15:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    ag = sum(gains[-14:]) / 14
    al = sum(losses[-14:]) / 14
    if al == 0:
        return 100.0
    rs = ag / al
    return round(100 - 100 / (1 + rs), 2)


def compute_ma(rows: list[dict], window: int) -> float | None:
    """Simple moving average of close over `window` periods."""
    closes: list[float] = [v for r in rows if (v := _f(r.get("close"))) is not None]
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def compute_volume_ratio20(rows: list[dict]) -> float | None:
    """Today's volume / 20-day average volume (excluding today)."""
    vols: list[float] = [v for r in rows if (v := _f(r.get("volume"))) is not None and v > 0]
    if len(vols) < 2:
        return None
    today_vol = vols[-1]
    avg_vol = sum(vols[-21:-1]) / len(vols[-21:-1]) if len(vols) >= 2 else None
    if not avg_vol or avg_vol <= 0:
        return None
    return round(today_vol / avg_vol, 3)


def compute_daily_down_atr(
    prev_close: float | None,
    today_high: float | None,
    today_close: float | None,
    atr20: float | None,
) -> float | None:
    """
    Volatility-relative downside speed:
        max(prevClose - todayClose, todayHigh - todayClose, 0) / ATR20

    Captures both day-over-day decline and intraday wick (gap-up then dump).
    """
    if None in (prev_close, today_high, today_close, atr20):
        return None
    if atr20 <= 0:  # type: ignore[operator]
        return None
    val = max(prev_close - today_close, today_high - today_close, 0)  # type: ignore[operator]
    return round(val / atr20, 4)  # type: ignore[operator]


def compute_ma20_disparity(close: float | None, ma20: float | None) -> float | None:
    """close / ma20  (>1 = above MA20, <1 = below)."""
    if close is None or ma20 is None or ma20 <= 0:
        return None
    return round(close / ma20, 4)


def compute_range_bounds(rows: list[dict], lookback: int = 40) -> tuple[float | None, float | None]:
    """
    Rolling high and low over `lookback` periods *excluding the current bar*
    so that a breakout today is detected against the historical range.
    """
    hist = rows[-lookback - 1:-1] if len(rows) > 1 else []
    if not hist:
        return None, None
    highs = [v for r in hist if (v := _f(r.get("high"))) is not None]
    lows  = [v for r in hist if (v := _f(r.get("low"))) is not None]
    if not highs or not lows:
        return None, None
    return max(highs), min(lows)


def compute_all(rows: list[dict]) -> dict[str, Any]:
    """Compute all indicators for the latest row; return as a flat dict."""
    if not rows:
        return {}
    last = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else {}

    atr20      = compute_atr20(rows)
    rsi14      = compute_rsi14(rows)
    ma20       = compute_ma(rows, 20)
    ma10       = compute_ma(rows, 10)
    ma5        = compute_ma(rows, 5)
    vol_ratio  = compute_volume_ratio20(rows)
    close      = _f(last.get("close"))
    prev_close = _f(prev.get("close"))
    today_high = _f(last.get("high"))
    today_low  = _f(last.get("low"))
    dda        = compute_daily_down_atr(prev_close, today_high, close, atr20)
    disp       = compute_ma20_disparity(close, ma20)
    rh, rl     = compute_range_bounds(rows, 40)

    return {
        "atr20":          atr20,
        "rsi14":          rsi14,
        "ma20":           ma20,
        "ma10":           ma10,
        "ma5":            ma5,
        "ma20Disparity":  disp,
        "volumeRatio20":  vol_ratio,
        "dailyDownAtr":   dda,
        "close":          close,
        "prevClose":      prev_close,
        "todayHigh":      today_high,
        "todayLow":       today_low,
        "rangeHigh":      rh,
        "rangeLow":       rl,
        "rangeWidth":     round((rh - rl) / rl, 4) if rh and rl and rl > 0 else None,
    }
