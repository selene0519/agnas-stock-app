from __future__ import annotations

from typing import Any

import pandas as pd


GRADE_COLUMNS = [
    "original_grade",
    "final_grade",
    "grade_change_reason",
    "regime_downgrade_reason",
    "review_penalty_reason",
    "hard_block_reason",
]


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_str(value).lower()
    if text in {"1", "1.0", "true", "t", "yes", "y", "on"}:
        return True
    if text in {"0", "0.0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _append_reason(parts: list[str], value: str) -> None:
    value = _safe_str(value)
    if value and value not in parts:
        parts.append(value)


def ensure_grade_change_columns(candidate_df: pd.DataFrame) -> pd.DataFrame:
    out = candidate_df.copy() if candidate_df is not None else pd.DataFrame()
    if "grade" not in out.columns:
        out["grade"] = ""
    if "original_grade" not in out.columns:
        out["original_grade"] = out["grade"].astype(str)
    out["final_grade"] = out.get("grade", pd.Series("", index=out.index)).astype(str)
    if "grade_change_reason" not in out.columns:
        out["grade_change_reason"] = ""
    original = out.get("original_grade", pd.Series("", index=out.index)).astype(str)
    final = out["final_grade"].astype(str)
    changed = original.ne(final)
    out.loc[changed, "grade_change_reason"] = original[changed] + " -> " + final[changed]
    for col in ["regime_downgrade_reason", "review_penalty_reason", "hard_block_reason"]:
        if col not in out.columns:
            out[col] = ""
    return out


def build_hard_block_reason(row: dict[str, Any]) -> str:
    parts: list[str] = []
    if "위험" in _safe_str(row.get("strategy_mode")):
        _append_reason(parts, "위험장")
    if _safe_str(row.get("risk_final_decision")) == "손절 우선":
        _append_reason(parts, "손절 우선")
    if not _safe_bool(row.get("rr_pass"), True):
        _append_reason(parts, "rr_pass=False")
    if _safe_str(row.get("market_risk_level")) == "매우 높음":
        _append_reason(parts, "시장 위험 매우 높음")
    if _safe_str(row.get("overheat_level")) == "매우 높음":
        _append_reason(parts, "과열 매우 높음")
    if _safe_str(row.get("strategy_adjusted_grade")) == "금지":
        _append_reason(parts, "전략 금지")
    if _safe_bool(row.get("new_buy_blocked"), False):
        _append_reason(parts, "신규매수 제한")
    return " / ".join(parts)


def apply_hard_block_reasons(candidate_df: pd.DataFrame) -> pd.DataFrame:
    out = ensure_grade_change_columns(candidate_df)
    if out.empty:
        if "hard_block_reason" not in out.columns:
            out["hard_block_reason"] = []
        return out
    out["hard_block_reason"] = [build_hard_block_reason(row) for row in out.to_dict(orient="records")]
    return out


def classify_final_candidate(row: dict[str, Any]) -> str:
    grade = _safe_str(row.get("grade") or row.get("final_grade")).upper()
    strategy_grade = _safe_str(row.get("strategy_adjusted_grade")).upper()
    strong_watch = _safe_bool(row.get("strong_watch_candidate"), False) or _safe_bool(row.get("weak_market_leader_flag"), False)
    trade_allowed = _safe_bool(row.get("strategy_trade_allowed"), grade in {"A", "B"})
    hard_block = bool(build_hard_block_reason(row))
    if not trade_allowed or strategy_grade == "금지" or hard_block:
        return "FORBIDDEN"
    if grade == "A" or strategy_grade == "A":
        return "A_TOP"
    if strong_watch:
        return "STRONG_WATCH"
    if grade == "B" or strategy_grade == "B":
        return "B_WATCH"
    return "C_EXCLUDED"


def apply_final_candidate_bucket(candidate_df: pd.DataFrame) -> pd.DataFrame:
    out = apply_hard_block_reasons(candidate_df)
    if out.empty:
        if "final_candidate_bucket" not in out.columns:
            out["final_candidate_bucket"] = []
        return out
    out["final_candidate_bucket"] = [classify_final_candidate(row) for row in out.to_dict(orient="records")]
    return out
