"""수익포착 실패 진단 (PROFIT_CAPTURE).

MFE(최대 유리 이탈, mfe_pct)와 target_progress를 이용해 실제 수익 기회가 있었지만
결국 목표가에 도달하지 못하거나 손절에 걸린 거래를 진단한다.
추천 로직·진입가·손절가·목표가 산식 변경은 수행하지 않는다.
"""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import median
from typing import Any, Iterable

from app.services import trade_failure_analytics as failure_analytics
from app.services import virtual_trade_journal as vtj

MIN_SEGMENT_SAMPLE = 8

# 수익 기회가 있었다고 판단하는 MFE 최소 임계값 (%)
MFE_OPPORTUNITY_THRESHOLD = 2.0
# 목표가 50% 이상 도달했으나 실패한 경우
TARGET_PROGRESS_HALF = 0.5


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


def _is_win(row: dict[str, Any]) -> bool:
    reason = _reason(row)
    if reason == "TARGET_BEFORE_STOP":
        return True
    ret = _num(row.get("net_pnl_pct") or row.get("returnPct"))
    return (ret or 0) > 0


def _avg(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 4) if vals else None


def _mfe(row: dict[str, Any]) -> float | None:
    v = _num(row.get("mfe_pct"))
    if v is not None:
        return v
    return _num(row.get("maxFavorableExcursion"))


def _target_prog(row: dict[str, Any]) -> float | None:
    return _num(row.get("target_progress"))


def _metrics_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"count": 0, "avgReturn": None, "avgMfe": None, "medianMfe": None, "avgTargetProgress": None}
    rets = [v for r in rows if (v := _num(r.get("net_pnl_pct"))) is not None]
    mfes = [v for r in rows if (v := _mfe(r)) is not None]
    progs = [v for r in rows if (v := _target_prog(r)) is not None]
    wins = sum(1 for r in rows if _is_win(r))
    return {
        "count": len(rows),
        "winRate": round(wins / len(rows), 4),
        "avgReturn": _avg(rets),
        "medianReturn": round(median(rets), 4) if rets else None,
        "avgMfe": _avg(mfes),
        "medianMfe": round(median(mfes), 4) if mfes else None,
        "avgTargetProgress": _avg(progs),
        "medianTargetProgress": round(median(progs), 4) if progs else None,
    }


def _target_progress_bucket(row: dict[str, Any]) -> str:
    prog = _target_prog(row)
    if prog is None:
        return "진행률 없음"
    if prog < 0.25:
        return "0-25%"
    if prog < 0.5:
        return "25-50%"
    if prog < 0.75:
        return "50-75%"
    if prog < 1.0:
        return "75-100%"
    return "100% 초과"


def _mfe_bucket(row: dict[str, Any]) -> str:
    mfe = _mfe(row)
    if mfe is None:
        return "MFE 없음"
    if mfe < 2.0:
        return "MFE 0-2%"
    if mfe < 5.0:
        return "MFE 2-5%"
    if mfe < 10.0:
        return "MFE 5-10%"
    return "MFE 10%+"


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
    target_not_reached: list[dict[str, Any]],
    stop_with_mfe: list[dict[str, Any]],
    half_way: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    # 목표가 50%+ 도달 후 실패한 케이스
    if len(half_way) >= MIN_SEGMENT_SAMPLE:
        m = _metrics_for(half_way)
        candidates.append({
            "causeType": "HALFWAY_TARGET_FAILURE",
            "title": "목표가 절반 이상 도달 후 미달",
            "summary": (
                f"목표가 50% 이상 진행했으나 최종적으로 실패한 거래가 {len(half_way)}건 있습니다. "
                f"평균 진행률 {(m.get('avgTargetProgress') or 0)*100:.1f}%, 평균 MFE {m.get('avgMfe') or 0:.2f}%. "
                "분할 익절 또는 목표가 절반 도달 시 trailing stop 전략을 검토할 수 있습니다."
            ),
            "evidence": {
                "count": len(half_way),
                "avgTargetProgress": m.get("avgTargetProgress"),
                "avgMfe": m.get("avgMfe"),
                "avgReturn": m.get("avgReturn"),
            },
        })

    # MFE 있지만 손절에 걸린 케이스
    if len(stop_with_mfe) >= MIN_SEGMENT_SAMPLE:
        m = _metrics_for(stop_with_mfe)
        candidates.append({
            "causeType": "STOP_AFTER_POSITIVE_MFE",
            "title": "양의 MFE 후 손절 청산",
            "summary": (
                f"상승 후 되돌림으로 손절에 걸린 거래가 {len(stop_with_mfe)}건 있습니다. "
                f"평균 MFE {m.get('avgMfe') or 0:.2f}%(상승 기회)였으나 "
                f"최종 수익률 평균 {m.get('avgReturn') or 0:.2f}%로 마감됐습니다. "
                f"trailing stop 또는 목표가 일부 도달 시 부분 익절을 검토할 수 있습니다."
            ),
            "evidence": {
                "count": len(stop_with_mfe),
                "avgMfe": m.get("avgMfe"),
                "avgReturn": m.get("avgReturn"),
            },
        })

    # 목표가 미도달로 만료된 케이스
    if len(target_not_reached) >= MIN_SEGMENT_SAMPLE:
        m = _metrics_for(target_not_reached)
        candidates.append({
            "causeType": "TARGET_NOT_REACHED_WINDOW",
            "title": "평가 기간 내 목표가 미도달",
            "summary": (
                f"평가 기간 내 목표가에 도달하지 못한 거래가 {len(target_not_reached)}건 있습니다. "
                f"평균 목표 진행률 {(m.get('avgTargetProgress') or 0)*100:.1f}%, 평균 MFE {m.get('avgMfe') or 0:.2f}%. "
                "목표가 기간을 늘리거나 목표가를 낮추는 방향을 검토할 수 있습니다. "
                "단, 산식 변경 전 before/after 검증이 필요합니다."
            ),
            "evidence": {
                "count": len(target_not_reached),
                "avgTargetProgress": m.get("avgTargetProgress"),
                "avgMfe": m.get("avgMfe"),
                "avgReturn": m.get("avgReturn"),
            },
        })

    if not candidates:
        candidates.append({
            "causeType": "PROFIT_CAPTURE_UNCLEAR",
            "title": "수익포착 실패 원인 불명확",
            "summary": "현재 표본에서 명확한 수익포착 실패 패턴이 관측되지 않습니다. 표본이 더 쌓이면 재분석이 필요합니다.",
            "evidence": {},
        })

    return candidates[:4]


def _patch_decision(total: int, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if total < 40:
        reason = "평가 완료 표본이 40건 미만이어서 운영 로직 변경 대신 진단만 제공합니다."
    elif not candidates or candidates[0].get("causeType") == "PROFIT_CAPTURE_UNCLEAR":
        reason = "명확한 수익포착 실패 패턴이 확인되지 않아 목표가·손절가 산식 변경을 보류합니다."
    else:
        reason = (
            "수익포착 개선 후보가 관측됐으나 trailing stop·부분익절 전략은 "
            "before/after 검증 없이 라이브 적용하지 않습니다."
        )
    return {
        "appliedPatch": False,
        "patchType": "diagnostic_only",
        "patchReason": reason,
        "shouldModifyTradingLogicNow": False,
    }


def build_profit_capture_diagnostics(
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

    wins = [r for r in evaluated if _is_win(r)]
    losses = [r for r in evaluated if not _is_win(r)]

    # TARGET_NOT_REACHED — 시간초과로 목표 미달
    target_not_reached = [r for r in evaluated if _reason(r) == "TARGET_NOT_REACHED"]

    # STOP_BEFORE_TARGET + MFE >= 2% — 양의 이동 후 손절
    stop_with_mfe = [
        r for r in evaluated
        if _reason(r) in {"STOP_BEFORE_TARGET", "STOP_TOO_TIGHT"}
        and (_mfe(r) or 0) >= MFE_OPPORTUNITY_THRESHOLD
    ]

    # 목표가 50% 이상 도달 + 실패 (not win)
    half_way = [
        r for r in losses
        if (_target_prog(r) or 0) >= TARGET_PROGRESS_HALF
    ]

    # 수익 기회 총 건수 (MFE >= 2% 또는 target_progress >= 0.5)
    opportunity_rows = list({
        id(r): r for r in (stop_with_mfe + half_way + target_not_reached)
    }.values())

    candidates = _cause_candidates(target_not_reached, stop_with_mfe, half_way)
    patch = _patch_decision(len(evaluated), candidates)

    mfes_all = [v for r in evaluated if (v := _mfe(r)) is not None]
    progs_all = [v for r in evaluated if (v := _target_prog(r)) is not None]

    target_prog_segments = _segment_by(
        [r for r in evaluated if _target_prog(r) is not None],
        _target_progress_bucket,
    )
    mfe_segments = _segment_by(
        [r for r in evaluated if _mfe(r) is not None],
        _mfe_bucket,
    )

    summary = {
        "totalEvaluatedTrades": len(evaluated),
        "winTrades": len(wins),
        "lossTrades": len(losses),
        "targetNotReached": len(target_not_reached),
        "stopWithMfe": len(stop_with_mfe),
        "halfwayFailures": len(half_way),
        "opportunityTrades": len(opportunity_rows),
        "opportunityRate": round(len(opportunity_rows) / len(evaluated), 4) if evaluated else 0.0,
        "avgMfeAll": _avg(mfes_all),
        "avgTargetProgressAll": _avg(progs_all),
        "targetNotReachedMetrics": _metrics_for(target_not_reached),
        "stopWithMfeMetrics": _metrics_for(stop_with_mfe),
        "halfwayMetrics": _metrics_for(half_way),
        "winMetrics": _metrics_for(wins),
        "lossMetrics": _metrics_for(losses),
    }

    return {
        "status": "OK",
        "source": vtj._relative(vtj.EVALUATION_CSV),
        "scope": {
            "market": market, "mode": mode, "horizon": horizon,
            "sourceType": source_type, "journalSession": journal_session,
        },
        "summary": summary,
        "targetProgressSegments": target_prog_segments,
        "mfeSegments": mfe_segments,
        "causeCandidates": candidates,
        "patch": patch,
        "appliedPatch": False,
        "patchType": "diagnostic_only",
        "patchReason": patch["patchReason"],
        "shouldModifyTradingLogicNow": False,
        "note": (
            "수익포착 진단은 MFE·목표진행률 기반 분석이며 "
            "진입가·손절가·목표가 산식 변경, 추천 후보 제외, 액션 변경을 수행하지 않습니다."
        ),
    }


def _empty(
    market: str, mode: str, horizon: str,
    source_type: str, journal_session: str,
    warning: str = "",
) -> dict[str, Any]:
    empty_m = _metrics_for([])
    base = {
        "status": "OK",
        "source": "",
        "scope": {
            "market": market, "mode": mode, "horizon": horizon,
            "sourceType": source_type, "journalSession": journal_session,
        },
        "summary": {
            "totalEvaluatedTrades": 0,
            "winTrades": 0,
            "lossTrades": 0,
            "targetNotReached": 0,
            "stopWithMfe": 0,
            "halfwayFailures": 0,
            "opportunityTrades": 0,
            "opportunityRate": 0.0,
            "avgMfeAll": None,
            "avgTargetProgressAll": None,
            "targetNotReachedMetrics": empty_m,
            "stopWithMfeMetrics": empty_m,
            "halfwayMetrics": empty_m,
            "winMetrics": empty_m,
            "lossMetrics": empty_m,
        },
        "targetProgressSegments": [],
        "mfeSegments": [],
        "causeCandidates": [],
        "patch": _patch_decision(0, []),
        "appliedPatch": False,
        "patchType": "diagnostic_only",
        "patchReason": "분석 가능한 평가 완료 거래가 아직 없습니다.",
        "shouldModifyTradingLogicNow": False,
        "note": "수익포착 진단 — 추천 로직 변경 없음.",
    }
    if warning:
        base["warning"] = warning
    return base
