from __future__ import annotations

from typing import Any

import pandas as pd


PRACTICAL_SCORE_COL = "\uc2e4\uc804\ub4f1\uae09\uc810\uc218"

MODE_UP = "\uc0c1\uc2b9\uc7a5"
MODE_BOX = "\ubc15\uc2a4\uc7a5"
MODE_DOWN = "\ud558\ub77d\uc7a5"
MODE_RISK = "\uc704\ud5d8\uc7a5"
GRADE_FORBIDDEN = "\uae08\uc9c0"

DECISION_BREAKOUT = "\ub3cc\ud30c \ud655\uc778 \ud6c4 \uc811\uadfc"
DECISION_PULLBACK = "\ub20c\ub9bc\ubaa9 \ub9e4\uc218 \uac00\ub2a5"
DECISION_STOP_FIRST = "\uc190\uc808 \uc6b0\uc120"
DECISION_WAIT = "\uad00\ub9dd \uc6b0\uc704"

RISK_VERY_HIGH = "\ub9e4\uc6b0 \ub192\uc74c"
RISK_HIGH = "\ub192\uc74c"
RISK_VERY_DANGEROUS = "\ub9e4\uc6b0 \uc704\ud5d8"
RISK_DANGEROUS = "\uc704\ud5d8"
RR_WEAK = "\ubd80\uc871"
RR_BAD = "\ubd88\ub7c9"
NEWS_PREPRICED = "\ub274\uc2a4 \uc120\ubc18\uc601"

MODE_BIAS = {
    MODE_UP: 10,
    MODE_BOX: 0,
    MODE_DOWN: -12,
    MODE_RISK: -25,
}
MODE_ORDER = [MODE_UP, MODE_BOX, MODE_DOWN, MODE_RISK]


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


def _first(row: dict[str, Any], keys: tuple[str, ...], default: Any = "") -> Any:
    for key in keys:
        if key in row and _safe_str(row.get(key)) != "":
            return row.get(key)
    return default


def _more_conservative(mode: str) -> str:
    try:
        return MODE_ORDER[min(len(MODE_ORDER) - 1, MODE_ORDER.index(mode) + 1)]
    except ValueError:
        return MODE_BOX


def _approach_for_mode(mode: str) -> str:
    if mode == MODE_UP:
        return "\ub3cc\ud30c/\ub20c\ub9bc \ubaa8\ub450 \uac00\ub2a5\ud558\ub098 \uacfc\uc5f4 \uc81c\uc678"
    if mode == MODE_BOX:
        return "\ub20c\ub9bc\ubaa9 \uc911\uc2ec, \ub3cc\ud30c\ub294 \ud655\uc778 \ud6c4 \uc811\uadfc"
    if mode == MODE_DOWN:
        return "\uc2e0\uaddc\ub9e4\uc218 \ucd95\uc18c, \uad00\ub9dd \uc6b0\uc704"
    return "\uc2e0\uaddc\ub9e4\uc218 \uae08\uc9c0, \ube44\uc911 \ucd95\uc18c/\uc190\uc808 \uae30\uc900 \uc6b0\uc120"


def detect_strategy_mode(row_or_context: dict[str, Any]) -> dict[str, Any]:
    src = row_or_context or {}
    rules: list[str] = []
    warning = ""

    market_regime = _safe_str(_first(src, ("market_regime", "regime", "\uc2dc\uc7a5\uc0c1\ud0dc")))
    market_risk_level = _safe_str(_first(src, ("market_risk_level", "risk_level", "\uc2dc\uc7a5\uc704\ud5d8")))
    market_score = _safe_float(_first(src, ("market_score", "auto_market_score", "\uc2dc\uc7a5\uc810\uc218"), 0), 0)
    market_risk_score = _safe_float(_first(src, ("market_risk_score", "\uc2dc\uc7a5\uc704\ud5d8\uc810\uc218"), None), float("nan"))
    hardblock = bool(src.get("market_hardblock")) or _safe_str(src.get("hardblock_level")) in {"강함", "매우 강함"}

    if hardblock and _safe_str(src.get("hardblock_level")) == "매우 강함":
        mode = MODE_RISK
        rules.append("\uc704\ud5d8\uc7a5: \uc2dc\uc7a5 \ud558\ub4dc\ube14\ub85d \ub9e4\uc6b0 \uac15\ud568")
    elif hardblock:
        mode = MODE_DOWN
        rules.append("\ud558\ub77d\uc7a5: \uc2dc\uc7a5 \ud558\ub4dc\ube14\ub85d")
    elif market_risk_level in {RISK_VERY_HIGH, RISK_VERY_DANGEROUS}:
        mode = MODE_RISK
        rules.append("\uc704\ud5d8\uc7a5: \uc2dc\uc7a5 \uc704\ud5d8 \ub9e4\uc6b0 \ub192\uc74c")
    elif market_risk_score == market_risk_score and market_risk_score >= 80:
        mode = MODE_RISK
        rules.append("\uc704\ud5d8\uc7a5: \uc2dc\uc7a5 \uc704\ud5d8\uc810\uc218 80 \uc774\uc0c1")
    elif market_risk_score == market_risk_score and market_risk_score >= 70:
        mode = MODE_DOWN
        rules.append("\ud558\ub77d\uc7a5: \uc2dc\uc7a5 \uc704\ud5d8\uc810\uc218 70 \uc774\uc0c1")
    elif "\uc704\ud5d8" in market_regime or "\uae09\ub77d" in market_regime:
        mode = MODE_RISK
        rules.append("\uc704\ud5d8\uc7a5: \uc2dc\uc7a5\uad6d\uba74 \uc704\ud5d8/\uae09\ub77d")
    elif "\ud558\ub77d" in market_regime:
        mode = MODE_DOWN
        rules.append("\ud558\ub77d\uc7a5: \uc2dc\uc7a5\uad6d\uba74 \ud558\ub77d")
    elif market_score <= -4:
        mode = MODE_RISK
        rules.append("\uc704\ud5d8\uc7a5: market_score <= -4")
    elif market_score <= -2:
        mode = MODE_DOWN
        rules.append("\ud558\ub77d\uc7a5: market_score <= -2")
    elif market_score >= 3:
        mode = MODE_UP
        rules.append("\uc0c1\uc2b9\uc7a5: market_score >= 3")
    else:
        mode = MODE_BOX
        rules.append("\ubc15\uc2a4\uc7a5: \uc2dc\uc7a5 \uc810\uc218 \uc911\ub9bd\uad8c")

    usdkrw = _safe_float(_first(src, ("usdkrw_change_pct", "usdkrw_pct"), 0), 0)
    vix = _safe_float(_first(src, ("vix_change_pct", "vix_pct"), 0), 0)
    nasdaq = _safe_float(_first(src, ("nasdaq_change_pct", "nasdaq_pct"), 0), 0)
    kosdaq = _safe_float(_first(src, ("kosdaq_change_pct", "kosdaq_pct"), 0), 0)
    soxx = _safe_float(_first(src, ("soxx_change_pct", "soxx_pct"), 0), 0)
    foreign_flow = _safe_float(_first(src, ("foreign_flow_score",), 0), 0)
    institution_flow = _safe_float(_first(src, ("institution_flow_score",), 0), 0)

    macro_shock = []
    if usdkrw >= 1.2:
        macro_shock.append("usdkrw spike")
    if vix >= 8:
        macro_shock.append("vix spike")
    if nasdaq <= -1.5 or kosdaq <= -2.0 or soxx <= -2.0:
        macro_shock.append("growth index drop")
    if foreign_flow <= -3 and institution_flow <= -3:
        macro_shock.append("flow weak")

    if macro_shock:
        old = mode
        mode = _more_conservative(mode)
        rules.append("\uac70\uc2dc \uc704\ud5d8: " + ", ".join(macro_shock))
        warning = f"{old} -> {mode}: \uac70\uc2dc \uc704\ud5d8 \ubcf4\uc218 \uc870\uc815"

    return {
        "strategy_mode": mode,
        "strategy_bias_score": MODE_BIAS.get(mode, 0),
        "strategy_rules": rules,
        "strategy_warning": warning,
        "today_recommended_action": _approach_for_mode(mode),
    }


def _base_score(row: dict[str, Any]) -> float:
    value = _first(row, ("adjusted_score_after_review", PRACTICAL_SCORE_COL, "score"), 0)
    return _safe_float(value, 0)


def _has_bonus_blocker(row: dict[str, Any]) -> bool:
    return (
        _safe_str(row.get("overheat_level")) in {RISK_HIGH, RISK_VERY_HIGH}
        or _safe_str(row.get("rr_level")) in {RR_BAD, RR_WEAK}
        or _safe_bool(row.get("sell_the_news_risk"), False)
        or NEWS_PREPRICED in _safe_str(row.get("failure_reason"))
    )


def _infer_final_decision(text: Any) -> str:
    raw = _safe_str(text)
    if not raw:
        return ""
    if "\uc190\uc808" in raw:
        return DECISION_STOP_FIRST
    if "\ub3cc\ud30c" in raw:
        return DECISION_BREAKOUT
    if "\ub20c\ub9bc" in raw or "\ub9e4\uc218" in raw or "\uc9c4\uc785" in raw or "\ubc18\ub4f1" in raw:
        return DECISION_PULLBACK
    if "\uad00\ub9dd" in raw or "\ube44\uc911" in raw or "\ucd95\uc18c" in raw or "\uc81c\uc678" in raw:
        return DECISION_WAIT
    return ""


def normalize_risk_final_decision(row: dict[str, Any]) -> str:
    for key in (
        "risk_final_decision",
        "final_decision",
        "final_decision_ko",
        "decision",
        "risk_decision",
        "event_decision",
        "exclude_reason",
        "hard_filter_reason",
    ):
        value = _safe_str(row.get(key))
        if value in {DECISION_BREAKOUT, DECISION_PULLBACK, DECISION_STOP_FIRST, DECISION_WAIT}:
            return value
        inferred = _infer_final_decision(value)
        if inferred:
            return inferred
    return DECISION_WAIT


def _grade_from_score(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 45:
        return "C"
    return GRADE_FORBIDDEN


def _merge_context(row: dict[str, Any], strategy_context: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(row or {})
    if strategy_context:
        for key, value in strategy_context.items():
            if _safe_str(merged.get(key)) == "":
                merged[key] = value
    return merged


def apply_regime_strategy_to_row(
    row: dict[str, Any],
    strategy_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = _merge_context(row, strategy_context)
    detected = detect_strategy_mode(merged)
    mode = detected["strategy_mode"]
    reasons: list[str] = list(detected.get("strategy_rules", []))
    warnings: list[str] = []
    if detected.get("strategy_warning"):
        warnings.append(str(detected["strategy_warning"]))

    base = _base_score(merged)
    adjustment = int(detected.get("strategy_bias_score", 0))
    decision = normalize_risk_final_decision(merged)
    merged["risk_final_decision"] = decision
    force_forbidden = False
    row_grade = _safe_str(merged.get("grade")).upper()

    market_risk_level = _safe_str(merged.get("market_risk_level") or merged.get("risk_level"))
    overheat_level = _safe_str(merged.get("overheat_level"))
    rr_level = _safe_str(merged.get("rr_level"))
    rr_pass = _safe_bool(merged.get("rr_pass"), True)
    sell_the_news = _safe_bool(merged.get("sell_the_news_risk"), False)

    if overheat_level in {RISK_HIGH, RISK_VERY_HIGH}:
        warnings.append("\uacfc\uc5f4 \uad6c\uac04")
    if rr_level in {RR_BAD, RR_WEAK} or rr_pass is False:
        warnings.append("\uc190\uc775\ube44 \ubd80\uc871")
    if market_risk_level in {RISK_HIGH, RISK_VERY_HIGH, RISK_DANGEROUS, RISK_VERY_DANGEROUS}:
        warnings.append("\uc2dc\uc7a5 \uc704\ud5d8 \ub192\uc74c")
    if sell_the_news:
        warnings.append("\ub274\uc2a4 \uc120\ubc18\uc601 \uc704\ud5d8")

    if mode == MODE_UP:
        if not _has_bonus_blocker(merged):
            if decision == DECISION_BREAKOUT:
                adjustment += 5
                reasons.append("\uc0c1\uc2b9\uc7a5: \ub3cc\ud30c \uc804\ub7b5 \ud5c8\uc6a9")
            elif decision == DECISION_PULLBACK:
                adjustment += 3
                reasons.append("\uc0c1\uc2b9\uc7a5: \ub20c\ub9bc\ubaa9 \uc811\uadfc \ud5c8\uc6a9")
            else:
                reasons.append("\uc0c1\uc2b9\uc7a5: \uad00\ub9dd \ud310\ub2e8\uc740 \uac00\uc810 \uc5c6\uc74c")
        else:
            reasons.append("\uc0c1\uc2b9\uc7a5: \uacfc\uc5f4/\uc190\uc775\ube44/\ub274\uc2a4 \uc704\ud5d8\uc73c\ub85c \uac00\uc810 \uc81c\ud55c")
    elif mode == MODE_BOX:
        if decision == DECISION_PULLBACK:
            adjustment += 5
            reasons.append("\ubc15\uc2a4\uc7a5: \ub20c\ub9bc\ubaa9 \uc6b0\ub300")
        elif decision == DECISION_BREAKOUT:
            adjustment -= 3
            reasons.append("\ubc15\uc2a4\uc7a5: \ub3cc\ud30c\ub294 \ud655\uc778 \ud6c4 \uc811\uadfc")
        else:
            reasons.append("\ubc15\uc2a4\uc7a5: \uad00\ub9dd \uc6b0\uc704")
        if _safe_bool(_first(merged, ("near_resistance", "resistance_near", "\uc800\ud56d\uc120\uadfc\ucc98"), False), False):
            adjustment -= 8
            warnings.append("\uc800\ud56d\uc120 \uadfc\ucc98")
    elif mode == MODE_DOWN:
        adjustment -= 10
        reasons.append("\ud558\ub77d\uc7a5: \uc2e0\uaddc\ub9e4\uc218 \uac10\uc810")
        if decision == DECISION_BREAKOUT:
            adjustment -= 12
            reasons.append("\ud558\ub77d\uc7a5: \ub3cc\ud30c \uc811\uadfc \uac15\ud55c \uac10\uc810")
        elif decision == DECISION_PULLBACK:
            adjustment -= 6
            reasons.append("\ud558\ub77d\uc7a5: \ub20c\ub9bc\ubaa9\ub3c4 \ubcf4\uc218 \uc811\uadfc")
        warnings.append("\uad00\ub9dd/\ube44\uc911 \ucd95\uc18c \uc6b0\uc704")
    elif mode == MODE_RISK:
        force_forbidden = True
        reasons.append("\uc704\ud5d8\uc7a5: \uc2e0\uaddc\ub9e4\uc218 \uae08\uc9c0")
        warnings.append(_approach_for_mode(mode))

    if market_risk_level in {RISK_VERY_HIGH, RISK_VERY_DANGEROUS}:
        force_forbidden = True
        warnings.append("\uc2dc\uc7a5 \uc704\ud5d8 \ub9e4\uc6b0 \ub192\uc74c")
    if decision == DECISION_STOP_FIRST:
        force_forbidden = True
        warnings.append("\uc190\uc808 \uc6b0\uc120")
    if rr_pass is False:
        force_forbidden = True
        warnings.append("rr_pass=False")
    if overheat_level == RISK_VERY_HIGH:
        force_forbidden = True
        warnings.append("\uacfc\uc5f4 \ub9e4\uc6b0 \ub192\uc74c")
    if row_grade == "C":
        warnings.append("C/\uc81c\uc678 \ud6c4\ubcf4")

    adjusted = max(0, min(100, int(round(base + adjustment))))
    grade = _grade_from_score(adjusted)
    if mode == MODE_DOWN and grade == "A" and adjusted < 90:
        grade = "B"
        warnings.append("\ud558\ub77d\uc7a5 A\uae09\uc740 90\uc810 \uc774\uc0c1 \ud544\uc694")
    if force_forbidden:
        grade = GRADE_FORBIDDEN
        adjusted = min(adjusted, 44)

    return {
        "strategy_mode": mode,
        "strategy_adjustment_score": int(adjustment),
        "strategy_adjusted_score": int(adjusted),
        "strategy_adjusted_grade": grade,
        "strategy_trade_allowed": bool(grade not in {"C", GRADE_FORBIDDEN} and row_grade != "C"),
        "strategy_reasons": reasons,
        "strategy_warnings": list(dict.fromkeys(warnings)),
    }


def apply_regime_strategy_to_candidates(
    candidate_df: pd.DataFrame,
    market_context: dict[str, Any] | None = None,
) -> pd.DataFrame:
    if candidate_df is None:
        return pd.DataFrame()

    out = candidate_df.copy()
    add_cols = [
        "strategy_mode",
        "strategy_adjustment_score",
        "strategy_adjusted_score",
        "strategy_adjusted_grade",
        "strategy_trade_allowed",
        "strategy_reasons",
        "strategy_warnings",
    ]
    if out.empty:
        for col in add_cols:
            if col not in out.columns:
                out[col] = []
        return out

    out["risk_final_decision"] = [
        normalize_risk_final_decision(row) for row in out.to_dict(orient="records")
    ]

    results = [apply_regime_strategy_to_row(row, market_context) for row in out.to_dict(orient="records")]
    result_df = pd.DataFrame(results, index=out.index)
    for col in add_cols:
        values = result_df[col]
        if col in {"strategy_reasons", "strategy_warnings"}:
            values = values.apply(lambda x: " / ".join(map(str, x)) if isinstance(x, list) else _safe_str(x))
        out[col] = values.values

    mapped = out["strategy_adjusted_grade"].astype(str)
    if "grade" not in out.columns:
        out["grade"] = ""
    current_grade = out["grade"].astype(str).str.upper()
    rank = {"": 3, "A": 3, "B": 2, "C": 1}
    strategy_rank = {"A": 3, "B": 2, "C": 1, GRADE_FORBIDDEN: 0}

    final_grades: list[str] = []
    for cur, strategic in zip(current_grade, mapped):
        cur_rank = rank.get(cur, 1)
        strat_rank = strategy_rank.get(strategic, 1)
        final_rank = min(cur_rank, strat_rank)
        if final_rank >= 3:
            final_grades.append("A")
        elif final_rank == 2:
            final_grades.append("B")
        else:
            final_grades.append("C")
    out["grade"] = final_grades
    if "grade_label" in out.columns:
        out.loc[out["grade"].eq("A"), "grade_label"] = "A\uae09 Top \ud6c4\ubcf4"
        out.loc[out["grade"].eq("B"), "grade_label"] = "\uc131\uc7a5 \uad00\ucc30 \ud6c4\ubcf4"
        out.loc[out["grade"].eq("C") & mapped.eq(GRADE_FORBIDDEN), "grade_label"] = "\ub9e4\uc218 \uae08\uc9c0"
        out.loc[out["grade"].eq("C") & ~mapped.eq(GRADE_FORBIDDEN), "grade_label"] = "C\uae09 \uc81c\uc678"

    final_allowed = out["grade"].isin(["A", "B"]) & mapped.isin(["A", "B"])
    out["strategy_trade_allowed"] = final_allowed.astype(bool)
    if "trade_allowed" in out.columns:
        out["trade_allowed"] = out["strategy_trade_allowed"]
    if PRACTICAL_SCORE_COL in out.columns:
        out[PRACTICAL_SCORE_COL] = out["strategy_adjusted_score"]
    return out
