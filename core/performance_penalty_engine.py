from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd


REVIEWED_RESULTS = {"success", "fail", "neutral"}
FAIL_PATTERNS = (
    "\uacfc\uc5f4 \ucd94\uaca9",
    "\uc190\uc775\ube44 \ubd80\uc871",
    "\ub274\uc2a4 \uc120\ubc18\uc601",
)
PRACTICAL_GRADE_COL = "\uc2e4\uc804\ub4f1\uae09"
PRACTICAL_SCORE_COL = "\uc2e4\uc804\ub4f1\uae09\uc810\uc218"

CONDITION_DEFS: dict[str, dict[str, Any]] = {
    "overheat_high": {
        "label": "\uacfc\uc5f4 \ub192\uc74c/\ub9e4\uc6b0 \ub192\uc74c",
        "column": "overheat_level",
        "values": {"\ub192\uc74c", "\ub9e4\uc6b0 \ub192\uc74c"},
        "base_penalty": -10,
        "severe_penalty": -20,
    },
    "rr_weak": {
        "label": "\uc190\uc775\ube44 \ubd88\ub7c9/\ubd80\uc871",
        "column": "rr_level",
        "values": {"\ubd88\ub7c9", "\ubd80\uc871"},
        "base_penalty": -10,
        "severe_penalty": -20,
    },
    "news_grade_c": {
        "label": "\ub274\uc2a4 \ub4f1\uae09 C",
        "column": "news_grade",
        "values": {"C"},
        "base_penalty": -10,
        "severe_penalty": -10,
    },
    "market_risk_high": {
        "label": "\uc2dc\uc7a5 \uc704\ud5d8 \ub192\uc74c/\ub9e4\uc6b0 \ub192\uc74c",
        "column": "market_risk_level",
        "values": {"\ub192\uc74c", "\ub9e4\uc6b0 \ub192\uc74c"},
        "base_penalty": -10,
        "severe_penalty": -20,
    },
    "chase_risk": {
        "label": "\ucd94\uaca9 \uc704\ud5d8",
        "column": "chase_risk",
        "truthy": True,
        "base_penalty": -10,
        "severe_penalty": -10,
    },
    "sell_the_news": {
        "label": "\ub274\uc2a4 \uc120\ubc18\uc601 \uc704\ud5d8",
        "column": "sell_the_news_risk",
        "truthy": True,
        "base_penalty": -10,
        "severe_penalty": -10,
    },
}


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
            value = value.replace(",", "").replace("%", "").strip()
        return float(value)
    except Exception:
        return default


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_str(value).lower()
    return text in {"1", "1.0", "true", "t", "yes", "y", "on"}


def _reviewed_rows(review_df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    df = review_df.copy()
    if "prediction_result" not in df.columns:
        df["prediction_result"] = ""

    result = df["prediction_result"].astype(str).str.strip().str.lower()
    reviewed = df[result.isin(REVIEWED_RESULTS)].copy()
    if "target_date" in reviewed.columns:
        reviewed["_sort_dt"] = pd.to_datetime(reviewed["target_date"], errors="coerce")
        reviewed = reviewed.sort_values("_sort_dt", ascending=False, na_position="last")
    elif "created_at" in reviewed.columns:
        reviewed["_sort_dt"] = pd.to_datetime(reviewed["created_at"], errors="coerce")
        reviewed = reviewed.sort_values("_sort_dt", ascending=False, na_position="last")
    return reviewed.head(max(0, int(lookback)))


def _is_fail_frame(df: pd.DataFrame) -> pd.Series:
    result = df.get("prediction_result", pd.Series("", index=df.index)).astype(str).str.strip().str.lower()
    decision_success = df.get("decision_success", pd.Series("", index=df.index)).astype(str).str.strip().str.lower()
    return result.eq("fail") | decision_success.isin({"false", "0", "0.0"})


def _condition_mask(df: pd.DataFrame, spec: dict[str, Any]) -> pd.Series:
    col = str(spec.get("column", ""))
    if col not in df.columns:
        return pd.Series(False, index=df.index)
    if spec.get("truthy"):
        return df[col].map(_safe_bool)
    values = {str(v) for v in spec.get("values", set())}
    return df[col].astype(str).str.strip().isin(values)


def build_failure_profile(review_df: pd.DataFrame, lookback: int = 120) -> dict[str, Any]:
    if review_df is None or review_df.empty:
        return {
            "total_reviewed": 0,
            "fail_rate": 0.0,
            "failure_reason_counts": {},
            "failure_reason_fail_rates": {},
            "high_risk_conditions": {},
            "penalty_notes": [],
        }

    reviewed = _reviewed_rows(review_df, lookback)
    fail_mask = _is_fail_frame(reviewed)
    fail_count = int(fail_mask.sum())
    total = int(len(reviewed))
    fail_rate = round(fail_count / total, 4) if total else 0.0

    failure_reason_counts: dict[str, int] = {}
    failure_reason_fail_rates: dict[str, dict[str, Any]] = {}
    if total and "failure_reason" in reviewed.columns:
        fail_reasons = reviewed.loc[fail_mask, "failure_reason"].map(_safe_str)
        failure_reason_counts = dict(Counter(r for r in fail_reasons if r and r.lower() not in {"nan", "none"}))
        for reason, count in failure_reason_counts.items():
            reason_mask = reviewed["failure_reason"].astype(str).str.contains(reason, regex=False, na=False)
            reason_total = int(reason_mask.sum())
            reason_fail = int((reason_mask & fail_mask).sum())
            failure_reason_fail_rates[reason] = {
                "reviewed": reason_total,
                "fail_count": reason_fail,
                "fail_rate": round(reason_fail / reason_total, 4) if reason_total else 0.0,
            }

    high_risk_conditions: dict[str, dict[str, Any]] = {}
    penalty_notes: list[str] = []
    for key, spec in CONDITION_DEFS.items():
        mask = _condition_mask(reviewed, spec)
        cond_total = int(mask.sum())
        cond_fail = int((mask & fail_mask).sum())
        cond_rate = round(cond_fail / cond_total, 4) if cond_total else 0.0
        strong = bool(cond_total >= 5 and cond_rate >= 0.5)
        high_risk_conditions[key] = {
            "label": spec["label"],
            "reviewed": cond_total,
            "fail_count": cond_fail,
            "fail_rate": cond_rate,
            "strong_penalty": strong,
        }
        if strong:
            penalty_notes.append(f"{spec['label']} fail_rate {cond_rate:.0%} ({cond_fail}/{cond_total})")

    for reason in FAIL_PATTERNS:
        stat = failure_reason_fail_rates.get(reason)
        if stat and stat["reviewed"] >= 5 and stat["fail_rate"] >= 0.5:
            penalty_notes.append(f"{reason} repeated fail_rate {stat['fail_rate']:.0%}")

    return {
        "total_reviewed": total,
        "fail_rate": fail_rate,
        "failure_reason_counts": failure_reason_counts,
        "failure_reason_fail_rates": failure_reason_fail_rates,
        "high_risk_conditions": high_risk_conditions,
        "penalty_notes": penalty_notes,
    }


def _condition_hit(row: dict[str, Any], spec: dict[str, Any]) -> bool:
    value = row.get(spec.get("column", ""))
    if spec.get("truthy"):
        return _safe_bool(value)
    values = {str(v) for v in spec.get("values", set())}
    return _safe_str(value) in values


def calculate_performance_penalty(row: dict[str, Any], failure_profile: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    penalty = 0
    high_risk = failure_profile.get("high_risk_conditions", {}) if isinstance(failure_profile, dict) else {}

    for key, spec in CONDITION_DEFS.items():
        stat = high_risk.get(key, {})
        if not stat.get("strong_penalty") or not _condition_hit(row, spec):
            continue
        rate = _safe_float(stat.get("fail_rate"), 0.0)
        delta = int(spec.get("severe_penalty", -10) if rate >= 0.7 else spec.get("base_penalty", -10))
        penalty += delta
        reasons.append(f"{spec['label']} recent fail_rate {rate:.0%}: {delta}")

    failure_reason = _safe_str(row.get("failure_reason"))
    reason_stats = failure_profile.get("failure_reason_fail_rates", {}) if isinstance(failure_profile, dict) else {}
    for pattern in FAIL_PATTERNS:
        stat = reason_stats.get(pattern, {})
        repeated = bool(stat.get("reviewed", 0) >= 5 and stat.get("fail_rate", 0) >= 0.5)
        if repeated and pattern in failure_reason:
            penalty -= 10
            reasons.append(f"{pattern} repeated failure pattern: -10")

    penalty = max(-40, min(0, int(penalty)))
    return {
        "performance_penalty_score": penalty,
        "performance_penalty_reasons": reasons,
        "recent_fail_pattern_hit": bool(reasons),
    }


def _base_score_series(out: pd.DataFrame) -> pd.Series:
    if PRACTICAL_SCORE_COL in out.columns:
        base = pd.to_numeric(out[PRACTICAL_SCORE_COL], errors="coerce")
    else:
        base = pd.Series(float("nan"), index=out.index, dtype="float64")
    score = pd.to_numeric(out.get("score", pd.Series(0, index=out.index)), errors="coerce")
    return base.where(base.notna(), score).fillna(0).astype(float)


def apply_performance_penalty_to_candidates(candidate_df: pd.DataFrame, review_df: pd.DataFrame) -> pd.DataFrame:
    if candidate_df is None:
        return pd.DataFrame()

    out = candidate_df.copy()
    if out.empty:
        for col in [
            "performance_penalty_score",
            "performance_penalty_reasons",
            "recent_fail_pattern_hit",
            "adjusted_score_after_review",
        ]:
            if col not in out.columns:
                out[col] = []
        return out

    profile = build_failure_profile(review_df)
    penalties = [calculate_performance_penalty(row, profile) for row in out.to_dict(orient="records")]
    penalty_df = pd.DataFrame(penalties, index=out.index)
    out["performance_penalty_score"] = pd.to_numeric(
        penalty_df.get("performance_penalty_score", pd.Series(0, index=out.index)),
        errors="coerce",
    ).fillna(0).astype(int)
    out["performance_penalty_reasons"] = penalty_df.get(
        "performance_penalty_reasons",
        pd.Series([[] for _ in range(len(out))], index=out.index),
    ).apply(lambda x: " / ".join(map(str, x)) if isinstance(x, list) else _safe_str(x))
    out["recent_fail_pattern_hit"] = penalty_df.get(
        "recent_fail_pattern_hit",
        pd.Series(False, index=out.index),
    ).map(_safe_bool)

    out["adjusted_score_after_review"] = (
        _base_score_series(out) + out["performance_penalty_score"]
    ).clip(lower=0, upper=100).round(2)

    if "grade" in out.columns:
        grade = out["grade"].astype(str).str.upper()
        hit = out["recent_fail_pattern_hit"].map(_safe_bool)
        penalty = pd.to_numeric(out["performance_penalty_score"], errors="coerce").fillna(0)
        a_downgrade = grade.eq("A") & hit & penalty.le(-15)
        b_exclude = grade.eq("B") & penalty.le(-25)
        out.loc[a_downgrade, "grade"] = "B"
        out.loc[a_downgrade, "grade_label"] = "\uc131\uc7a5 \uad00\ucc30 \ud6c4\ubcf4"
        out.loc[b_exclude, "grade"] = "C"
        out.loc[b_exclude, "grade_label"] = "C\uae09 \uc81c\uc678"

    if PRACTICAL_GRADE_COL in out.columns and "grade" in out.columns:
        out[PRACTICAL_GRADE_COL] = out["grade"].map(
            lambda x: "A\uae09" if str(x).upper() == "A" else "B\uae09" if str(x).upper() == "B" else "C/\uc81c\uc678"
        )
    if PRACTICAL_SCORE_COL in out.columns:
        out[PRACTICAL_SCORE_COL] = out["adjusted_score_after_review"]

    return out
