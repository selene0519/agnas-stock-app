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


def _clip(value: float) -> int:
    return int(max(0, min(100, round(value))))


def _series_num(df: pd.DataFrame, columns: list[str], default: float = 0.0) -> pd.Series:
    for col in columns:
        if col in df.columns:
            return df[col].apply(lambda x: _safe_float(x, default))
    return pd.Series(default, index=df.index, dtype=float)


def _market_change_from_context(market_context: dict[str, Any] | None) -> float:
    context = market_context or {}
    candidates = [
        "market_change_pct",
        "candidate_avg_change_pct",
        "nasdaq_change_pct",
        "kosdaq_change_pct",
        "sp500_change_pct",
        "kospi_change_pct",
        "nasdaq_pct",
        "kosdaq_pct",
    ]
    vals = [_safe_float(context.get(key), 0.0) for key in candidates if key in context]
    return sum(vals) / len(vals) if vals else _safe_float(context.get("market_score"), 0.0)


def _is_weak_market(market_context: dict[str, Any] | None) -> bool:
    context = market_context or {}
    text = " ".join(_safe_str(context.get(k)) for k in ["market_regime", "strategy_mode", "market_risk_level", "risk_level"])
    if any(token in text for token in ["\ud558\ub77d", "\uc704\ud5d8", "\ub9e4\uc6b0 \ub192\uc74c", "high", "risk"]):
        return True
    return _safe_float(context.get("market_score"), 0.0) <= -2 or _market_change_from_context(context) < 0


def calculate_aggressive_sector_scores(
    candidate_df: pd.DataFrame,
    market_context: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Find sectors showing unusual strength while the broad market is weak."""
    if candidate_df is None:
        return pd.DataFrame(
            columns=[
                "sector",
                "sector_momentum_score",
                "sector_relative_strength_score",
                "sector_breadth_score",
                "sector_money_flow_score",
                "weak_market_strong_sector_flag",
                "sector_attack_reasons",
            ]
        )
    df = candidate_df.copy()
    if df.empty:
        return pd.DataFrame(
            columns=[
                "sector",
                "sector_momentum_score",
                "sector_relative_strength_score",
                "sector_breadth_score",
                "sector_money_flow_score",
                "weak_market_strong_sector_flag",
                "sector_attack_reasons",
            ]
        )
    if "sector" not in df.columns:
        df["sector"] = df.get("theme", pd.Series("\uae30\ud0c0", index=df.index)).replace("", "\uae30\ud0c0")

    df["_change_pct"] = _series_num(df, ["change_pct", "pct_change", "day_change_pct"], 0.0)
    df["_volume_ratio"] = _series_num(df, ["volume_ratio", "volume_strength"], 1.0)
    df["_trading_value"] = _series_num(df, ["trading_value", "turnover"], 0.0)
    df["_near_high"] = _series_num(df, ["near_high_score"], 50.0)
    df["_momentum5"] = _series_num(df, ["momentum_5d", "momentum5", "five_day_momentum"], 0.0)
    df["_momentum20"] = _series_num(df, ["momentum_20d", "momentum20", "twenty_day_momentum"], 0.0)
    df["_news"] = _series_num(df, ["news_momentum_score", "catalyst_score"], 50.0)
    df["_volatility"] = _series_num(df, ["volatility_risk", "atr_pct"], 0.0)

    market_change = _market_change_from_context(market_context)
    weak_market = _is_weak_market(market_context)
    records: list[dict[str, Any]] = []
    for sector, group in df.groupby(df["sector"].astype(str).replace("", "\uae30\ud0c0")):
        avg_change = float(group["_change_pct"].mean())
        up_ratio = float((group["_change_pct"] > 0).mean()) if len(group) else 0.0
        volume_strength = float(group["_volume_ratio"].mean())
        trading_value = float(group["_trading_value"].mean())
        near_high_ratio = float((group["_near_high"] >= 70).mean()) if len(group) else 0.0
        momentum = float(group["_momentum5"].mean() * 4 + group["_momentum20"].mean() * 2)
        news_score = float(group["_news"].mean())
        volatility = float(group["_volatility"].mean())
        rel_strength = avg_change - market_change

        momentum_score = _clip(50 + avg_change * 8 + momentum + near_high_ratio * 15 + (news_score - 50) * 0.15)
        relative_score = _clip(50 + rel_strength * 10)
        breadth_score = _clip(up_ratio * 100)
        money_score = _clip(45 + min(volume_strength, 5.0) * 10 + min(trading_value / 10_000_000_000, 4) * 6)
        risk_penalty = 10 if volatility >= 8 else 5 if volatility >= 5 else 0
        composite = _clip(momentum_score * 0.3 + relative_score * 0.3 + breadth_score * 0.2 + money_score * 0.2 - risk_penalty)
        strong_flag = bool(weak_market and composite >= 70 and rel_strength > 0 and up_ratio >= 0.5)

        reasons: list[str] = []
        if rel_strength > 0:
            reasons.append("\uc2dc\uc7a5 \ub300\ube44 \uc139\ud130 \uc0c1\ub300\uac15\ub3c4")
        if up_ratio >= 0.6:
            reasons.append("\uc139\ud130 \ub0b4 \uc0c1\uc2b9 \ud655\uc0b0")
        if volume_strength >= 1.3 or trading_value >= 10_000_000_000:
            reasons.append("\uac70\ub798\ub7c9/\uac70\ub798\ub300\uae08 \uc720\uc785")
        if near_high_ratio >= 0.4:
            reasons.append("20\uc77c \uace0\uc810 \uadfc\uc811 \ube44\uc728 \uc591\ud638")
        if news_score >= 65:
            reasons.append("\ub274\uc2a4/\uc774\uc288 \uc5f0\uc18d\uc131")
        if volatility >= 5:
            reasons.append("\ubcc0\ub3d9\uc131 \ub9ac\uc2a4\ud06c \uc874\uc7ac")
        if not reasons:
            reasons.append("\uc139\ud130 \uacf5\uaca9 \uc2e0\ud638 \uc911\ub9bd")

        records.append(
            {
                "sector": sector,
                "sector_momentum_score": composite,
                "sector_relative_strength_score": relative_score,
                "sector_breadth_score": breadth_score,
                "sector_money_flow_score": money_score,
                "weak_market_strong_sector_flag": strong_flag,
                "sector_attack_reasons": " / ".join(dict.fromkeys(reasons)),
            }
        )
    return pd.DataFrame(records).sort_values("sector_momentum_score", ascending=False).reset_index(drop=True)


def apply_aggressive_sector_scores(
    candidate_df: pd.DataFrame,
    market_context: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if candidate_df is None:
        return pd.DataFrame()
    out = candidate_df.copy()
    cols = [
        "sector_momentum_score",
        "sector_relative_strength_score",
        "sector_breadth_score",
        "sector_money_flow_score",
        "weak_market_strong_sector_flag",
        "sector_attack_reasons",
    ]
    if out.empty:
        for col in cols:
            if col not in out.columns:
                out[col] = []
        return out
    stale_cols = list(cols) + [
        col
        for col in out.columns
        if col.endswith("_aggressive_sector")
        or "_aggressive_sector." in col
        or col.endswith(".1")
        and col.replace(".1", "") in cols
        or col.endswith(".2")
        and col.replace(".2", "") in cols
    ]
    if stale_cols:
        out = out.drop(columns=stale_cols, errors="ignore")
    sector_scores = calculate_aggressive_sector_scores(out, market_context)
    if "sector" not in out.columns:
        out["sector"] = out.get("theme", pd.Series("\uae30\ud0c0", index=out.index)).replace("", "\uae30\ud0c0")
    if sector_scores.empty:
        for col in cols:
            if col not in out.columns:
                out[col] = "" if col.endswith("reasons") else 0
        return out
    merged = out.merge(sector_scores, on="sector", how="left", suffixes=("", "_aggressive_sector"))
    for col in cols:
        fill = "" if col.endswith("reasons") else False if col.endswith("flag") else 0
        merged[col] = merged[col].fillna(fill)
    return merged
