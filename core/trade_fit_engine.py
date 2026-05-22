from __future__ import annotations

from typing import Any

import pandas as pd


LEVEL_BAD = "\ub098\uc068"
LEVEL_WEAK = "\ubd80\uc871"
LEVEL_NORMAL = "\ubcf4\ud1b5"
LEVEL_GOOD = "\uc88b\uc74c"


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        if isinstance(value, str):
            value = (
                value.replace(",", "")
                .replace("%", "")
                .replace("\ubc30", "")
                .replace("x", "")
                .replace("X", "")
                .strip()
            )
            if value in {"", "-", "nan", "None", "\ud655\uc778 \ud544\uc694"}:
                return default
        return float(value)
    except Exception:
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_str(value).lower()
    if text in {"1", "1.0", "true", "t", "yes", "y", "on"}:
        return True
    if text in {"0", "0.0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _clip(value: float) -> int:
    return int(max(0, min(100, round(value))))


def _level(score: int) -> str:
    if score >= 75:
        return LEVEL_GOOD
    if score >= 55:
        return LEVEL_NORMAL
    if score >= 40:
        return LEVEL_WEAK
    return LEVEL_BAD


def calculate_trade_fit(row: dict[str, Any]) -> dict[str, Any]:
    """Measure whether the current price and risk/reward are fit for a trade."""
    last_price = _safe_float(row.get("last_price") or row.get("current_price"), 0.0)
    entry = _safe_float(row.get("entry") or row.get("preferred_entry"), 0.0)
    stop = _safe_float(row.get("stop") or row.get("stop_loss"), 0.0)
    tp1 = _safe_float(row.get("tp1") or row.get("take_profit1"), 0.0)
    tp2 = _safe_float(row.get("tp2") or row.get("take_profit2"), 0.0)
    rr = _safe_float(row.get("rr"), 0.0)
    rr_pass = _safe_bool(row.get("rr_pass"), rr >= 1.5)

    reasons: list[str] = []
    warnings: list[str] = []
    score = 55.0

    if entry > 0 and last_price > 0:
        entry_gap_pct = (last_price / entry - 1.0) * 100.0
    else:
        entry_gap_pct = 0.0
        warnings.append("\uc9c4\uc785\uac00/\ud604\uc7ac\uac00 \ud655\uc778 \ubd80\uc871")

    if not rr_pass:
        score -= 35
        warnings.append("\uc190\uc775\ube44 \ubbf8\ud1b5\uacfc")
    elif rr >= 3.0:
        score += 15
        reasons.append("\uc190\uc775\ube44 3.0 \uc774\uc0c1")
    elif rr >= 2.0:
        score += 10
        reasons.append("\uc190\uc775\ube44 2.0 \uc774\uc0c1")
    elif rr >= 1.5:
        score += 3
        reasons.append("\uc190\uc775\ube44 \uae30\ubcf8 \ud1b5\uacfc")
    else:
        score -= 15
        warnings.append("\uc190\uc775\ube44 \ubd80\uc871")

    abs_gap = abs(entry_gap_pct)
    if abs_gap <= 2:
        score += 12
        reasons.append("\uc9c4\uc785\uac00 \uadfc\uc811")
    elif entry_gap_pct > 5:
        score -= 22
        warnings.append("\ud604\uc7ac\uac00\uac00 \uc9c4\uc785\uac00\ubcf4\ub2e4 \ub192\uc544 \ucd94\uaca9 \uc704\ud5d8")
    elif entry_gap_pct > 2:
        score -= 6
        warnings.append("\uc9c4\uc785\uac00 \uc774\uaca9")
    elif entry_gap_pct < -8:
        score -= 10
        warnings.append("\uc9c4\uc785\uac00 \uc544\ub798\uc5d0\uc11c \ucd94\uc138 \ud655\uc778 \ud544\uc694")

    stop_clarity_score = 30
    if stop > 0 and entry > stop:
        stop_gap_pct = (entry / stop - 1.0) * 100.0
        if 2 <= stop_gap_pct <= 12:
            stop_clarity_score = 85
            score += 8
            reasons.append("\uc190\uc808 \uae30\uc900 \uba85\ud655")
        elif stop_gap_pct > 0:
            stop_clarity_score = 60
            score += 2
        else:
            score -= 10
            warnings.append("\uc190\uc808\uac00 \uad6c\uc870 \uc774\uc0c1")
    else:
        score -= 8
        warnings.append("\uc190\uc808\uac00 \ud655\uc778 \ubd80\uc871")

    resistance_room_pct = _safe_float(row.get("resistance_room_pct"), 0.0)
    if resistance_room_pct == 0.0 and last_price > 0:
        target = tp1 if tp1 > 0 else tp2
        if target > 0:
            resistance_room_pct = (target / last_price - 1.0) * 100.0
    if resistance_room_pct >= 8:
        score += 10
        reasons.append("\uc800\ud56d\uae4c\uc9c0 \uc5ec\uc720 \ucda9\ubd84")
    elif resistance_room_pct >= 4:
        score += 4
    elif resistance_room_pct > 0:
        score -= 12
        warnings.append("\uc800\ud56d\uae4c\uc9c0 \uc5ec\uc720 \ubd80\uc871")

    if _safe_bool(row.get("support_holding"), False):
        score += 8
        reasons.append("\uc9c0\uc9c0 \uc720\uc9c0")
    elif "support_holding" in row:
        score -= 8
        warnings.append("\uc9c0\uc9c0 \ud655\uc778 \ubd80\uc871")

    if _safe_bool(row.get("volume_confirmed"), False):
        score += 5
        reasons.append("\uac70\ub798\ub7c9 \ud655\uc778")
    if _safe_bool(row.get("pullback_confirmed"), False):
        score += 5
        reasons.append("\ub20c\ub9bc \ud655\uc778")
    if _safe_bool(row.get("breakout_confirmed"), False):
        score += 5
        reasons.append("\ub3cc\ud30c \ud655\uc778")

    final_score = _clip(score)
    if not reasons:
        reasons.append("\uac00\uaca9 \uc801\ud569\ub3c4 \uc911\ub9bd")

    return {
        "trade_fit_score": final_score,
        "price_fit_level": _level(final_score),
        "entry_gap_pct": round(float(entry_gap_pct), 2),
        "stop_clarity_score": int(stop_clarity_score),
        "resistance_room_pct": round(float(resistance_room_pct), 2),
        "trade_fit_reasons": list(dict.fromkeys(reasons)),
        "trade_fit_warnings": list(dict.fromkeys(warnings)),
    }


def apply_trade_fit(candidate_df: pd.DataFrame) -> pd.DataFrame:
    if candidate_df is None:
        return pd.DataFrame()
    out = candidate_df.copy()
    add_cols = [
        "trade_fit_score",
        "price_fit_level",
        "entry_gap_pct",
        "stop_clarity_score",
        "resistance_room_pct",
        "trade_fit_reasons",
        "trade_fit_warnings",
    ]
    if out.empty:
        for col in add_cols:
            if col not in out.columns:
                out[col] = []
        return out
    result = pd.DataFrame([calculate_trade_fit(row) for row in out.to_dict(orient="records")], index=out.index)
    for col in add_cols:
        values = result[col]
        if col in {"trade_fit_reasons", "trade_fit_warnings"}:
            values = values.apply(lambda x: " / ".join(map(str, x)) if isinstance(x, list) else _safe_str(x))
        out[col] = values.values
    return out
