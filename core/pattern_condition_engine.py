"""
조건 기반 유사 패턴 엔진
- surgeLabel / timingLabel / decisionBucket / sector / mode / horizon 조합으로
  과거 추천 이력에서 유사 조건을 찾아 분포를 분석한다.
- OHLCV 벡터 매칭 대신 MONE이 이미 계산한 조건 라벨 기반
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

REPORT_DIR = Path("reports")

_MODE_LABELS = {"conservative": "보수", "balanced": "균형", "aggressive": "공격"}
_HORIZON_LABELS = {"short": "단기", "swing": "스윙", "mid": "중기"}
_MARKET_LABELS = {"kr": "국장", "us": "미장"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        s = str(value).strip()
        if s in {"", "nan", "None", "-"}:
            return default
        return float(s.replace(",", "").replace("%", "").replace("원", ""))
    except Exception:
        return default


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() in {"nan", "none", "null"} else s


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc).fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def load_all_snapshots() -> pd.DataFrame:
    """날짜 스냅샷 포함 모든 trade_validation CSV를 합쳐 이력 풀을 만든다."""
    frames: list[pd.DataFrame] = []
    for path in sorted(REPORT_DIR.glob("mone_v36_final_trade_validation_*.csv")):
        parts = path.stem.replace("mone_v36_final_trade_validation_", "").split("_")
        if len(parts) < 3:
            continue
        market = parts[0]
        mode = parts[1] if len(parts) > 1 else ""
        horizon = parts[2] if len(parts) > 2 else ""
        snapshot_date = parts[3] if len(parts) >= 4 else "latest"
        df = _read_csv(path)
        if df.empty:
            continue
        df["_market_tag"] = market
        df["_mode_tag"] = mode
        df["_horizon_tag"] = horizon
        df["_snapshot_date"] = snapshot_date
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    try:
        return pd.concat(frames, ignore_index=True, sort=False).fillna("")
    except Exception:
        return frames[0]


def find_similar_conditions(
    df: pd.DataFrame,
    *,
    market: str = "",
    mode: str = "",
    horizon: str = "",
    surge_label: str = "",
    timing_label: str = "",
    decision_bucket: str = "",
    sector: str = "",
    min_score: float = 0.0,
    max_score: float = 100.0,
) -> pd.DataFrame:
    """
    조건 필터로 유사 이력 레코드를 찾는다.
    빈 문자열 조건은 무시(전체 포함)한다.
    """
    sub = df.copy()

    if market:
        sub = sub[sub["_market_tag"].apply(_safe_str) == market]
    if mode:
        sub = sub[sub["_mode_tag"].apply(_safe_str) == mode]
    if horizon:
        sub = sub[sub["_horizon_tag"].apply(_safe_str) == horizon]
    if surge_label and "surgeLabel" in sub.columns:
        sub = sub[sub["surgeLabel"].apply(_safe_str).str.contains(surge_label, case=False, na=False)]
    if timing_label and "timingLabel" in sub.columns:
        sub = sub[sub["timingLabel"].apply(_safe_str).str.contains(timing_label, case=False, na=False)]
    if decision_bucket and "decisionBucket" in sub.columns:
        sub = sub[sub["decisionBucket"].apply(_safe_str).str.contains(decision_bucket, case=False, na=False)]
    if sector and "sector" in sub.columns:
        sub = sub[sub["sector"].apply(_safe_str).str.contains(sector, case=False, na=False)]
    if min_score > 0 or max_score < 100:
        if "finalScore" in sub.columns:
            scores = sub["finalScore"].apply(_safe_float)
            sub = sub[(scores >= min_score) & (scores <= max_score)]

    return sub.reset_index(drop=True)


def analyze_pattern_distribution(df: pd.DataFrame) -> dict[str, Any]:
    """
    유사 조건 이력의 분포를 분석한다.

    Returns:
        {
            "total": int,
            "score_mean": float,
            "score_p25": float,
            "score_p75": float,
            "decision_bucket_dist": dict,
            "data_status_dist": dict,
            "market_dist": dict,
            "mode_dist": dict,
            "horizon_dist": dict,
            "top_sectors": list,
            "top_surge_labels": list,
            "probability_mean": float,
            "rr_mean": float,
        }
    """
    if df.empty:
        return {"total": 0}

    total = len(df)
    result: dict[str, Any] = {"total": total}

    if "finalScore" in df.columns:
        scores = df["finalScore"].apply(_safe_float).replace(0.0, float("nan"))
        result["score_mean"] = round(scores.mean(), 1) if scores.notna().any() else 0
        result["score_p25"] = round(float(scores.quantile(0.25)), 1) if scores.notna().any() else 0
        result["score_p75"] = round(float(scores.quantile(0.75)), 1) if scores.notna().any() else 0

    if "probability" in df.columns:
        probs = df["probability"].apply(_safe_float).replace(0.0, float("nan"))
        result["probability_mean"] = round(probs.mean(), 1) if probs.notna().any() else 0

    if "rrActual" in df.columns:
        rr = df["rrActual"].apply(_safe_float).replace(0.0, float("nan"))
        result["rr_mean"] = round(rr.mean(), 2) if rr.notna().any() else 0

    if "decisionBucket" in df.columns:
        result["decision_bucket_dist"] = df["decisionBucket"].value_counts().to_dict()

    if "dataStatus" in df.columns:
        result["data_status_dist"] = df["dataStatus"].value_counts().to_dict()

    if "_market_tag" in df.columns:
        result["market_dist"] = {
            _MARKET_LABELS.get(k, k): int(v)
            for k, v in df["_market_tag"].value_counts().items()
        }
    if "_mode_tag" in df.columns:
        result["mode_dist"] = {
            _MODE_LABELS.get(k, k): int(v)
            for k, v in df["_mode_tag"].value_counts().items()
        }
    if "_horizon_tag" in df.columns:
        result["horizon_dist"] = {
            _HORIZON_LABELS.get(k, k): int(v)
            for k, v in df["_horizon_tag"].value_counts().items()
        }

    if "sector" in df.columns:
        result["top_sectors"] = [
            {"섹터": k, "건수": int(v)}
            for k, v in df["sector"].apply(_safe_str).replace("", "미분류").value_counts().head(8).items()
        ]

    if "surgeLabel" in df.columns:
        from collections import Counter
        all_tags: list[str] = []
        for val in df["surgeLabel"].apply(_safe_str):
            for tag in val.split("|"):
                t = tag.strip()
                if t:
                    all_tags.append(t)
        counts = Counter(all_tags)
        result["top_surge_labels"] = [
            {"태그": k, "건수": int(v)} for k, v in counts.most_common(10)
        ]

    return result


def find_pattern_for_symbol(
    df: pd.DataFrame,
    symbol: str,
    *,
    use_same_sector: bool = True,
    use_same_mode: bool = False,
    use_same_horizon: bool = False,
) -> dict[str, Any]:
    """
    특정 종목의 현재 조건과 유사한 과거 이력을 찾는다.
    """
    symbol_upper = str(symbol).upper().strip()
    sym_rows = df[
        df["symbol"].apply(lambda x: str(x).upper().strip()) == symbol_upper
    ] if "symbol" in df.columns else pd.DataFrame()

    if sym_rows.empty:
        return {"found": False, "symbol": symbol, "similar": pd.DataFrame(), "stats": {}}

    # 최신 레코드의 조건 사용
    latest = sym_rows.sort_values("_snapshot_date", ascending=False).iloc[0] if "_snapshot_date" in sym_rows.columns else sym_rows.iloc[0]
    sector = _safe_str(latest.get("sector", ""))
    mode = _safe_str(latest.get("_mode_tag", ""))
    horizon = _safe_str(latest.get("_horizon_tag", ""))
    timing = _safe_str(latest.get("timingLabel", ""))
    bucket = _safe_str(latest.get("decisionBucket", ""))

    similar = find_similar_conditions(
        df,
        sector=sector if use_same_sector else "",
        mode=mode if use_same_mode else "",
        horizon=horizon if use_same_horizon else "",
        timing_label=timing[:5] if timing else "",  # 부분 매칭
        decision_bucket=bucket[:4] if bucket else "",
    )

    # 자기 자신 제외
    similar = similar[similar["symbol"].apply(lambda x: str(x).upper().strip()) != symbol_upper] if "symbol" in similar.columns else similar

    stats = analyze_pattern_distribution(similar)

    return {
        "found": True,
        "symbol": symbol,
        "sector": sector,
        "mode": _MODE_LABELS.get(mode, mode),
        "horizon": _HORIZON_LABELS.get(horizon, horizon),
        "timing": timing,
        "bucket": bucket,
        "similar": similar,
        "stats": stats,
    }
