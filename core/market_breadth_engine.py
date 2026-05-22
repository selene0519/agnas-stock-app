from __future__ import annotations

from typing import Any

import pandas as pd


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        text = str(value).strip()
        for token in ["%", "배", "$", "원", ",", "+"]:
            text = text.replace(token, "")
        if text == "" or text.lower() in {"nan", "none", "nat"}:
            return default
        return float(text)
    except Exception:
        return default


def _first_col(df: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    return None


def calculate_candidate_breadth(candidate_df: pd.DataFrame) -> dict[str, Any]:
    if candidate_df is None or candidate_df.empty:
        return {
            "candidate_up_ratio": 0.0,
            "candidate_down_ratio": 0.0,
            "candidate_avg_change_pct": 0.0,
            "candidate_median_change_pct": 0.0,
            "candidate_volume_strength": 0.0,
            "breadth_risk_score": 50,
            "market_breadth_warning": "후보군 데이터 부족",
        }

    df = candidate_df.copy()
    change_col = _first_col(df, ("change_pct", "등락률", "pct_change", "daily_change_pct"))
    volume_col = _first_col(df, ("volume_ratio", "거래량비율", "volume_strength", "volume_ratio_20d"))
    if change_col is None:
        change = pd.Series([0.0] * len(df), index=df.index)
    else:
        change = df[change_col].map(_num)
    if volume_col is None:
        volume = pd.Series([1.0] * len(df), index=df.index)
    else:
        volume = df[volume_col].map(lambda x: _num(x, 1.0))

    total = max(1, len(df))
    up_ratio = float(change.gt(0).sum() / total)
    down_ratio = float(change.lt(0).sum() / total)
    avg_change = float(change.mean()) if len(change) else 0.0
    median_change = float(change.median()) if len(change) else 0.0
    volume_strength = float(volume.mean()) if len(volume) else 0.0

    risk = 0
    warning = "정상"
    if down_ratio >= 0.85:
        risk += 80
        warning = "위험회피 후보: 후보군 하락 비율 85% 이상"
    elif down_ratio >= 0.75:
        risk += 65
        warning = "신규매수 제한 후보: 후보군 하락 비율 75% 이상"
    elif down_ratio >= 0.60:
        risk += 45
        warning = "WARNING: 후보군 하락 비율 60% 이상"
    else:
        risk += int(max(0, down_ratio) * 40)

    if avg_change < 0 and median_change < 0:
        risk += 15
    down_volume = volume[change.lt(0)].mean() if bool(change.lt(0).any()) else 0.0
    up_volume = volume[change.gt(0)].mean() if bool(change.gt(0).any()) else 0.0
    if down_volume > max(1.2, up_volume * 1.15):
        risk += 10
        if warning == "정상":
            warning = "하락 종목 거래량 집중"

    return {
        "candidate_up_ratio": round(up_ratio, 4),
        "candidate_down_ratio": round(down_ratio, 4),
        "candidate_avg_change_pct": round(avg_change, 4),
        "candidate_median_change_pct": round(median_change, 4),
        "candidate_volume_strength": round(volume_strength, 4),
        "breadth_risk_score": int(max(0, min(100, risk))),
        "market_breadth_warning": warning,
    }


def calculate_sector_internal_strength(candidate_df: pd.DataFrame) -> pd.DataFrame:
    if candidate_df is None or candidate_df.empty:
        return pd.DataFrame(
            columns=[
                "sector",
                "sector_up_ratio",
                "sector_avg_change_pct",
                "sector_volume_strength",
                "sector_breadth_score",
                "sector_spread_score",
            ]
        )

    df = candidate_df.copy()
    sector_col = _first_col(df, ("sector", "theme", "섹터", "업종"))
    change_col = _first_col(df, ("change_pct", "등락률", "pct_change", "daily_change_pct"))
    volume_col = _first_col(df, ("volume_ratio", "거래량비율", "volume_strength", "volume_ratio_20d"))
    df["_sector"] = df[sector_col].astype(str).replace("", "미분류") if sector_col else "미분류"
    df["_change"] = df[change_col].map(_num) if change_col else 0.0
    df["_volume"] = df[volume_col].map(lambda x: _num(x, 1.0)) if volume_col else 1.0

    rows: list[dict[str, Any]] = []
    for sector, group in df.groupby("_sector", dropna=False):
        up_ratio = float(group["_change"].gt(0).mean()) if len(group) else 0.0
        avg_change = float(group["_change"].mean()) if len(group) else 0.0
        vol = float(group["_volume"].mean()) if len(group) else 0.0
        breadth_score = int(max(0, min(100, round(up_ratio * 70 + max(-3, min(3, avg_change)) * 5 + min(2, vol) * 10))))
        rows.append(
            {
                "sector": str(sector) or "미분류",
                "sector_up_ratio": round(up_ratio, 4),
                "sector_avg_change_pct": round(avg_change, 4),
                "sector_volume_strength": round(vol, 4),
                "sector_breadth_score": breadth_score,
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        out["sector_spread_score"] = []
        return out
    strong = int(out["sector_breadth_score"].ge(60).sum())
    total = max(1, len(out))
    spread_score = int(max(0, min(100, round(strong / total * 100))))
    out["sector_spread_score"] = spread_score
    return out.sort_values("sector_breadth_score", ascending=False).reset_index(drop=True)
