from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPORT_DIR = Path("reports")
CATALYST_SCORE_SUMMARY_JSON = REPORT_DIR / "catalyst_score_summary.json"
NEWS_DEDUP_SUMMARY_JSON = REPORT_DIR / "news_dedup_summary.json"
DISCLOSURE_SCORE_SUMMARY_JSON = REPORT_DIR / "disclosure_score_summary.json"
DEFAULT_CANDIDATE_FILES = [
    REPORT_DIR / "swing_candidates_us_A_top3.csv",
    REPORT_DIR / "swing_candidates_us_B_watch.csv",
    REPORT_DIR / "swing_candidates_us_C_excluded.csv",
    REPORT_DIR / "swing_candidates_kr_A_top3.csv",
    REPORT_DIR / "swing_candidates_kr_B_watch.csv",
    REPORT_DIR / "swing_candidates_kr_C_excluded.csv",
]


POSITIVE_KEYWORDS = [
    "수주",
    "계약",
    "실적",
    "흑자",
    "증가",
    "성장",
    "서프라이즈",
    "승인",
    "buyback",
    "beat",
    "growth",
    "contract",
    "order",
    "partnership",
    "approval",
]
NEGATIVE_KEYWORDS = [
    "소송",
    "적자",
    "감자",
    "증자",
    "하향",
    "리스크",
    "조사",
    "손상",
    "recall",
    "lawsuit",
    "offering",
    "miss",
    "downgrade",
    "investigation",
    "risk",
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
            value = (
                value.replace(",", "")
                .replace("%", "")
                .replace("배", "")
                .replace("x", "")
                .replace("X", "")
                .strip()
            )
            if value in {"", "-", "nan", "None", "확인 필요"}:
                return default
        return float(value)
    except Exception:
        return default


def _clip(value: float) -> int:
    return int(max(0, min(100, round(value))))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _text_of(item: Any) -> str:
    if isinstance(item, dict):
        return " ".join(
            _safe_str(item.get(key))
            for key in ["title", "headline", "summary", "description", "form", "type", "category"]
        ).strip()
    return _safe_str(item)


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = _safe_str(value)
    if not text:
        return None
    if text.isdigit():
        try:
            timestamp = int(text)
            if timestamp > 10_000_000_000:
                timestamp = timestamp // 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except Exception:
            return None
    for fmt in ["%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ"]:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _age_days(value: Any, now: datetime | None = None) -> float:
    parsed = _parse_datetime(value)
    if parsed is None:
        return 999.0
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return max(0.0, (base - parsed).total_seconds() / 86400)


def deduplicate_news_items(news_items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    unique: list[Any] = []
    for item in news_items:
        text = _text_of(item).lower()
        key = " ".join(text.split())
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _sentiment_score(text: str) -> tuple[int, list[str], list[str]]:
    lower = text.lower()
    positives = [word for word in POSITIVE_KEYWORDS if word.lower() in lower]
    negatives = [word for word in NEGATIVE_KEYWORDS if word.lower() in lower]
    score = 50 + min(30, len(positives) * 8) - min(35, len(negatives) * 10)
    return _clip(score), positives, negatives


def _news_scores(news_items: list[Any], now: datetime | None = None) -> tuple[int, int, list[str], list[str], int]:
    unique = deduplicate_news_items(news_items)
    if not unique:
        return 50, 50, ["최근 뉴스 없음: 중립 유지"], [], 0
    importance_values: list[int] = []
    freshness_values: list[int] = []
    reasons: list[str] = []
    warnings: list[str] = []
    for item in unique:
        text = _text_of(item)
        sentiment, positives, negatives = _sentiment_score(text)
        explicit = _safe_float(item.get("importance") if isinstance(item, dict) else None, sentiment)
        importance = _clip((sentiment * 0.7) + (explicit * 0.3))
        date_value = None
        if isinstance(item, dict):
            date_value = item.get("datetime") or item.get("published_at") or item.get("date") or item.get("time")
        age = _age_days(date_value, now)
        freshness = _clip(100 - min(90, age * 8))
        importance_values.append(importance)
        freshness_values.append(freshness)
        if positives:
            reasons.append("긍정 뉴스: " + ", ".join(positives[:3]))
        if negatives:
            warnings.append("부정 뉴스: " + ", ".join(negatives[:3]))
    return (
        _clip(sum(importance_values) / len(importance_values)),
        _clip(sum(freshness_values) / len(freshness_values)),
        list(dict.fromkeys(reasons)),
        list(dict.fromkeys(warnings)),
        len(unique),
    )


def _disclosure_score(items: list[Any]) -> tuple[int, list[str], list[str]]:
    if not items:
        return 50, ["공시 특이사항 없음: 중립 유지"], []
    score = 50
    reasons: list[str] = []
    warnings: list[str] = []
    for item in items:
        text = _text_of(item)
        _, positives, negatives = _sentiment_score(text)
        form = _safe_str(item.get("form") if isinstance(item, dict) else "")
        if form in {"8-K", "10-Q", "10-K"}:
            score += 4
            reasons.append(f"SEC {form} 확인")
        if positives:
            score += min(15, len(positives) * 6)
            reasons.append("긍정 공시/이벤트: " + ", ".join(positives[:3]))
        if negatives:
            score -= min(30, len(negatives) * 10)
            warnings.append("악재 공시: " + ", ".join(negatives[:3]))
    return _clip(score), list(dict.fromkeys(reasons)), list(dict.fromkeys(warnings))


def _disclosure_sources(items: list[Any]) -> set[str]:
    sources: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        source_text = " ".join(
            _safe_str(item.get(key)).upper()
            for key in ["source", "provider", "market", "form", "type", "category"]
        )
        if "DART" in source_text or "KR" in source_text or "KOREA" in source_text:
            sources.add("DART")
        if "SEC" in source_text or any(form in source_text for form in ["8-K", "10-Q", "10-K"]):
            sources.add("SEC")
    return sources


def _earnings_score(row: dict[str, Any], api_context: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    earnings = {}
    for key in ["earnings", "fundamentals"]:
        value = api_context.get(key)
        if isinstance(value, dict):
            earnings.update(value)
    reasons: list[str] = []
    warnings: list[str] = []
    score = 50
    revenue_growth = _safe_float(earnings.get("revenue_growth") or row.get("revenue_growth"), 0)
    op_growth = _safe_float(earnings.get("operating_income_growth") or row.get("operating_income_growth"), 0)
    net_growth = _safe_float(earnings.get("net_income_growth") or row.get("net_income_growth"), 0)
    op_margin = _safe_float(earnings.get("operating_margin") or row.get("operating_margin"), 0)
    roe = _safe_float(earnings.get("roe") or row.get("roe"), 0)
    debt_ratio = _safe_float(earnings.get("debt_ratio") or row.get("debt_ratio"), 0)
    surprise = _safe_float(earnings.get("earnings_surprise_pct") or row.get("earnings_surprise_pct"), 0)
    per = _safe_float(earnings.get("per") or row.get("per"), 0)
    pbr = _safe_float(earnings.get("pbr") or row.get("pbr"), 0)
    psr = _safe_float(earnings.get("psr") or row.get("psr"), 0)

    for label, value in [("매출 성장", revenue_growth), ("영업이익 성장", op_growth), ("순이익 성장", net_growth)]:
        if value >= 20:
            score += 8
            reasons.append(f"{label} 우수")
        elif value < -10:
            score -= 8
            warnings.append(f"{label} 둔화")
    if op_margin >= 15:
        score += 6
        reasons.append("영업이익률 우수")
    if roe >= 12:
        score += 5
        reasons.append("ROE 우수")
    if debt_ratio >= 200:
        score -= 8
        warnings.append("부채비율 부담")
    if surprise >= 5:
        score += 8
        reasons.append("실적 서프라이즈")
    elif surprise <= -5:
        score -= 8
        warnings.append("실적 쇼크")
    if per > 0 and per < 15:
        score += 2
    if pbr > 0 and pbr < 2:
        score += 2
    if psr > 0 and psr < 3:
        score += 2
    if not reasons and not warnings:
        warnings.append("실적 데이터 부족: 보수 점수 적용")
    return _clip(score), reasons, warnings


def _supply_score(row: dict[str, Any], api_context: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    supply = api_context.get("supply") if isinstance(api_context.get("supply"), dict) else {}
    fallback = api_context.get("row_fallback") if isinstance(api_context.get("row_fallback"), dict) else {}
    volume_ratio = _safe_float(supply.get("volume_ratio") or fallback.get("volume_ratio") or row.get("volume_ratio"), 1)
    trading_value = _safe_float(supply.get("trading_value") or fallback.get("trading_value") or row.get("trading_value") or row.get("turnover"), 0)
    institutional = _safe_float(supply.get("institutional_flow_score"), 0)
    foreign = _safe_float(supply.get("foreign_flow_score"), 0)
    score = 45
    reasons: list[str] = []
    warnings: list[str] = []
    if volume_ratio >= 2:
        score += 18
        reasons.append("거래량 강한 증가")
    elif volume_ratio >= 1.3:
        score += 10
        reasons.append("거래량 증가")
    elif volume_ratio < 0.8:
        score -= 8
        warnings.append("거래량 부진")
    if trading_value >= 10_000_000_000:
        score += 8
        reasons.append("거래대금 충분")
    if institutional > 0:
        score += min(10, institutional)
        reasons.append("기관 수급 우호")
    if foreign > 0:
        score += min(10, foreign)
        reasons.append("외국인 수급 우호")
    if not reasons:
        warnings.append("수급 데이터 부족: 보수 점수 적용")
    return _clip(score), reasons, warnings


def _row_feature_score(row: dict[str, Any], api_context: dict[str, Any]) -> tuple[int, list[str], list[str], list[str]]:
    fallback = api_context.get("row_fallback") if isinstance(api_context.get("row_fallback"), dict) else {}
    reasons: list[str] = []
    warnings: list[str] = []
    logs: list[str] = []
    score = 50.0

    candidate_score = _safe_float(row.get("score") or row.get("technical_score") or fallback.get("score"), 0)
    if candidate_score > 0:
        score += (candidate_score - 50) * 0.40
        if candidate_score >= 80:
            logs.append("후보 기본 점수 우위 반영: 가산")
        elif candidate_score <= 35:
            logs.append("후보 기본 점수 약함: 감점")

    relative_strength = _safe_float(row.get("relative_strength_score") or fallback.get("relative_strength_score"), 0)
    if relative_strength > 0:
        score += (relative_strength - 50) * 0.18
        if relative_strength >= 65:
            reasons.append("상대강도 우위")
            logs.append("상대강도 우위 반영: 가산")
        elif relative_strength <= 35:
            warnings.append("상대강도 약함")
            logs.append("상대강도 약함: 감점")

    news_momentum = _safe_float(row.get("news_momentum_score") or fallback.get("news_momentum_score"), 0)
    if news_momentum > 0:
        score += (news_momentum - 50) * 0.12
        if news_momentum >= 65:
            logs.append("뉴스 모멘텀 우위 반영: 가산")
        elif news_momentum <= 35:
            logs.append("뉴스 모멘텀 약함: 감점")

    earnings_growth = _safe_float(row.get("earnings_growth_score") or fallback.get("earnings_growth_score"), 0)
    if earnings_growth > 0:
        score += (earnings_growth - 50) * 0.12
        if earnings_growth >= 65:
            logs.append("실적 성장 점수 우위 반영: 가산")
        elif earnings_growth <= 35:
            logs.append("실적 성장 점수 약함: 감점")

    trading_value = _safe_float(row.get("trading_value") or row.get("turnover") or fallback.get("trading_value"), 0)
    market = _safe_str(row.get("market") or fallback.get("market"))
    if trading_value > 0:
        if "한국" in market:
            if trading_value >= 100_000_000_000:
                score += 8
                reasons.append("거래대금 강함")
                logs.append("거래대금 증가 반영: 가산")
            elif trading_value >= 20_000_000_000:
                score += 4
                logs.append("거래대금 증가 반영: 소폭 가산")
            elif trading_value < 5_000_000_000:
                score -= 5
                warnings.append("거래대금 약함")
                logs.append("거래대금 약함: 소폭 감점")
        else:
            if trading_value >= 2_000_000_000:
                score += 8
                reasons.append("거래대금 강함")
                logs.append("거래대금 증가 반영: 가산")
            elif trading_value >= 500_000_000:
                score += 4
                logs.append("거래대금 증가 반영: 소폭 가산")
            elif trading_value < 100_000_000:
                score -= 5
                warnings.append("거래대금 약함")
                logs.append("거래대금 약함: 소폭 감점")

    sector_theme = f"{_safe_str(row.get('sector'))} {_safe_str(row.get('theme'))}".lower()
    if any(token in sector_theme for token in ["ai", "반도체", "방산", "조선", "클라우드"]):
        score += 3
        logs.append("섹터/테마 모멘텀 반영: 소폭 가산")
    if any(token in sector_theme for token in ["가상자산", "비트코인", "코인", "speculative"]):
        score -= 3
        logs.append("고변동 테마 리스크 반영: 소폭 감점")

    return _clip(score), list(dict.fromkeys(reasons)), list(dict.fromkeys(warnings)), list(dict.fromkeys(logs))


def _component_statuses(
    news_items: list[Any],
    disclosure_items: list[Any],
    row: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, str]:
    has_api_errors = bool([x for x in _as_list(context.get("api_errors")) if _safe_str(x)])
    earnings_context = context.get("earnings") if isinstance(context.get("earnings"), dict) else {}
    fundamentals_context = context.get("fundamentals") if isinstance(context.get("fundamentals"), dict) else {}
    supply_context = context.get("supply") if isinstance(context.get("supply"), dict) else {}
    has_row_supply = bool(_safe_float(row.get("trading_value") or row.get("turnover"), 0) > 0 or _safe_float(row.get("volume_ratio"), 0) > 0)
    has_row_earnings = any(_safe_float(row.get(key), 0) != 0 for key in ["revenue_growth", "operating_income_growth", "earnings_growth_score", "roe"])
    return {
        "news_data_status": "api_confirmed" if news_items else ("fallback_default" if has_api_errors else "no_recent_issue"),
        "disclosure_data_status": "api_confirmed" if disclosure_items else ("fallback_default" if has_api_errors else "no_recent_issue"),
        "earnings_data_status": "api_confirmed" if earnings_context or fundamentals_context or has_row_earnings else "data_missing",
        "supply_data_status": "api_confirmed" if supply_context else ("neutral_confirmed" if has_row_supply else "data_missing"),
    }


def calculate_catalyst_score(row: dict[str, Any], api_context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = dict(api_context or {})
    reasons: list[str] = []
    warnings: list[str] = []
    change_log: list[str] = []
    for warning in _as_list(context.get("api_warnings")):
        if _safe_str(warning):
            warnings.append(_safe_str(warning))
    for error in _as_list(context.get("api_errors")):
        if _safe_str(error):
            warnings.append("API 실패: " + _safe_str(error))
    kis_token_status = _safe_str(context.get("kis_token_status")).lower()
    if kis_token_status in {"failed", "missing"} or context.get("kis_token_failed"):
        warnings.append("KIS 토큰 발급 실패: fallback 점수 사용")

    news_items = _as_list(context.get("news"))
    news_score, freshness_score, news_reasons, news_warnings, unique_news_count = _news_scores(news_items)
    disclosure_items = _as_list(context.get("disclosures")) + _as_list(context.get("filings"))
    disclosure_score, disclosure_reasons, disclosure_warnings = _disclosure_score(disclosure_items)
    earnings_score, earnings_reasons, earnings_warnings = _earnings_score(row, context)
    supply_score, supply_reasons, supply_warnings = _supply_score(row, context)
    row_feature_score, row_reasons, row_warnings, row_logs = _row_feature_score(row, context)
    statuses = _component_statuses(news_items, disclosure_items, row, context)

    reasons.extend(news_reasons + disclosure_reasons + earnings_reasons + supply_reasons + row_reasons)
    warnings.extend(news_warnings + disclosure_warnings + earnings_warnings + supply_warnings + row_warnings)
    if unique_news_count:
        change_log.append(f"뉴스 중복 제거 후 {unique_news_count}건 반영")
        if news_score >= 60:
            change_log.append("긍정 뉴스 확인: 가산")
        elif news_score <= 40:
            change_log.append("부정 뉴스 확인: 감점")
    else:
        change_log.append("최근 뉴스 없음: 중립 유지")
    if news_items and freshness_score < 40:
        change_log.append("뉴스 신선도 낮음: 소폭 감점")
    if disclosure_warnings:
        sources = _disclosure_sources(disclosure_items)
        if "DART" in sources:
            change_log.append("DART 부정 공시 확인: 감점")
        if "SEC" in sources:
            change_log.append("SEC 부정 공시 확인: 감점")
        if not sources:
            change_log.append("부정 공시 확인: 감점")
    elif disclosure_items:
        change_log.append("공시 특이사항 확인: 중립 유지")
    else:
        change_log.append("공시 특이사항 없음: 중립 유지")
    if not earnings_reasons and not earnings_warnings:
        change_log.append("실적 특이사항 없음: 중립 유지")
    elif earnings_score < 45:
        change_log.append("실적 점수 약함: 소폭 감점")
    elif earnings_score > 58:
        change_log.append("실적 점수 우위 반영: 가산")
    if any("실적 데이터 부족" in str(x) for x in earnings_warnings):
        change_log.append("실적 데이터 부족: 보수 점수 적용")
    if supply_score < 45:
        change_log.append("수급 점수 약함: 소폭 감점")
    elif supply_score >= 58:
        change_log.append("수급 점수 우위 반영: 가산")
    elif not supply_reasons:
        change_log.append("수급 특이사항 없음: 중립 유지")
    change_log.extend(row_logs)
    if context.get("api_errors"):
        change_log.append("API 실패 항목은 데이터 부족 경고로 처리")
    if kis_token_status in {"failed", "missing"} or context.get("kis_token_failed"):
        change_log.append("KIS 인증 실패 항목은 fallback 점수로 처리")

    score = (
        news_score * 0.16
        + freshness_score * 0.08
        + disclosure_score * 0.16
        + earnings_score * 0.16
        + supply_score * 0.20
        + row_feature_score * 0.24
    )
    if not context.get("news") and not disclosure_items:
        score -= 0
    catalyst_score = _clip(score)
    if not reasons:
        reasons.append("촉매 데이터 중립")
    if not warnings:
        warnings.append("특이 경고 없음")
    if not change_log:
        change_log.append("점수 변화 없음")

    return {
        "catalyst_score": catalyst_score,
        "news_importance_score": news_score,
        "news_freshness_score": freshness_score,
        "disclosure_score": disclosure_score,
        "earnings_score": earnings_score,
        "supply_score": supply_score,
        "row_feature_score": row_feature_score,
        "catalyst_reasons": list(dict.fromkeys(reasons)),
        "catalyst_warnings": list(dict.fromkeys(warnings)),
        "decision_change_log": list(dict.fromkeys(change_log)),
        "catalyst_data_status": "fallback_default" if context.get("api_errors") else ("api_confirmed" if news_items or disclosure_items else "mixed_row_fallback"),
        "news_data_status": statuses["news_data_status"],
        "disclosure_data_status": statuses["disclosure_data_status"],
        "earnings_data_status": statuses["earnings_data_status"],
        "supply_data_status": statuses["supply_data_status"],
        "catalyst_score_source": "api_confirmed" if news_items or disclosure_items else "row_fallback",
    }


def apply_catalyst_scores(candidate_df: pd.DataFrame, api_context: dict[str, Any] | None = None) -> pd.DataFrame:
    if candidate_df is None:
        return pd.DataFrame()
    out = candidate_df.copy()
    cols = [
        "catalyst_score",
        "news_importance_score",
        "news_freshness_score",
        "disclosure_score",
        "earnings_score",
        "supply_score",
        "catalyst_reasons",
        "catalyst_warnings",
        "decision_change_log",
        "catalyst_data_status",
        "news_data_status",
        "disclosure_data_status",
        "earnings_data_status",
        "supply_data_status",
        "catalyst_score_source",
    ]
    if out.empty:
        for col in cols:
            if col not in out.columns:
                out[col] = []
        return out
    context = api_context or {}
    rows = []
    for row in out.to_dict(orient="records"):
        symbol = _safe_str(row.get("symbol") or row.get("ticker")).upper()
        row_context = context.get(symbol, context) if isinstance(context, dict) else {}
        if not isinstance(row_context, dict):
            row_context = {}
        rows.append(calculate_catalyst_score(row, row_context))
    result = pd.DataFrame(rows, index=out.index)
    for col in cols:
        values = result[col]
        if col in {"catalyst_reasons", "catalyst_warnings", "decision_change_log"}:
            values = values.apply(lambda x: " / ".join(map(str, x)) if isinstance(x, list) else _safe_str(x))
        out[col] = values.values
    return out


def _read_candidate_frames(candidate_files: list[str | Path] | None = None) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for path in candidate_files or DEFAULT_CANDIDATE_FILES:
        try:
            p = Path(path)
            if p.exists() and p.stat().st_size > 0:
                frames.append(pd.read_csv(p))
        except Exception:
            continue
    return frames


def _concat_candidate_frames(candidate_files: list[str | Path] | None = None, candidate_df: pd.DataFrame | None = None) -> pd.DataFrame:
    frames = []
    if candidate_df is not None:
        frames.append(candidate_df.copy())
    if candidate_files is not None or candidate_df is None:
        frames.extend(_read_candidate_frames(candidate_files))
    if not frames:
        return pd.DataFrame()
    populated_frames = [frame for frame in frames if not frame.empty]
    if populated_frames:
        return pd.concat(populated_frames, ignore_index=True, sort=False)
    return frames[0].copy()


def build_catalyst_score_summary(
    candidate_files: list[str | Path] | None = None,
    candidate_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    df = _concat_candidate_frames(candidate_files, candidate_df)
    scores = pd.to_numeric(df.get("catalyst_score", pd.Series(dtype=float)), errors="coerce")
    row_count = int(len(df))
    fallback_score_used = bool(row_count == 0 or scores.fillna(0).eq(0).all())
    return {
        "row_count": row_count,
        "avg_catalyst_score": round(float(scores.mean()), 4) if scores.notna().any() else 0.0,
        "min_catalyst_score": round(float(scores.min()), 4) if scores.notna().any() else 0.0,
        "max_catalyst_score": round(float(scores.max()), 4) if scores.notna().any() else 0.0,
        "news_score_available": bool(pd.to_numeric(df.get("news_importance_score", pd.Series(dtype=float)), errors="coerce").gt(0).any()),
        "disclosure_score_available": bool(pd.to_numeric(df.get("disclosure_score", pd.Series(dtype=float)), errors="coerce").gt(0).any()),
        "earnings_score_available": bool(pd.to_numeric(df.get("earnings_score", pd.Series(dtype=float)), errors="coerce").gt(0).any()),
        "supply_score_available": bool(pd.to_numeric(df.get("supply_score", pd.Series(dtype=float)), errors="coerce").gt(0).any()),
        "fallback_score_used": fallback_score_used,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def save_catalyst_score_summary(
    path: str | Path | None = None,
    candidate_files: list[str | Path] | None = None,
    candidate_df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    summary = build_catalyst_score_summary(candidate_files, candidate_df)
    target = Path(path) if path is not None else CATALYST_SCORE_SUMMARY_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def _contexts_to_list(api_contexts: Any = None) -> list[dict[str, Any]]:
    if api_contexts is None:
        return []
    if isinstance(api_contexts, dict):
        if any(key in api_contexts for key in ["news", "disclosures", "filings"]):
            return [api_contexts]
        return [value for value in api_contexts.values() if isinstance(value, dict)]
    if isinstance(api_contexts, list):
        return [value for value in api_contexts if isinstance(value, dict)]
    return []


def build_news_dedup_summary(api_contexts: Any = None) -> dict[str, Any]:
    contexts = _contexts_to_list(api_contexts)
    collected: list[Any] = []
    for context in contexts:
        collected.extend(_as_list(context.get("news")))
    deduped = deduplicate_news_items(collected)
    fallback_used = len(collected) == 0
    return {
        "collected_news_count": int(len(collected)),
        "deduped_news_count": int(len(deduped)),
        "duplicate_removed_count": int(max(0, len(collected) - len(deduped))),
        "api_available": bool(len(collected) > 0),
        "fallback_used": fallback_used,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def save_news_dedup_summary(
    path: str | Path | None = None,
    api_contexts: Any = None,
) -> dict[str, Any]:
    summary = build_news_dedup_summary(api_contexts)
    target = Path(path) if path is not None else NEWS_DEDUP_SUMMARY_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def build_disclosure_score_summary(api_contexts: Any = None) -> dict[str, Any]:
    contexts = _contexts_to_list(api_contexts)
    disclosures: list[Any] = []
    for context in contexts:
        disclosures.extend(_as_list(context.get("disclosures")))
        disclosures.extend(_as_list(context.get("filings")))
    negative = 0
    positive = 0
    for item in disclosures:
        text = _text_of(item).lower()
        if any(word.lower() in text for word in NEGATIVE_KEYWORDS):
            negative += 1
        if any(word.lower() in text for word in POSITIVE_KEYWORDS):
            positive += 1
    return {
        "disclosure_count": int(len(disclosures)),
        "negative_disclosure_count": int(negative),
        "positive_disclosure_count": int(positive),
        "api_available": bool(len(disclosures) > 0),
        "fallback_used": bool(len(disclosures) == 0),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def save_disclosure_score_summary(
    path: str | Path | None = None,
    api_contexts: Any = None,
) -> dict[str, Any]:
    summary = build_disclosure_score_summary(api_contexts)
    target = Path(path) if path is not None else DISCLOSURE_SCORE_SUMMARY_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def save_catalyst_runtime_reports(
    candidate_df: pd.DataFrame | None = None,
    candidate_files: list[str | Path] | None = None,
    api_contexts: Any = None,
) -> dict[str, Any]:
    from core.api_data_quality_engine import save_api_data_quality_summary

    contexts = _contexts_to_list(api_contexts)
    warning_count = 0
    error_count = 0
    warning_reasons: list[str] = []
    for context in contexts:
        context_warnings = [x for x in _as_list(context.get("api_warnings")) if _safe_str(x)]
        warning_count += len(context_warnings)
        warning_reasons.extend(_safe_str(x) for x in context_warnings)
        error_count += len([x for x in _as_list(context.get("api_errors")) if _safe_str(x)])
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    api_fallback_used = True if error_count > 0 else None
    return {
        "api_data_quality": save_api_data_quality_summary(
            warning_count=warning_count,
            error_count=error_count,
            fallback_used=api_fallback_used,
            warning_reasons=warning_reasons,
        ),
        "catalyst_score": save_catalyst_score_summary(candidate_df=candidate_df, candidate_files=candidate_files),
        "news_dedup": save_news_dedup_summary(api_contexts=api_contexts),
        "disclosure_score": save_disclosure_score_summary(api_contexts=api_contexts),
    }
