"""postmortem.py — 추천 실패 원인 분석 및 저장 서비스 (4차 작업)

추천 검증 결과가 실패(FAIL/STOP_FIRST)인 경우
data/postmortem_ledger.csv 에 postmortem row를 저장합니다.
"""
from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = REPO_ROOT / "data"
POSTMORTEM_CSV = DATA_DIR / "postmortem_ledger.csv"

POSTMORTEM_COLS = [
    "symbol",
    "market",
    "recommendationDate",
    "validationDate",
    "winLossResult",
    "failureType",
    "failureReasonTags",
    "chartSignalAtEntry",
    "trendlineLearningStatus",
    "supportResistanceStatus",
    "newsEventTag",
    "disclosureEventTag",
    "earningsEventTag",
    "macroEventTag",
    "sectorEventTag",
    "eventRiskScore",
    "mdd",
    "stopTouched",
    "targetTouched",
    "dataSourceType",
    "eventDataSourceType",
    "postmortemSummary",
    "createdAt",
]

# 실패 유형 분류 기준
_FAILURE_TYPE_MAP = {
    "손절 도달": "STOP_FIRST",
    "목표/손절 동시 · 보수적 손절 우선": "STOP_FIRST",
    "STOP_FIRST": "STOP_FIRST",
    "SUPPORT_BREAK": "SUPPORT_BREAK",
    "TRENDLINE_BREAK": "TRENDLINE_BREAK",
    "FALSE_BREAKOUT": "FALSE_BREAKOUT",
}


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


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not POSTMORTEM_CSV.exists():
        with open(POSTMORTEM_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=POSTMORTEM_COLS).writeheader()


def _read_rows(limit: int = 2000) -> list[dict[str, Any]]:
    _ensure()
    try:
        with open(POSTMORTEM_CSV, newline="", encoding="utf-8-sig") as f:
            rows: list[dict[str, Any]] = []
            for row in csv.DictReader(f):
                rows.append(dict(row))
                if len(rows) >= limit:
                    break
        return rows
    except Exception:
        return []


def _write_rows(rows: list[dict[str, Any]]) -> None:
    _ensure()
    with open(POSTMORTEM_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=POSTMORTEM_COLS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _classify_failure_type(row: dict[str, Any]) -> str:
    """추천 row에서 failureType을 분류합니다."""
    exit_status = _as_text(row.get("exitStatus") or row.get("execution", {}).get("exitStatus", "") if isinstance(row.get("execution"), dict) else "")
    execution_reason = _as_text(row.get("executionReason") or "")

    # 직접 매핑
    for keyword, failure_type in _FAILURE_TYPE_MAP.items():
        if keyword in exit_status or keyword in execution_reason:
            return failure_type

    # 이벤트 기반 분류
    news_tag = _as_text(row.get("newsEventTag", ""))
    disc_tag = _as_text(row.get("disclosureEventTag", ""))
    earn_tag = _as_text(row.get("earningsEventTag", ""))
    macro_tag = _as_text(row.get("macroEventTag", ""))
    sector_tag = _as_text(row.get("sectorEventTag", ""))

    if earn_tag in {"earnings_miss", "guidance_down"}:
        return "EVENT_SHOCK"
    if disc_tag == "negative_disclosure":
        return "EVENT_SHOCK"
    if macro_tag in {"fomc_risk", "rate_risk", "inflation_risk", "volatility_risk"}:
        return "MACRO_PRESSURE"
    if sector_tag == "sector_weak":
        return "SECTOR_WEAKNESS"
    if news_tag == "negative_news":
        return "EVENT_SHOCK"

    # 차트 기반 분류
    trendline_status = _as_text(row.get("trendlineLearningStatus", ""))
    if trendline_status == "FAILED_ANCHOR_HISTORY":
        return "TRENDLINE_BREAK"

    support_used = row.get("supportResistanceUsed") or row.get("supportUsed")
    if support_used:
        return "SUPPORT_BREAK"

    data_src = _as_text(row.get("dataSourceType", ""))
    if data_src in {"unavailable", "placeholder", "mock"}:
        return "DATA_INSUFFICIENT"

    return "UNKNOWN"


def _build_failure_reason_tags(row: dict[str, Any]) -> str:
    """실패 원인 태그 목록을 쉼표 구분 문자열로 반환합니다."""
    tags: list[str] = []
    news_tag = _as_text(row.get("newsEventTag", ""))
    disc_tag = _as_text(row.get("disclosureEventTag", ""))
    earn_tag = _as_text(row.get("earningsEventTag", ""))
    macro_tag = _as_text(row.get("macroEventTag", ""))
    sector_tag = _as_text(row.get("sectorEventTag", ""))

    if news_tag == "negative_news":
        tags.append("negative_news")
    if disc_tag == "negative_disclosure":
        tags.append("negative_disclosure")
    if earn_tag in {"earnings_miss", "guidance_down"}:
        tags.append(earn_tag)
    if macro_tag in {"fomc_risk", "rate_risk", "inflation_risk", "volatility_risk"}:
        tags.append(macro_tag)
    if sector_tag == "sector_weak":
        tags.append("sector_weak")

    trendline_status = _as_text(row.get("trendlineLearningStatus", ""))
    if trendline_status == "FAILED_ANCHOR_HISTORY":
        tags.append("trendline_failed_history")
    if row.get("fakeBreakoutRiskUsed"):
        tags.append("fake_breakout_risk")

    data_src = _as_text(row.get("dataSourceType", ""))
    if data_src in {"unavailable", "placeholder", "mock"}:
        tags.append("data_insufficient")

    return ",".join(tags) if tags else "none"


def _build_postmortem_summary(
    symbol: str,
    failure_type: str,
    tags: str,
    row: dict[str, Any],
) -> str:
    """사람이 읽기 쉬운 postmortem 요약 문자열을 반환합니다."""
    exit_status = _as_text(
        row.get("exitStatus") or
        (row.get("execution", {}).get("exitStatus", "") if isinstance(row.get("execution"), dict) else "")
    )
    pnl = row.get("execution", {}).get("pnlPct", "") if isinstance(row.get("execution"), dict) else row.get("pnlPct", "")
    pnl_text = f" 수익률={pnl}%" if pnl not in ("", None) else ""
    summary = f"{symbol} {failure_type} | 결과={exit_status}{pnl_text}"
    if tags and tags != "none":
        summary += f" | 원인태그=[{tags}]"
    event_summary = _as_text(row.get("eventSummary", ""))
    if event_summary and event_summary != "이벤트 특이사항 없음":
        summary += f" | {event_summary[:80]}"
    return summary[:300]


def is_failure(row: dict[str, Any]) -> bool:
    """추천 row가 실패 케이스인지 판단합니다."""
    exit_status = _as_text(
        row.get("exitStatus") or
        (row.get("execution", {}).get("exitStatus", "") if isinstance(row.get("execution"), dict) else "")
    )
    win_loss = _as_text(row.get("winLossResult", ""))
    exec_status = _as_text(row.get("executionStatus", ""))

    fail_keywords = {"손절", "STOP", "stop", "FAIL", "fail", "LOSS"}
    if any(k in exit_status for k in fail_keywords):
        return True
    if any(k in win_loss for k in fail_keywords):
        return True
    if exec_status == "체결" and exit_status == "손절 도달":
        return True
    return False


def save_postmortem(
    row: dict[str, Any],
    validation_date: str | None = None,
) -> dict[str, Any]:
    """실패 케이스의 postmortem을 저장합니다.

    Parameters
    ----------
    row:              final_recommendations() 에서 나온 item dict
    validation_date:  검증 날짜 (없으면 오늘)

    Returns
    -------
    dict with status, saved (bool), postmortem_row
    """
    try:
        _ensure()
        symbol = _as_text(row.get("symbol", ""))
        market = _as_text(row.get("market", "kr"))
        if not symbol:
            return {"status": "SKIP", "saved": False, "reason": "symbol missing"}

        # 실패 판정
        if not is_failure(row):
            return {"status": "SKIP", "saved": False, "reason": "not a failure case"}

        failure_type = _classify_failure_type(row)
        failure_tags = _build_failure_reason_tags(row)

        # execution 서브딕트에서 필드 추출
        execution = row.get("execution") or {}
        if not isinstance(execution, dict):
            execution = {}

        stop_touched = bool(
            execution.get("exitStatus") == "손절 도달"
            or _as_text(row.get("stopTouched")).lower() in {"true", "1"}
        )
        target_touched = bool(
            execution.get("exitStatus") == "목표 도달"
            or _as_text(row.get("targetTouched")).lower() in {"true", "1"}
        )

        pnl = _safe_float(execution.get("pnlPct") or row.get("pnlPct"))
        mdd = pnl if pnl is not None and pnl < 0 else None

        postmortem_row: dict[str, Any] = {
            "symbol": symbol,
            "market": market,
            "recommendationDate": _as_text(
                row.get("sourceDate") or row.get("priceSourceDate") or row.get("generatedAt") or ""
            )[:10],
            "validationDate": (validation_date or datetime.now().strftime("%Y-%m-%d"))[:10],
            "winLossResult": _as_text(row.get("winLossResult") or execution.get("exitStatus") or "FAIL"),
            "failureType": failure_type,
            "failureReasonTags": failure_tags,
            "chartSignalAtEntry": _as_text(
                row.get("entryBasis") or row.get("chartSignalSummary", {}).get("chartSignalTag", "") if isinstance(row.get("chartSignalSummary"), dict) else ""
            ),
            "trendlineLearningStatus": _as_text(row.get("trendlineLearningStatus", "NO_DATA")),
            "supportResistanceStatus": "used" if row.get("supportResistanceUsed") else "not_used",
            "newsEventTag": _as_text(row.get("newsEventTag", "unknown")),
            "disclosureEventTag": _as_text(row.get("disclosureEventTag", "unknown")),
            "earningsEventTag": _as_text(row.get("earningsEventTag", "unknown")),
            "macroEventTag": _as_text(row.get("macroEventTag", "unknown")),
            "sectorEventTag": _as_text(row.get("sectorEventTag", "unknown")),
            "eventRiskScore": _safe_float(row.get("eventRiskScore")) or 0.0,
            "mdd": round(mdd, 3) if mdd is not None else "",
            "stopTouched": stop_touched,
            "targetTouched": target_touched,
            "dataSourceType": _as_text(row.get("dataSourceType", "")),
            "eventDataSourceType": _as_text(row.get("eventDataSourceType", "")),
            "postmortemSummary": _build_postmortem_summary(symbol, failure_type, failure_tags, row),
            "createdAt": datetime.now().isoformat(timespec="seconds"),
        }

        # 기존 원장 읽기
        existing = _read_rows(5000)
        # 중복 방지: 같은 symbol + recommendationDate + failureType 은 덮어쓰기
        key = f"{symbol}|{postmortem_row['recommendationDate']}|{failure_type}"
        existing_idx = next(
            (i for i, r in enumerate(existing)
             if f"{r.get('symbol')}|{r.get('recommendationDate')}|{r.get('failureType')}" == key),
            None,
        )
        if existing_idx is not None:
            existing[existing_idx] = postmortem_row
        else:
            existing.append(postmortem_row)

        # 최근 5000행만 유지
        if len(existing) > 5000:
            existing = existing[-5000:]

        _write_rows(existing)
        return {"status": "OK", "saved": True, "postmortem_row": postmortem_row}

    except Exception as exc:
        return {"status": "ERROR", "saved": False, "error": str(exc)}


def postmortem_summary(market: str = "all", limit: int = 200) -> dict[str, Any]:
    """postmortem_ledger.csv 요약을 반환합니다."""
    try:
        rows = _read_rows(5000)
        if market not in {"", "all"}:
            rows = [r for r in rows if r.get("market") == market]

        total = len(rows)
        if total == 0:
            return {"status": "NO_DATA", "market": market, "count": 0, "items": []}

        # failureType 분포
        by_failure: dict[str, int] = {}
        by_news: dict[str, int] = {}
        by_earnings: dict[str, int] = {}
        by_macro: dict[str, int] = {}
        by_sector: dict[str, int] = {}

        for r in rows:
            ft = _as_text(r.get("failureType", "UNKNOWN"))
            by_failure[ft] = by_failure.get(ft, 0) + 1
            for tag_field, counter in (
                ("newsEventTag", by_news),
                ("earningsEventTag", by_earnings),
                ("macroEventTag", by_macro),
                ("sectorEventTag", by_sector),
            ):
                tag = _as_text(r.get(tag_field, "unknown"))
                counter[tag] = counter.get(tag, 0) + 1

        return {
            "status": "OK",
            "market": market,
            "count": total,
            "byFailureType": by_failure,
            "byNewsEventTag": by_news,
            "byEarningsEventTag": by_earnings,
            "byMacroEventTag": by_macro,
            "bySectorEventTag": by_sector,
            "source": str(POSTMORTEM_CSV),
            "items": sorted(rows, key=lambda r: str(r.get("createdAt", "")), reverse=True)[:limit],
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc), "count": 0, "items": []}
