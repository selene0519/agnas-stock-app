"""validation_display_policy.py — retrospective validation 결과를 UI 표시 정책으로 변환

소급 검증 통계(1,905건)를 기반으로 추천 항목별 진단 문구를 생성합니다.
점수·랭킹·entry/target/stop에 영향 없음 — 표시 전용.

검증 기준 (retrospective_action_tag_validation_summary.json):
  entryTimingScore HIGH(70+)   → WR 36.1% (n=1,096)
  entryTimingScore MID(55-69)  → WR 25.7% (n=625)
  entryTimingScore LOW(40-54)  → WR 9.6%  (n=179)
  모멘텀 지속 태그              → WR 38.4% (n=690)
  추세 유지 태그               → WR 34.5% (n=633)
  눌림목 태그                  → WR 21.6% (n=71)
  단기 과매도 반등 태그          → WR 14.3% (n=159)
  손절 선도달 위험 태그          → WR 3.9%  (n=126)
  관찰 유지 action             → WR 10.0% (n=77)
  추격 금지 action             → WR 35.7% (n=235)
"""
from __future__ import annotations

import math
from typing import Any


# ─── 정책 상수 ────────────────────────────────────────────────────────────────

_HIGH_ET = 70.0   # entryTimingScore HIGH 임계값
_LOW_ET  = 55.0   # entryTimingScore 주의 임계값

_STRONG_STRATEGY_TAGS = {"모멘텀 지속", "추세 유지"}  # WR ≥ 34%
_WEAK_STRATEGY_TAGS   = {"눌림목", "단기 과매도 반등"}  # WR ≤ 22%

_STOP_RISK_TAG = "손절 선도달 위험"  # WR 3.9% — 강한 경고

_JOURNAL_SAMPLE_COUNT = 1905


# ─── 유틸 ────────────────────────────────────────────────────────────────────

def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def _tags(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(t) for t in v]
    if isinstance(v, str):
        try:
            import json
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [str(t) for t in parsed]
        except Exception:
            pass
        return [v] if v else []
    return []


# ─── 개별 policy 함수 ─────────────────────────────────────────────────────────

def build_entry_timing_warning(entry_timing_score: float | None) -> str:
    """
    Policy A/B: entryTimingScore 기반 진입 적시성 문구.
    - A: score < 55  → 경고
    - B: score >= 70 → 양호 표시
    """
    et = _f(entry_timing_score)
    if et is None:
        return ""
    if et < _LOW_ET:
        return f"진입 적시성 낮음 (검증 WR {9.6:.0f}% — HIGH 구간 {36.1:.0f}% 대비 낮음)"
    if et >= _HIGH_ET:
        return f"진입 적시성 양호 (검증 WR {36.1:.0f}%)"
    return f"진입 적시성 보통 (검증 WR {25.7:.0f}%)"


def build_strategy_validation_note(strategy_tags: list[str] | str | None) -> str:
    """
    Policy C/D: 전략 태그 기반 과거 검증 문구.
    - C: 강한 태그(모멘텀 지속/추세 유지) → 양호
    - D: 약한 태그(눌림목/단기 과매도 반등) → 성과 약함 경고
    """
    tags = _tags(strategy_tags)
    tag_set = set(tags)

    weak_present   = tag_set & _WEAK_STRATEGY_TAGS
    strong_present = tag_set & _STRONG_STRATEGY_TAGS

    if weak_present and strong_present:
        return (
            f"전략 태그 혼재 "
            f"(강: {', '.join(sorted(strong_present))} / 약: {', '.join(sorted(weak_present))}). "
            f"약 태그({', '.join(sorted(weak_present))})는 검증 WR 14~22%."
        )
    if weak_present:
        tags_str = ", ".join(sorted(weak_present))
        return (
            f"전략 태그 '{tags_str}' 는 과거 검증에서 성과가 약했습니다 "
            f"(검증 WR 14~22%, 전체 평균 {30.9:.0f}% 대비 낮음)."
        )
    if strong_present:
        tags_str = ", ".join(sorted(strong_present))
        return (
            f"전략 태그 '{tags_str}' 는 과거 검증에서 상대적으로 강했습니다 "
            f"(검증 WR 34~38%)."
        )
    return ""


def build_risk_validation_note(risk_tags: list[str] | str | None) -> str:
    """
    Policy E: 리스크 태그 기반 경고 문구.
    - E: '손절 선도달 위험' 태그 → 강한 경고 (WR 3.9%)
    """
    tags = _tags(risk_tags)
    if _STOP_RISK_TAG in tags:
        return (
            f"'{_STOP_RISK_TAG}' 태그 감지. "
            f"과거 검증 WR {3.9:.1f}% — 손절 선도달 빈도가 높습니다. "
            "포지션 크기 축소 또는 관망 고려."
        )
    return ""


def build_action_validation_note(main_action: str | None) -> str:
    """
    Policy F/G: mainAction 기반 과거 검증 문구.
    - F: 관찰 유지 → 성과 약함 경고 (WR 10.0%)
    - G: 추격 금지 → 평균 성과 약함 신규 진입 비권장 (WR 35.7% but 추격 진입 리스크)
    """
    action = str(main_action or "").strip()
    if action == "관찰 유지":
        return (
            "과거 검증에서 '관찰 유지' 구간의 성과가 약했습니다 "
            f"(검증 WR {10.0:.0f}%, n=77). 즉시 진입보다 조건 확인 후 대기 권장."
        )
    if action == "추격 금지":
        return (
            "단기 목표 도달 가능성은 있으나 "
            "신규 추격 진입은 손절 위험이 높아 권장하지 않습니다 "
            f"(추격 진입 검증 WR {35.7:.0f}%이나 추격 손절 위험 수반). "
            "기보유자는 익절 수준 확인 권장."
        )
    return ""


def build_journal_evidence_status(item: dict[str, Any]) -> dict[str, Any]:
    """
    journalEvidence 필드 생성.
    현재 journal은 종목 단위 이력이 없으므로 항상 집합 통계 기반.
    """
    symbol = item.get("symbol") or item.get("ticker") or ""
    market = item.get("market") or "kr"
    et_score = _f(item.get("entryTimingScore"))
    main_action = str(item.get("mainAction") or "")

    return {
        "status": "INSUFFICIENT_DATA",
        "reason": "종목별 journal 이력이 없어 집합 통계를 사용합니다",
        "sampleType": "aggregate_tag_based",
        "sampleCount": _JOURNAL_SAMPLE_COUNT,
        "market": market,
        "symbol": symbol,
        "note": (
            f"1,905건 소급 검증 기준. "
            f"entryTimingScore={et_score:.0f}" if et_score is not None else "1,905건 소급 검증 기준"
        ),
        "upgradeRequirement": "종목별 10건 이상 평가 완료 시 CONFIRMED 상태로 전환 예정",
    }


# ─── stabilizer item 전처리 ───────────────────────────────────────────────────

def _enrich_from_indicators(item: dict[str, Any]) -> None:
    """
    apply_quant_overlay 이후 item.indicators 에서 진단 필드를 계산해 item에 주입.
    entryTimingScore / mainAction / riskTags 가 없을 때만 채운다.
    (기존 값이 있으면 덮어쓰지 않음)
    """
    ind = item.get("indicators") or {}
    rsi      = _f(ind.get("rsi14"))
    dist20   = _f(ind.get("distanceToMa20"))
    atr_pct  = _f(ind.get("atr14Pct"))
    vol_r    = _f(ind.get("volumeRatio20"))
    rr       = _f(item.get("rrActual"))

    # entryTimingScore
    if item.get("entryTimingScore") is None:
        try:
            from app.services.entry_timing import compute as _et_compute
            _et = _et_compute(rr=rr, oe_score=None, dist_ma20_pct=dist20, rsi14=rsi, vol_ratio=vol_r)
            item["entryTimingScore"] = _et.get("score")
        except Exception:
            pass

    # mainAction (decisionBucket 기반 빠른 매핑)
    if not item.get("mainAction"):
        db = str(item.get("decisionBucket") or "")
        et = _f(item.get("entryTimingScore"))
        mode = str(item.get("mode") or "balanced").lower()
        _min_et = {"conservative": 70.0, "balanced": 65.0, "aggressive": 55.0}.get(mode, 65.0)

        risk_flags = item.get("riskFlags") or []
        if "RSI_OVERHEATED" in risk_flags or "GAP_UP_15PCT" in risk_flags:
            item["mainAction"] = "추격 금지"
        elif db in {"오늘 진입", "추천"} and (et is None or et >= _min_et):
            item["mainAction"] = "오늘 진입"
        elif db in {"오늘 진입", "추천", "기다림", "다음 진입"}:
            item["mainAction"] = "눌림 대기"
        elif db in {"관찰", "관찰 유지", "대기 관찰"}:
            item["mainAction"] = "관찰 유지"
        elif db in {"추격 금지"}:
            item["mainAction"] = "추격 금지"
        else:
            item["mainAction"] = "관찰 유지"

    # riskTags (riskFlags 기반 간소 계산)
    if not item.get("riskTags"):
        tags: list[str] = []
        risk_flags = item.get("riskFlags") or []
        if "RSI_OVERHEATED" in risk_flags:
            tags.append("과열 주의")
        elif rsi is not None and 44 <= rsi <= 56:
            tags.append("RSI 전환 구간")
        et = _f(item.get("entryTimingScore"))
        if rr is not None and rr > 2.5 and et is not None and et < 45:
            tags.append("손절 선도달 위험")
        if atr_pct is not None and atr_pct >= 5:
            tags.append("변동성 확대")
        if vol_r is not None and vol_r < 0.5:
            tags.append("거래량 부족")
        item["riskTags"] = tags[:2]


# ─── 통합 함수 ────────────────────────────────────────────────────────────────

def build_validation_display(item: dict[str, Any]) -> dict[str, Any]:
    """
    추천 항목 dict에서 validationDisplay 필드를 생성합니다.
    점수·랭킹에 영향 없음 — 표시 전용.

    Returns:
        dict with keys: entryTimingNote, strategyNote, riskNote, actionNote,
                        severityLevel, displayFlags
    """
    et_score     = _f(item.get("entryTimingScore"))
    strategy_tags = item.get("strategyTags") or []
    risk_tags     = item.get("riskTags") or []
    main_action   = str(item.get("mainAction") or "")

    et_note       = build_entry_timing_warning(et_score)
    strategy_note = build_strategy_validation_note(strategy_tags)
    risk_note     = build_risk_validation_note(risk_tags)
    action_note   = build_action_validation_note(main_action)

    # active policy codes
    flags: list[str] = []
    if et_score is not None and et_score < _LOW_ET:
        flags.append("A")
    elif et_score is not None and et_score >= _HIGH_ET:
        flags.append("B")

    tag_set = set(_tags(strategy_tags))
    if tag_set & _STRONG_STRATEGY_TAGS:
        flags.append("C")
    if tag_set & _WEAK_STRATEGY_TAGS:
        flags.append("D")

    if _STOP_RISK_TAG in _tags(risk_tags):
        flags.append("E")

    if main_action == "관찰 유지":
        flags.append("F")
    if main_action == "추격 금지":
        flags.append("G")

    # severity: HIGH (A or E), MED (D or F), LOW (G), OK (B or C only)
    if "A" in flags or "E" in flags:
        severity = "HIGH"
    elif "D" in flags or "F" in flags:
        severity = "MED"
    elif "G" in flags:
        severity = "LOW"
    else:
        severity = "OK"

    return {
        "entryTimingNote": et_note,
        "strategyNote": strategy_note,
        "riskNote": risk_note,
        "actionNote": action_note,
        "severityLevel": severity,
        "displayFlags": flags,
        "dataSource": "retrospective_1905_rows",
    }


def enrich_item_and_build(item: dict[str, Any]) -> None:
    """
    stabilizer item에 entryTimingScore/mainAction/riskTags를 주입하고
    validationDisplay + journalEvidence 를 item에 추가합니다.
    점수·랭킹에 영향 없음 — 표시 전용.
    """
    _enrich_from_indicators(item)
    item["validationDisplay"] = build_validation_display(item)
    item["journalEvidence"] = build_journal_evidence_status(item)
