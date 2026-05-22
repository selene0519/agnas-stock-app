from __future__ import annotations

from typing import Any

import pandas as pd


TYPE_BEFORE_PULLBACK = "\ub20c\ub9bc \uc804"
TYPE_PULLBACK_IN_PROGRESS = "\ub20c\ub9bc \uc911"
TYPE_PULLBACK_CONFIRMED = "\ub20c\ub9bc \ud655\uc778 \uc644\ub8cc"
TYPE_BEFORE_BREAKOUT = "\ub3cc\ud30c \uc804"
TYPE_BREAKOUT_CONFIRMED = "\ub3cc\ud30c \ud655\uc778 \uc644\ub8cc"
TYPE_CHASE_RISK = "\ucd94\uaca9\ub9e4\uc218 \uc704\ud5d8"
TYPE_TREND_BROKEN = "\ucd94\uc138 \ud6fc\uc190"
TYPE_BOX_MIDDLE = "\ubc15\uc2a4\uad8c \uc911\uac04\uac12"


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


def classify_entry_position(row: dict[str, Any]) -> dict[str, Any]:
    """Classify the current entry location independently from stock quality."""
    last_price = _safe_float(row.get("last_price") or row.get("current_price"), 0.0)
    entry = _safe_float(row.get("entry") or row.get("preferred_entry"), 0.0)
    stop = _safe_float(row.get("stop") or row.get("stop_loss"), 0.0)
    resistance_room_pct = _safe_float(row.get("resistance_room_pct"), 0.0)
    entry_gap_pct = _safe_float(row.get("entry_gap_pct"), 0.0)
    if entry > 0 and last_price > 0:
        entry_gap_pct = (last_price / entry - 1.0) * 100.0

    overheat = _safe_str(row.get("overheat_level"))
    chase_risk = _safe_bool(row.get("chase_risk"), False)
    support_holding = _safe_bool(row.get("support_holding"), True)
    pullback_confirmed = _safe_bool(row.get("pullback_confirmed"), False)
    breakout_confirmed = _safe_bool(row.get("breakout_confirmed"), False)
    volume_confirmed = _safe_bool(row.get("volume_confirmed"), False)

    if stop > 0 and last_price > 0 and last_price <= stop:
        return {
            "entry_position_type": TYPE_TREND_BROKEN,
            "entry_position_score": 15,
            "entry_position_reason": "\ud604\uc7ac\uac00\uac00 \uc190\uc808/\uc9c0\uc9c0 \uae30\uc900 \uc774\ud558",
            "entry_position_warning": "\ucd94\uc138 \ud6fc\uc190",
        }
    if support_holding is False and entry_gap_pct < -3:
        return {
            "entry_position_type": TYPE_TREND_BROKEN,
            "entry_position_score": 25,
            "entry_position_reason": "\uc9c0\uc9c0 \uc720\uc9c0 \uc2e4\ud328 \uac00\ub2a5\uc131",
            "entry_position_warning": "\uc9c4\uc785 \ubcf4\ub958",
        }
    if chase_risk or entry_gap_pct >= 6 or overheat in {"\ub192\uc74c", "\ub9e4\uc6b0 \ub192\uc74c"}:
        return {
            "entry_position_type": TYPE_CHASE_RISK,
            "entry_position_score": 20,
            "entry_position_reason": "\uc9c4\uc785\uac00 \uc774\uaca9 \ub610\ub294 \uacfc\uc5f4",
            "entry_position_warning": "\ucd94\uaca9\ub9e4\uc218 \uae08\uc9c0",
        }
    if pullback_confirmed:
        score = 86 + (6 if volume_confirmed else 0)
        return {
            "entry_position_type": TYPE_PULLBACK_CONFIRMED,
            "entry_position_score": _clip(score),
            "entry_position_reason": "\ub20c\ub9bc \ud6c4 \uc9c0\uc9c0/\ud655\uc778 \uc644\ub8cc",
            "entry_position_warning": "",
        }
    if breakout_confirmed:
        score = 78 + (5 if volume_confirmed else 0)
        return {
            "entry_position_type": TYPE_BREAKOUT_CONFIRMED,
            "entry_position_score": _clip(score),
            "entry_position_reason": "\ub3cc\ud30c \ud655\uc778 \uc644\ub8cc",
            "entry_position_warning": "" if volume_confirmed else "\uac70\ub798\ub7c9 \ucd94\uac00 \ud655\uc778",
        }
    if -3 <= entry_gap_pct <= 2:
        return {
            "entry_position_type": TYPE_PULLBACK_IN_PROGRESS,
            "entry_position_score": 68,
            "entry_position_reason": "\uc9c4\uc785\uac00 \uadfc\ucc98\uc758 \ub20c\ub9bc \uad6c\uac04",
            "entry_position_warning": "\ud655\uc778 \uc804 \uc18c\uc561/\uad00\ucc30",
        }
    if entry_gap_pct > 2 and resistance_room_pct >= 5:
        return {
            "entry_position_type": TYPE_BEFORE_PULLBACK,
            "entry_position_score": 55,
            "entry_position_reason": "\uc885\ubaa9\uc740 \uc720\ud6a8\ud558\ub098 \ub20c\ub9bc \ub300\uae30",
            "entry_position_warning": "\ud604\uc7ac\uac00 \ucd94\uaca9 \uc790\uc81c",
        }
    if entry_gap_pct < -3:
        return {
            "entry_position_type": TYPE_BEFORE_BREAKOUT,
            "entry_position_score": 50,
            "entry_position_reason": "\ub3cc\ud30c/\ud68c\ubcf5 \ud655\uc778 \uc804",
            "entry_position_warning": "\ucd94\uc138 \ud655\uc778 \ud544\uc694",
        }
    return {
        "entry_position_type": TYPE_BOX_MIDDLE,
        "entry_position_score": 45,
        "entry_position_reason": "\ub9e4\uc218/\ub9e4\ub3c4 \uc6b0\uc704\uac00 \ubd84\uba85\ud558\uc9c0 \uc54a\uc740 \uc911\uac04\uac12",
        "entry_position_warning": "\ubc29\ud5a5 \ud655\uc778 \ud544\uc694",
    }


def apply_entry_position(candidate_df: pd.DataFrame) -> pd.DataFrame:
    if candidate_df is None:
        return pd.DataFrame()
    out = candidate_df.copy()
    add_cols = [
        "entry_position_type",
        "entry_position_score",
        "entry_position_reason",
        "entry_position_warning",
    ]
    if out.empty:
        for col in add_cols:
            if col not in out.columns:
                out[col] = []
        return out
    result = pd.DataFrame([classify_entry_position(row) for row in out.to_dict(orient="records")], index=out.index)
    for col in add_cols:
        out[col] = result[col].values
    return out
