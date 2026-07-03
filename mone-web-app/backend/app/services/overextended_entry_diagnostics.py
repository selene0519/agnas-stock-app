"""과열구간 진입 진단 (OVEREXTENDED_ENTRY).

진입 시점의 RSI·MA20 이격도를 기준으로 세그먼트를 나누고, 각 구간의 손절 실패율·
평균 수익률·승률을 집계한다. 추천 로직·진입가 산식·액션 변경은 수행하지 않는다.
"""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any, Iterable

from app.services import trade_failure_analytics as failure_analytics
from app.services import virtual_trade_journal as vtj

MIN_SEGMENT_SAMPLE = 8

RSI_THRESHOLDS = [
    (0.0,   55.0, "RSI≤55(저과열)"),
    (55.0,  62.0, "RSI 55-62(중간)"),
    (62.0,  70.0, "RSI 62-70(고과열)"),
    (70.0, 999.0, "RSI≥70(극과열)"),
]

MA20_THRESHOLDS = [
    (-999.0, -3.0, "MA20 -3%이하(저평가)"),
    (-3.0,    3.0, "MA20 ±3%(중간)"),
    (3.0,    10.0, "MA20 +3-10%(상단)"),
    (10.0,  999.0, "MA20 +10%이상(극단)"),
]


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    return str(v).strip()


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        n = float(str(v).replace(",", "").replace("%", ""))
    except Exception:
        return None
    return n if math.isfinite(n) else None


def _reason(row: dict[str, Any]) -> str:
    return failure_analytics._failure_reason(row)


def _is_evaluated(row: dict[str, Any]) -> bool:
    return failure_analytics.failure_reason_group(_reason(row)) == failure_analytics.REASON_GROUP_EVALUATED


def _is_stop_failure(reason: str) -> bool:
    return reason in {"STOP_BEFORE_TARGET", "STOP_TOO_TIGHT"}


def _is_win(row: dict[str, Any]) -> bool:
    reason = _reason(row)
    if reason == "TARGET_BEFORE_STOP":
        return True
    ret = _num(row.get("net_pnl_pct") or row.get("returnPct"))
    return (ret or 0) > 0


def _avg(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 4) if vals else None


def _segment_label_rsi(rsi: float | None) -> str:
    if rsi is None:
        return "RSI 없음"
    for lo, hi, label in RSI_THRESHOLDS:
        if lo <= rsi < hi:
            return label
    return f"RSI {rsi:.0f}"


def _segment_label_ma20(dist: float | None) -> str:
    if dist is None:
        return "MA20 없음"
    for lo, hi, label in MA20_THRESHOLDS:
        if lo <= dist < hi:
            return label
    return f"MA20 {dist:.1f}%"


def _metrics_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reasons = [_reason(r) for r in rows]
    stop_fail = sum(1 for r in reasons if _is_stop_failure(r))
    wins = sum(1 for r in rows if _is_win(r))
    rets = [v for r in rows if (v := _num(r.get("net_pnl_pct") or r.get("returnPct"))) is not None]
    return {
        "count": len(rows),
        "stopFailCount": stop_fail,
        "stopFailRate": round(stop_fail / len(rows), 4) if rows else None,
        "winCount": wins,
        "winRate": round(wins / len(rows), 4) if rows else None,
        "avgReturn": _avg(rets),
        "medianReturn": round(median(rets), 4) if rets else None,
    }


def _segment_by(rows: Iterable[dict[str, Any]], label_fn: Any) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[label_fn(row)].append(row)
    out = []
    for label, group in groups.items():
        item = {"segment": label}
        item.update(_metrics_for(group))
        out.append(item)
    return sorted(out, key=lambda x: x.get("segment") or "")


def _cause_candidates(
    rsi_segments: list[dict[str, Any]],
    ma20_segments: list[dict[str, Any]],
    baseline_stop_rate: float | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    baseline = baseline_stop_rate or 0.0

    # RSI 고과열 구간이 baseline보다 손절 실패율 높으면 후보
    for seg in rsi_segments:
        if seg.get("count", 0) < MIN_SEGMENT_SAMPLE:
            continue
        seg_rate = seg.get("stopFailRate") or 0.0
        if "고과열" in str(seg.get("segment")) or "극과열" in str(seg.get("segment")):
            if seg_rate > baseline * 1.2:
                candidates.append({
                    "causeType": "HIGH_RSI_STOP_FAILURE",
                    "title": "고RSI 진입 손절 실패율 높음",
                    "summary": (
                        f"{seg['segment']} 구간 손절 실패율 {seg_rate*100:.1f}%가 "
                        f"전체 기준선 {baseline*100:.1f}%보다 높습니다. "
                        "과열 구간 진입이 추가 상승 여력이 제한적일 때 리스크를 높이는 것으로 보입니다."
                    ),
                    "evidence": {
                        "segment": seg["segment"],
                        "count": seg["count"],
                        "stopFailRate": seg_rate,
                        "baseline": baseline,
                    },
                })
                break

    # MA20 상단 이격 구간이 baseline보다 나쁘면 후보
    for seg in ma20_segments:
        if seg.get("count", 0) < MIN_SEGMENT_SAMPLE:
            continue
        seg_rate = seg.get("stopFailRate") or 0.0
        if "+10%" in str(seg.get("segment")) or "+3-10%" in str(seg.get("segment")):
            if seg_rate > baseline * 1.2:
                candidates.append({
                    "causeType": "MA20_OVEREXTENDED_STOP_FAILURE",
                    "title": "MA20 상단 이격 과다 진입",
                    "summary": (
                        f"{seg['segment']} 구간 손절 실패율 {seg_rate*100:.1f}%가 "
                        f"전체 기준선 {baseline*100:.1f}%보다 높습니다. "
                        "이평선 상단 과이격 시 되돌림 압력으로 손절이 먼저 걸리는 패턴으로 보입니다."
                    ),
                    "evidence": {
                        "segment": seg["segment"],
                        "count": seg["count"],
                        "stopFailRate": seg_rate,
                        "baseline": baseline,
                    },
                })
                break

    if not candidates:
        candidates.append({
            "causeType": "OVEREXTENSION_PATTERN_UNCLEAR",
            "title": "과열구간 패턴 불명확",
            "summary": (
                "RSI·MA20 이격도와 손절 실패율 간의 명확한 단조 관계가 현재 데이터에서 관측되지 않습니다. "
                "표본이 더 쌓이면 재분석이 필요합니다."
            ),
            "evidence": {"rsiSegments": len(rsi_segments), "ma20Segments": len(ma20_segments)},
        })

    return candidates[:3]


def _patch_decision(total: int, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if total < 40:
        reason = "평가 완료 표본이 40건 미만이어서 운영 로직 변경 대신 진단만 제공합니다."
    elif not candidates or candidates[0].get("causeType") == "OVEREXTENSION_PATTERN_UNCLEAR":
        reason = "RSI/MA20 과열 지표와 성과 간의 명확한 인과 관계가 확인되지 않아 액션 변경을 보류합니다."
    else:
        reason = "원인 후보가 관측됐지만 before/after 검증 없이 추천 액션이나 필터를 변경하지 않습니다."
    return {
        "appliedPatch": False,
        "patchType": "diagnostic_only",
        "patchReason": reason,
        "shouldModifyTradingLogicNow": False,
    }


def build_overextended_entry_diagnostics(
    market: str = "all",
    mode: str = "all",
    horizon: str = "all",
    source_type: str = "all",
    journal_session: str = "all",
) -> dict[str, Any]:
    try:
        vtj._ensure()
        rows = vtj._filter_rows(
            vtj._merge_evaluations(vtj._read_journal_rows()),
            market, mode, horizon, source_type, journal_session, "all",
        )
        if vtj._session_filter(journal_session) == "ALL":
            rows = [r for r in rows if vtj._is_trade_evaluation_session(r)]
    except Exception as exc:
        return _empty(market, mode, horizon, source_type, journal_session, warning=str(exc))

    evaluated = [r for r in rows if _is_evaluated(r)]
    if not evaluated:
        return _empty(market, mode, horizon, source_type, journal_session)

    # RSI 세그먼트 분석
    rsi_evaluated = [r for r in evaluated if _num(r.get("rsi_at_entry")) is not None]
    rsi_segments = _segment_by(
        rsi_evaluated,
        lambda r: _segment_label_rsi(_num(r.get("rsi_at_entry"))),
    )

    # MA20 이격도 세그먼트 분석
    ma20_evaluated = [r for r in evaluated if _num(r.get("distance_to_ma20_at_entry")) is not None]
    ma20_segments = _segment_by(
        ma20_evaluated,
        lambda r: _segment_label_ma20(_num(r.get("distance_to_ma20_at_entry"))),
    )

    baseline = _metrics_for(evaluated)
    baseline_stop_rate = baseline.get("stopFailRate")

    rsi_high = [r for r in rsi_evaluated if (_num(r.get("rsi_at_entry")) or 0) >= 62]
    rsi_normal = [r for r in rsi_evaluated if (_num(r.get("rsi_at_entry")) or 0) < 62]

    candidates = _cause_candidates(rsi_segments, ma20_segments, baseline_stop_rate)
    patch = _patch_decision(len(evaluated), candidates)

    rsi_vals = [v for r in evaluated if (v := _num(r.get("rsi_at_entry"))) is not None]
    ma20_vals = [v for r in evaluated if (v := _num(r.get("distance_to_ma20_at_entry"))) is not None]

    summary = {
        "totalEvaluatedTrades": len(evaluated),
        "rsiDataAvailable": len(rsi_evaluated),
        "ma20DataAvailable": len(ma20_evaluated),
        "overextendedEntryCount": 0,
        "avgRsiAtEntry": _avg(rsi_vals),
        "avgMa20DistAtEntry": _avg(ma20_vals),
        "highRsiGroup": _metrics_for(rsi_high),
        "normalRsiGroup": _metrics_for(rsi_normal),
        "baselineStopFailRate": baseline_stop_rate,
        "baselineWinRate": baseline.get("winRate"),
        "baselineAvgReturn": baseline.get("avgReturn"),
        "note": (
            "overextendedEntryCount는 현재 failureReason='OVEREXTENDED_ENTRY'인 평가 행이 없어 0입니다. "
            "RSI/MA20 기반 세그먼트 분석으로 대체합니다."
        ),
    }

    return {
        "status": "OK",
        "source": vtj._relative(vtj.EVALUATION_CSV),
        "scope": {
            "market": market, "mode": mode, "horizon": horizon,
            "sourceType": source_type, "journalSession": journal_session,
        },
        "summary": summary,
        "rsiSegments": rsi_segments,
        "ma20Segments": ma20_segments,
        "causeCandidates": candidates,
        "patch": patch,
        "appliedPatch": False,
        "patchType": "diagnostic_only",
        "patchReason": patch["patchReason"],
        "shouldModifyTradingLogicNow": False,
        "note": (
            "과열구간 진단은 진입 시점 RSI·MA20 이격도와 결과의 상관 분석이며 "
            "추천 후보 제외·액션 변경·진입가 산식 수정을 수행하지 않습니다."
        ),
    }


def _empty(
    market: str, mode: str, horizon: str,
    source_type: str, journal_session: str,
    warning: str = "",
) -> dict[str, Any]:
    base = {
        "status": "OK",
        "source": "",
        "scope": {
            "market": market, "mode": mode, "horizon": horizon,
            "sourceType": source_type, "journalSession": journal_session,
        },
        "summary": {
            "totalEvaluatedTrades": 0,
            "rsiDataAvailable": 0,
            "ma20DataAvailable": 0,
            "overextendedEntryCount": 0,
            "avgRsiAtEntry": None,
            "avgMa20DistAtEntry": None,
            "highRsiGroup": _metrics_for([]),
            "normalRsiGroup": _metrics_for([]),
            "baselineStopFailRate": None,
            "baselineWinRate": None,
            "baselineAvgReturn": None,
        },
        "rsiSegments": [],
        "ma20Segments": [],
        "causeCandidates": [],
        "patch": _patch_decision(0, []),
        "appliedPatch": False,
        "patchType": "diagnostic_only",
        "patchReason": "분석 가능한 평가 완료 거래가 아직 없습니다.",
        "shouldModifyTradingLogicNow": False,
        "note": "과열구간 진단 — 추천 로직 변경 없음.",
    }
    if warning:
        base["warning"] = warning
    return base
