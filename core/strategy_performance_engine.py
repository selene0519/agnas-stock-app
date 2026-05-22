from __future__ import annotations

from typing import Any

import pandas as pd

from core.review_learning_engine import enrich_predictions_with_review


def _ensure_review(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if "prediction_result" not in df.columns:
        return enrich_predictions_with_review(df)
    return df.copy()


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _rate(success: int, reviewed: int) -> float:
    if reviewed <= 0:
        return 0.0
    return round(success / reviewed * 100.0, 2)


def _mode_reason(series: pd.Series) -> str:
    if series is None or series.empty:
        return ""
    clean = series.astype(str)
    clean = clean[~clean.isin(["", "정상 범위", "중립", "nan", "None"])]
    if clean.empty:
        return ""
    return str(clean.value_counts().index[0])


def summarize_decision_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Summarize review performance by final practical decision."""
    work = _ensure_review(df)
    columns = [
        "risk_final_decision",
        "total_count",
        "reviewed_count",
        "success_count",
        "fail_count",
        "neutral_count",
        "success_rate",
        "avg_max_profit_pct",
        "avg_max_drawdown_pct",
        "most_common_failure_reason",
    ]
    if work.empty:
        return pd.DataFrame(columns=columns)

    if "risk_final_decision" not in work.columns:
        work["risk_final_decision"] = "관망 우위"
    work["risk_final_decision"] = work["risk_final_decision"].fillna("").astype(str).replace("", "관망 우위")
    rows: list[dict[str, Any]] = []
    for decision, group in work.groupby("risk_final_decision", dropna=False):
        result = group.get("prediction_result", pd.Series(index=group.index, dtype=str)).astype(str)
        reviewed = result.ne("not_enough_data") & result.ne("")
        success_count = int(result.eq("success").sum())
        fail_count = int(result.eq("fail").sum())
        neutral_count = int(result.eq("neutral").sum())
        reviewed_count = int(reviewed.sum())
        profit = _num(group.get("max_profit_pct", pd.Series(index=group.index, dtype=float)))
        drawdown = _num(group.get("max_drawdown_pct", pd.Series(index=group.index, dtype=float)))
        rows.append(
            {
                "risk_final_decision": str(decision),
                "total_count": int(len(group)),
                "reviewed_count": reviewed_count,
                "success_count": success_count,
                "fail_count": fail_count,
                "neutral_count": neutral_count,
                "success_rate": _rate(success_count, reviewed_count),
                "avg_max_profit_pct": round(float(profit[reviewed].mean()), 4) if reviewed.any() else "",
                "avg_max_drawdown_pct": round(float(drawdown[reviewed].mean()), 4) if reviewed.any() else "",
                "most_common_failure_reason": _mode_reason(group.get("failure_reason", pd.Series(dtype=str))),
            }
        )
    return pd.DataFrame(rows, columns=columns).sort_values(["success_rate", "reviewed_count"], ascending=[False, False])


def summarize_regime_performance(df: pd.DataFrame) -> pd.DataFrame:
    """Summarize review performance by market/regime/risk feature groups."""
    work = _ensure_review(df)
    columns = [
        "group_type",
        "group_value",
        "count",
        "reviewed_count",
        "success_count",
        "fail_count",
        "success_rate",
        "avg_max_profit_pct",
        "avg_max_drawdown_pct",
    ]
    if work.empty:
        return pd.DataFrame(columns=columns)

    group_cols = ["market_regime", "market_risk_level", "overheat_level", "rr_level", "news_grade"]
    rows: list[dict[str, Any]] = []
    result = work.get("prediction_result", pd.Series(index=work.index, dtype=str)).astype(str)
    for col in group_cols:
        if col not in work.columns:
            continue
        temp = work.copy()
        temp[col] = temp[col].fillna("").astype(str).replace("", "확인 필요")
        for value, group in temp.groupby(col, dropna=False):
            group_result = result.loc[group.index]
            reviewed = group_result.ne("not_enough_data") & group_result.ne("")
            success_count = int(group_result.eq("success").sum())
            fail_count = int(group_result.eq("fail").sum())
            reviewed_count = int(reviewed.sum())
            profit = _num(group.get("max_profit_pct", pd.Series(index=group.index, dtype=float)))
            drawdown = _num(group.get("max_drawdown_pct", pd.Series(index=group.index, dtype=float)))
            rows.append(
                {
                    "group_type": col,
                    "group_value": str(value),
                    "count": int(len(group)),
                    "reviewed_count": reviewed_count,
                    "success_count": success_count,
                    "fail_count": fail_count,
                    "success_rate": _rate(success_count, reviewed_count),
                    "avg_max_profit_pct": round(float(profit[reviewed].mean()), 4) if reviewed.any() else "",
                    "avg_max_drawdown_pct": round(float(drawdown[reviewed].mean()), 4) if reviewed.any() else "",
                }
            )
    return pd.DataFrame(rows, columns=columns).sort_values(["group_type", "reviewed_count"], ascending=[True, False])


def generate_strategy_adjustment_notes(df: pd.DataFrame) -> list[str]:
    """Generate conservative strategy-tuning notes from recent review data."""
    work = _ensure_review(df)
    if work.empty:
        return ["아직 전략 조정에 필요한 복기 데이터가 부족합니다."]

    notes: list[str] = []
    result = work.get("prediction_result", pd.Series(index=work.index, dtype=str)).astype(str)
    reviewed = result.ne("not_enough_data") & result.ne("")
    if int(reviewed.sum()) == 0:
        return ["실제 OHLC가 붙은 복기 완료 건이 아직 부족합니다."]

    if "overheat_level" in work.columns:
        hot = work["overheat_level"].astype(str).isin(["높음", "매우 높음"]) & reviewed
        hot_count = int(hot.sum())
        if hot_count >= 3:
            hot_fail = int((hot & result.eq("fail")).sum())
            if hot_fail / max(hot_count, 1) >= 0.4:
                notes.append("과열 높음 구간의 실패율이 높습니다. chase_risk=True일 때 신규매수를 더 제한하세요.")

    if "risk_final_decision" in work.columns:
        wait = work["risk_final_decision"].astype(str).eq("관망 우위") & reviewed
        wait_success = int((wait & result.eq("success")).sum())
        wait_count = int(wait.sum())
        if wait_count >= 3 and wait_success / max(wait_count, 1) >= 0.5:
            notes.append("관망 우위 판단의 손실 회피율이 높습니다. 시장 위험장에서는 보수 판단을 유지하세요.")

    if "rr_level" in work.columns:
        weak_rr = work["rr_level"].astype(str).isin(["불량", "부족"]) & reviewed
        weak_rr_count = int(weak_rr.sum())
        if weak_rr_count >= 3:
            weak_rr_success = int((weak_rr & result.eq("success")).sum())
            if weak_rr_success / max(weak_rr_count, 1) < 0.4:
                notes.append("rr_level 부족 구간의 성공률이 낮습니다. 최소 손익비 기준을 강화하세요.")

    if "failure_reason" in work.columns:
        common = _mode_reason(work.loc[result.eq("fail"), "failure_reason"])
        if common:
            notes.append(f"최근 실패 이유는 '{common}' 비중이 큽니다. 해당 조건에서는 최종 판단을 한 단계 보수화하세요.")

    if not notes:
        notes.append("현재 누적 복기 기준으로 즉시 강화할 전략 규칙은 뚜렷하지 않습니다. 기존 보수 기준을 유지하세요.")
    return notes
