from __future__ import annotations

from typing import Any

import pandas as pd


INTRADAY_SIGNAL_COLUMNS = [
    "intraday_price_change_pct",
    "intraday_volume",
    "intraday_trading_value",
    "intraday_volume_ratio",
    "intraday_trading_value_ratio",
    "intraday_money_flow_score",
    "intraday_order_strength_score",
    "intraday_signal_score",
    "intraday_action_label",
    "intraday_entry_confirmed",
    "intraday_chase_risk",
    "intraday_warning",
    "intraday_reason",
    "intraday_updated_at",
    "intraday_fetch_status",
    "intraday_failure_reason",
    "intraday_market_session",
    "intraday_composite_score",
    "intraday_final_label",
    "intraday_final_reason",
    "intraday_final_warning",
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


def _is_blocked_candidate(row: dict[str, Any]) -> bool:
    grade = str(row.get("grade", "")).strip().upper()
    source = str(row.get("source_file", row.get("_source_file", ""))).lower()
    bucket = str(row.get("final_candidate_bucket", "") or row.get("forecast_label", ""))
    hard_block = str(row.get("hard_block_reason", "") or row.get("exclude_reason", "")).strip()
    return (
        grade == "C"
        or "c_excluded" in source
        or "금지" in bucket
        or "제외" in bucket
        or _has_false_flag(row, "strategy_trade_allowed")
        or _has_false_flag(row, "trade_allowed")
        or bool(hard_block and hard_block.lower() not in {"nan", "none", "-"})
    )


def _clamp_score(value: float) -> int:
    return int(max(0, min(100, round(value))))


def calculate_intraday_money_flow_score(row: dict[str, Any]) -> dict[str, Any]:
    change_pct = _num(row.get("intraday_change_pct", row.get("intraday_price_change_pct")), 0.0)
    volume_ratio = _num(row.get("intraday_volume_ratio"), 0.0)
    trading_value_ratio = _num(row.get("intraday_trading_value_ratio"), 0.0)
    trading_value = _num(row.get("intraday_trading_value"), 0.0)
    available = _truthy(row.get("intraday_data_available"))

    if not available:
        return {"intraday_money_flow_score": 40, "money_flow_reason": "장중 데이터 없음: 보수 점수"}

    score = 45.0
    reasons: list[str] = []
    if trading_value_ratio >= 2.0:
        score += 24
        reasons.append("거래대금 증가 강함")
    elif trading_value_ratio >= 1.2:
        score += 14
        reasons.append("거래대금 증가")
    elif trading_value_ratio <= 0.35:
        score -= 16
        reasons.append("거래대금 부족")
    else:
        reasons.append("거래대금 보통")

    if volume_ratio >= 2.0:
        score += 16
        reasons.append("거래량 증가 강함")
    elif volume_ratio >= 1.2:
        score += 9
        reasons.append("거래량 증가")
    elif volume_ratio <= 0.35:
        score -= 10
        reasons.append("거래량 부족")

    if change_pct >= 2.0:
        score += 8
        reasons.append("가격 상승")
    elif change_pct <= -2.0:
        score -= 10
        reasons.append("가격 하락")

    if trading_value > 0:
        score += min(8, max(0, trading_value / 1_000_000_000))

    return {
        "intraday_money_flow_score": _clamp_score(score),
        "money_flow_reason": " / ".join(reasons) or "장중 자금흐름 중립",
    }


def calculate_order_strength_score(row: dict[str, Any]) -> dict[str, Any]:
    bid = _num(row.get("bid_total_volume"), 0.0)
    ask = _num(row.get("ask_total_volume"), 0.0)
    imbalance = _num(row.get("orderbook_imbalance"), 0.0)
    execution = _num(row.get("execution_strength"), 0.0)
    reasons: list[str] = []

    if bid <= 0 and ask <= 0 and execution <= 0 and imbalance == 0:
        return {
            "intraday_order_strength_score": 50,
            "order_strength_reason": "호가/체결강도 데이터 미지원 또는 미수신",
        }

    score = 50.0
    if bid > 0 or ask > 0:
        if ask > bid * 1.5:
            score -= 18
            reasons.append("매도잔량 우위")
        elif bid > ask * 1.5:
            score += 14
            reasons.append("매수잔량 우위")
    if imbalance:
        score += max(-18, min(18, imbalance * 25))
        reasons.append("호가 불균형 반영")
    if execution:
        if execution >= 120:
            score += 12
            reasons.append("체결강도 우위")
        elif execution <= 80:
            score -= 12
            reasons.append("체결강도 약화")
    return {
        "intraday_order_strength_score": _clamp_score(score),
        "order_strength_reason": " / ".join(reasons) or "호가/체결 중립",
    }


def classify_intraday_action(row: dict[str, Any]) -> dict[str, Any]:
    available = _truthy(row.get("intraday_data_available"))
    money = calculate_intraday_money_flow_score(row)
    order = calculate_order_strength_score(row)
    money_score = int(money["intraday_money_flow_score"])
    order_score = int(order["intraday_order_strength_score"])
    signal_score = _clamp_score(money_score * 0.72 + order_score * 0.28)
    change_pct = _num(row.get("intraday_change_pct", row.get("intraday_price_change_pct")), 0.0)
    volume_ratio = _num(row.get("intraday_volume_ratio"), 0.0)
    value_ratio = _num(row.get("intraday_trading_value_ratio"), 0.0)
    trading_value = _num(row.get("intraday_trading_value"), 0.0)
    blocked = _is_blocked_candidate(row)
    warning = str(row.get("intraday_warning", "") or "").strip()

    if not available:
        label = "장중 판단 보류"
        reason = "장중 데이터 없음"
        entry_confirmed = False
        chase_risk = False
    elif blocked:
        label = "신규매수 금지 유지"
        reason = "C/금지 후보는 장중 관찰만 허용"
        entry_confirmed = False
        chase_risk = False
    elif trading_value <= 0 or value_ratio <= 0.35:
        label = "진입 보류"
        reason = "거래대금 부족"
        entry_confirmed = False
        chase_risk = False
    elif change_pct >= 7.0 and value_ratio >= 2.0:
        label = "추격매수 경고"
        reason = "가격 급등과 거래대금 과열"
        entry_confirmed = False
        chase_risk = True
    elif value_ratio >= 1.2 and volume_ratio >= 1.1 and change_pct > 0:
        label = "관찰 강화"
        reason = "거래대금 증가 + 가격 상승 + 거래량 증가"
        entry_confirmed = signal_score >= 70
        chase_risk = change_pct >= 5.0
    elif value_ratio >= 1.2 and change_pct < 0:
        label = "위험 경고"
        reason = "거래대금 증가 중 가격 하락"
        entry_confirmed = False
        chase_risk = False
    elif order_score <= 35:
        label = "돌파 확인 대기"
        reason = "호가/체결강도 약화"
        entry_confirmed = False
        chase_risk = False
    else:
        label = "진입 보류"
        reason = "장중 확인 신호 부족"
        entry_confirmed = False
        chase_risk = False

    if blocked:
        entry_confirmed = False
    composite = build_intraday_composite_signal(
        {
            **row,
            **money,
            **order,
            "intraday_signal_score": signal_score,
            "intraday_action_label": label,
            "intraday_chase_risk": chase_risk,
        }
    )
    if blocked:
        composite["intraday_final_label"] = "신규매수 금지 유지"
        composite["intraday_final_reason"] = "C/금지 후보는 장중 관찰만 허용"
        composite["intraday_final_warning"] = "기존 위험 필터 유지"
    return {
        **money,
        **order,
        "intraday_signal_score": signal_score,
        "intraday_action_label": label,
        "intraday_entry_confirmed": bool(entry_confirmed),
        "intraday_chase_risk": bool(chase_risk or composite.get("intraday_final_label") == "추격매수 경고"),
        "intraday_warning": warning,
        "intraday_reason": reason,
        **composite,
    }


def build_intraday_composite_signal(row: dict[str, Any]) -> dict[str, Any]:
    money_score = _num(row.get("intraday_money_flow_score"), 40.0)
    order_score = _num(row.get("order_strength_score", row.get("intraday_order_strength_score")), 50.0)
    flow_score = _num(row.get("intraday_flow_score"), 50.0)
    sector_alignment = _num(row.get("sector_flow_alignment_score"), 50.0)
    composite_score = _clamp_score(money_score * 0.48 + order_score * 0.28 + flow_score * 0.16 + sector_alignment * 0.08)
    price_change = _num(row.get("intraday_change_pct", row.get("intraday_price_change_pct")), 0.0)
    value_ratio = _num(row.get("intraday_trading_value_ratio"), 0.0)
    order_label = str(row.get("order_strength_label", "") or "")
    flow_label = str(row.get("intraday_flow_label", "") or "")
    sector_label = str(row.get("sector_flow_label", "") or "")
    action = str(row.get("intraday_action_label", "") or "")
    available = _truthy(row.get("intraday_data_available"))
    order_available = _truthy(row.get("orderbook_data_available"))
    flow_available = _truthy(row.get("flow_data_available"))
    warning_parts: list[str] = []

    if not available:
        label = "장중 판단 보류"
        reason = "데이터 부족"
    elif _is_blocked_candidate(row):
        label = "신규매수 금지 유지"
        reason = "C/금지 후보는 장중 관찰만 허용"
        warning_parts.append("기존 위험 필터 유지")
    elif price_change >= 7.0 and value_ratio >= 2.0 and flow_label == "추격 주의":
        label = "추격매수 경고"
        reason = "가격 급등 + 개인 매수 과열 + 체결 둔화 가능"
        warning_parts.append("추격매수 위험")
    elif value_ratio >= 1.2 and price_change > 0 and flow_label == "수급 우호" and "강세" in sector_label:
        label = "관찰 강화"
        reason = "거래대금 증가 + 가격 상승 + 수급 우호 + 섹터 강세"
    elif value_ratio >= 1.2 and price_change > 0 and order_label in {"돌파 확인 대기", "진입 보류"}:
        label = "돌파 확인 대기"
        reason = "가격/거래대금은 양호하나 매도벽 확인 필요"
    elif value_ratio >= 1.2 and price_change < 0 and flow_label in {"수급 위험", "진입 보류"}:
        label = "위험 경고"
        reason = "거래대금 증가 + 가격 하락 + 수급 악화"
        warning_parts.append("하락 거래대금 증가")
    elif price_change >= 7.0 and value_ratio >= 2.0 and order_label in {"체결강도 약화", "진입 보류", "호가 판단 보류"}:
        label = "추격매수 경고"
        reason = "가격 급등 + 거래대금 과열 + 체결 둔화"
        warning_parts.append("추격매수 위험")
    elif value_ratio >= 1.2 and price_change > 0 and order_label == "매수세 우위":
        label = "관찰 강화"
        reason = "거래대금 증가 + 가격 상승 + 매수세 우위"
    elif flow_label == "수급 판단 보류" and not flow_available:
        label = "장중 판단 보류"
        reason = "수급 데이터 부족"
    elif action:
        label = action
        reason = str(row.get("intraday_reason", "장중 신호 반영") or "장중 신호 반영")
    else:
        label = "장중 판단 보류" if not order_available else "진입 보류"
        reason = "종합 신호 부족"

    existing_warning = str(
        row.get("intraday_warning", "")
        or row.get("order_strength_warning", "")
        or row.get("intraday_flow_warning", "")
        or ""
    ).strip()
    if existing_warning:
        warning_parts.append(existing_warning)
    return {
        "intraday_composite_score": composite_score,
        "intraday_final_label": label,
        "intraday_final_reason": reason,
        "intraday_final_warning": "; ".join(dict.fromkeys([p for p in warning_parts if p])),
    }


def _empty_intraday_defaults() -> dict[str, Any]:
    return {
        "intraday_price_change_pct": 0.0,
        "intraday_volume": 0.0,
        "intraday_trading_value": 0.0,
        "intraday_volume_ratio": 0.0,
        "intraday_trading_value_ratio": 0.0,
        "intraday_money_flow_score": 40,
        "intraday_order_strength_score": 50,
        "intraday_signal_score": 43,
        "intraday_action_label": "장중 판단 보류",
        "intraday_entry_confirmed": False,
        "intraday_chase_risk": False,
        "intraday_warning": "장중 데이터 미수신",
        "intraday_reason": "장중 데이터 없음",
        "intraday_updated_at": "",
        "intraday_fetch_status": "no_data",
        "intraday_failure_reason": "장중 데이터 미수신",
        "intraday_market_session": "unknown",
        "intraday_composite_score": 43,
        "intraday_final_label": "장중 판단 보류",
        "intraday_final_reason": "데이터 부족",
        "intraday_final_warning": "장중 데이터 미수신",
    }


def apply_intraday_signals_to_candidates(candidate_df: pd.DataFrame, intraday_df: pd.DataFrame) -> pd.DataFrame:
    out = candidate_df.copy() if candidate_df is not None else pd.DataFrame()
    defaults = _empty_intraday_defaults()
    for col, value in defaults.items():
        if col not in out.columns:
            out[col] = value
    if out.empty:
        return out

    symbol_col = "symbol" if "symbol" in out.columns else ("ticker" if "ticker" in out.columns else "")
    if not symbol_col:
        return out

    quotes = pd.DataFrame() if intraday_df is None else intraday_df.copy()
    quote_map: dict[tuple[str, str], dict[str, Any]] = {}
    if not quotes.empty and "symbol" in quotes.columns:
        if "market" not in quotes.columns:
            quotes["market"] = ""
        for _, q in quotes.iterrows():
            key = (str(q.get("symbol", "")).strip().upper(), str(q.get("market", "")).strip())
            if key[0]:
                quote_map[key] = q.to_dict()
                quote_map[(key[0], "")] = q.to_dict()

    updated_rows: list[dict[str, Any]] = []
    for _, row in out.iterrows():
        item = row.to_dict()
        sym = str(item.get(symbol_col, "")).strip().upper()
        market = str(item.get("market", "")).strip()
        quote = quote_map.get((sym, market), quote_map.get((sym, ""), {}))
        merged = {**item, **quote}
        if quote:
            merged["intraday_price_change_pct"] = quote.get("intraday_change_pct", quote.get("intraday_price_change_pct", 0.0))
            merged["intraday_volume"] = quote.get("intraday_volume", 0.0)
            merged["intraday_trading_value"] = quote.get("intraday_trading_value", 0.0)
            merged["intraday_volume_ratio"] = quote.get("intraday_volume_ratio", 0.0)
            merged["intraday_trading_value_ratio"] = quote.get("intraday_trading_value_ratio", 0.0)
            merged["intraday_updated_at"] = quote.get("intraday_updated_at", "")
            merged["intraday_warning"] = quote.get("intraday_warning", "")
            merged["intraday_fetch_status"] = quote.get("intraday_fetch_status", "")
            merged["intraday_failure_reason"] = quote.get("intraday_failure_reason", "")
            merged["intraday_market_session"] = quote.get("intraday_market_session", "")
        decision = classify_intraday_action(merged)
        for key, value in decision.items():
            merged[key] = value
        if _is_blocked_candidate(merged):
            merged["intraday_entry_confirmed"] = False
            merged["intraday_action_label"] = "신규매수 금지 유지"
            merged["intraday_final_label"] = "신규매수 금지 유지"
            merged["intraday_reason"] = "C/금지 후보는 장중 관찰만 허용"
            merged["intraday_final_reason"] = "C/금지 후보는 장중 관찰만 허용"
        for col in INTRADAY_SIGNAL_COLUMNS:
            item[col] = merged.get(col, defaults.get(col, ""))
        updated_rows.append(item)

    result = pd.DataFrame(updated_rows)
    for col in out.columns:
        if col not in result.columns:
            result[col] = out[col]
    for col in ["intraday_entry_confirmed", "intraday_chase_risk"]:
        if col in result.columns:
            result[col] = result[col].map(lambda value: bool(value)).astype(object)
    ordered = [*out.columns, *[c for c in INTRADAY_SIGNAL_COLUMNS if c not in out.columns]]
    return result[ordered]
