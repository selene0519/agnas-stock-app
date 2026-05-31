from __future__ import annotations

from datetime import datetime
from typing import Any

from app.engine import backtest, session
from app.engine.symbols import normalize_market

PENALTY_PCT = 15.0
CONSECUTIVE_FAILURE_THRESHOLD = 3


def _mode(value: Any) -> str:
    aliases = {
        "보수": "conservative",
        "균형": "balanced",
        "공격": "aggressive",
        "conservative": "conservative",
        "balanced": "balanced",
        "aggressive": "aggressive",
    }
    return aliases.get(str(value or "balanced").strip().lower(), aliases.get(str(value or "balanced").strip(), "balanced"))


def _horizon(value: Any) -> str:
    aliases = {
        "단기": "short",
        "스윙": "swing",
        "장기": "mid",
        "short": "short",
        "swing": "swing",
        "mid": "mid",
        "long": "mid",
    }
    return aliases.get(str(value or "swing").strip().lower(), aliases.get(str(value or "swing").strip(), "swing"))


def _is_stop_failure(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("result", "exitStatus", "failure_reason", "failureReason", "executionReason", "pnlText")
    )
    return bool(row.get("is_loss")) or "손절" in text or "stop" in text.lower()


def correction_summary(market: str = "kr", mode: str = "balanced", horizon: str = "swing") -> dict[str, Any]:
    normalized_market = normalize_market(market)
    normalized_mode = _mode(mode)
    normalized_horizon = _horizon(horizon)
    trade_payload = backtest.trades(normalized_market, normalized_mode, normalized_horizon, limit=30)
    rows = [row for row in trade_payload.get("items") or [] if row.get("is_executed")]

    consecutive_failures = 0
    recent_failures: list[dict[str, Any]] = []
    for row in rows:
        if _is_stop_failure(row):
            consecutive_failures += 1
            recent_failures.append(row)
        else:
            break

    active = consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD
    return {
        "status": "OK",
        "market": normalized_market,
        "mode": normalized_mode,
        "horizon": normalized_horizon,
        "active": active,
        "penaltyPct": PENALTY_PCT if active else 0.0,
        "priorityDowngrade": active,
        "consecutiveStopFailures": consecutive_failures,
        "threshold": CONSECUTIVE_FAILURE_THRESHOLD,
        "reason": (
            f"최근 {CONSECUTIVE_FAILURE_THRESHOLD}회 연속 손절 실패로 승률 {PENALTY_PCT}% 감산"
            if active
            else "자가 보정 비활성"
        ),
        "recentFailures": recent_failures[:CONSECUTIVE_FAILURE_THRESHOLD],
        "generatedAt": datetime.now(session.KST).isoformat(),
    }


def apply_penalty(candidate: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    if not summary.get("active"):
        return candidate

    penalty = float(summary.get("penaltyPct") or PENALTY_PCT)
    adjusted = dict(candidate)

    for key in ("winProbability", "probability", "confidence"):
        value = adjusted.get(key)
        if isinstance(value, (int, float)):
            adjusted[key] = max(0.0, round(float(value) - penalty, 2))

    text_keys = ("probabilityText", "winProbabilityText")
    for key in text_keys:
        value = adjusted.get(key)
        if isinstance(value, str) and value.endswith("%"):
            try:
                adjusted[key] = f"{max(0.0, float(value[:-1].replace(',', '')) - penalty):.1f}%"
            except Exception:
                pass

    if isinstance(adjusted.get("finalRankScore"), (int, float)):
        adjusted["finalRankScore"] = round(float(adjusted["finalRankScore"]) * 0.85, 4)

    warning = str(adjusted.get("warning_reason") or adjusted.get("warningReason") or "").strip()
    addition = summary.get("reason") or "자가 보정 감산 적용"
    adjusted["warning_reason"] = f"{warning} · {addition}" if warning else addition
    adjusted["selfCorrectionPenaltyPct"] = penalty
    adjusted["priorityDowngraded"] = True
    return adjusted
