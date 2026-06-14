"""
outcome_analyzer.py — 추천 결과를 실패/성공 원인으로 분류한다 (7-B)

outcomeReason 코드:
    MISS_ENTRY_TOO_LOW       진입가 미도달 + MFE가 작음 (원래 신호는 있었음)
    ENTRY_TOO_AGGRESSIVE     체결됐으나 MAE가 ATR 대비 크게 발생
    STOP_TOO_TIGHT           손절 후 회복: 손절 직후 고가가 목표가에 근접
    TARGET_TOO_FAR           MFE가 목표가의 80% 이상인데 미도달
    TARGET_TOO_CLOSE         목표 도달하나 추가 MFE 여력이 2배 이상 남음
    VOLATILITY_TOO_HIGH      MAE/MFE 비율 > 1.2 (방향 없이 크게 흔들림)
    NEWS_RISK_UNDERWEIGHTED  dataStatus=STALE/PARTIAL + 손실
    DATA_STALE               dataStatus=STALE/ERROR → 학습 제외
    LOW_LIQUIDITY            미체결 + 거래량 희박 신호
    GOOD_SIGNAL_WEAK_EXIT    체결+수익이나 target/stop 타이밍 미흡
    GOOD                     정상 성공 (별도 개선 불필요)
"""
from __future__ import annotations

from typing import Any


_NUM_FIELDS = (
    "netPnlPct", "grossPnlPct", "mfePct", "maePct",
    "entryPrice", "targetPrice", "stopPrice", "currentPrice",
    "atr", "volatility", "distanceToEntryPct", "riskRewardRatio",
)


def _f(d: dict[str, Any], key: str) -> float | None:
    try:
        v = d.get(key)
        if v is None or str(v).strip().lower() in {"nan", "none", "null", ""}:
            return None
        return float(str(v).replace(",", "").replace("원", "").replace("$", "").replace("%", ""))
    except Exception:
        return None


def classify_outcome(rec: dict[str, Any], result: dict[str, Any]) -> str:
    """
    추천(rec) + 백테스트 결과(result)를 받아 outcomeReason 문자열을 반환한다.

    Parameters
    ----------
    rec    : 원본 추천 딕셔너리 (entry, stop, target, dataStatus 등 포함)
    result : backtest_v2.evaluate_recommendation() 결과
    """
    exec_status = str(result.get("executionStatus") or "")
    exit_status = str(result.get("exitStatus") or "")
    data_status = str(rec.get("dataStatus") or result.get("dataStatus") or "")

    # DATA_STALE: 학습 제외 대상 → 먼저 처리
    if data_status.upper() in {"STALE", "ERROR"}:
        return "DATA_STALE"

    net_pnl   = _f(result, "netPnlPct")
    mfe       = _f(result, "mfePct")
    mae       = _f(result, "maePct")
    entry     = _f(rec, "entry") or _f(rec, "entryPrice")
    stop      = _f(rec, "stop")  or _f(rec, "stopPrice")
    target    = _f(rec, "target") or _f(rec, "targetPrice")
    atr       = _f(rec, "atr")
    volatility = _f(rec, "volatility")

    # ── 미체결 ──────────────────────────────────────────────────────────────
    if exec_status == "미체결":
        if mfe is not None and mfe < 0.5:
            return "MISS_ENTRY_TOO_LOW"
        return "MISS_ENTRY_TOO_LOW"

    # ── 체결된 케이스 ────────────────────────────────────────────────────────
    if exec_status != "체결":
        return "DATA_STALE"

    # 변동성 과다: MAE / MFE 비율 기준
    if mae is not None and mfe is not None and mfe > 0.0:
        if abs(mae) / (mfe + 1e-6) > 1.2:
            return "VOLATILITY_TOO_HIGH"

    if exit_status in {"손절", "손절(동시터치)", "추적손절"}:
        # 손절 후 MFE가 상당히 남아 있었다면 손절이 너무 타이트
        if mfe is not None and mfe > 1.5 and entry and stop:
            stop_dist_pct = abs(entry - stop) / entry * 100
            if stop_dist_pct < 3.0:
                return "STOP_TOO_TIGHT"
        # MAE가 크면 진입이 너무 공격적
        if mae is not None and abs(mae) > 3.0:
            return "ENTRY_TOO_AGGRESSIVE"
        # 뉴스/데이터 이슈
        if data_status.upper() in {"PARTIAL"} and net_pnl is not None and net_pnl < 0:
            return "NEWS_RISK_UNDERWEIGHTED"
        return "ENTRY_TOO_AGGRESSIVE"

    if exit_status == "목표도달":
        # 목표 도달했지만 MFE가 훨씬 더 컸다면 → 목표가가 너무 가깝게 설정
        if mfe is not None and target and entry:
            target_pct = (target - entry) / entry * 100
            if mfe > target_pct * 1.8:
                return "TARGET_TOO_CLOSE"
        return "GOOD"

    if exit_status == "기간종료":
        # MFE가 목표가의 80% 이상에 도달했는데 기간 내 못 찍음 → 목표가 너무 멂
        if mfe is not None and target and entry:
            target_pct = (target - entry) / entry * 100
            if mfe >= target_pct * 0.8:
                return "TARGET_TOO_FAR"
        # net_pnl이 양수면 타이밍이 아쉬웠지만 성공에 가까움
        if net_pnl is not None and net_pnl > 0:
            return "GOOD_SIGNAL_WEAK_EXIT"
        # 저유동성 가능성 (진입 자체는 됐으나 방향성 없음)
        if mfe is not None and abs(mfe) < 0.5:
            return "LOW_LIQUIDITY"
        return "GOOD_SIGNAL_WEAK_EXIT"

    return "GOOD"


def analyze_batch(
    records: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    여러 추천/결과 쌍에 대해 outcomeReason을 일괄 생성한다.

    Parameters
    ----------
    records : 추천 딕셔너리 목록 (rec)
    results : backtest_v2 결과 목록 (result), records와 동일 순서/길이

    Returns
    -------
    각 항목에 outcomeReason이 추가된 combined dict 목록
    """
    out = []
    for rec, res in zip(records, results):
        reason = classify_outcome(rec, res)
        combined = {**rec, **res, "outcomeReason": reason}
        out.append(combined)
    return out


def reason_counts(analyzed: list[dict[str, Any]]) -> dict[str, int]:
    """outcomeReason별 카운트."""
    counts: dict[str, int] = {}
    for item in analyzed:
        r = str(item.get("outcomeReason") or "UNKNOWN")
        counts[r] = counts.get(r, 0) + 1
    return counts


def top_failure_reasons(analyzed: list[dict[str, Any]], n: int = 5) -> list[str]:
    """상위 N개 실패 원인 코드 반환 (GOOD/DATA_STALE 제외)."""
    counts = reason_counts(analyzed)
    failure_counts = {k: v for k, v in counts.items() if k not in {"GOOD", "DATA_STALE"}}
    return [k for k, _ in sorted(failure_counts.items(), key=lambda x: -x[1])[:n]]
