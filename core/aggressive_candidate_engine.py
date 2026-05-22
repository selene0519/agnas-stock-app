from __future__ import annotations

from typing import Any

import pandas as pd


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


def _market_change(row: dict[str, Any]) -> float:
    for key in [
        "market_change_pct",
        "candidate_avg_change_pct",
        "nasdaq_change_pct",
        "kosdaq_change_pct",
        "sp500_change_pct",
        "kospi_change_pct",
        "nasdaq_pct",
        "kosdaq_pct",
    ]:
        if key in row:
            return _safe_float(row.get(key), 0.0)
    return _safe_float(row.get("market_score"), 0.0)


def _is_weak_market(row: dict[str, Any]) -> bool:
    text = " ".join(_safe_str(row.get(k)) for k in ["market_regime", "strategy_mode", "market_risk_level", "risk_level"])
    if any(token in text for token in ["\ud558\ub77d", "\uc704\ud5d8", "\ub9e4\uc6b0 \ub192\uc74c", "high", "risk"]):
        return True
    return _safe_float(row.get("market_score"), 0.0) <= -2 or _market_change(row) < 0


def calculate_aggressive_candidate_score(row: dict[str, Any]) -> dict[str, Any]:
    """Score stocks that resist weak markets without turning them into immediate buys."""
    change_pct = _safe_float(row.get("change_pct") or row.get("pct_change") or row.get("day_change_pct"), 0.0)
    market_change = _market_change(row)
    sector_avg_change = _safe_float(row.get("sector_avg_change_pct"), market_change)
    candidate_avg_change = _safe_float(row.get("candidate_avg_change_pct"), market_change)
    market_relative_strength = round(change_pct - market_change, 2)
    sector_relative_strength = round(change_pct - sector_avg_change, 2)
    candidate_relative_strength = change_pct - candidate_avg_change

    volume_ratio = _safe_float(row.get("volume_ratio") or row.get("volume_strength"), 1.0)
    trading_value = _safe_float(row.get("trading_value") or row.get("turnover"), 0.0)
    sector_score = _safe_float(row.get("sector_momentum_score"), 50.0)
    near_high_score = _safe_float(row.get("near_high_score"), 50.0)
    high20_gap = _safe_float(row.get("high20_gap_pct") or row.get("distance_to_20d_high_pct"), 0.0)
    pullback_confirmed = _safe_bool(row.get("pullback_confirmed"), False)
    breakout_confirmed = _safe_bool(row.get("breakout_confirmed"), False)
    news_score = _safe_float(row.get("news_momentum_score") or row.get("catalyst_score"), 50.0)
    chase_risk = _safe_bool(row.get("chase_risk"), False)
    weak_market = _is_weak_market(row)

    resilience = 50.0
    if weak_market and change_pct > 0:
        resilience += 25
    resilience += max(-20, min(25, market_relative_strength * 6))
    if change_pct >= 0:
        resilience += 5
    if volume_ratio >= 1.5:
        resilience += 8
    down_market_resilience_score = _clip(resilience)

    score = 45.0
    score += max(-18, min(25, market_relative_strength * 5))
    score += max(-12, min(18, sector_relative_strength * 4))
    score += max(-10, min(14, candidate_relative_strength * 3))
    score += min(max(volume_ratio - 1.0, 0.0), 3.0) * 7
    score += min(trading_value / 10_000_000_000, 3.0) * 4
    score += (sector_score - 50.0) * 0.25
    score += 10 if near_high_score >= 75 or -5 <= high20_gap <= 2 else 0
    score += 8 if breakout_confirmed else 5 if pullback_confirmed else 0
    score += (news_score - 50.0) * 0.15
    if weak_market and change_pct > 0:
        score += 10
    if chase_risk:
        score -= 20

    aggressive_score = _clip(score)
    weak_market_leader_flag = bool(weak_market and change_pct > 0 and market_relative_strength > 0 and aggressive_score >= 65)
    strong_watch_candidate = bool(aggressive_score >= 80 and not chase_risk)

    reasons: list[str] = []
    warnings: list[str] = []
    if market_relative_strength > 0:
        reasons.append("\uc2dc\uc7a5 \ub300\ube44 \uc0c1\ub300\uac15\ub3c4")
    if sector_relative_strength > 0:
        reasons.append("\uc139\ud130 \ub300\ube44 \uc0c1\ub300\uac15\ub3c4")
    if weak_market_leader_flag:
        reasons.append("\uc2dc\uc7a5 \uc57d\uc138 \uc18d \uc5ed\ud589")
    if volume_ratio >= 1.5 or trading_value >= 10_000_000_000:
        reasons.append("\uac70\ub798\ub7c9/\uac70\ub798\ub300\uae08 \uc99d\uac00")
    if sector_score >= 70:
        reasons.append("\uacf5\uaca9\ud615 \uc139\ud130 \uc18d\ud55c \ud6c4\ubcf4")
    if near_high_score >= 75 or -5 <= high20_gap <= 2:
        reasons.append("20\uc77c \uace0\uc810 \uadfc\uc811/\ub3cc\ud30c")
    if pullback_confirmed:
        reasons.append("\ub20c\ub9bc \ud6c4 \ubc18\ub4f1 \uc2e0\ud638")
    if news_score >= 65:
        reasons.append("\ub274\uc2a4/\uc774\uc288 \uc5f0\uc18d\uc131")
    if chase_risk:
        warnings.append("\ucd94\uaca9\ub9e4\uc218 \uae08\uc9c0")
    if weak_market:
        warnings.append("\uc57d\uc138\uc7a5: \uc989\uc2dc\ub9e4\uc218 \uae08\uc9c0, \uad00\ucc30 \uc6b0\uc120")
    if not reasons:
        reasons.append("\uacf5\uaca9\ud615 \uc2e0\ud638 \uc911\ub9bd")

    return {
        "aggressive_score": aggressive_score,
        "market_relative_strength": market_relative_strength,
        "sector_relative_strength": sector_relative_strength,
        "down_market_resilience_score": down_market_resilience_score,
        "weak_market_leader_flag": weak_market_leader_flag,
        "strong_watch_candidate": strong_watch_candidate,
        "aggressive_reasons": list(dict.fromkeys(reasons)),
        "aggressive_warnings": list(dict.fromkeys(warnings)),
    }


def apply_aggressive_candidate_scores(candidate_df: pd.DataFrame) -> pd.DataFrame:
    if candidate_df is None:
        return pd.DataFrame()
    out = candidate_df.copy()
    cols = [
        "aggressive_score",
        "market_relative_strength",
        "sector_relative_strength",
        "down_market_resilience_score",
        "weak_market_leader_flag",
        "strong_watch_candidate",
        "aggressive_reasons",
        "aggressive_warnings",
    ]
    if out.empty:
        for col in cols:
            if col not in out.columns:
                out[col] = []
        return out
    result = pd.DataFrame([calculate_aggressive_candidate_score(row) for row in out.to_dict(orient="records")], index=out.index)
    for col in cols:
        values = result[col]
        if col in {"aggressive_reasons", "aggressive_warnings"}:
            values = values.apply(lambda x: " / ".join(map(str, x)) if isinstance(x, list) else _safe_str(x))
        out[col] = values.values
    return out
