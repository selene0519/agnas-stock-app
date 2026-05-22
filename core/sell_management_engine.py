from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


OVERHEAT_HIGH = "\ub192\uc74c"
OVERHEAT_VERY_HIGH = "\ub9e4\uc6b0 \ub192\uc74c"
MODE_DOWN = "\ud558\ub77d\uc7a5"
MODE_RISK = "\uc704\ud5d8\uc7a5"
DECISION_STOP_FIRST = "\uc190\uc808 \uc6b0\uc120"
SELL_MANAGEMENT_COLUMNS = [
    "sell_timing_label",
    "profit_taking_plan",
    "hold_or_sell_decision",
    "trailing_stop_level",
    "exit_invalid_condition",
    "sell_reasons",
    "sell_warnings",
]
DEFAULT_CANDIDATE_FILES = [
    Path("reports") / "swing_candidates_us_A_top3.csv",
    Path("reports") / "swing_candidates_us_B_watch.csv",
    Path("reports") / "swing_candidates_us_C_excluded.csv",
    Path("reports") / "swing_candidates_kr_A_top3.csv",
    Path("reports") / "swing_candidates_kr_B_watch.csv",
    Path("reports") / "swing_candidates_kr_C_excluded.csv",
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
            if value in {"", "-", "nan", "None"}:
                return default
        return float(value)
    except Exception:
        return default


def _clip_price(value: float) -> float:
    if value <= 0:
        return 0.0
    return round(float(value), 4)


def _near_target(price: float, target: float, threshold_pct: float = 3.0) -> bool:
    if price <= 0 or target <= 0:
        return False
    return price >= target * (1 - threshold_pct / 100)


def _calculate_trailing_stop(last_price: float, entry: float, stop: float, tp1: float, tp2: float) -> float:
    if last_price <= 0:
        return _clip_price(stop)
    if entry <= 0:
        return _clip_price(stop if stop > 0 else last_price * 0.92)
    base_stop = stop if stop > 0 else entry * 0.93
    if last_price <= entry:
        return _clip_price(base_stop)
    profit = last_price - entry
    if tp2 > 0 and last_price >= tp2:
        trail = entry + profit * 0.70
    elif tp1 > 0 and last_price >= tp1:
        trail = entry + profit * 0.55
    else:
        trail = max(base_stop, entry + profit * 0.20)
    return _clip_price(max(base_stop, min(trail, last_price * 0.98)))


def calculate_sell_management_plan(row: dict[str, Any]) -> dict[str, Any]:
    last_price = _safe_float(row.get("last_price") or row.get("current_price"), 0)
    entry = _safe_float(row.get("entry") or row.get("preferred_entry"), 0)
    stop = _safe_float(row.get("stop") or row.get("stop_loss"), 0)
    tp1 = _safe_float(row.get("tp1") or row.get("take_profit1"), 0)
    tp2 = _safe_float(row.get("tp2") or row.get("take_profit2"), 0)
    prob_up_1d = _safe_float(row.get("prob_up_1d"), 0)
    prob_up_3d = _safe_float(row.get("prob_up_3d"), 0)
    prob_up_5d = _safe_float(row.get("prob_up_5d"), 0)
    prob_tp1_5d = _safe_float(row.get("prob_tp1_5d"), 0)
    prob_stop_5d = _safe_float(row.get("prob_stop_5d"), 0)
    expected_return_5d = _safe_float(row.get("expected_return_5d"), 0)
    overheat = _safe_str(row.get("overheat_level"))
    mode = _safe_str(row.get("strategy_mode"))
    decision = _safe_str(row.get("risk_final_decision"))
    position_size_raw = row.get("position_size_pct")
    has_position_size = _safe_str(position_size_raw) != ""
    position_size = _safe_float(position_size_raw, 0)
    trade_allowed_text = _safe_str(row.get("strategy_trade_allowed")).lower()
    trade_allowed = trade_allowed_text in {"true", "1", "1.0", "yes", "y"}
    grade = _safe_str(row.get("strategy_adjusted_grade") or row.get("grade")).upper()
    rr = _safe_float(row.get("rr"), 0)
    resistance_room = _safe_float(row.get("resistance_room_pct"), 0)
    entry_position = _safe_str(row.get("entry_position_type"))

    reasons: list[str] = []
    warnings: list[str] = []
    trailing_stop = _calculate_trailing_stop(last_price, entry, stop, tp1, tp2)
    exit_invalid_condition = f"종가 기준 {trailing_stop:g} 이탈" if trailing_stop > 0 else "손절/무효 가격 재확인 필요"

    if stop > 0 and last_price > 0 and last_price <= stop:
        return {
            "sell_timing_label": "손절 우선",
            "profit_taking_plan": "익절 보류, 손절 실행 우선",
            "hold_or_sell_decision": "손절 우선",
            "trailing_stop_level": _clip_price(stop),
            "exit_invalid_condition": f"손절선 {stop:g} 이탈",
            "sell_reasons": ["손절선 이탈"],
            "sell_warnings": ["리스크 한도 초과 가능"],
        }

    if decision == DECISION_STOP_FIRST:
        warnings.append("기존 판단이 손절 우선")
        return {
            "sell_timing_label": "손절 우선",
            "profit_taking_plan": "반등 시 비중 축소, 손절선 이탈 시 청산",
            "hold_or_sell_decision": "축소/손절 우선",
            "trailing_stop_level": trailing_stop,
            "exit_invalid_condition": exit_invalid_condition,
            "sell_reasons": ["risk_final_decision=손절 우선"],
            "sell_warnings": warnings,
        }

    forbidden_or_observation = (has_position_size and position_size <= 0) or (trade_allowed_text and not trade_allowed) or grade in {"C", "금지"}
    if forbidden_or_observation:
        return {
            "sell_timing_label": "보유자만 관리",
            "profit_taking_plan": "신규 진입 금지, 보유자는 손절선/트레일링 스탑 기준만 관리",
            "hold_or_sell_decision": "신규매수 금지/관망",
            "trailing_stop_level": trailing_stop,
            "exit_invalid_condition": exit_invalid_condition,
            "sell_reasons": ["신규매수 금지 상태: 보유자만 매도 기준 관리"],
            "sell_warnings": ["시장/전략 금지 상태에서는 신규 진입 금지"],
        }

    target_near = _near_target(last_price, tp1)
    overheated = overheat in {OVERHEAT_HIGH, OVERHEAT_VERY_HIGH}
    weak_probability = (
        (prob_up_5d > 0 and prob_up_5d < 45)
        or expected_return_5d < 0
        or (prob_stop_5d >= max(prob_tp1_5d, 1) and prob_stop_5d >= 35)
    )
    market_risk = mode in {MODE_DOWN, MODE_RISK}

    if target_near and overheated:
        label = "일부 익절"
        decision_text = "일부 익절 후 잔여 보유"
        plan = "1차 목표 근접분 30~50% 분할익절, 잔여는 트레일링 스탑 적용"
        reasons.extend(["1차 목표가 근접", "과열 구간"])
        if prob_up_5d >= 55 and prob_stop_5d < 35:
            reasons.append("5일 상승확률 유지")
        if overheat == OVERHEAT_VERY_HIGH:
            warnings.append("과열 매우 높음")
    elif weak_probability or market_risk:
        label = "비중 축소"
        decision_text = "축소 또는 관망"
        plan = "보유 비중 30~50% 축소, 재상승 확인 전 추가매수 금지"
        if expected_return_5d < 0:
            reasons.append("5일 기대값 하락")
        if prob_up_5d > 0 and prob_up_5d < 45:
            reasons.append("상승확률 약화")
        if prob_stop_5d >= 35:
            reasons.append("손절확률 상승")
        if market_risk:
            reasons.append("시장 위험 상승")
        warnings.append("방어적 관리 필요")
    elif prob_up_5d >= 55 and prob_stop_5d <= 30 and expected_return_5d >= 0:
        label = "보유 가능"
        decision_text = "보유 가능"
        plan = "보유 유지, 1차 목표 도달 시 30% 내외 분할익절"
        reasons.extend(["5일 상승확률 유지", "손절확률 낮음"])
    elif target_near:
        label = "분할익절 검토"
        decision_text = "부분 익절 검토"
        plan = "1차 목표 근접분 20~30% 익절, 잔여는 추세 확인"
        reasons.append("1차 목표가 근접")
    else:
        label = "보유 관찰"
        decision_text = "보유 관찰"
        plan = "트레일링 스탑 기준 유지, 확률/시장 위험 악화 시 축소"
        reasons.append("뚜렷한 매도 신호 없음")

    if has_position_size and position_size <= 0:
        warnings.append("권장 포지션 0%: 신규 진입이 아닌 보유 대응만 참고")
    if rr and rr < 1.5:
        warnings.append("손익비 약화")
    if resistance_room and resistance_room < 3:
        warnings.append("저항까지 여유 부족")
    if "추격" in entry_position:
        warnings.append("추격매수 구간 이후 변동성 주의")
    if prob_up_1d and prob_up_3d and prob_up_1d < prob_up_3d - 15:
        warnings.append("단기 탄력 둔화")

    return {
        "sell_timing_label": label,
        "profit_taking_plan": plan,
        "hold_or_sell_decision": decision_text,
        "trailing_stop_level": trailing_stop,
        "exit_invalid_condition": exit_invalid_condition,
        "sell_reasons": list(dict.fromkeys(reasons)),
        "sell_warnings": list(dict.fromkeys(warnings)) or ["특이 경고 없음"],
    }


def apply_sell_management_plan(candidate_df: pd.DataFrame) -> pd.DataFrame:
    if candidate_df is None:
        return pd.DataFrame()
    out = candidate_df.copy()
    cols = SELL_MANAGEMENT_COLUMNS
    if out.empty:
        for col in cols:
            if col not in out.columns:
                out[col] = []
        return out
    result = pd.DataFrame([calculate_sell_management_plan(row) for row in out.to_dict(orient="records")], index=out.index)
    for col in cols:
        values = result[col]
        if col in {"sell_reasons", "sell_warnings"}:
            values = values.apply(lambda x: " / ".join(map(str, x)) if isinstance(x, list) else _safe_str(x))
        out[col] = values.values
    for col in ["sell_reasons", "sell_warnings"]:
        if col in out.columns:
            text = out[col].astype(str)
            blank = text.str.strip().isin(["", "nan", "None"])
            out.loc[blank, col] = "신규매수 금지 상태: 보유자만 매도 기준 관리" if col == "sell_reasons" else "시장/전략 금지 상태에서는 신규 진입 금지"
    return out


def apply_sell_management(candidate_df: pd.DataFrame) -> pd.DataFrame:
    return apply_sell_management_plan(candidate_df)


def backfill_sell_management_candidate_files(candidate_files: list[str | Path] | None = None) -> dict[str, Any]:
    paths = [Path(p) for p in (candidate_files or DEFAULT_CANDIDATE_FILES)]
    result: dict[str, Any] = {"updated_files": [], "missing_files": [], "errors": {}}
    for path in paths:
        try:
            if path.exists() and path.stat().st_size > 0:
                df = pd.read_csv(path)
            else:
                df = pd.DataFrame()
            out = apply_sell_management_plan(df)
            path.parent.mkdir(parents=True, exist_ok=True)
            out.to_csv(path, index=False, encoding="utf-8-sig")
            result["updated_files"].append(str(path))
        except Exception as exc:
            result["errors"][str(path)] = str(exc)
    return result
