"""
MONE Phase 6 — Claude API News Sentiment Analysis
Skeleton integration for Claude API-based news sentiment analysis.
Gracefully degrades to keyword-based sentiment if Claude API unavailable.

Design:
- Non-blocking: Errors fallback to news_sentiment_engine keyword analysis
- Credentials optional: Works without ANTHROPIC_API_KEY (uses fallback)
- Caching: Results cached for 24 hours
- Graceful degradation: Uses existing keyword-based fallback
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
import os
_APP_DIR = Path(__file__).resolve().parents[3]  # backend/app/services → backend/app → backend → mone-web-app
REPO_ROOT = Path(os.environ.get("MONE_REPO_ROOT", _APP_DIR.parent)).resolve()
REPORT_DIR = REPO_ROOT / "reports"
CACHE_TTL_SEC = 24 * 3600  # 24시간

# ── Claude API 설정 ──────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_SENTIMENT_MODEL", "claude-haiku-4-5-20251001")


def _read_cache(market: str) -> dict[str, dict[str, Any]]:
    """Claude API 캐시 로드. 만료됐거나 없으면 빈 dict 반환."""
    cache_path = REPORT_DIR / f"claude_news_sentiment_cache_{market}.json"
    try:
        if not cache_path.exists():
            return {}
        with cache_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        age = time.time() - float(payload.get("built_at", 0))
        if age > CACHE_TTL_SEC:
            return {}  # 만료
        return payload.get("data", {})
    except Exception:
        return {}


def _write_cache(market: str, data: dict[str, dict[str, Any]]) -> None:
    """Claude API 결과를 캐시에 저장."""
    cache_path = REPORT_DIR / f"claude_news_sentiment_cache_{market}.json"
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "market": market,
            "built_at": time.time(),
            "count": len(data),
            "data": data,
        }
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        pass


def _call_claude_api(
    market: str,
    symbol: str,
    name: str,
    recent_news: list[dict[str, Any]],
    recent_disclosures: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    Claude API를 호출해 뉴스/공시 감성을 분석한다.
    - 반환: {"sentiment": "positive"|"negative"|"neutral", "confidence": 0~100, "reasoning": str}
    - 실패 시 None 반환 (폴백 트리거)
    """
    if not ANTHROPIC_API_KEY:
        return None  # API 키 없으면 폴백

    try:
        import anthropic
    except ImportError:
        return None  # 패키지 없으면 폴백

    # 뉴스/공시 요약
    news_summary = "\n".join(
        f"- {item.get('title', item.get('headline', ''))}"
        for item in recent_news[:5]
    ) or "(최근 뉴스 없음)"

    disc_summary = "\n".join(
        f"- {item.get('title', '')}"
        for item in recent_disclosures[:3]
    ) or "(최근 공시 없음)"

    prompt = f"""
종목 {symbol} ({name})의 최근 뉴스와 공시를 분석해 투자 심리를 평가해주세요.

### 최근 뉴스 (5건)
{news_summary}

### 최근 공시 (3건)
{disc_summary}

### 분석 기준
1. 호재(긍정): 실적 개선, 수주, 신제품, 승인 등
2. 악재(부정): 손실, 소송, 규제, 감원 등
3. 중립: 위 범주에 속하지 않는 뉴스

### 응답 형식 (JSON)
{{
  "sentiment": "positive|negative|neutral",
  "confidence": 0~100,
  "reasoning": "한국어 설명 (50자 이내)"
}}
"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        response_text = message.content[0].text
        # JSON 추출 (마크다운 블록 포함 처리)
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0].strip()
        else:
            json_str = response_text
        result = json.loads(json_str)
        return {
            "sentiment": result.get("sentiment", "neutral").lower(),
            "confidence": min(100, max(0, int(result.get("confidence", 50)))),
            "reasoning": str(result.get("reasoning", ""))[:80],
            "source": "claude_api",
        }
    except Exception as e:
        # API 호출 실패 → 폴백 사용
        return None


def score_news_sentiment_with_claude(
    market: str,
    symbol: str,
    name: str,
    recent_news: list[dict[str, Any]] | None = None,
    recent_disclosures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Claude API를 사용한 뉴스 감성 분석.
    실패 시 keyword-based 폴백으로 자동 전환된다.

    반환:
        sentiment: "positive" | "negative" | "neutral"
        confidence: 0~100
        source: "claude_api" | "keyword_fallback"
        reasoning: 분석 사유 (Claude API 사용 시만)
    """
    # 캐시 확인
    cache = _read_cache(market)
    if symbol in cache:
        return cache[symbol]

    # Claude API 시도
    if ANTHROPIC_API_KEY:
        result = _call_claude_api(
            market,
            symbol,
            name,
            recent_news or [],
            recent_disclosures or [],
        )
        if result:
            # 캐시에 저장
            cache[symbol] = result
            _write_cache(market, cache)
            return result

    # 폴백: keyword-based 분석 (news_sentiment_engine 사용)
    from app.engine.news_sentiment_engine import score_news_sentiment

    keyword_result = score_news_sentiment(market, symbol, name)
    fallback_result = {
        "sentiment": _map_keyword_tag_to_sentiment(keyword_result.get("tag", "NEUTRAL")),
        "confidence": 60,  # keyword 기반이므로 신뢰도 낮게 설정
        "source": "keyword_fallback",
        "penalty": keyword_result.get("penalty", 0.0),
        "reasons": keyword_result.get("reasons", []),
    }
    cache[symbol] = fallback_result
    _write_cache(market, cache)
    return fallback_result


def _map_keyword_tag_to_sentiment(tag: str) -> str:
    """news_sentiment_engine 태그 → sentiment 변환."""
    if tag == "POSITIVE":
        return "positive"
    elif tag in {"HIGH_RISK", "CAUTION"}:
        return "negative"
    else:
        return "neutral"


def get_symbol_sentiment(market: str, symbol: str, name: str) -> dict[str, Any]:
    """
    단일 종목 감성 조회.
    캐시 우선, 없으면 계산.
    """
    return score_news_sentiment_with_claude(market, symbol, name)
