from __future__ import annotations

from typing import Any

import pandas as pd


ORDER_STRENGTH_COLUMNS = [
    "bid_total_volume",
    "ask_total_volume",
    "bid_ask_ratio",
    "orderbook_imbalance",
    "spread_pct",
    "execution_strength",
    "orderbook_imbalance_score",
    "execution_strength_score",
    "order_strength_score",
    "order_strength_label",
    "order_strength_warning",
    "order_strength_reason",
    "orderbook_data_available",
    "orderbook_updated_at",
]


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat", "-"}:
        return default
    for token in ["$", "원", ",", "배", "%"]:
        text = text.replace(token, "")
    try:
        return float(text)
    except Exception:
        return default


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "1.0", "yes", "y"}


def _has_false_flag(row: dict[str, Any], key: str) -> bool:
    value = str(row.get(key, "")).strip().lower()
    return bool(value) and value in {"false", "0", "0.0", "no", "n"}


def _blocked(row: dict[str, Any]) -> bool:
    grade = str(row.get("grade", "")).strip().upper()
    source = str(row.get("source_file", row.get("_source_file", ""))).lower()
    bucket = str(row.get("final_candidate_bucket", "") or row.get("forecast_label", ""))
    return (
        grade == "C"
        or "c_excluded" in source
        or "금지" in bucket
        or "제외" in bucket
        or _has_false_flag(row, "strategy_trade_allowed")
        or _has_false_flag(row, "trade_allowed")
    )


def _clamp(value: float) -> int:
    return int(max(0, min(100, round(value))))


def calculate_orderbook_imbalance_score(row: dict[str, Any]) -> dict[str, Any]:
    available = _truthy(row.get("orderbook_data_available"))
    if not available:
        return {"orderbook_imbalance_score": 50, "orderbook_imbalance_reason": "호가 데이터 없음: 중립 점수"}
    bid = _num(row.get("bid_total_volume"), 0.0)
    ask = _num(row.get("ask_total_volume"), 0.0)
    spread_pct = _num(row.get("spread_pct"), 0.0)
    total = bid + ask
    imbalance = _num(row.get("orderbook_imbalance"), (bid - ask) / total if total > 0 else 0.0)
    score = 50 + imbalance * 45
    reasons: list[str] = []
    if bid > ask * 1.5 and bid > 0:
        reasons.append("매수잔량 우위")
    elif ask > bid * 1.5 and ask > 0:
        reasons.append("매도잔량 과다")
    else:
        reasons.append("호가 균형")
    if spread_pct >= 1.0:
        score -= 15
        reasons.append("스프레드 과도")
    elif spread_pct >= 0.5:
        score -= 7
        reasons.append("스프레드 주의")
    return {"orderbook_imbalance_score": _clamp(score), "orderbook_imbalance_reason": " / ".join(reasons)}


def calculate_execution_strength_score(row: dict[str, Any]) -> dict[str, Any]:
    available = _truthy(row.get("orderbook_data_available"))
    if not available:
        return {"execution_strength_score": 50, "execution_strength_reason": "체결강도 데이터 없음: 중립 점수"}
    execution = _num(row.get("execution_strength"), 0.0)
    buy_execution = _num(row.get("buy_execution_strength"), 0.0)
    sell_execution = _num(row.get("sell_execution_strength"), 0.0)
    reasons: list[str] = []
    if execution <= 0 and (buy_execution > 0 or sell_execution > 0):
        total = buy_execution + sell_execution
        execution = (buy_execution / total) * 200 if total > 0 else 100
    if execution >= 130:
        score = 78
        reasons.append("체결강도 강함")
    elif execution >= 105:
        score = 65
        reasons.append("체결강도 양호")
    elif execution > 0 and execution <= 80:
        score = 35
        reasons.append("체결강도 약함")
    elif execution > 0:
        score = 50
        reasons.append("체결강도 중립")
    else:
        score = 50
        reasons.append("체결강도 미수신")
    return {"execution_strength_score": _clamp(score), "execution_strength_reason": " / ".join(reasons)}


def classify_order_strength_action(row: dict[str, Any]) -> dict[str, Any]:
    available = _truthy(row.get("orderbook_data_available"))
    imbalance = calculate_orderbook_imbalance_score(row)
    execution = calculate_execution_strength_score(row)
    imbalance_score = int(imbalance["orderbook_imbalance_score"])
    execution_score = int(execution["execution_strength_score"])
    score = _clamp(imbalance_score * 0.52 + execution_score * 0.48)
    bid = _num(row.get("bid_total_volume"), 0.0)
    ask = _num(row.get("ask_total_volume"), 0.0)
    spread_pct = _num(row.get("spread_pct"), 0.0)
    execution_value = _num(row.get("execution_strength"), 0.0)
    price_change = _num(row.get("intraday_price_change_pct", row.get("intraday_change_pct")), 0.0)
    warning = str(row.get("orderbook_warning", "") or "").strip()

    if not available:
        label = "호가 판단 보류"
        reason = "호가/체결강도 데이터 없음"
        warning = warning or "호가/체결강도 데이터 미지원 또는 미수신"
    elif _blocked(row):
        label = "신규매수 금지 유지"
        reason = "C/금지 후보는 호가가 좋아도 관찰만 허용"
        warning = warning or "기존 위험 필터 유지"
    elif spread_pct >= 1.0:
        label = "유동성 주의"
        reason = "스프레드 과도"
        warning = warning or "스프레드 과도"
    elif ask > bid * 1.7 and execution_value and execution_value <= 90:
        label = "진입 보류"
        reason = "매도잔량 과다 + 체결강도 약함"
    elif price_change >= 7.0 and execution_value and execution_value <= 95:
        label = "추격매수 경고"
        reason = "가격 급등 + 체결강도 둔화"
        warning = warning or "추격매수 위험"
    elif ask > bid * 1.7:
        label = "돌파 확인 대기"
        reason = "돌파 후보라도 매도벽 확인 필요"
    elif bid > ask * 1.3 and (execution_value >= 105 or execution_score >= 65):
        label = "매수세 우위"
        reason = "매수잔량 우위 + 체결강도 양호"
    elif execution_value and execution_value <= 85:
        label = "체결강도 약화"
        reason = "체결강도 약함"
    else:
        label = "호가 중립"
        reason = "호가/체결강도 특이사항 없음"

    return {
        **imbalance,
        **execution,
        "order_strength_score": score,
        "order_strength_label": label,
        "order_strength_warning": warning,
        "order_strength_reason": reason,
    }


def _defaults() -> dict[str, Any]:
    return {
        "bid_total_volume": 0.0,
        "ask_total_volume": 0.0,
        "bid_ask_ratio": 0.0,
        "orderbook_imbalance": 0.0,
        "spread_pct": 0.0,
        "execution_strength": 0.0,
        "orderbook_imbalance_score": 50,
        "execution_strength_score": 50,
        "order_strength_score": 50,
        "order_strength_label": "호가 판단 보류",
        "order_strength_warning": "호가/체결강도 데이터 미지원 또는 미수신",
        "order_strength_reason": "호가/체결강도 데이터 없음",
        "orderbook_data_available": False,
        "orderbook_updated_at": "",
    }


def apply_order_strength_to_candidates(candidate_df: pd.DataFrame, orderbook_df: pd.DataFrame) -> pd.DataFrame:
    out = candidate_df.copy() if candidate_df is not None else pd.DataFrame()
    defaults = _defaults()
    for col, value in defaults.items():
        if col not in out.columns:
            out[col] = value
    if out.empty:
        return out
    symbol_col = "symbol" if "symbol" in out.columns else ("ticker" if "ticker" in out.columns else "")
    if not symbol_col:
        return out

    ob = pd.DataFrame() if orderbook_df is None else orderbook_df.copy()
    ob_map: dict[tuple[str, str], dict[str, Any]] = {}
    if not ob.empty and "symbol" in ob.columns:
        if "market" not in ob.columns:
            ob["market"] = ""
        for _, row in ob.iterrows():
            key = (str(row.get("symbol", "")).strip().upper(), str(row.get("market", "")).strip())
            if key[0]:
                ob_map[key] = row.to_dict()
                ob_map[(key[0], "")] = row.to_dict()

    rows: list[dict[str, Any]] = []
    for _, row in out.iterrows():
        item = row.to_dict()
        sym = str(item.get(symbol_col, "")).strip().upper()
        market = str(item.get("market", "")).strip()
        data = ob_map.get((sym, market), ob_map.get((sym, ""), {}))
        merged = {**item, **data}
        decision = classify_order_strength_action(merged)
        for key, value in decision.items():
            merged[key] = value
        if _blocked(merged):
            merged["order_strength_label"] = "신규매수 금지 유지"
            merged["order_strength_reason"] = "C/금지 후보는 호가가 좋아도 관찰만 허용"
            if "intraday_entry_confirmed" in merged:
                merged["intraday_entry_confirmed"] = False
            if "today_buy_allowed" in merged and str(merged.get("grade", "")).upper() == "C":
                merged["today_buy_allowed"] = False
        for col in ORDER_STRENGTH_COLUMNS:
            item[col] = merged.get(col, defaults.get(col, ""))
        if "intraday_entry_confirmed" in item and _blocked(merged):
            item["intraday_entry_confirmed"] = False
        rows.append(item)

    result = pd.DataFrame(rows)
    for col in out.columns:
        if col not in result.columns:
            result[col] = out[col]
    if "intraday_entry_confirmed" in result.columns:
        result["intraday_entry_confirmed"] = result["intraday_entry_confirmed"].map(lambda value: bool(value)).astype(object)
    ordered = [*out.columns, *[c for c in ORDER_STRENGTH_COLUMNS if c not in out.columns]]
    return result[ordered]
