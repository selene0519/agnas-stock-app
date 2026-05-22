from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


REPORT_DIR = Path("reports")
HISTORICAL_PATTERN_STATS_CSV = REPORT_DIR / "historical_pattern_stats.csv"
WEIGHT_ADJUSTMENT_SUGGESTIONS_JSON = REPORT_DIR / "weight_adjustment_suggestions.json"
REVIEWED_RESULTS = {"success", "fail", "neutral"}
DEFAULT_INSUFFICIENT_NOTE = "표본 부족: 유사조건 통계 미적용"


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
                .replace("배", "")
                .replace("x", "")
                .replace("X", "")
                .strip()
            )
            if value in {"", "-", "nan", "None", "확인 필요"}:
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


def _has_value(row: dict[str, Any], key: str) -> bool:
    if key not in row:
        return False
    text = _safe_str(row.get(key))
    return text not in {"", "-", "nan", "None"}


def _bucket_num(value: float, cuts: list[tuple[float, str]], default: str) -> str:
    for upper, label in cuts:
        if value < upper:
            return label
    return default


def _score_bucket(row: dict[str, Any]) -> str:
    if not any(
        _has_value(row, key)
        for key in ["strategy_adjusted_score", "adjusted_score_after_review", "실전등급점수", "score"]
    ):
        return "score_unknown"
    score = _safe_float(
        row.get("strategy_adjusted_score")
        or row.get("adjusted_score_after_review")
        or row.get("실전등급점수")
        or row.get("score"),
        0,
    )
    return _bucket_num(score, [(45, "score_<45"), (65, "score_45_64"), (80, "score_65_79")], "score_80+")


def _rr_bucket(row: dict[str, Any]) -> str:
    if not _has_value(row, "rr") and not _has_value(row, "rr_pass"):
        return "rr_unknown"
    rr = _safe_float(row.get("rr"), 0)
    if not _safe_bool(row.get("rr_pass"), rr >= 1.5):
        return "rr_fail"
    return _bucket_num(rr, [(1.5, "rr_<1.5"), (2.0, "rr_1.5_1.99"), (3.0, "rr_2_2.99")], "rr_3+")


def _entry_gap_bucket(row: dict[str, Any]) -> str:
    if not _has_value(row, "entry_gap_pct") and not _has_value(row, "gap_pct_vs_entry"):
        return "entry_unknown"
    gap = _safe_float(row.get("entry_gap_pct") or row.get("gap_pct_vs_entry"), 0)
    return _bucket_num(gap, [(-5, "entry_far_below"), (2, "entry_near"), (6, "entry_above")], "entry_chase")


def _news_bucket(row: dict[str, Any]) -> str:
    grade = _safe_str(row.get("news_grade"))
    if grade:
        return f"news_{grade}"
    if not _has_value(row, "news_momentum_score") and not _has_value(row, "news_risk_level"):
        return "news_unknown"
    score = _safe_float(row.get("news_momentum_score") or row.get("news_risk_level"), 0)
    return _bucket_num(score, [(1, "news_low"), (2, "news_mid"), (4, "news_high")], "news_none")


def _aggressive_bucket(row: dict[str, Any]) -> str:
    if not _has_value(row, "aggressive_score"):
        return "agg_unknown"
    score = _safe_float(row.get("aggressive_score"), 0)
    return _bucket_num(score, [(50, "agg_<50"), (70, "agg_50_69"), (80, "agg_70_79")], "agg_80+")


def build_condition_bucket(row: dict[str, Any]) -> dict[str, Any]:
    sector = _safe_str(row.get("sector") or row.get("theme") or "unknown") or "unknown"
    entry_position = _safe_str(row.get("entry_position_type") or "unknown") or "unknown"
    chart_state = _safe_str(row.get("daily_setup") or row.get("weekly_trend") or entry_position) or "unknown"
    market_state = _safe_str(
        row.get("strategy_mode") or row.get("market_regime") or row.get("market_risk_level") or "unknown"
    ) or "unknown"
    bucket = {
        "score_bucket": _score_bucket(row),
        "rr_bucket": _rr_bucket(row),
        "entry_gap_bucket": _entry_gap_bucket(row),
        "sector": sector,
        "chart_state": chart_state,
        "news_bucket": _news_bucket(row),
        "market_state": market_state,
        "entry_position_type": entry_position,
        "aggressive_bucket": _aggressive_bucket(row),
    }
    parts = [
        bucket["score_bucket"],
        bucket["rr_bucket"],
        bucket["entry_gap_bucket"],
        f"sector={sector}",
        f"chart={chart_state}",
        bucket["news_bucket"],
        f"market={market_state}",
        f"entry={entry_position}",
        bucket["aggressive_bucket"],
    ]
    bucket["condition_key"] = "|".join(parts)
    return bucket


def _reviewed_frame(review_df: pd.DataFrame) -> pd.DataFrame:
    if review_df is None or review_df.empty:
        return pd.DataFrame()
    out = review_df.copy()
    if "prediction_result" in out.columns:
        result = out["prediction_result"].astype(str)
        out = out[result.isin(REVIEWED_RESULTS)].copy()
    else:
        out = out.iloc[0:0].copy()
    return out


def _rate(series: pd.Series) -> float:
    if len(series) == 0:
        return 0.0
    return round(float(series.mean()) * 100.0, 2)


def _num_col(df: pd.DataFrame, names: list[str], default: float = 0.0) -> pd.Series:
    for name in names:
        if name in df.columns:
            return df[name].apply(lambda x: _safe_float(x, default))
    return pd.Series(default, index=df.index, dtype=float)


def _bool_col(df: pd.DataFrame, names: list[str], fallback: pd.Series | None = None) -> pd.Series:
    for name in names:
        if name in df.columns:
            return df[name].apply(lambda x: _safe_bool(x, False)).astype(bool)
    if fallback is not None:
        return fallback.astype(bool)
    return pd.Series(False, index=df.index, dtype=bool)


def summarize_historical_pattern_performance(review_df: pd.DataFrame) -> pd.DataFrame:
    reviewed = _reviewed_frame(review_df)
    columns = [
        "condition_key",
        "sample_count",
        "avg_return_1d",
        "avg_return_3d",
        "avg_return_5d",
        "avg_return_10d",
        "tp1_hit_rate_5d",
        "stop_hit_rate_5d",
        "tp_first_rate",
        "stop_first_rate",
        "market_outperform_rate_5d",
        "sector_outperform_rate_5d",
        "expected_return_5d",
    ]
    if reviewed.empty:
        return pd.DataFrame(columns=columns)

    bucket_df = pd.DataFrame([build_condition_bucket(row) for row in reviewed.to_dict(orient="records")], index=reviewed.index)
    work = pd.concat([reviewed, bucket_df], axis=1)
    ret_1d = _num_col(work, ["return_1d", "actual_return_1d", "realized_return_1d"], 0)
    ret_3d = _num_col(work, ["return_3d", "actual_return_3d", "realized_return_3d"], 0)
    ret_5d = _num_col(work, ["return_5d", "actual_return_5d", "realized_return_5d", "max_profit_pct"], 0)
    ret_10d = _num_col(work, ["return_10d", "actual_return_10d", "realized_return_10d"], 0)
    drawdown = _num_col(work, ["max_drawdown_pct", "drawdown_5d", "actual_drawdown_5d"], 0)
    market_excess = _num_col(work, ["market_excess_return_5d", "market_outperform_5d"], 0)
    sector_excess = _num_col(work, ["sector_excess_return_5d", "sector_outperform_5d"], 0)
    tp_hit = _bool_col(work, ["tp1_hit_5d", "target_hit_5d"], ret_5d >= _num_col(work, ["tp1_return_pct"], 3))
    stop_hit = _bool_col(work, ["stop_hit_5d"], drawdown <= -abs(_num_col(work, ["stop_loss_pct"], 3)))
    tp_first = _bool_col(work, ["tp_first", "tp_first_5d"], tp_hit & ~stop_hit)
    stop_first = _bool_col(work, ["stop_first", "stop_first_5d"], stop_hit & ~tp_hit)

    work["_ret_1d"] = ret_1d
    work["_ret_3d"] = ret_3d
    work["_ret_5d"] = ret_5d
    work["_ret_10d"] = ret_10d
    work["_tp_hit"] = tp_hit
    work["_stop_hit"] = stop_hit
    work["_tp_first"] = tp_first
    work["_stop_first"] = stop_first
    work["_market_out"] = market_excess > 0
    work["_sector_out"] = sector_excess > 0

    rows: list[dict[str, Any]] = []
    for condition_key, group in work.groupby("condition_key"):
        rows.append(
            {
                "condition_key": condition_key,
                "sample_count": int(len(group)),
                "avg_return_1d": round(float(group["_ret_1d"].mean()), 4),
                "avg_return_3d": round(float(group["_ret_3d"].mean()), 4),
                "avg_return_5d": round(float(group["_ret_5d"].mean()), 4),
                "avg_return_10d": round(float(group["_ret_10d"].mean()), 4),
                "tp1_hit_rate_5d": _rate(group["_tp_hit"]),
                "stop_hit_rate_5d": _rate(group["_stop_hit"]),
                "tp_first_rate": _rate(group["_tp_first"]),
                "stop_first_rate": _rate(group["_stop_first"]),
                "market_outperform_rate_5d": _rate(group["_market_out"]),
                "sector_outperform_rate_5d": _rate(group["_sector_out"]),
                "expected_return_5d": round(float(group["_ret_5d"].mean()), 4),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(["sample_count", "expected_return_5d"], ascending=[False, False])


def generate_weight_adjustment_suggestions(stats_df: pd.DataFrame) -> list[dict[str, Any]]:
    if stats_df is None or stats_df.empty:
        return []
    suggestions: list[dict[str, Any]] = []
    for _, row in stats_df.iterrows():
        sample_count = int(_safe_float(row.get("sample_count"), 0))
        expected = _safe_float(row.get("expected_return_5d"), 0)
        stop_rate = _safe_float(row.get("stop_hit_rate_5d"), 0)
        tp_rate = _safe_float(row.get("tp1_hit_rate_5d"), 0)
        condition_key = _safe_str(row.get("condition_key"))
        if sample_count < 20:
            if abs(expected) >= 3 or max(stop_rate, tp_rate) >= 70:
                suggestions.append(
                    {
                        "condition_key": condition_key,
                        "sample_count": sample_count,
                        "suggestion_type": "observe_only",
                        "strength": "weak",
                        "reason": "표본 20건 미만이라 강한 가중치 제안은 보류",
                    }
                )
            continue
        if expected <= -1.0 or stop_rate >= 60:
            suggestions.append(
                {
                    "condition_key": condition_key,
                    "sample_count": sample_count,
                    "suggestion_type": "penalty_candidate",
                    "strength": "medium" if expected > -3 and stop_rate < 75 else "strong",
                    "reason": f"5일 기대값 {expected:.2f}, 손절률 {stop_rate:.1f}%로 감점 검토",
                }
            )
        elif expected >= 1.0 and tp_rate >= 50:
            suggestions.append(
                {
                    "condition_key": condition_key,
                    "sample_count": sample_count,
                    "suggestion_type": "bonus_candidate",
                    "strength": "medium",
                    "reason": f"5일 기대값 {expected:.2f}, 목표가 도달률 {tp_rate:.1f}%로 가점 검토",
                }
            )
    return suggestions


def save_historical_pattern_reports(review_df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    stats = summarize_historical_pattern_performance(review_df)
    suggestions = generate_weight_adjustment_suggestions(stats)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stats.to_csv(HISTORICAL_PATTERN_STATS_CSV, index=False, encoding="utf-8-sig")
    WEIGHT_ADJUSTMENT_SUGGESTIONS_JSON.write_text(
        json.dumps(suggestions, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return stats, suggestions


def apply_historical_pattern_stats_to_candidates(candidate_df: pd.DataFrame, stats_df: pd.DataFrame) -> pd.DataFrame:
    if candidate_df is None:
        return pd.DataFrame()
    out = candidate_df.copy()
    add_cols = [
        "condition_key",
        "historical_condition_key",
        "historical_sample_count",
        "historical_tp1_hit_rate_5d",
        "historical_stop_hit_rate_5d",
        "historical_expected_return_5d",
        "historical_pattern_note",
    ]
    if out.empty:
        for col in add_cols:
            if col not in out.columns:
                out[col] = []
        return out
    buckets = pd.DataFrame([build_condition_bucket(row) for row in out.to_dict(orient="records")], index=out.index)
    out["condition_key"] = buckets["condition_key"].values
    out["historical_condition_key"] = buckets["condition_key"].values
    if stats_df is None or stats_df.empty:
        out["historical_sample_count"] = 0
        out["historical_tp1_hit_rate_5d"] = 0.0
        out["historical_stop_hit_rate_5d"] = 0.0
        out["historical_expected_return_5d"] = 0.0
        out["historical_pattern_note"] = DEFAULT_INSUFFICIENT_NOTE
        return out
    needed = [
        "condition_key",
        "sample_count",
        "tp1_hit_rate_5d",
        "stop_hit_rate_5d",
        "expected_return_5d",
    ]
    stats_subset = stats_df[[c for c in needed if c in stats_df.columns]].copy()
    stats_subset = stats_subset.rename(
        columns={
            "sample_count": "_hist_sample_count",
            "tp1_hit_rate_5d": "_hist_tp1_hit_rate_5d",
            "stop_hit_rate_5d": "_hist_stop_hit_rate_5d",
            "expected_return_5d": "_hist_expected_return_5d",
        }
    )
    merged = out.merge(stats_subset, on="condition_key", how="left")
    merged["historical_sample_count"] = pd.to_numeric(merged.get("_hist_sample_count"), errors="coerce").fillna(0).astype(int)
    merged["historical_tp1_hit_rate_5d"] = pd.to_numeric(merged.get("_hist_tp1_hit_rate_5d"), errors="coerce").fillna(0.0)
    merged["historical_stop_hit_rate_5d"] = pd.to_numeric(merged.get("_hist_stop_hit_rate_5d"), errors="coerce").fillna(0.0)
    merged["historical_expected_return_5d"] = pd.to_numeric(merged.get("_hist_expected_return_5d"), errors="coerce").fillna(0.0)
    if "historical_condition_key" not in merged.columns:
        merged["historical_condition_key"] = merged["condition_key"]
    else:
        merged["historical_condition_key"] = merged["historical_condition_key"].fillna(merged["condition_key"])
    merged["historical_pattern_note"] = merged.apply(
        lambda r: (
            DEFAULT_INSUFFICIENT_NOTE
            if int(r.get("historical_sample_count", 0)) < 5
            else f"유사조건 {int(r.get('historical_sample_count', 0))}건: 5일 목표 {float(r.get('historical_tp1_hit_rate_5d', 0)):.1f}%, 손절 {float(r.get('historical_stop_hit_rate_5d', 0)):.1f}%, 기대값 {float(r.get('historical_expected_return_5d', 0)):.2f}"
        ),
        axis=1,
    )
    merged["historical_pattern_note"] = (
        merged["historical_pattern_note"]
        .fillna(DEFAULT_INSUFFICIENT_NOTE)
        .astype(str)
        .replace({"": DEFAULT_INSUFFICIENT_NOTE, "nan": DEFAULT_INSUFFICIENT_NOTE, "None": DEFAULT_INSUFFICIENT_NOTE})
    )
    zero_sample = pd.to_numeric(merged["historical_sample_count"], errors="coerce").fillna(0).eq(0)
    merged.loc[zero_sample, "historical_pattern_note"] = DEFAULT_INSUFFICIENT_NOTE
    for col in ["_hist_sample_count", "_hist_tp1_hit_rate_5d", "_hist_stop_hit_rate_5d", "_hist_expected_return_5d"]:
        if col in merged.columns:
            merged = merged.drop(columns=[col])
    return merged
