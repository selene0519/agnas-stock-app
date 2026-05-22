from __future__ import annotations

from typing import Any

import pandas as pd


CONF_LOW = "낮음"
CONF_NORMAL = "보통"
CONF_HIGH = "높음"
LABEL_BUY = "매수 가능 후보"
LABEL_STRONG_WATCH = "강한 관찰 후보"
LABEL_WEAK_LEADER = "시장 약세 속 역행 후보"
LABEL_CHASE_BLOCK = "추격매수 금지 후보"
LABEL_EXCLUDED = "완전 제외 후보"
LABEL_NO_BUY = "신규매수 금지"
LABEL_WAIT = "관망 우위"


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


def _clip_prob(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 2)


def _clip_return(value: float) -> float:
    return round(max(-50.0, min(80.0, float(value))), 2)


def _is_risk_mode(row: dict[str, Any]) -> bool:
    text = " ".join(
        _safe_str(row.get(key))
        for key in ["strategy_mode", "market_risk_level", "market_regime", "hardblock_level"]
    )
    if any(token in text for token in ["위험", "매우 높음", "강함", "risk"]):
        return True
    return _safe_bool(row.get("new_buy_blocked"), False)


def _grade_score(row: dict[str, Any]) -> float:
    grade = _safe_str(row.get("strategy_adjusted_grade") or row.get("grade")).upper()
    if grade == "A":
        return 68.0
    if grade == "B":
        return 58.0
    if grade == "C":
        return 43.0
    if "금지" in grade:
        return 35.0
    return 50.0


def _confidence(row: dict[str, Any], reasons_count: int) -> str:
    filled = 0
    for key in [
        "stock_attractiveness_score",
        "trade_fit_score",
        "entry_position_score",
        "rr",
        "entry",
        "stop",
        "tp1",
        "last_price",
        "risk_confidence_score",
    ]:
        if _safe_str(row.get(key)) not in {"", "-", "nan", "None"}:
            filled += 1
    if filled < 5:
        return CONF_LOW
    if _safe_bool(row.get("actual_review_ready"), False) and _safe_float(row.get("risk_confidence_score"), 0) >= 70 and reasons_count >= 3:
        return CONF_HIGH
    return CONF_NORMAL


def _label(row: dict[str, Any], score: float, prob_stop_5d: float) -> str:
    grade = _safe_str(row.get("strategy_adjusted_grade") or row.get("grade")).upper()
    risk_mode = _is_risk_mode(row)
    chase = _safe_bool(row.get("chase_risk"), False) or "추격" in _safe_str(row.get("entry_position_type"))
    strong_watch = _safe_bool(row.get("strong_watch_candidate"), False)
    weak_leader = _safe_bool(row.get("weak_market_leader_flag"), False)
    trade_allowed = _safe_bool(row.get("strategy_trade_allowed", row.get("trade_allowed")), False)

    if chase:
        return LABEL_CHASE_BLOCK
    if risk_mode and (strong_watch or weak_leader or score >= 62):
        return LABEL_WEAK_LEADER if weak_leader else LABEL_STRONG_WATCH
    if risk_mode:
        return LABEL_NO_BUY
    if grade == "C" or "금지" in grade:
        return LABEL_EXCLUDED
    if strong_watch or weak_leader:
        return LABEL_WEAK_LEADER if weak_leader else LABEL_STRONG_WATCH
    if trade_allowed and score >= 68 and prob_stop_5d < 45:
        return LABEL_BUY
    return LABEL_WAIT


def _final_forecast_warnings(row: dict[str, Any], label: str, warnings: list[str], prob_up_5d: float) -> list[str]:
    out = list(dict.fromkeys([w for w in warnings if _safe_str(w)]))
    trade_allowed = _safe_bool(row.get("strategy_trade_allowed", row.get("trade_allowed")), False)
    blocked_grade = _safe_str(row.get("strategy_adjusted_grade") or row.get("grade"))
    hardblocked = _is_risk_mode(row) or "금지" in blocked_grade or "湲덉?" in blocked_grade or not trade_allowed
    if hardblocked and label not in {LABEL_BUY, LABEL_WAIT}:
        out.append("상승확률은 있으나 시장/전략/하드블록 조건으로 즉시매수 금지")
    if hardblocked and prob_up_5d >= 55:
        out.append("상승확률과 매수허용은 별도 판단: 방어 필터 우선")
    if not out:
        out.append("특이 경고 없음")
    return list(dict.fromkeys(out))


def calculate_multiday_probability(row: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    warnings: list[str] = []

    base = _grade_score(row)
    stock_score = _safe_float(row.get("stock_attractiveness_score"), 50)
    trade_score = _safe_float(row.get("trade_fit_score"), 50)
    entry_score = _safe_float(row.get("entry_position_score"), 50)
    risk_confidence = _safe_float(row.get("risk_confidence_score"), 50)
    rr = _safe_float(row.get("rr"), 0)
    rr_pass = _safe_bool(row.get("rr_pass"), rr >= 1.5)
    aggressive = _safe_float(row.get("aggressive_score"), 0)
    market_rs = _safe_float(row.get("market_relative_strength"), 0)
    sector_rs = _safe_float(row.get("sector_relative_strength"), 0)
    sector_strength = _safe_float(row.get("sector_strength"), 0)
    relative_strength = _safe_float(row.get("relative_strength_score"), 50)
    volume_ratio = _safe_float(row.get("volume_ratio"), 1)
    penalty = _safe_float(row.get("performance_penalty_score"), 0)
    risk_mode = _is_risk_mode(row)
    chase = _safe_bool(row.get("chase_risk"), False) or "추격" in _safe_str(row.get("entry_position_type"))
    overheat = _safe_str(row.get("overheat_level"))
    sell_news = _safe_bool(row.get("sell_the_news_risk"), False)
    market_risk = _safe_str(row.get("market_risk_level"))

    score = base
    score += (stock_score - 50) * 0.18
    score += (trade_score - 50) * 0.22
    score += (entry_score - 50) * 0.16
    score += (risk_confidence - 50) * 0.08

    if rr_pass:
        score += min(max(rr - 1.5, 0), 2.5) * 4
        reasons.append("손익비 통과")
    else:
        score -= 16
        warnings.append("손익비 미통과")
    if rr >= 2:
        reasons.append("손익비 우호")
    if stock_score >= 70:
        reasons.append("종목 매력도 높음")
    if trade_score >= 70:
        reasons.append("가격 적합도 양호")
    if entry_score >= 70:
        reasons.append("진입 위치 양호")

    if aggressive >= 80:
        score += 8
        reasons.append("공격형 상대강도 우수")
    elif aggressive >= 65:
        score += 4
        reasons.append("상대강도 관찰 후보")
    score += max(-8, min(10, market_rs * 2.5))
    score += max(-6, min(8, sector_rs * 2.0))
    if market_rs > 0:
        reasons.append("시장 대비 강함")
    if sector_rs > 0:
        reasons.append("섹터 대비 강함")
    if volume_ratio >= 1.5:
        score += 4
        reasons.append("거래량 증가")
    if relative_strength >= 75 or sector_strength >= 3:
        score += 4
        reasons.append("상대강도/섹터 강도 우호")

    if risk_mode:
        score -= 14
        warnings.append("위험장/하드블록: 즉시매수 확률 하향")
    if market_risk == "매우 높음":
        score -= 10
        warnings.append("시장 위험 매우 높음")
    if overheat in {"높음", "매우 높음"}:
        score -= 8 if overheat == "높음" else 14
        warnings.append("과열 구간")
    if chase:
        score -= 18
        warnings.append("추격매수 위험")
    if sell_news:
        score -= 10
        warnings.append("뉴스 선반영 위험")
    if penalty < 0:
        score += max(-18, penalty * 0.5)
        warnings.append("복기 실패 패턴 감점")
    if _safe_str(row.get("prediction_result")) == "fail":
        score -= 5
        warnings.append("최근 복기 실패")
    if any(token in _safe_str(row.get("failure_reason")) for token in ["과열", "손익비", "뉴스"]):
        score -= 5
        warnings.append("반복 실패 사유 주의")

    prob_up_5d = _clip_prob(score)
    prob_up_1d = _clip_prob(50 + (prob_up_5d - 50) * 0.45 - (5 if risk_mode else 0) - (4 if chase else 0))
    prob_up_3d = _clip_prob(50 + (prob_up_5d - 50) * 0.72 - (3 if risk_mode else 0))
    prob_up_10d = _clip_prob(50 + (prob_up_5d - 50) * 0.9 + (4 if stock_score >= 70 else 0) - (4 if trade_score < 45 else 0))
    prob_down_5d = _clip_prob(100 - prob_up_5d + (8 if risk_mode else 0) + (8 if chase else 0) + (6 if not rr_pass else 0))

    entry = _safe_float(row.get("entry"), 0)
    stop = _safe_float(row.get("stop"), 0)
    tp1 = _safe_float(row.get("tp1"), 0)
    last_price = _safe_float(row.get("last_price"), entry)
    upside_pct = ((tp1 / max(last_price, 1e-9) - 1) * 100) if tp1 > 0 and last_price > 0 else max(rr * 3, 3)
    downside_pct = ((last_price / max(stop, 1e-9) - 1) * 100) if stop > 0 and last_price > 0 else 5
    prob_tp1_5d = _clip_prob(prob_up_5d - max(0, upside_pct - 5) * 1.5 + (8 if rr >= 2 else 0) + (4 if entry_score >= 70 else 0))
    prob_stop_5d = _clip_prob(100 - prob_up_5d + max(0, downside_pct - 6) * 1.2 + (14 if not rr_pass else 0) + (12 if chase else 0) + (8 if risk_mode else 0))
    prob_tp_first = _clip_prob(prob_tp1_5d - prob_stop_5d * 0.25 + 15)
    prob_stop_first = _clip_prob(prob_stop_5d - prob_tp1_5d * 0.2 + 10)
    prob_market_outperform_5d = _clip_prob(50 + market_rs * 8 + aggressive * 0.18 + (6 if _safe_bool(row.get("weak_market_leader_flag"), False) else 0))
    prob_sector_outperform_5d = _clip_prob(50 + sector_rs * 8 + aggressive * 0.14)
    expected_return_5d = _clip_return((prob_tp1_5d / 100) * max(upside_pct, 1) - (prob_stop_5d / 100) * max(downside_pct, 1))

    label = _label(row, score, prob_stop_5d)
    confidence = _confidence(row, len(reasons))
    if confidence == CONF_LOW:
        warnings.append("데이터 부족: 예측 신뢰도 낮음")
    historical_note = _safe_str(row.get("historical_pattern_note"))
    historical_n = _safe_float(row.get("historical_sample_count"), 0)
    if historical_note:
        reasons.append(historical_note)
    elif historical_n <= 0:
        reasons.append("유사조건 복기 표본 부족")
    if not reasons:
        reasons.append("확률 전망 중립")
    warnings = _final_forecast_warnings(row, label, warnings, prob_up_5d)

    return {
        "prob_up_1d": prob_up_1d,
        "prob_up_3d": prob_up_3d,
        "prob_up_5d": prob_up_5d,
        "prob_up_10d": prob_up_10d,
        "prob_down_5d": prob_down_5d,
        "prob_tp1_5d": prob_tp1_5d,
        "prob_stop_5d": prob_stop_5d,
        "prob_tp_first": prob_tp_first,
        "prob_stop_first": prob_stop_first,
        "prob_market_outperform_5d": prob_market_outperform_5d,
        "prob_sector_outperform_5d": prob_sector_outperform_5d,
        "expected_return_5d": expected_return_5d,
        "forecast_label": label,
        "forecast_confidence": confidence,
        "forecast_reasons": list(dict.fromkeys(reasons)),
        "forecast_warnings": warnings,
    }


def apply_multiday_probability(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    cols = [
        "prob_up_1d",
        "prob_up_3d",
        "prob_up_5d",
        "prob_up_10d",
        "prob_down_5d",
        "prob_tp1_5d",
        "prob_stop_5d",
        "prob_tp_first",
        "prob_stop_first",
        "prob_market_outperform_5d",
        "prob_sector_outperform_5d",
        "expected_return_5d",
        "forecast_label",
        "forecast_confidence",
        "forecast_reasons",
        "forecast_warnings",
    ]
    if out.empty:
        for col in cols:
            if col not in out.columns:
                out[col] = []
        return out
    result = pd.DataFrame([calculate_multiday_probability(row) for row in out.to_dict(orient="records")], index=out.index)
    for col in cols:
        values = result[col]
        if col in {"forecast_reasons", "forecast_warnings"}:
            values = values.apply(lambda x: " / ".join(map(str, x)) if isinstance(x, list) else _safe_str(x))
        out[col] = values.values
    return out
