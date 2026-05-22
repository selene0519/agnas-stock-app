from __future__ import annotations

from typing import Any

import pandas as pd


MODE_UP = "\uc0c1\uc2b9\uc7a5"
MODE_BOX = "\ubc15\uc2a4\uc7a5"
MODE_DOWN = "\ud558\ub77d\uc7a5"
MODE_RISK = "\uc704\ud5d8\uc7a5"
GRADE_FORBIDDEN = "\uae08\uc9c0"
DECISION_PULLBACK = "\ub20c\ub9bc\ubaa9 \ub9e4\uc218 \uac00\ub2a5"
DECISION_STOP_FIRST = "\uc190\uc808 \uc6b0\uc120"
RISK_VERY_HIGH = "\ub9e4\uc6b0 \ub192\uc74c"
RISK_HIGH = "\ub192\uc74c"


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


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = _safe_str(value).lower()
    if text in {"1", "1.0", "true", "t", "yes", "y", "on"}:
        return True
    if text in {"0", "0.0", "false", "f", "no", "n", "off"}:
        return False
    return default


def _clip(value: float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, round(value))))


def _base_position(mode: str, grade: str) -> int:
    if mode == MODE_RISK or grade == GRADE_FORBIDDEN:
        return 0
    if grade == "A":
        if mode == MODE_UP:
            return 80
        if mode == MODE_BOX:
            return 60
        if mode == MODE_DOWN:
            return 35
    if grade == "B":
        return 35 if mode in {MODE_UP, MODE_BOX} else 20
    if grade == "C":
        return 10
    return 0


def _risk_level(size: int) -> str:
    if size <= 10:
        return "\ub9e4\uc6b0 \ubcf4\uc218\uc801"
    if size <= 35:
        return "\ubcf4\uc218\uc801"
    if size <= 65:
        return "\uc911\ub9bd"
    return "\uacf5\uaca9\uc801"


def _action(size: int, allowed: bool) -> str:
    if not allowed or size <= 0:
        return "\uc2e0\uaddc\ub9e4\uc218 \uae08\uc9c0"
    if size <= 20:
        return "\uad00\ub9dd \uc6b0\uc704"
    if size <= 50:
        return "\uc18c\uc561 \uc811\uadfc"
    return "\ub9e4\uc218 \uac00\ub2a5"


def calculate_position_sizing(row: dict[str, Any]) -> dict[str, Any]:
    mode = _safe_str(row.get("strategy_mode"))
    grade = _safe_str(row.get("strategy_adjusted_grade") or row.get("grade")).upper()
    allowed = _safe_bool(row.get("strategy_trade_allowed"), False)
    decision = _safe_str(row.get("risk_final_decision"))
    rr = _safe_float(row.get("rr"), 0)
    rr_pass = _safe_bool(row.get("rr_pass"), True)
    confidence = _safe_float(row.get("risk_confidence_score"), 0)
    overheat = _safe_str(row.get("overheat_level"))
    market_risk = _safe_str(row.get("market_risk_level"))
    penalty = _safe_float(row.get("performance_penalty_score"), 0)

    reasons: list[str] = []
    warnings: list[str] = []
    force_zero = False

    if not allowed:
        force_zero = True
        warnings.append("strategy_trade_allowed=False")
    if mode == MODE_RISK:
        force_zero = True
        warnings.append("\uc704\ud5d8\uc7a5")
    if market_risk == RISK_VERY_HIGH:
        force_zero = True
        warnings.append("\uc2dc\uc7a5 \uc704\ud5d8 \ub9e4\uc6b0 \ub192\uc74c")
    if rr_pass is False:
        force_zero = True
        warnings.append("rr_pass=False")
    if overheat == RISK_VERY_HIGH:
        force_zero = True
        warnings.append("\uacfc\uc5f4 \ub9e4\uc6b0 \ub192\uc74c")
    if decision == DECISION_STOP_FIRST:
        force_zero = True
        warnings.append("\uc190\uc808 \uc6b0\uc120")

    if force_zero:
        return {
            "position_size_pct": 0,
            "position_risk_level": "\ub9e4\uc6b0 \ubcf4\uc218\uc801",
            "position_action": "\uc2e0\uaddc\ub9e4\uc218 \uae08\uc9c0",
            "position_reasons": reasons or ["\uac15\uc81c 0% \uc870\uac74"],
            "position_warnings": list(dict.fromkeys(warnings)),
        }

    size = _base_position(mode, grade)
    reasons.append(f"{mode or '-'} {grade or '-'} \uae30\uc900 {size}%")

    if penalty <= -15:
        size -= 15
        warnings.append("\ubcf5\uae30 \uc2e4\ud328 \ud328\ud134 \uac10\uc810")
    if _safe_bool(row.get("chase_risk"), False):
        size -= 10
        warnings.append("\ucd94\uaca9 \uc704\ud5d8")
    if _safe_bool(row.get("sell_the_news_risk"), False):
        size -= 10
        warnings.append("\ub274\uc2a4 \uc120\ubc18\uc601 \uc704\ud5d8")
    if rr < 2.0:
        size -= 10
        warnings.append("rr < 2.0")
    if overheat == RISK_HIGH:
        size -= 10
        warnings.append("\uacfc\uc5f4 \ub192\uc74c")

    if confidence >= 80:
        size += 5
        reasons.append("\uc2e0\ub8b0\ub3c4 80 \uc774\uc0c1")
    if rr >= 3.0:
        size += 8
        reasons.append("rr >= 3.0")
    if decision == DECISION_PULLBACK and mode in {MODE_UP, MODE_BOX}:
        size += 5
        reasons.append("\ub20c\ub9bc\ubaa9 + \uc0c1\uc2b9/\ubc15\uc2a4\uc7a5")

    if grade == "B":
        size = max(20, min(50, size))
    elif grade in {"C", GRADE_FORBIDDEN}:
        size = max(0, min(20, size))
    size = _clip(size)

    return {
        "position_size_pct": size,
        "position_risk_level": _risk_level(size),
        "position_action": _action(size, allowed),
        "position_reasons": list(dict.fromkeys(reasons)),
        "position_warnings": list(dict.fromkeys(warnings)),
    }


def apply_position_sizing(candidate_df: pd.DataFrame) -> pd.DataFrame:
    if candidate_df is None:
        return pd.DataFrame()
    out = candidate_df.copy()
    cols = [
        "position_size_pct",
        "position_risk_level",
        "position_action",
        "position_reasons",
        "position_warnings",
    ]
    if out.empty:
        for col in cols:
            if col not in out.columns:
                out[col] = []
        return out
    result = pd.DataFrame([calculate_position_sizing(row) for row in out.to_dict(orient="records")], index=out.index)
    for col in cols:
        values = result[col]
        if col in {"position_reasons", "position_warnings"}:
            values = values.apply(lambda x: " / ".join(map(str, x)) if isinstance(x, list) else _safe_str(x))
        out[col] = values.values
    return out
