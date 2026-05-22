from __future__ import annotations

import math
import re
from typing import Any


FINAL_DECISIONS = [
    "관망 우위",
    "눌림목 매수 가능",
    "돌파 확인 후 접근",
    "비중 축소 우선",
    "손절 우선",
]

BUY_DECISIONS = {"눌림목 매수 가능", "돌파 확인 후 접근"}


def _safe_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None:
            return default
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null", "n/a", "na", "-"}:
            return default
        text = text.replace(",", "").replace("%", "").replace("$", "").replace("원", "")
        return float(text)
    except Exception:
        return default


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "ok", "확인", "공시확인", "공시 확인"}


def _clip(value: float, low: float, high: float) -> float:
    if math.isnan(value):
        value = low
    return max(low, min(high, value))


def _join_text(*values: Any) -> str:
    return " ".join(str(v or "") for v in values).strip()


def overheating_filter(data: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    missing: list[str] = []
    score = 0

    close = _safe_float(data.get("close", data.get("current_price")))
    ma10 = _safe_float(data.get("ma10", data.get("ma5")))
    rsi = _safe_float(data.get("rsi"))
    volume_ratio = _safe_float(data.get("volume_ratio"))
    upper_shadow_pct = _safe_float(data.get("upper_shadow_pct"))
    gap_up_pct = _safe_float(data.get("gap_up_pct"))
    consecutive_rise_days = _safe_float(data.get("consecutive_rise_days"))

    if not math.isnan(close) and not math.isnan(ma10) and ma10 > 0:
        ma10_gap_pct = (close / ma10 - 1.0) * 100
        if ma10_gap_pct >= 15:
            score += 25
            reasons.append(f"10일선 이격 과다({ma10_gap_pct:.1f}%)")
        elif ma10_gap_pct >= 8:
            score += 10
            reasons.append(f"10일선 이격 확대({ma10_gap_pct:.1f}%)")
    else:
        missing.append("close/ma10")

    if not math.isnan(rsi):
        if rsi >= 80:
            score += 30
            reasons.append(f"RSI 매우 과열({rsi:.1f})")
        elif rsi >= 75:
            score += 20
            reasons.append(f"RSI 과열({rsi:.1f})")
    else:
        missing.append("rsi")

    if not math.isnan(gap_up_pct) and gap_up_pct >= 5:
        score += 15
        reasons.append(f"갭상승 추격주의({gap_up_pct:.1f}%)")

    if (
        not math.isnan(upper_shadow_pct)
        and not math.isnan(volume_ratio)
        and upper_shadow_pct >= 35
        and volume_ratio >= 2
    ):
        score += 20
        reasons.append(f"윗꼬리 물량출회 위험({upper_shadow_pct:.1f}%, 거래량 {volume_ratio:.1f}배)")

    if not math.isnan(consecutive_rise_days) and consecutive_rise_days >= 3:
        score += 15
        reasons.append(f"연속 상승 과열({int(consecutive_rise_days)}일)")

    if missing:
        reasons.append("과열 데이터 부족: " + "/".join(missing))

    score = int(_clip(round(score), 0, 100))
    if score >= 70:
        level = "매우 높음"
    elif score >= 45:
        level = "높음"
    elif score >= 20:
        level = "보통"
    else:
        level = "낮음"
    return {
        "overheat_score": score,
        "overheat_level": level,
        "overheat_reasons": reasons,
        "chase_risk": level in {"높음", "매우 높음"},
    }


def news_quality_filter(data: dict[str, Any]) -> dict[str, Any]:
    title = str(data.get("news_title", data.get("title", "")) or "")
    summary = str(data.get("news_summary", data.get("snippet", "")) or "")
    source = str(data.get("source", "") or "")
    text = _join_text(title, summary, source).lower()
    raw_text = _join_text(title, summary, source)

    if not raw_text:
        return {
            "news_grade": "Unknown",
            "news_score": 0,
            "news_reasons": ["뉴스 데이터 없음"],
            "sell_the_news_risk": False,
        }

    linked_disclosure = _is_true(data.get("linked_disclosure", data.get("disclosure_confirmed", False)))
    volume_confirmed = data.get("volume_confirmed", None)
    price_runup = _safe_float(data.get("price_runup_before_news_pct"), 0.0)

    s_keywords = [
        "실적", "수주", "계약", "공시", "fda", "정책", "승인", "공급계약",
        "earnings", "contract", "approval", "guidance raised", "revenue growth",
    ]
    b_keywords = ["전망", "리포트", "인터뷰", "기대감", "estimate", "outlook", "interview"]
    c_keywords = ["테마", "루머", "커뮤니티", "단순 반복", "찌라시", "hype", "rumor", "meme"]
    risk_keywords = ["소송", "조사", "규제", "하향", "유상증자", "전환사채", "거래정지", "감사의견", "회계", "lawsuit", "investigation", "restatement"]

    reasons: list[str] = []
    if any(k in text or k in raw_text for k in risk_keywords):
        grade = "C"
        score = 20
        reasons.append("리스크 키워드 포함")
    elif linked_disclosure and any(k in text or k in raw_text for k in s_keywords):
        grade = "S"
        score = 90
        reasons.append("공시 확인 + 실적/계약 연결")
    elif linked_disclosure:
        grade = "A"
        score = 78
        reasons.append("공시로 확인된 뉴스")
    elif any(k in text or k in raw_text for k in s_keywords):
        grade = "A"
        score = 74
        reasons.append("실적/계약/승인 연결 가능")
    elif any(k in text or k in raw_text for k in b_keywords):
        grade = "B"
        score = 52
        reasons.append("전망/기대감 중심")
    elif any(k in text or k in raw_text for k in c_keywords):
        grade = "C"
        score = 28
        reasons.append("테마/루머성 가능성")
    else:
        grade = "Unknown"
        score = 40
        reasons.append("품질 판단 키워드 부족")

    sell_the_news_risk = price_runup >= 30
    if sell_the_news_risk:
        score -= 20
        reasons.append(f"뉴스 전 선반영 위험({price_runup:.1f}%)")

    if volume_confirmed is not None and not _is_true(volume_confirmed):
        score = min(score, 55)
        reasons.append("거래량 확인 부족")

    return {
        "news_grade": grade,
        "news_score": int(_clip(score, 0, 100)),
        "news_reasons": reasons,
        "sell_the_news_risk": bool(sell_the_news_risk),
    }


def rr_filter(data: dict[str, Any]) -> dict[str, Any]:
    entry = _safe_float(data.get("entry_price", data.get("preferred_entry")))
    stop = _safe_float(data.get("stop_loss"))
    tp1 = _safe_float(data.get("take_profit1"))
    if math.isnan(entry) or math.isnan(stop) or math.isnan(tp1) or entry <= 0 or stop <= 0 or tp1 <= 0:
        return {"rr": 0.0, "rr_level": "불량", "rr_reason": "진입가/손절가/목표가 데이터 부족", "rr_pass": False}
    if entry <= stop:
        return {"rr": 0.0, "rr_level": "불량", "rr_reason": "진입가가 손절가 이하", "rr_pass": False}
    risk = entry - stop
    reward = tp1 - entry
    rr = reward / risk if risk > 0 else 0.0
    if rr < 1.2:
        level = "불량"
    elif rr < 1.5:
        level = "부족"
    elif rr < 2.0:
        level = "보통"
    else:
        level = "우수"
    return {
        "rr": round(float(rr), 4),
        "rr_level": level,
        "rr_reason": f"손익비 {rr:.2f}:1",
        "rr_pass": bool(rr >= 1.5),
    }


def normalize_final_decision(text: str) -> str:
    value = str(text or "").strip()
    if value in FINAL_DECISIONS:
        return value
    compact = re.sub(r"\s+", "", value.lower())
    if any(k in compact for k in ["손절", "이탈", "stop", "loss"]):
        return "손절 우선"
    if any(k in compact for k in ["축소", "리스크관리", "보유주의", "trim", "reduce"]):
        return "비중 축소 우선"
    if any(k in compact for k in ["돌파", "확인", "breakout"]):
        return "돌파 확인 후 접근"
    if any(k in compact for k in ["눌림", "매수", "진입", "buy", "entry"]):
        return "눌림목 매수 가능"
    return "관망 우위"


def _downgrade_to_watch(decision: str) -> str:
    if decision in BUY_DECISIONS:
        return "관망 우위"
    return decision if decision in FINAL_DECISIONS else "관망 우위"


def final_risk_decision_engine(data: dict[str, Any]) -> dict[str, Any]:
    try:
        overheat = data.get("overheat_result") or overheating_filter(data)
        news = data.get("news_result") or news_quality_filter(data)
        rr = data.get("rr_result") or rr_filter(data)

        base_decision = normalize_final_decision(str(data.get("base_decision", "")))
        confidence = _safe_float(data.get("confidence_score"), 50)
        missing_items = list(data.get("data_missing_items") or [])
        reasons: list[str] = []
        flags: list[str] = []
        decision = base_decision

        current_price = _safe_float(data.get("current_price"))
        stop_loss = _safe_float(data.get("stop_loss"))
        if str(data.get("position_status", "")).lower() == "stop_broken" or (
            not math.isnan(current_price) and not math.isnan(stop_loss) and current_price < stop_loss
        ):
            decision = "손절 우선"
            reasons.append("손절 기준 이탈")
            flags.append("STOP_BROKEN")
        elif len(missing_items) >= 3:
            decision = "관망 우위"
            reasons.append("데이터 부족 3개 이상")
            flags.append("DATA_MISSING")
        else:
            if _is_true(data.get("market_force_downgrade")) or str(data.get("market_risk_level", "")) == "매우 높음":
                if decision in BUY_DECISIONS:
                    decision = "관망 우위"
                reasons.append("시장위험 높음으로 신규매수 제한")
                flags.append("MARKET_RISK")

            if str(overheat.get("overheat_level")) == "매우 높음" and not bool(rr.get("rr_pass")):
                decision = "관망 우위"
                reasons.append("매우 과열 + 손익비 미통과")
                flags.append("OVERHEAT_RR_FAIL")
            elif bool(overheat.get("chase_risk")) and str(rr.get("rr_level")) in {"불량", "부족"}:
                decision = "관망 우위"
                reasons.append("추격매수 위험 + 손익비 부족")
                flags.append("CHASE_RISK")

            if not bool(rr.get("rr_pass")) and decision == "눌림목 매수 가능":
                decision = "관망 우위"
                reasons.append("손익비 1.5 미만으로 눌림목 매수 제한")
                flags.append("RR_FAIL")

            if confidence < 60 and decision == "눌림목 매수 가능":
                decision = "관망 우위"
                reasons.append("신뢰도 60 미만으로 눌림목 매수 제한")
                flags.append("LOW_CONFIDENCE")
            elif confidence < 50 and decision in BUY_DECISIONS:
                decision = "관망 우위"
                reasons.append("신뢰도 50 미만으로 신규매수 제한")
                flags.append("VERY_LOW_CONFIDENCE")

            if _is_true(data.get("resistance_near")) and decision == "눌림목 매수 가능":
                decision = "돌파 확인 후 접근"
                reasons.append("저항 근접으로 돌파 확인 우선")
                flags.append("RESISTANCE_NEAR")

            if bool(news.get("sell_the_news_risk")) and decision in BUY_DECISIONS:
                decision = "관망 우위"
                reasons.append("뉴스 선반영 위험")
                flags.append("SELL_THE_NEWS")

        risk_conf = confidence
        risk_conf -= 15 if str(overheat.get("overheat_level")) == "매우 높음" else 8 if str(overheat.get("overheat_level")) == "높음" else 0
        risk_conf -= 10 if not bool(rr.get("rr_pass")) else 0
        risk_conf -= 10 if bool(news.get("sell_the_news_risk")) else 0
        risk_conf -= min(20, len(missing_items) * 5)
        risk_conf = int(_clip(round(risk_conf), 0, 100))

        if not reasons:
            reasons.append("리스크 필터 통과 또는 관망 유지")

        return {
            "risk_final_decision": decision if decision in FINAL_DECISIONS else "관망 우위",
            "risk_confidence_score": risk_conf,
            "risk_decision_reasons": reasons,
            "risk_warning_flags": flags,
            "missing_items": missing_items,
        }
    except Exception as exc:
        return {
            "risk_final_decision": "관망 우위",
            "risk_confidence_score": 0,
            "risk_decision_reasons": [f"리스크 엔진 예외로 보수 판단: {exc}"],
            "risk_warning_flags": ["RISK_ENGINE_ERROR"],
            "missing_items": list(data.get("data_missing_items") or []),
        }

