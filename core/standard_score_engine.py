from __future__ import annotations

import re
from typing import Any

import pandas as pd

FINAL_JUDGMENTS = [
    "손절 우선",
    "비중 축소 우선",
    "관망 우위",
    "돌파 확인 후 접근",
    "눌림목 매수 가능",
]


def get_standard_score_weights() -> dict[str, int]:
    return {
        "시장 방향성": 10,
        "업종·테마 모멘텀": 12,
        "실적 성장성": 13,
        "수급": 13,
        "차트 추세": 13,
        "거래량·거래대금": 10,
        "밸류에이션": 8,
        "재무 안정성": 8,
        "뉴스·공시 질": 8,
        "손익비": 15,
    }


def _num(value: Any) -> float | None:
    try:
        text = str(value).replace(",", "").replace("%", "").replace("원", "").replace("$", "").strip()
        if text == "" or text.lower() in {"nan", "none", "n/a", "na"}:
            return None
        return float(text)
    except Exception:
        return None


def _text(row: Any, keys: list[str]) -> str:
    for key in keys:
        try:
            if hasattr(row, "get"):
                value = row.get(key, "")
            else:
                value = ""
            if value not in (None, ""):
                return str(value)
        except Exception:
            continue
    return ""


def _first_num(row: Any, keys: list[str]) -> float | None:
    for key in keys:
        try:
            value = row.get(key, None) if hasattr(row, "get") else None
        except Exception:
            value = None
        out = _num(value)
        if out is not None:
            return out
    return None


def _scaled(value: float, src_min: float, src_max: float, max_score: int) -> int:
    if src_max == src_min:
        return 0
    ratio = (value - src_min) / (src_max - src_min)
    return int(round(max(0, min(1, ratio)) * max_score))


def _item(name: str, score: int | None, max_score: int, reason: str) -> dict[str, Any]:
    if score is None:
        return {"항목": name, "점수": "", "배점": max_score, "상태": "확인 필요", "해석": reason}
    return {"항목": name, "점수": int(max(0, min(max_score, score))), "배점": max_score, "상태": "확인됨", "해석": reason}


def classify_news_quality(title: str, snippet: str = "", source: str = "", linked_disclosure: bool = False) -> dict[str, Any]:
    text = f"{title} {snippet} {source}".lower()
    kr = f"{title} {snippet} {source}"
    risk_words = [
        "소송", "조사", "규제", "실적 하향", "유상증자", "전환사채", "거래정지", "감사의견", "회계",
        "lawsuit", "investigation", "default", "delisting", "restatement", "material weakness",
    ]
    earnings_words = [
        "수주", "공급계약", "가격 인상", "실적 발표", "가이던스 상향", "매출 증가", "영업이익 증가",
        "contract", "revenue", "earnings", "guidance raised", "profit",
    ]
    structural_words = [
        "산업 재편", "장기 정책", "독점", "대규모 투자", "성장 사이클", "reshoring", "capex",
        "long-term", "policy", "monopoly", "infrastructure",
    ]
    one_off_words = ["급등", "기대감", "테마", "루머", "묻지마", "surge", "rumor", "meme", "hype"]

    if any(w in text or w in kr for w in risk_words):
        news_type = "리스크 뉴스"
        score = 15
        reason = "소송/규제/증자/회계 등 리스크 키워드 확인"
    elif any(w in text or w in kr for w in structural_words):
        news_type = "구조적 변화 뉴스"
        score = 82
        reason = "장기 정책/투자/산업 변화 키워드 확인"
    elif any(w in text or w in kr for w in earnings_words):
        news_type = "실적 연결 뉴스"
        score = 72
        reason = "수주/실적/가이던스 등 실적 연결 키워드 확인"
    elif any(w in text or w in kr for w in one_off_words):
        news_type = "일회성 뉴스"
        score = 42
        reason = "단기 테마/기대감 중심 뉴스"
    elif str(title or snippet).strip():
        news_type = "확인 필요"
        score = 50
        reason = "분류 키워드 부족"
    else:
        news_type = "확인 필요"
        score = None
        reason = "뉴스 데이터 없음"

    revenue_linked = news_type in {"실적 연결 뉴스", "구조적 변화 뉴스"}
    priced_in_risk = bool(re.search(r"급등|surge|rally|상한가| 신고가", f"{title} {snippet}", flags=re.IGNORECASE))
    material_expiry_risk = bool(re.search(r"루머|기대감|rumor|hype|일회성", f"{title} {snippet}", flags=re.IGNORECASE))
    return {
        "news_type": news_type,
        "news_quality_score": "" if score is None else int(score),
        "revenue_linked": bool(revenue_linked),
        "disclosure_confirmed": bool(linked_disclosure),
        "priced_in_risk": bool(priced_in_risk),
        "material_expiry_risk": bool(material_expiry_risk),
        "news_summary_reason": reason,
    }


def build_standard_score_table(row: Any, market: str, extra_context: dict[str, Any] | None = None) -> pd.DataFrame:
    extra_context = extra_context or {}
    weights = get_standard_score_weights()
    items: list[dict[str, Any]] = []

    market_score = _first_num(row, ["market_score", "market_risk_score", "시장점수"])
    if market_score is None:
        items.append(_item("시장 방향성", None, weights["시장 방향성"], "market_score/market_risk_score 없음"))
    elif "market_risk_score" in getattr(row, "keys", lambda: [])():
        items.append(_item("시장 방향성", _scaled(100 - market_score, 0, 100, weights["시장 방향성"]), weights["시장 방향성"], f"시장위험 {market_score:.0f} 기준"))
    else:
        items.append(_item("시장 방향성", _scaled(market_score, -5, 5, weights["시장 방향성"]), weights["시장 방향성"], f"시장 점수 {market_score:g} 기준"))

    sector_score = _first_num(row, ["sector_score", "sector_cycle_score", "theme_score", "업종점수"])
    items.append(_item("업종·테마 모멘텀", None if sector_score is None else _scaled(sector_score, -5, 5, weights["업종·테마 모멘텀"]), weights["업종·테마 모멘텀"], "업종/테마 점수 기준" if sector_score is not None else "업종·테마 데이터 없음"))

    growth = _first_num(row, ["revenue_growth", "sales_growth", "매출성장률", "growth_score", "fundamental_score"])
    items.append(_item("실적 성장성", None if growth is None else _scaled(growth, 0, 100, weights["실적 성장성"]), weights["실적 성장성"], "매출성장률/펀더멘털 점수 기준" if growth is not None else "실적 성장 데이터 없음"))

    supply = _first_num(row, ["supply_score", "foreign_institution_score", "수급점수"])
    items.append(_item("수급", None if supply is None else _scaled(supply, -5, 5, weights["수급"]), weights["수급"], "수급 점수 기준" if supply is not None else "수급 데이터 없음"))

    technical = _first_num(row, ["technical_score", "chart_score", "trend_score", "차트점수"])
    items.append(_item("차트 추세", None if technical is None else _scaled(technical, 0, 100, weights["차트 추세"]), weights["차트 추세"], "기술/차트 점수 기준" if technical is not None else "차트 추세 데이터 없음"))

    volume_ratio = _first_num(row, [
        "volume_ratio", "VOL_RATIO", "premarket_volume_ratio", "volume_amount_ratio",
        "turnover_ratio", "거래량비율", "거래량배율", "거래대금증가율",
    ])
    volume_amount = _first_num(row, [
        "volume", "actual_volume", "basis_volume", "거래량",
        "거래대금", "trading_value", "amount",
    ])
    if volume_ratio is not None:
        items.append(_item("거래량·거래대금", _scaled(volume_ratio, 1, 5, weights["거래량·거래대금"]), weights["거래량·거래대금"], f"거래량/거래대금 배율 {volume_ratio:g} 기준"))
    elif volume_amount is not None:
        items.append(_item("거래량·거래대금", _scaled(volume_amount, 0, 1_000_000, weights["거래량·거래대금"]), weights["거래량·거래대금"], f"거래량/거래대금 원천값 {volume_amount:g} 기준"))
    else:
        items.append(_item("거래량·거래대금", None, weights["거래량·거래대금"], "거래량·거래대금 데이터 없음"))

    valuation_score = _first_num(row, ["valuation_score"])
    per = _first_num(row, ["per", "PER", "kr_dart_per"])
    pbr = _first_num(row, ["pbr", "PBR"])
    psr = _first_num(row, ["psr", "PSR"])
    ev_ebitda = _first_num(row, ["ev_ebitda", "EV_EBITDA", "EV/EBITDA"])
    roe_for_value = _first_num(row, ["roe", "ROE", "kr_dart_roe"])
    discount = _first_num(row, ["per_discount", "pbr_discount", "psr_discount"])
    if valuation_score is not None:
        items.append(_item("밸류에이션", _scaled(valuation_score, 0, 100, weights["밸류에이션"]), weights["밸류에이션"], "밸류 점수 기준"))
    elif discount is not None:
        items.append(_item("밸류에이션", _scaled(discount, 0, 60, weights["밸류에이션"]), weights["밸류에이션"], f"업종 대비 할인율 {discount:g} 기준"))
    elif per is not None:
        items.append(_item("밸류에이션", _scaled(30 - per, 0, 30, weights["밸류에이션"]), weights["밸류에이션"], f"PER {per:g} 기준"))
    elif pbr is not None:
        items.append(_item("밸류에이션", _scaled(3 - pbr, 0, 3, weights["밸류에이션"]), weights["밸류에이션"], f"PBR {pbr:g} 기준"))
    elif psr is not None:
        items.append(_item("밸류에이션", _scaled(5 - psr, 0, 5, weights["밸류에이션"]), weights["밸류에이션"], f"PSR {psr:g} 기준"))
    elif ev_ebitda is not None:
        items.append(_item("밸류에이션", _scaled(20 - ev_ebitda, 0, 20, weights["밸류에이션"]), weights["밸류에이션"], f"EV/EBITDA {ev_ebitda:g} 기준"))
    elif roe_for_value is not None:
        items.append(_item("밸류에이션", _scaled(roe_for_value, 0, 25, weights["밸류에이션"]), weights["밸류에이션"], f"ROE {roe_for_value:g}% 기준"))
    else:
        items.append(_item("밸류에이션", None, weights["밸류에이션"], "밸류에이션 데이터 없음"))

    stability = _first_num(row, ["financial_stability_score", "quality_score", "debt_ratio", "부채비율"])
    if stability is None:
        items.append(_item("재무 안정성", None, weights["재무 안정성"], "재무 안정성 데이터 없음"))
    elif _text(row, ["debt_ratio", "부채비율"]):
        items.append(_item("재무 안정성", _scaled(250 - stability, 0, 250, weights["재무 안정성"]), weights["재무 안정성"], f"부채비율 {stability:g}% 기준"))
    else:
        items.append(_item("재무 안정성", _scaled(stability, 0, 100, weights["재무 안정성"]), weights["재무 안정성"], "품질/재무 점수 기준"))

    news_score = _first_num(row, ["news_quality_score", "news_score", "auto_news_score", "disclosure_adjustment_score", "disclosure_score", "dart_score", "dart_disclosure_score", "sec_risk_score"])
    risk_text = _text(row, ["risk_keywords", "no_buy_reasons", "disclosure_risk_label", "disclosure_summary", "dart_risk_label", "dart_risk_keywords", "sec_risk_label", "sec_risk_keywords", "disclosure_risk_level", "sec_risk_level"])
    if news_score is None and not risk_text:
        items.append(_item("뉴스·공시 질", None, weights["뉴스·공시 질"], "뉴스·공시 데이터 없음"))
    else:
        score = _scaled(news_score if news_score is not None else 0, -5, 5, weights["뉴스·공시 질"])
        if any(k in risk_text for k in ["높음", "강한", "리스크", "소송", "감사의견", "delisting", "material weakness"]):
            score = min(score, max(0, weights["뉴스·공시 질"] // 3))
        items.append(_item("뉴스·공시 질", score, weights["뉴스·공시 질"], "뉴스 점수 및 공시 리스크 기준"))

    rr = _first_num(row, ["rr1", "risk_reward", "손익비", "current_rr"])
    items.append(_item("손익비", None if rr is None else _scaled(rr, 0.8, 2.5, weights["손익비"]), weights["손익비"], f"손익비 {rr:g} 기준" if rr is not None else "손익비 데이터 없음"))
    return pd.DataFrame(items)


def normalize_final_judgment(total_score: float, row: Any = None, market: str | None = None) -> str:
    if row is None:
        row = {}

    text = " ".join(
        [
            _text(row, ["no_buy_flags", "no_buy_reasons", "risk_keywords", "risk_reason", "data_status", "disclosure_risk_label", "disclosure_summary", "dart_risk_label", "sec_risk_label"]),
            _text(row, ["final_decision", "primary_action", "portfolio_action"]),
        ]
    )
    rr = _first_num(row, ["rr1", "risk_reward", "손익비", "current_rr"])
    no_buy = _first_num(row, ["no_buy_score"])
    market_risk = _first_num(row, ["market_risk_score"])
    disclosure_score = _first_num(row, ["disclosure_adjustment_score", "dart_disclosure_score", "sec_risk_score"])
    price = _first_num(row, ["current_price", "현재가", "last_price"])
    stop = _first_num(row, ["stop_loss", "손절가"])

    if price is not None and stop is not None and price <= stop:
        return "손절 우선"
    if any(k in text.upper() for k in ["DATA_MISSING", "자본잠식", "감사의견", "거래정지", "DELISTING", "MATERIAL WEAKNESS", "GOING CONCERN"]):
        return "관망 우위"
    if disclosure_score is not None and disclosure_score <= -6:
        return "비중 축소 우선" if any(k in text for k in ["보유", "holding", "HOLDING"]) else "관망 우위"
    if disclosure_score is not None and disclosure_score <= -3 and total_score >= 75:
        total_score = 64
    if no_buy is not None and no_buy >= 86:
        return "비중 축소 우선"
    if rr is not None and rr < 0.8:
        return "손절 우선"
    if market_risk is not None and market_risk >= 80:
        return "비중 축소 우선" if total_score < 65 else "관망 우위"
    if no_buy is not None and no_buy >= 70:
        return "관망 우위"
    if total_score >= 75 and (rr is None or rr >= 2.0) and (no_buy is None or no_buy < 50):
        return "눌림목 매수 가능"
    if total_score >= 65:
        return "돌파 확인 후 접근"
    return "관망 우위"


def calculate_standard_100_score(row: Any, market: str, extra_context: dict[str, Any] | None = None) -> dict[str, Any]:
    table = build_standard_score_table(row, market, extra_context)
    raw_max = float(table["배점"].sum()) if not table.empty else 0.0
    scores = pd.to_numeric(table["점수"], errors="coerce").fillna(0)
    raw_score = float(scores.sum())
    total_score = int(round(raw_score / raw_max * 100)) if raw_max else 0
    missing = table.loc[table["상태"].astype(str).eq("확인 필요"), "항목"].astype(str).tolist() if not table.empty else []
    judgment = normalize_final_judgment(total_score, row=row, market=market)
    return {
        "total_score": total_score,
        "raw_score": round(raw_score, 2),
        "raw_max_score": int(raw_max),
        "grade": judgment,
        "final_judgment": judgment,
        "items": table.to_dict("records"),
        "missing_items": missing,
    }
