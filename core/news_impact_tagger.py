"""
뉴스 · 공시 영향도 태그 엔진
- 키워드 룰 기반 호재 / 악재 / 중립 분류
- 카테고리 태그: 실적 / 공시 / 수급 / 규제 / 시장 / 섹터이슈
- confidence 점수 반환
- newsRiskPenalty 산출 보조
"""
from __future__ import annotations

import re
from typing import Any


# ── 감성 키워드 ────────────────────────────────────────────────

_BULLISH = [
    "수주", "계약 체결", "계약체결", "신규 수주", "대규모 계약", "수익성 개선",
    "호재", "실적 호조", "어닝 서프라이즈", "실적 상회", "매출 증가", "영업이익 증가",
    "자사주 매입", "자사주 취득", "배당 증가", "특별 배당", "배당 확대",
    "기술이전", "기술 수출", "MOU", "파트너십", "전략적 제휴",
    "임상 성공", "FDA 승인", "허가", "특허 등록", "특허 취득",
    "흑자 전환", "흑자전환", "적자 축소", "턴어라운드",
    "증자 완료", "상장 성공",
    "목표가 상향", "투자의견 매수", "매수 의견",
    "수출 증가", "해외 수주",
    "추가 수주", "공급 계약",
    "증설", "설비 투자", "신공장",
]

_BEARISH = [
    "유상증자", "제3자배정", "CB 발행", "BW 발행", "전환사채", "신주인수권부사채",
    "횡령", "배임", "사기", "주가조작", "불공정거래",
    "소송", "법적 분쟁", "손해배상",
    "영업정지", "거래정지", "상장폐지", "관리종목",
    "적자", "영업손실", "당기순손실", "어닝 쇼크",
    "임직원 매도", "대주주 매도", "경영진 지분 처분",
    "공급 과잉", "단가 인하", "가격 인하",
    "임상 실패", "임상 중단", "부작용",
    "규제 강화", "세무조사", "공정거래 제재",
    "목표가 하향", "투자의견 하향", "매도 의견",
    "계약 해지", "수주 취소", "해지",
    "화재", "사고", "리콜",
    "부채 증가", "자본잠식",
]

_NEUTRAL = [
    "임원 변경", "대표이사 변경", "합병", "분할", "인수",
    "결산", "배당 기준일", "주총",
    "주주환원", "IR",
]

# ── 카테고리 키워드 ────────────────────────────────────────────

_CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("실적", ["실적", "어닝", "EPS", "매출", "영업이익", "당기순이익", "흑자", "적자", "분기", "연간 실적"]),
    ("공시", ["공시", "주요사항", "증자", "CB", "BW", "주식매수선택권", "자기주식", "자사주", "배당"]),
    ("수급", ["외국인", "기관", "프로그램 매매", "순매수", "순매도", "수급", "매집", "대량 거래"]),
    ("규제", ["규제", "법률", "소송", "조사", "제재", "처벌", "금지", "과징금", "공정위", "금감원"]),
    ("시장", ["FOMC", "금리", "달러", "물가", "CPI", "PPI", "고용", "연준", "Fed", "기준금리", "국채"]),
    ("섹터이슈", ["반도체", "AI", "배터리", "전기차", "바이오", "헬스케어", "방산", "우주", "로봇", "플랫폼"]),
]

_CAUTION_PATTERNS = [
    "유상증자", "CB 발행", "BW 발행", "횡령", "배임", "소송", "영업정지", "상장폐지",
    "관리종목", "주가조작", "불공정거래",
]


def _count_hits(text: str, keywords: list[str]) -> int:
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def classify_news(title: str, snippet: str = "") -> dict[str, Any]:
    """
    뉴스 제목과 본문을 분석하여 영향도 태그를 반환한다.

    Returns:
        {
            "sentiment": "호재" | "악재" | "중립",
            "confidence": 0~100,
            "categories": ["실적", "공시", ...],
            "is_caution": bool,
            "caution_reasons": [...],
            "bullish_score": int,
            "bearish_score": int,
            "risk_penalty": int,   # newsRiskPenalty 보조값 (0, -5, -10)
            "confidence_adj": int, # newsReliabilityScore 보조값 (+0, +5, +10)
        }
    """
    combined = f"{title} {snippet}"

    bullish_hits = _count_hits(combined, _BULLISH)
    bearish_hits = _count_hits(combined, _BEARISH)

    # 감성 결정
    total = bullish_hits + bearish_hits
    if total == 0:
        sentiment = "중립"
        confidence = 40
    elif bullish_hits > bearish_hits:
        sentiment = "호재"
        confidence = min(95, 50 + bullish_hits * 12)
    elif bearish_hits > bullish_hits:
        sentiment = "악재"
        confidence = min(95, 50 + bearish_hits * 12)
    else:
        sentiment = "중립"
        confidence = 45

    # 카테고리
    categories: list[str] = []
    for cat_name, cat_kws in _CATEGORY_RULES:
        if _count_hits(combined, cat_kws) > 0:
            categories.append(cat_name)

    # 주의 패턴
    caution_reasons = [p for p in _CAUTION_PATTERNS if p.lower() in combined.lower()]
    is_caution = len(caution_reasons) > 0

    # 추천 보정값
    if is_caution or sentiment == "악재":
        if bearish_hits >= 3 or is_caution:
            risk_penalty = -10
        else:
            risk_penalty = -5
    else:
        risk_penalty = 0

    confidence_adj = 10 if sentiment == "호재" and confidence >= 70 else 0

    return {
        "sentiment": sentiment,
        "confidence": confidence,
        "categories": categories,
        "is_caution": is_caution,
        "caution_reasons": caution_reasons,
        "bullish_score": bullish_hits,
        "bearish_score": bearish_hits,
        "risk_penalty": risk_penalty,
        "confidence_adj": confidence_adj,
    }


def classify_news_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    뉴스 아이템 리스트에 영향도 태그를 추가한다.
    각 아이템은 'title' 또는 'headline' 키와 선택적으로 'summary'/'snippet' 키를 가진다.
    """
    results = []
    for item in items:
        title = str(item.get("title") or item.get("headline") or "")
        snippet = str(item.get("summary") or item.get("snippet") or item.get("description") or "")
        tag = classify_news(title, snippet)
        merged = dict(item)
        merged["impact_sentiment"] = tag["sentiment"]
        merged["impact_confidence"] = tag["confidence"]
        merged["impact_categories"] = ", ".join(tag["categories"]) if tag["categories"] else "일반"
        merged["impact_is_caution"] = tag["is_caution"]
        merged["impact_caution_reasons"] = ", ".join(tag["caution_reasons"])
        merged["impact_risk_penalty"] = tag["risk_penalty"]
        results.append(merged)
    return results


def sentiment_badge(sentiment: str) -> str:
    """UI용 감성 배지 HTML."""
    colors = {
        "호재": ("#173d2b", "#40f28b", "#2e8058"),
        "악재": ("#4c1b22", "#ff7782", "#9a2b39"),
        "중립": ("#1e2a3a", "#94a3b8", "#334155"),
    }
    bg, fg, bd = colors.get(sentiment, colors["중립"])
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        f'font-weight:700;font-size:.78rem;background:{bg};color:{fg};border:1px solid {bd};">'
        f"{sentiment}</span>"
    )


def category_badge(cat: str) -> str:
    """UI용 카테고리 배지 HTML."""
    return (
        f'<span style="display:inline-block;padding:2px 6px;border-radius:6px;'
        f'font-size:.74rem;background:#1e2a3a;color:#94a3b8;border:1px solid #334155;'
        f'margin:1px;">{cat}</span>'
    )


def aggregate_news_impact(items: list[dict[str, Any]]) -> dict[str, Any]:
    """여러 뉴스의 영향도 집계."""
    if not items:
        return {"sentiment_counts": {}, "total_risk_penalty": 0, "dominant_sentiment": "중립"}
    tagged = classify_news_list(items)
    counts: dict[str, int] = {}
    total_penalty = 0
    for t in tagged:
        s = t.get("impact_sentiment", "중립")
        counts[s] = counts.get(s, 0) + 1
        total_penalty += t.get("impact_risk_penalty", 0)
    dominant = max(counts, key=counts.get) if counts else "중립"
    return {
        "sentiment_counts": counts,
        "total_risk_penalty": total_penalty,
        "dominant_sentiment": dominant,
        "bullish_count": counts.get("호재", 0),
        "bearish_count": counts.get("악재", 0),
        "neutral_count": counts.get("중립", 0),
    }
