from __future__ import annotations

from typing import Any

import pandas as pd


LEVEL_LOW = "\ub0ae\uc74c"
LEVEL_NORMAL = "\ubcf4\ud1b5"
LEVEL_HIGH = "\ub192\uc74c"
LEVEL_VERY_HIGH = "\ub9e4\uc6b0 \ub192\uc74c"


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
            if value in {"", "-", "nan", "None"}:
                return default
        return float(value)
    except Exception:
        return default


def _score_like_0_100(value: Any, default: float = 50.0) -> float:
    num = _safe_float(value, default)
    if -5 <= num <= 5:
        return max(0.0, min(100.0, 50.0 + num * 10.0))
    return max(0.0, min(100.0, num))


def _clip(value: float) -> int:
    return int(max(0, min(100, round(value))))


def _level(score: int) -> str:
    if score >= 85:
        return LEVEL_VERY_HIGH
    if score >= 70:
        return LEVEL_HIGH
    if score >= 50:
        return LEVEL_NORMAL
    return LEVEL_LOW


def calculate_stock_attractiveness(row: dict[str, Any]) -> dict[str, Any]:
    """Measure whether the stock itself is worth watching, separate from entry price."""
    sector_strength = _score_like_0_100(row.get("sector_strength"))
    inputs = [
        sector_strength,
        _score_like_0_100(row.get("sector_momentum_score")),
        _score_like_0_100(row.get("leader_score")),
        _score_like_0_100(row.get("earnings_growth_score")),
        _score_like_0_100(row.get("news_momentum_score")),
        _score_like_0_100(row.get("relative_strength_score")),
        _score_like_0_100(row.get("near_high_score")),
        _score_like_0_100(row.get("catalyst_score")),
    ]
    score = sum(inputs) / len(inputs)
    reasons: list[str] = []
    warnings: list[str] = []

    if sector_strength >= 70:
        score += 6
        reasons.append("\uc139\ud130 \uac15\ub3c4 \uc6b0\uc218")
    elif sector_strength < 40:
        score -= 8
        warnings.append("\uc139\ud130 \uac15\ub3c4 \ubd80\uc871")

    volume_ratio = _safe_float(row.get("volume_ratio"), 1.0)
    if volume_ratio >= 2.0:
        score += 10
        reasons.append("\uac70\ub798\ub7c9 \uac15\ud55c \uc99d\uac00")
    elif volume_ratio >= 1.3:
        score += 5
        reasons.append("\uac70\ub798\ub7c9 \ud655\uc778")
    elif volume_ratio < 0.8:
        score -= 8
        warnings.append("\uac70\ub798\ub7c9 \ubd80\uc871")

    trading_value = _safe_float(row.get("trading_value"), 0.0)
    if trading_value >= 10_000_000_000:
        score += 5
        reasons.append("\uac70\ub798\ub300\uae08 \ucda9\ubd84")
    elif 0 < trading_value < 1_000_000_000:
        score -= 5
        warnings.append("\uac70\ub798\ub300\uae08 \uc81c\ud55c")

    relative_strength = _score_like_0_100(row.get("relative_strength_score"))
    leader_score = _score_like_0_100(row.get("leader_score"))
    catalyst = _score_like_0_100(row.get("catalyst_score"))
    if relative_strength >= 75:
        reasons.append("\uc0c1\ub300\uac15\ub3c4 \uc6b0\uc218")
    if leader_score >= 75:
        reasons.append("\uc8fc\ub3c4\uc8fc \ud6c4\ubcf4")
    if catalyst >= 70:
        reasons.append("\ubaa8\uba58\ud140/\ucd09\ub9e4 \uc874\uc7ac")
    if relative_strength < 35:
        warnings.append("\uc0c1\ub300\uac15\ub3c4 \uc57d\ud568")

    final_score = _clip(score)
    if not reasons:
        reasons.append("\uc885\ubaa9 \ub9e4\ub825\ub3c4 \uc911\ub9bd")

    return {
        "stock_attractiveness_score": final_score,
        "stock_quality_level": _level(final_score),
        "stock_quality_reasons": list(dict.fromkeys(reasons)),
        "stock_quality_warnings": list(dict.fromkeys(warnings)),
    }


def apply_stock_attractiveness(candidate_df: pd.DataFrame) -> pd.DataFrame:
    if candidate_df is None:
        return pd.DataFrame()
    out = candidate_df.copy()
    add_cols = [
        "stock_attractiveness_score",
        "stock_quality_level",
        "stock_quality_reasons",
        "stock_quality_warnings",
    ]
    if out.empty:
        for col in add_cols:
            if col not in out.columns:
                out[col] = []
        return out
    result = pd.DataFrame([calculate_stock_attractiveness(row) for row in out.to_dict(orient="records")], index=out.index)
    for col in add_cols:
        values = result[col]
        if col in {"stock_quality_reasons", "stock_quality_warnings"}:
            values = values.apply(lambda x: " / ".join(map(str, x)) if isinstance(x, list) else _safe_str(x))
        out[col] = values.values
    return out
