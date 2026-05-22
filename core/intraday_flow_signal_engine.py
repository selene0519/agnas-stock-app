from __future__ import annotations

import math
from typing import Any

import pandas as pd


FLOW_SIGNAL_COLUMNS = [
    "foreign_net_buy",
    "institution_net_buy",
    "individual_net_buy",
    "program_net_buy",
    "foreign_flow_score",
    "institution_flow_score",
    "program_flow_score",
    "intraday_flow_score",
    "sector_intraday_strength_score",
    "sector_flow_label",
    "sector_flow_alignment_score",
    "intraday_flow_label",
    "intraday_flow_warning",
    "intraday_flow_reason",
    "flow_data_available",
    "flow_updated_at",
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


def calculate_intraday_flow_score(row: dict[str, Any]) -> dict[str, Any]:
    foreign = _num(row.get("foreign_net_buy"))
    institution = _num(row.get("institution_net_buy"))
    individual = _num(row.get("individual_net_buy"))
    program = _num(row.get("program_net_buy"))
    available = _truthy(row.get("flow_data_available"))
    if not available:
        return {
            "foreign_flow_score": 50,
            "institution_flow_score": 50,
            "program_flow_score": 50,
            "intraday_flow_score": 45,
        }
    def score(net: float, scale: float = 1_000_000.0) -> int:
        if net == 0:
            return 50
        mag = min(35.0, abs(net) / max(scale, 1.0) * 10.0)
        return _clamp(50 + (mag if net > 0 else -mag))

    foreign_score = score(foreign)
    institution_score = score(institution)
    program_score = score(program, 500_000.0)
    individual_score = score(individual, 800_000.0)
    flow_score = _clamp(foreign_score * 0.35 + institution_score * 0.35 + program_score * 0.2 + individual_score * 0.1)
    return {
        "foreign_flow_score": foreign_score,
        "institution_flow_score": institution_score,
        "program_flow_score": program_score,
        "intraday_flow_score": flow_score,
    }


def calculate_sector_flow_alignment(row: dict[str, Any]) -> dict[str, Any]:
    sector_label = str(row.get("sector_flow_label", "") or "")
    sector_strength = _num(row.get("sector_intraday_strength_score"), 50.0)
    change_pct = _num(row.get("intraday_change_pct", row.get("intraday_price_change_pct")), 0.0)
    score = _clamp(sector_strength)
    if "강세" in sector_label and change_pct > 0:
        score = _clamp(score + 10)
    elif "약세" in sector_label and change_pct < 0:
        score = _clamp(score - 10)
    elif "표본 부족" in sector_label:
        score = _clamp(45)
    return {
        "sector_intraday_strength_score": _clamp(sector_strength),
        "sector_flow_label": sector_label,
        "sector_flow_alignment_score": score,
    }


def classify_us_momentum_flow_action(row: dict[str, Any]) -> dict[str, Any]:
    available = _truthy(row.get("flow_data_available"))
    momentum = _num(row.get("intraday_momentum_score"), 45.0)
    change_pct = _num(row.get("intraday_change_pct", row.get("intraday_price_change_pct")), 0.0)
    execution = _num(row.get("execution_strength"), math.nan)
    pressure = _num(row.get("orderbook_pressure"), math.nan)
    warning = str(row.get("flow_warning", "") or "").strip()
    if not available:
        return {
            "foreign_flow_score": None,
            "institution_flow_score": None,
            "program_flow_score": None,
            "intraday_flow_score": 45,
            "sector_intraday_strength_score": _clamp(_num(row.get("sector_intraday_strength_score"), 50.0)),
            "sector_flow_label": str(row.get("sector_flow_label", "") or ""),
            "sector_flow_alignment_score": _clamp(_num(row.get("sector_flow_alignment_score"), 50.0)),
            "intraday_flow_label": "장중 수급 대체 보류",
            "intraday_flow_warning": warning or "미국주식 장중 수급 대체 지표 미수신",
            "intraday_flow_reason": "거래량/거래대금/체결강도/호가 압력 데이터 미수신",
            "flow_data_available": False,
            "flow_updated_at": str(row.get("flow_updated_at", "") or ""),
        }
    label = "장중 모멘텀 중립"
    reason = "거래량·거래대금·체결강도·호가 압력 종합"
    if momentum >= 65 and change_pct > 0:
        label = "장중 모멘텀 우호"
        reason = "거래/체결/호가 지표가 동반 강세"
    elif momentum <= 40 and change_pct < 0:
        label = "장중 모멘텀 약세"
        reason = "거래/체결/호가 지표가 동반 약세"
        warning = warning or "장중 모멘텀 약세"
    elif not math.isnan(execution) and execution >= 60 and not math.isnan(pressure) and pressure > 0.05:
        label = "관찰 강화"
        reason = "체결강도·호가 압력이 양호"
    return {
        "foreign_flow_score": None,
        "institution_flow_score": None,
        "program_flow_score": None,
        "intraday_flow_score": _clamp(momentum),
        "sector_intraday_strength_score": _clamp(_num(row.get("sector_intraday_strength_score"), 50.0)),
        "sector_flow_label": str(row.get("sector_flow_label", "") or ""),
        "sector_flow_alignment_score": _clamp(_num(row.get("sector_flow_alignment_score"), 50.0)),
        "intraday_flow_label": label,
        "intraday_flow_warning": warning,
        "intraday_flow_reason": reason,
        "flow_data_available": True,
        "flow_updated_at": str(row.get("flow_updated_at", "") or ""),
    }


def classify_intraday_flow_action(row: dict[str, Any]) -> dict[str, Any]:
    if str(row.get("flow_mode", "")).strip() == "us_momentum":
        return classify_us_momentum_flow_action(row)
    available = _truthy(row.get("flow_data_available"))
    scores = calculate_intraday_flow_score(row)
    sector = calculate_sector_flow_alignment(row)
    merged = {**row, **scores, **sector}
    foreign = _num(merged.get("foreign_net_buy"))
    institution = _num(merged.get("institution_net_buy"))
    individual = _num(merged.get("individual_net_buy"))
    program = _num(merged.get("program_net_buy"))
    change_pct = _num(merged.get("intraday_change_pct", merged.get("intraday_price_change_pct")))
    warning = str(merged.get("flow_warning", "") or "").strip()
    blocked = _blocked(merged)

    if not available:
        label = "수급 판단 보류"
        reason = "수급/프로그램 데이터 없음"
    elif blocked:
        label = "신규매수 금지 유지"
        reason = "C/금지 후보는 수급이 좋아도 관찰만 허용"
    elif foreign > 0 and institution > 0 and program >= 0:
        label = "수급 우호"
        reason = "외국인/기관 동반 순매수"
    elif program < 0 and change_pct < 0:
        label = "수급 위험"
        reason = "프로그램 순매도 + 가격 약세"
        warning = warning or "수급 악화"
    elif individual > 0 and change_pct >= 7.0:
        label = "추격 주의"
        reason = "개인 매수 과열 + 가격 급등"
        warning = warning or "추격매수 주의"
    elif "강세" in str(sector.get("sector_flow_label", "")) and change_pct > 0:
        label = "관찰 강화"
        reason = "업종 장중 강세 + 종목 상대강도 유지"
    elif "약세" in str(sector.get("sector_flow_label", "")) and change_pct < 0:
        label = "진입 보류"
        reason = "업종 약세 + 종목 하락"
    else:
        label = "수급 중립"
        reason = "수급 신호 뚜렷하지 않음"

    return {
        **scores,
        **sector,
        "intraday_flow_label": label,
        "intraday_flow_warning": warning,
        "intraday_flow_reason": reason,
        "flow_data_available": available,
        "flow_updated_at": str(merged.get("flow_updated_at", "") or ""),
    }


def _flow_defaults() -> dict[str, Any]:
    return {
        "foreign_net_buy": 0.0,
        "institution_net_buy": 0.0,
        "individual_net_buy": 0.0,
        "program_net_buy": 0.0,
        "foreign_flow_score": 50,
        "institution_flow_score": 50,
        "program_flow_score": 50,
        "intraday_flow_score": 45,
        "sector_intraday_strength_score": 50,
        "sector_flow_label": "",
        "sector_flow_alignment_score": 50,
        "intraday_flow_label": "수급 판단 보류",
        "intraday_flow_warning": "수급/프로그램 데이터 미지원 또는 미수신",
        "intraday_flow_reason": "수급 데이터 없음",
        "flow_data_available": False,
        "flow_updated_at": "",
    }


def apply_intraday_flow_to_candidates(
    candidate_df: pd.DataFrame,
    flow_df: pd.DataFrame,
    sector_flow_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    out = candidate_df.copy() if candidate_df is not None else pd.DataFrame()
    defaults = _flow_defaults()
    for col, value in defaults.items():
        if col not in out.columns:
            out[col] = value
    if out.empty:
        return out

    symbol_col = "symbol" if "symbol" in out.columns else ("ticker" if "ticker" in out.columns else "")
    if not symbol_col:
        return out

    flow_map: dict[tuple[str, str], dict[str, Any]] = {}
    if flow_df is not None and not flow_df.empty and "symbol" in flow_df.columns:
        for _, row in flow_df.iterrows():
            key = (str(row.get("symbol", "")).strip().upper(), str(row.get("market", "")).strip())
            if key[0]:
                flow_map[key] = row.to_dict()
                flow_map[(key[0], "")] = row.to_dict()

    sector_map: dict[str, dict[str, Any]] = {}
    sector_col_name = ""
    if sector_flow_df is not None and not sector_flow_df.empty:
        sector_col_name = "sector" if "sector" in sector_flow_df.columns else ""
        if sector_col_name:
            for _, row in sector_flow_df.iterrows():
                sector_map[str(row.get("sector", "")).strip()] = row.to_dict()

    updated_rows: list[dict[str, Any]] = []
    for _, row in out.iterrows():
        item = row.to_dict()
        sym = str(item.get(symbol_col, "")).strip().upper()
        market = str(item.get("market", "")).strip()
        flow = flow_map.get((sym, market), flow_map.get((sym, ""), {}))
        merged = {**item, **flow}
        sector_name = str(merged.get("sector", "") or merged.get("industry", "")).strip()
        if sector_name and sector_name in sector_map:
            sector_row = sector_map[sector_name]
            merged.update({
                "sector_intraday_strength_score": sector_row.get("sector_intraday_strength_score", 50),
                "sector_flow_label": sector_row.get("sector_flow_label", ""),
            })
        decision = classify_intraday_flow_action(merged)
        if _blocked(merged):
            decision["intraday_flow_label"] = "신규매수 금지 유지"
            decision["intraday_flow_reason"] = "C/금지 후보는 수급이 좋아도 관찰만 허용"
        for key, value in decision.items():
            item[key] = value
        for col in FLOW_SIGNAL_COLUMNS:
            item[col] = decision.get(col, merged.get(col, defaults.get(col, "")))
        updated_rows.append(item)

    result = pd.DataFrame(updated_rows)
    for col in out.columns:
        if col not in result.columns:
            result[col] = out[col]
    ordered = [*out.columns, *[c for c in FLOW_SIGNAL_COLUMNS if c not in out.columns]]
    return result[ordered]
