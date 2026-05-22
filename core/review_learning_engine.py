from __future__ import annotations

import math
from typing import Any

import pandas as pd


REVIEW_COLUMNS = [
    "prediction_result",
    "max_profit_pct",
    "max_drawdown_pct",
    "entry_touched",
    "tp1_touched",
    "tp2_touched",
    "stop_touched",
    "decision_success",
    "failure_reason",
    "review_tags",
]

BUY_DECISIONS = {"눌림목 매수 가능", "돌파 확인 후 접근"}


def _first(row: dict[str, Any], names: list[str], default: Any = "") -> Any:
    for name in names:
        if name in row:
            value = row.get(name)
            if value is not None and str(value).strip() != "":
                return value
    return default


def _safe_float(value: Any, default: float = math.nan) -> float:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            text = value.strip()
            if not text or text.lower() in {"nan", "none", "null", "n/a", "na", "-"}:
                return default
            text = (
                text.replace(",", "")
                .replace("%", "")
                .replace("원", "")
                .replace("$", "")
                .replace("₩", "")
            )
            if text.startswith("(") and text.endswith(")"):
                text = "-" + text[1:-1]
            return float(text)
        return float(value)
    except Exception:
        return default


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "1.0", "true", "yes", "y", "t", "on", "예", "맞음"}


def _as_row_dict(row: Any) -> dict[str, Any]:
    if hasattr(row, "to_dict"):
        return dict(row.to_dict())
    return dict(row or {})


def _decision(row: dict[str, Any]) -> str:
    return str(
        _first(
            row,
            [
                "risk_final_decision",
                "final_decision_after_no_buy_filter",
                "final_decision_after_market_filter",
                "final_decision_after_adjustment",
                "final_decision",
                "final_judgment",
                "suggested_action",
                "primary_action",
                "최종판단",
            ],
            "관망 우위",
        )
    ).strip()


def _price_down_pct(row: dict[str, Any], actual_close: float, entry: float) -> float:
    reference = entry
    actual_open = _safe_float(_first(row, ["actual_open", "open", "실제시초가", "시초가"]))
    if not math.isnan(actual_open) and actual_open > 0:
        reference = actual_open
    if math.isnan(reference) or reference <= 0 or math.isnan(actual_close):
        return math.nan
    return (actual_close / reference - 1.0) * 100.0


def _not_enough(reason: str = "데이터 부족") -> dict[str, Any]:
    return {
        "prediction_result": "not_enough_data",
        "max_profit_pct": math.nan,
        "max_drawdown_pct": math.nan,
        "entry_touched": False,
        "tp1_touched": False,
        "tp2_touched": False,
        "stop_touched": False,
        "decision_success": None,
        "failure_reason": reason,
        "review_tags": ["데이터 부족"],
    }


def classify_failure_reason(row: dict[str, Any]) -> str:
    """Classify the most likely failure cause with conservative priority rules."""
    src = _as_row_dict(row)
    regime = str(_first(src, ["market_regime", "market_risk_level", "시장상태"], "")).strip()
    actual_close = _safe_float(_first(src, ["actual_close", "close", "실제종가", "종가"]))
    entry = _safe_float(_first(src, ["preferred_entry", "entry_price", "우선진입가", "진입가"]))
    close_down = False
    if not math.isnan(actual_close) and not math.isnan(entry) and entry > 0:
        close_down = actual_close < entry
    if any(token in regime for token in ["하락", "급락", "위험", "변동성"]) and close_down:
        return "시장 급락"

    overheat = str(_first(src, ["overheat_level", "과열도"], "")).strip()
    if overheat in {"높음", "매우 높음"} or _safe_bool(_first(src, ["chase_risk", "추격위험"])):
        return "과열 추격"

    rr_level = str(_first(src, ["rr_level", "손익비등급"], "")).strip()
    if rr_level in {"불량", "부족"}:
        return "손익비 부족"

    if _safe_bool(_first(src, ["sell_the_news_risk", "뉴스선반영위험"])):
        return "뉴스 선반영"

    if "entry_touched" in src and not _safe_bool(src.get("entry_touched")):
        return "진입가 미도달"

    if _safe_bool(_first(src, ["stop_touched", "손절터치"])):
        return "손절선 이탈"

    volume_ratio = _safe_float(_first(src, ["volume_ratio", "VOL_RATIO", "거래량배율"]))
    volume_shortage = str(_first(src, ["volume_status", "volume_reason", "거래량상태"], ""))
    if (not math.isnan(volume_ratio) and volume_ratio < 0.8) or "부족" in volume_shortage:
        return "거래량 부족"

    if _safe_bool(_first(src, ["resistance_near", "저항근접"])) or str(
        _first(src, ["resistance_reason", "저항사유"], "")
    ).strip():
        return "저항 돌파 실패"

    return "기타"


def classify_prediction_result(row: dict[str, Any]) -> dict[str, Any]:
    """Classify one prediction into success/fail/neutral/not_enough_data."""
    src = _as_row_dict(row)
    actual_high = _safe_float(_first(src, ["actual_high", "high", "실제고가", "고가"]))
    actual_low = _safe_float(_first(src, ["actual_low", "low", "실제저가", "저가"]))
    actual_close = _safe_float(_first(src, ["actual_close", "close", "실제종가", "종가"]))
    entry = _safe_float(_first(src, ["preferred_entry", "entry_price", "우선진입가", "진입가"]))
    stop = _safe_float(_first(src, ["stop_loss", "손절가", "stop"]))
    tp1 = _safe_float(_first(src, ["take_profit1", "target_price", "1차익절가", "익절가"]))
    tp2 = _safe_float(_first(src, ["take_profit2", "2차익절가"]))

    if any(math.isnan(x) for x in [actual_high, actual_low, actual_close]):
        return _not_enough("실제 OHLC 데이터 부족")
    if math.isnan(entry) or entry <= 0:
        return _not_enough("진입가 데이터 부족")

    entry_touched = bool(actual_low <= entry <= actual_high)
    tp1_touched = bool(not math.isnan(tp1) and tp1 > 0 and actual_high >= tp1)
    tp2_touched = bool(not math.isnan(tp2) and tp2 > 0 and actual_high >= tp2)
    stop_touched = bool(not math.isnan(stop) and stop > 0 and actual_low <= stop)
    max_profit_pct = (actual_high / entry - 1.0) * 100.0
    max_drawdown_pct = (actual_low / entry - 1.0) * 100.0

    decision = _decision(src)
    result = "neutral"
    decision_success: bool | None = None
    tags: list[str] = []

    if decision in BUY_DECISIONS and stop_touched and not tp1_touched:
        result = "fail"
        decision_success = False
        tags.append("매수판단 실패")
    elif decision in BUY_DECISIONS and tp1_touched:
        result = "success"
        decision_success = True
        tags.append("목표가 터치")
    elif decision == "관망 우위" and (max_drawdown_pct <= -3.0 or _price_down_pct(src, actual_close, entry) <= -2.0):
        result = "success"
        decision_success = True
        tags.append("관망 손실회피")
    elif decision == "손절 우선":
        close_down_pct = _price_down_pct(src, actual_close, entry)
        if (not math.isnan(stop) and actual_close <= stop) or (not math.isnan(close_down_pct) and close_down_pct <= -2.0):
            result = "success"
            decision_success = True
            tags.append("손절판단 유효")
        else:
            result = "neutral"
            decision_success = None
    elif decision == "비중 축소 우선" and max_drawdown_pct <= -2.0:
        result = "success"
        decision_success = True
        tags.append("리스크관리 유효")

    review_row = {
        **src,
        "actual_high": actual_high,
        "actual_low": actual_low,
        "actual_close": actual_close,
        "preferred_entry": entry,
        "stop_loss": stop,
        "take_profit1": tp1,
        "entry_touched": entry_touched,
        "tp1_touched": tp1_touched,
        "tp2_touched": tp2_touched,
        "stop_touched": stop_touched,
    }
    failure_reason = "정상 범위"
    if result == "fail":
        failure_reason = classify_failure_reason(review_row)
    elif result == "neutral":
        failure_reason = "중립"
    elif result == "success":
        failure_reason = "정상 범위"
    if failure_reason and failure_reason not in {"정상 범위", "중립"}:
        tags.append(failure_reason)

    return {
        "prediction_result": result,
        "max_profit_pct": round(max_profit_pct, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "entry_touched": entry_touched,
        "tp1_touched": tp1_touched,
        "tp2_touched": tp2_touched,
        "stop_touched": stop_touched,
        "decision_success": decision_success,
        "failure_reason": failure_reason,
        "review_tags": tags,
    }


def enrich_predictions_with_review(df: pd.DataFrame) -> pd.DataFrame:
    """Append review-learning columns to predictions without deleting existing data."""
    if df is None or df.empty:
        out = pd.DataFrame() if df is None else df.copy()
        for col in REVIEW_COLUMNS:
            if col not in out.columns:
                out[col] = []
        return out

    out = df.copy()
    results = [classify_prediction_result(row) for row in out.to_dict(orient="records")]
    result_df = pd.DataFrame(results)
    for col in REVIEW_COLUMNS:
        if col not in result_df.columns:
            result_df[col] = ""
        values = result_df[col]
        if col == "review_tags":
            values = values.apply(lambda x: " / ".join(map(str, x)) if isinstance(x, list) else str(x or ""))
        out[col] = values.values
    return out
