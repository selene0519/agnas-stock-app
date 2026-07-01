"""event_context.py — 이벤트 컨텍스트 서비스 (4차 작업)

뉴스(GNews), 공시(DART), 실적(Finnhub/DART), 매크로 등 기존 API 결과를 읽어
이벤트 태그와 리스크 점수를 산출합니다.

주요 함수:
    get_event_context(symbol, market, as_of_date=None) -> dict
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 기본 상수
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[4]
REPORT_DIR = REPO_ROOT / "reports"

NEWS_CACHE_FILES = {
    "kr": REPORT_DIR / "news_sentiment_cache_kr.json",
    "us": REPORT_DIR / "news_sentiment_cache_us.json",
}

# 이벤트 키워드 (한국어 + 영어 혼용)
_MACRO_POSITIVE = ("금리 인하", "rate cut", "긍정", "완화", "dovish", "QE", "양적완화", "경기부양")
_MACRO_RATE = ("FOMC", "fed", "파월", "금리 인상", "rate hike", "기준금리")
_MACRO_INFLATION = ("CPI", "PPI", "PCE", "인플레이션", "inflation", "물가")
_MACRO_FX = ("환율", "달러", "fx", "dollar", "원달러", "usdkrw", "currency")
_MACRO_VOLATILITY = ("vix", "volatility", "변동성", "급락", "폭락", "crash")
_MACRO_NEGATIVE = ("FOMC", "CPI", "PPI", "PCE", "고용", "금리", "파월", "환율", "국채", "yield",
                   "hawkish", "rate hike", "인플레이션", "inflation", "긴축", "tapering",
                   "volatility", "달러 강세")

_EARNINGS_BEAT = ("어닝 서프라이즈", "earnings surprise", "어닝서프라이즈", "실적 호조",
                  "beat", "컨센서스 상회", "EPS beat", "guidance raised", "가이던스 상향")
_EARNINGS_MISS = ("어닝 쇼크", "earnings shock", "어닝쇼크", "실적 부진", "miss",
                  "컨센서스 하회", "EPS miss", "guidance cut", "가이던스 하향")
_EARNINGS_GUIDANCE_UP = ("가이던스 상향", "guidance raised", "guidance up", "guidance increase",
                         "outlook raised", "전망 상향")
_EARNINGS_GUIDANCE_DOWN = ("가이던스 하향", "guidance cut", "guidance down", "guidance lowered",
                           "outlook cut", "전망 하향")
_EARNINGS_SCHEDULED = ("실적발표", "earnings date", "earnings release", "실적 예정", "분기 실적",
                       "earnings call", "컨센서스")

_DISCLOSURE_POSITIVE = ("수주", "공급계약", "계약", "자사주", "배당", "흑자", "승인", "FDA",
                        "임상 성공", "수주 잔고", "신규 계약", "MOU", "파트너십", "partnership")
_DISCLOSURE_NEGATIVE = ("증자", "CB", "전환사채", "BW", "관리종목", "상장폐지", "감사의견",
                        "소송", "유상증자", "횡령", "배임", "조사", "제재", "과징금")

_SECTOR_STRONG = ("섹터 강세", "sector outperform", "섹터 랠리", "상승 주도", "leading sector",
                  "sector beat", "강세 섹터")
_SECTOR_WEAK = ("섹터 약세", "sector underperform", "섹터 하락", "약세 섹터", "sector weakness",
                "sector sell-off")

_NEGATIVE_GENERAL = ("악재", "리스크", "하락", "위험", "우려", "부진", "negative", "risk",
                     "downgrade", "sell", "목표가 하향", "실적 하향")
_POSITIVE_GENERAL = ("호재", "강세", "상승", "긍정", "positive", "upgrade", "buy",
                     "목표가 상향", "실적 상향", "매수")


# ---------------------------------------------------------------------------
# 내부 헬퍼
# ---------------------------------------------------------------------------

def _has(text: str, keywords: tuple[str, ...]) -> bool:
    lo = text.lower()
    return any(k.lower() in lo for k in keywords)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        raw = str(value).replace(",", "").strip()
        if not raw or raw.lower() in {"nan", "none", "null", "-", ""}:
            return None
        f = float(raw)
        return f if math.isfinite(f) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 캐시 로더
# ---------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _load_news_cache(market: str) -> dict[str, Any]:
    path = NEWS_CACHE_FILES.get(market)
    if path is None or not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        return obj.get("data", {}) if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _news_cache_entry(symbol: str, market: str) -> dict[str, Any]:
    """reports/news_sentiment_cache_{market}.json 에서 종목 항목을 반환합니다."""
    cache = _load_news_cache(market)
    entry = cache.get(symbol, {})
    if not entry and market == "kr":
        sym_stripped = symbol.lstrip("0")
        for key, val in cache.items():
            if key.lstrip("0") == sym_stripped:
                entry = val
                break
    return entry if isinstance(entry, dict) else {}


# ---------------------------------------------------------------------------
# 데이터 로더 (data_loader 동적 import — 순환 참조 방지)
# ---------------------------------------------------------------------------

def _get_news_rows(market: str) -> list[dict[str, Any]]:
    try:
        from app.services import data_loader as _dl
        return _dl.news_rows(market).get("items", []) or []
    except Exception:
        return []


def _get_disclosure_rows(market: str) -> list[dict[str, Any]]:
    try:
        from app.services import data_loader as _dl
        return _dl.disclosure_rows(market).get("items", []) or []
    except Exception:
        return []


def _normalize_symbol(symbol: str, market: str) -> str:
    try:
        from app.services import data_loader as _dl
        return _dl.normalize_symbol(symbol, market) or symbol
    except Exception:
        return symbol


# ---------------------------------------------------------------------------
# 개별 태그 산출 함수들
# ---------------------------------------------------------------------------

def _build_news_tag(
    symbol: str,
    market: str,
    cache_entry: dict[str, Any],
    news_rows: list[dict[str, Any]],
) -> tuple[str, float, float, list[str]]:
    """newsEventTag, risk_contribution, reliability, reasons 반환."""
    reasons: list[str] = []
    tag = cache_entry.get("tag", "")
    penalty = _safe_float(cache_entry.get("penalty")) or 0.0
    news_adj = _safe_float(cache_entry.get("newsAdj")) or 0.0

    if tag in {"NEGATIVE", "RISKY", "RISK"}:
        risk_c = min(4.0, abs(penalty) + abs(news_adj))
        reasons.append(f"cache tag={tag} penalty={penalty:.1f}")
        return "negative_news", risk_c, 0.75, reasons
    if tag in {"POSITIVE", "BULLISH"}:
        reasons.append(f"cache tag={tag}")
        return "positive_news", 0.0, 0.75, reasons

    sym_norm = _normalize_symbol(symbol, market)
    related: list[dict[str, Any]] = []
    for r in news_rows:
        if _normalize_symbol(str(r.get("symbol", "")), market) == sym_norm:
            related.append(r)
            if len(related) >= 8:
                break
    if not related:
        for r in news_rows[:30]:
            title = str(r.get("title", "") or r.get("headline", "") or "")
            if symbol.lower() in title.lower() or sym_norm.lower() in title.lower():
                related.append(r)

    if not related:
        if tag == "NEUTRAL":
            return "neutral_news", 0.0, 0.5, ["cache=NEUTRAL, no related news rows"]
        return "no_news", 0.0, 0.3, ["no news found"]

    combined = " ".join(
        str(r.get("title", "")) + " " + str(r.get("summary", "")) + " " + str(r.get("content", ""))
        for r in related
    )
    neg_hits = _has(combined, _NEGATIVE_GENERAL)
    pos_hits = _has(combined, _POSITIVE_GENERAL)
    reliability = 0.6 + min(0.25, len(related) * 0.05)

    if neg_hits and not pos_hits:
        return "negative_news", 2.5, reliability, [f"negative keyword in {len(related)} news rows"]
    if pos_hits and not neg_hits:
        return "positive_news", 0.0, reliability, [f"positive keyword in {len(related)} news rows"]
    if neg_hits and pos_hits:
        return "neutral_news", 0.5, reliability, ["mixed signals"]
    return "neutral_news", 0.0, reliability, ["no strong signal"]


def _build_disclosure_tag(
    symbol: str,
    market: str,
    disclosure_rows: list[dict[str, Any]],
) -> tuple[str, float, float, list[str]]:
    """disclosureEventTag, risk_contribution, reliability, reasons 반환."""
    sym_norm = _normalize_symbol(symbol, market)
    related: list[dict[str, Any]] = []
    for r in disclosure_rows:
        if _normalize_symbol(str(r.get("symbol", "")), market) == sym_norm:
            related.append(r)
            if len(related) >= 8:
                break

    if not related:
        return "no_disclosure", 0.0, 0.3, ["no disclosure found"]

    combined = " ".join(
        str(r.get("title", "")) + " " + str(r.get("summary", "")) + " " + str(r.get("description", ""))
        for r in related
    )
    neg_hits = _has(combined, _DISCLOSURE_NEGATIVE)
    pos_hits = _has(combined, _DISCLOSURE_POSITIVE)
    reliability = 0.65 + min(0.2, len(related) * 0.04)

    if neg_hits and not pos_hits:
        return "negative_disclosure", 4.0, reliability, [f"negative disclosure keyword, count={len(related)}"]
    if pos_hits and not neg_hits:
        return "positive_disclosure", 0.0, reliability, [f"positive disclosure keyword, count={len(related)}"]
    if neg_hits and pos_hits:
        return "neutral_disclosure", 1.0, reliability, ["mixed disclosure signals"]
    return "neutral_disclosure", 0.0, reliability, ["neutral disclosure"]


def _build_earnings_tag(
    symbol: str,
    market: str,
    news_rows: list[dict[str, Any]],
    disclosure_rows: list[dict[str, Any]],
) -> tuple[str, float, float, list[str]]:
    """earningsEventTag, risk_contribution, reliability, reasons 반환."""
    sym_norm = _normalize_symbol(symbol, market)
    all_rows: list[dict[str, Any]] = []
    for r in news_rows:
        if _normalize_symbol(str(r.get("symbol", "")), market) == sym_norm:
            all_rows.append(r)
    for r in disclosure_rows:
        if _normalize_symbol(str(r.get("symbol", "")), market) == sym_norm:
            all_rows.append(r)

    if not all_rows:
        return "no_earnings", 0.0, 0.3, ["no earnings-related data found"]

    combined = " ".join(
        str(r.get("title", "")) + " " + str(r.get("summary", "")) + " " + str(r.get("description", ""))
        for r in all_rows[:10]
    )
    reliability = 0.55 + min(0.25, len(all_rows) * 0.04)

    if _has(combined, _EARNINGS_BEAT):
        return "earnings_beat", 0.0, reliability, ["earnings beat keyword detected"]
    if _has(combined, _EARNINGS_MISS):
        return "earnings_miss", 5.0, reliability, ["earnings miss keyword detected"]
    if _has(combined, _EARNINGS_GUIDANCE_UP):
        return "guidance_up", 0.0, reliability, ["guidance raised keyword detected"]
    if _has(combined, _EARNINGS_GUIDANCE_DOWN):
        return "guidance_down", 4.0, reliability, ["guidance down keyword detected"]
    if _has(combined, _EARNINGS_SCHEDULED):
        return "earnings_scheduled", 1.0, reliability, ["earnings scheduled keyword detected"]
    return "no_earnings", 0.0, 0.3, ["no earnings keyword matched"]


def _build_macro_tag(
    market: str,
    news_rows: list[dict[str, Any]],
    disclosure_rows: list[dict[str, Any]],
) -> tuple[str, float, float, list[str]]:
    """macroEventTag, risk_contribution, reliability, reasons 반환."""
    combined = " ".join(
        str(r.get("title", "")) + " " + str(r.get("summary", ""))
        for r in news_rows[:30]
    )
    if not combined.strip():
        return "macro_neutral", 0.0, 0.2, ["no macro news available"]

    reliability = 0.5

    if _has(combined, _MACRO_RATE):
        return "fomc_risk", 2.5, reliability, ["FOMC/rate keyword detected"]
    if _has(combined, _MACRO_INFLATION):
        return "inflation_risk", 2.0, reliability, ["inflation keyword detected"]
    if _has(combined, _MACRO_VOLATILITY):
        return "volatility_risk", 3.0, reliability, ["volatility keyword detected"]
    if _has(combined, _MACRO_FX):
        return "fx_risk", 1.5, reliability, ["FX/exchange rate keyword detected"]
    if _has(combined, _MACRO_NEGATIVE):
        return "rate_risk", 1.5, reliability, ["macro risk keyword detected"]
    if _has(combined, _MACRO_POSITIVE):
        return "macro_positive", 0.0, reliability, ["macro positive keyword detected"]
    return "macro_neutral", 0.0, reliability, ["no macro risk keyword detected"]


def _build_sector_tag(
    symbol: str,
    market: str,
    news_rows: list[dict[str, Any]],
) -> tuple[str, float, float, list[str]]:
    """sectorEventTag, risk_contribution, reliability, reasons 반환."""
    combined = " ".join(
        str(r.get("title", "")) + " " + str(r.get("summary", ""))
        for r in news_rows[:30]
    )
    if not combined.strip():
        return "sector_neutral", 0.0, 0.2, ["no sector news"]

    if _has(combined, _SECTOR_STRONG):
        return "sector_strong", 0.0, 0.5, ["sector strong keyword detected"]
    if _has(combined, _SECTOR_WEAK):
        return "sector_weak", 2.0, 0.5, ["sector weak keyword detected"]
    return "sector_neutral", 0.0, 0.3, ["no sector direction keyword"]


# ---------------------------------------------------------------------------
# 데이터 소스 타입 판단
# ---------------------------------------------------------------------------

def _determine_data_source_type(
    cache_entry: dict[str, Any],
    news_rows: list[dict[str, Any]],
    disclosure_rows: list[dict[str, Any]],
) -> tuple[str, bool]:
    """(eventDataSourceType, eventLearningEligible) 반환."""
    has_cache = bool(cache_entry)
    has_api_news = bool(news_rows)
    has_api_disc = bool(disclosure_rows)

    if has_api_news or has_api_disc:
        return "actual_api", True
    if has_cache:
        return "csv", True
    return "unavailable", False


# ---------------------------------------------------------------------------
# 메인 함수
# ---------------------------------------------------------------------------

def get_event_context(
    symbol: str,
    market: str,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """이벤트 컨텍스트를 반환합니다.

    Parameters
    ----------
    symbol:      종목 코드
    market:      "kr" | "us"
    as_of_date:  기준일 (미사용, 향후 확장용)

    Returns
    -------
    dict with fields:
        newsEventTag, disclosureEventTag, earningsEventTag,
        macroEventTag, sectorEventTag,
        eventRiskScore, eventReliabilityScore,
        eventSummary, eventDataSourceType, eventLearningEligible
    """
    _base: dict[str, Any] = {
        "newsEventTag": "unknown",
        "disclosureEventTag": "unknown",
        "earningsEventTag": "unknown",
        "macroEventTag": "unknown",
        "sectorEventTag": "unknown",
        "eventRiskScore": 0.0,
        "eventReliabilityScore": 0.0,
        "eventSummary": "",
        "eventDataSourceType": "unavailable",
        "eventLearningEligible": False,
    }

    try:
        market = "us" if str(market).lower() == "us" else "kr"
        symbol = _normalize_symbol(symbol, market)

        cache_entry = _news_cache_entry(symbol, market)
        try:
            news_rows = _get_news_rows(market)
        except Exception:
            news_rows = []
        try:
            disclosure_rows = _get_disclosure_rows(market)
        except Exception:
            disclosure_rows = []

        data_source_type, learning_eligible = _determine_data_source_type(
            cache_entry, news_rows, disclosure_rows
        )

        try:
            news_tag, news_risk, news_rel, news_reasons = _build_news_tag(
                symbol, market, cache_entry, news_rows
            )
        except Exception:
            news_tag, news_risk, news_rel, news_reasons = "unknown", 0.0, 0.0, []

        try:
            disc_tag, disc_risk, disc_rel, disc_reasons = _build_disclosure_tag(
                symbol, market, disclosure_rows
            )
        except Exception:
            disc_tag, disc_risk, disc_rel, disc_reasons = "unknown", 0.0, 0.0, []

        try:
            earn_tag, earn_risk, earn_rel, earn_reasons = _build_earnings_tag(
                symbol, market, news_rows, disclosure_rows
            )
        except Exception:
            earn_tag, earn_risk, earn_rel, earn_reasons = "unknown", 0.0, 0.0, []

        try:
            macro_tag, macro_risk, macro_rel, macro_reasons = _build_macro_tag(
                market, news_rows, disclosure_rows
            )
        except Exception:
            macro_tag, macro_risk, macro_rel, macro_reasons = "unknown", 0.0, 0.0, []

        try:
            sector_tag, sector_risk, sector_rel, sector_reasons = _build_sector_tag(
                symbol, market, news_rows
            )
        except Exception:
            sector_tag, sector_risk, sector_rel, sector_reasons = "unknown", 0.0, 0.0, []

        total_risk = news_risk + disc_risk + earn_risk + macro_risk + sector_risk
        event_risk_score = round(min(10.0, max(0.0, total_risk)), 2)

        if data_source_type in {"unavailable", "placeholder", "mock"}:
            event_reliability = 0.0
        else:
            weights = [0.25, 0.25, 0.20, 0.15, 0.15]
            scores = [news_rel, disc_rel, earn_rel, macro_rel, sector_rel]
            event_reliability = round(sum(w * s for w, s in zip(weights, scores)), 3)

        summary_parts: list[str] = []
        if news_tag not in {"no_news", "neutral_news", "unknown"}:
            summary_parts.append(f"뉴스:{news_tag}")
        if disc_tag not in {"no_disclosure", "neutral_disclosure", "unknown"}:
            summary_parts.append(f"공시:{disc_tag}")
        if earn_tag not in {"no_earnings", "unknown"}:
            summary_parts.append(f"실적:{earn_tag}")
        if macro_tag not in {"macro_neutral", "unknown"}:
            summary_parts.append(f"매크로:{macro_tag}")
        if sector_tag not in {"sector_neutral", "unknown"}:
            summary_parts.append(f"섹터:{sector_tag}")
        event_summary = " | ".join(summary_parts) if summary_parts else "이벤트 특이사항 없음"

        return {
            "newsEventTag": news_tag,
            "disclosureEventTag": disc_tag,
            "earningsEventTag": earn_tag,
            "macroEventTag": macro_tag,
            "sectorEventTag": sector_tag,
            "eventRiskScore": event_risk_score,
            "eventReliabilityScore": event_reliability,
            "eventSummary": event_summary[:300],
            "eventDataSourceType": data_source_type,
            "eventLearningEligible": learning_eligible,
        }

    except Exception as exc:
        _base["eventSummary"] = f"event_context error: {exc}"
        return _base


def compute_event_score_adjustment(evt_ctx: dict[str, Any]) -> float:
    """이벤트 태그 기반 점수 보정치를 계산합니다 (±8 상한).

    eventLearningEligible=True 이고 데이터 소스가 actual_api/csv일 때만 0이 아닌 값을
    반환합니다. final_engine.py의 final_recommendations()에 있던 동일 로직을 공유하기
    위해 추출한 함수입니다 (이벤트 하나만으로 추천을 뒤집지 않도록 ±8로 clamp).
    """
    if not (evt_ctx.get("eventLearningEligible") and evt_ctx.get("eventDataSourceType") in {"actual_api", "csv"}):
        return 0.0

    adj = 0.0
    news_tag = evt_ctx.get("newsEventTag", "")
    disc_tag = evt_ctx.get("disclosureEventTag", "")
    earn_tag = evt_ctx.get("earningsEventTag", "")
    macro_tag = evt_ctx.get("macroEventTag", "")
    sector_tag = evt_ctx.get("sectorEventTag", "")

    if news_tag == "negative_news":
        adj -= 2.5
    if disc_tag == "negative_disclosure":
        adj -= 4.0
    if earn_tag == "earnings_miss":
        adj -= 5.0
    elif earn_tag == "guidance_down":
        adj -= 4.0
    if macro_tag in {"rate_risk", "fomc_risk"}:
        adj -= 2.5
    elif macro_tag in {"inflation_risk", "volatility_risk"}:
        adj -= 3.0
    if sector_tag == "sector_weak":
        adj -= 2.0

    if news_tag == "positive_news":
        adj += 1.5
    if disc_tag == "positive_disclosure":
        adj += 1.5
    if earn_tag == "earnings_beat":
        adj += 2.0
    elif earn_tag == "guidance_up":
        adj += 1.5
    if sector_tag == "sector_strong":
        adj += 1.0

    return max(-8.0, min(8.0, adj))
