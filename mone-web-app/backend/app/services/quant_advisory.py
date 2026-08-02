"""User-facing, fail-closed advisory contract for Quant V2 recommendations."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.services import product_scope, quant_execution_plan, quant_operating_governor


REPO_ROOT = Path(__file__).resolve().parents[4]
META_GATE_JSON = REPO_ROOT / "reports" / "shadow_meta_gate.json"
CONTRACT_VERSION = "quant-advisory-v1"
MAX_RECOMMENDATION_AGE_HOURS = 36.0

REASON_TEXT = {
    "DATA_NOT_NORMAL": "입력 데이터 품질이 정상 기준을 충족하지 못했습니다.",
    "EV_NOT_POSITIVE": "비용 차감 후 기대값이 양수가 아닙니다.",
    "RISK_REWARD_TOO_LOW": "손익비가 최소 기준을 충족하지 못했습니다.",
    "RESIDUAL_ALPHA_MODEL_NOT_PROVEN": "시장 영향을 제거한 잔차 알파 모델의 Forward 증거가 부족합니다.",
    "NO_RESIDUAL_ALPHA_PREDICTION": "이 후보에 봉인된 잔차 알파 예측이 없습니다.",
    "RESIDUAL_ALPHA_PREDICTION_NOT_FORWARD_SEALED": "잔차 알파 예측이 추천 전에 봉인되지 않았습니다.",
    "RESIDUAL_ALPHA_NOT_POSITIVE": "잔차 알파의 90% 하한이 양수가 아닙니다.",
    "NO_FORWARD_EVIDENCE": "이 전략 셀의 독립 Forward 표본이 없습니다.",
    "LOW_INDEPENDENT_DECISIONS": "독립 평가 표본이 최소 기준보다 적습니다.",
    "LOW_DISTINCT_SIGNAL_DATES": "서로 다른 추천일 표본이 최소 기준보다 적습니다.",
    "NON_POSITIVE_AFTER_COST_EXPECTANCY": "Forward 실측의 비용 차감 기대값이 양수가 아닙니다.",
    "PROFIT_FACTOR_NOT_ABOVE_ONE": "Forward 실측의 profit factor가 1을 넘지 못했습니다.",
    "RECOMMENDATION_TIME_INVALID": "추천 생성 시각이 유효하지 않습니다.",
    "RECOMMENDATION_STALE": "추천 유효기간이 지났습니다.",
    "RECOMMENDATION_FROM_FUTURE": "추천 생성 시각이 현재보다 미래입니다.",
    "INVALID_PRICE_PLAN": "진입가·손절가·목표가의 가격 계획이 유효하지 않습니다.",
    "NO_VERIFIED_RISK_ALLOCATION": "검증된 후보별 위험비중이 없어 TAKE를 허용할 수 없습니다.",
    "OPERATING_GATES_NOT_READY": "운영 안전 게이트가 아직 추천 검토를 허용하지 않습니다.",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    try:
        parsed = float(_text(value).replace(",", "").replace("%", "").replace("$", ""))
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _counter_evidence(reason_codes: list[str]) -> list[str]:
    mapped = [REASON_TEXT.get(code, code.replace("_", " ").lower()) for code in reason_codes]
    return list(dict.fromkeys(mapped))


def _rationale(row: dict[str, Any], cell: dict[str, Any], position: dict[str, Any] | None) -> list[str]:
    reasons: list[str] = []
    expected_value = _num(row.get("expectedValue"))
    risk_reward = _num(row.get("riskRewardRatio"))
    residual_lower = _num(row.get("residualAlphaLower90Pct"))
    if expected_value is not None and expected_value > 0:
        reasons.append(f"비용 반영 기대값 {expected_value:+.2f}%")
    if risk_reward is not None and risk_reward >= 1.5:
        reasons.append(f"계획 손익비 {risk_reward:.2f}")
    if residual_lower is not None and residual_lower > 0:
        reasons.append(f"시장중립 잔차 알파 90% 하한 {residual_lower:+.2f}%")
    if cell.get("evidenceStatus") == "PASS":
        reasons.append(
            f"독립 Forward {int(_num(cell.get('independentDecisions')) or 0)}건 · "
            f"추천일 {int(_num(cell.get('distinctSignalDates')) or 0)}일"
        )
    if position:
        reasons.append(f"위험예산이 최대 권고비중 {float(_num(position.get('weight')) or 0.0) * 100:.2f}%로 제한됨")
    return reasons


def build_advisory(
    meta: dict[str, Any],
    execution_plan: dict[str, Any],
    operating: dict[str, Any],
    *,
    market: str = "all",
    limit: int = 20,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Normalize internal evidence into a complete, human-decision-only contract."""
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    normalized_market = _text(market).lower() or "all"
    decisions = meta.get("decisions") if isinstance(meta.get("decisions"), list) else []
    cells = meta.get("cellEvidence") if isinstance(meta.get("cellEvidence"), dict) else {}
    positions = execution_plan.get("positions") if isinstance(execution_plan.get("positions"), list) else []
    positions_by_key = {
        _text(row.get("candidateKey")): row
        for row in positions
        if isinstance(row, dict) and _text(row.get("candidateKey"))
    }
    operating_markets = operating.get("markets") if isinstance(operating.get("markets"), dict) else {}
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in decisions:
        if not isinstance(raw, dict):
            continue
        row_market = _text(raw.get("market")).lower()
        if normalized_market in {"kr", "us"} and row_market != normalized_market:
            continue
        candidate_key = _text(raw.get("candidateKey"))
        if not candidate_key or candidate_key in seen:
            continue
        seen.add(candidate_key)
        original_decision = _text(raw.get("decision")).upper()
        decision = original_decision if original_decision in {"TAKE", "WAIT", "REJECT"} else "REJECT"
        reason_codes = [_text(code).upper() for code in (raw.get("reasons") or []) if _text(code)]
        generated_at = _parse_time(raw.get("generatedAt"))
        valid_until = generated_at + timedelta(hours=MAX_RECOMMENDATION_AGE_HOURS) if generated_at else None
        entry = _num(raw.get("entryPrice"))
        stop = _num(raw.get("stopPrice"))
        target = _num(raw.get("targetPrice"))
        valid_price_plan = (
            entry is not None and entry > 0
            and stop is not None and 0 < stop < entry
            and target is not None and target > entry
        )
        position = positions_by_key.get(candidate_key)
        market_authority = operating_markets.get(row_market) if isinstance(operating_markets.get(row_market), dict) else {}

        if generated_at is None:
            reason_codes.append("RECOMMENDATION_TIME_INVALID")
            decision = "REJECT"
        elif generated_at > now_utc:
            reason_codes.append("RECOMMENDATION_FROM_FUTURE")
            decision = "REJECT"
        elif valid_until is not None and now_utc > valid_until:
            reason_codes.append("RECOMMENDATION_STALE")
            decision = "REJECT"
        if not valid_price_plan:
            reason_codes.append("INVALID_PRICE_PLAN")
            if decision == "TAKE":
                decision = "REJECT"
        if decision == "TAKE" and (execution_plan.get("status") != "AUTHORIZED" or position is None):
            reason_codes.append("NO_VERIFIED_RISK_ALLOCATION")
            decision = "WAIT"
        if decision == "TAKE" and market_authority.get("recommendationActionable") is not True:
            reason_codes.append("OPERATING_GATES_NOT_READY")
            decision = "WAIT"

        reason_codes = list(dict.fromkeys(reason_codes))
        cell_key = "|".join((_text(raw.get("market")).lower(), _text(raw.get("mode")).lower(), _text(raw.get("horizon")).lower()))
        cell = cells.get(cell_key) if isinstance(cells.get(cell_key), dict) else {}
        uncertainty_level = "MODERATE" if decision == "TAKE" else "HIGH"
        counter = _counter_evidence(reason_codes)
        counter.extend([
            "과거 및 Paper 성과는 미래 수익을 보장하지 않습니다.",
            "갭과 유동성 부족으로 실제 체결 손실은 계획 손절폭보다 커질 수 있습니다.",
        ])
        max_weight = float(_num((position or {}).get("weight")) or 0.0)
        items.append({
            "contractVersion": CONTRACT_VERSION,
            "decisionId": _text(raw.get("decisionId")),
            "candidateKey": candidate_key,
            "market": row_market,
            "mode": _text(raw.get("mode")).lower(),
            "horizon": _text(raw.get("horizon")).lower(),
            "symbol": _text(raw.get("symbol")).upper(),
            "name": _text(raw.get("name")),
            "decision": decision,
            "sourceDecision": original_decision,
            "recommendationActionable": decision == "TAKE",
            "userAction": "REVIEW_MANUALLY" if decision == "TAKE" else ("WAIT" if decision == "WAIT" else "DO_NOT_USE"),
            "entryPrice": entry,
            "stopPrice": stop,
            "targetPrice": target,
            "maxRecommendedWeight": round(max_weight, 6),
            "maxRecommendedWeightPct": round(max_weight * 100.0, 4),
            "generatedAt": generated_at.isoformat() if generated_at else None,
            "validUntil": valid_until.isoformat() if valid_until else None,
            "reasonCodes": reason_codes,
            "rationale": _rationale(raw, cell, position),
            "counterEvidence": list(dict.fromkeys(counter)),
            "uncertainty": {
                "level": uncertainty_level,
                "calibratedWinProbabilityAvailable": False,
                "modelProbabilityDisplayOnly": _num(raw.get("modelProbabilityDisplayOnly")),
                "residualAlphaLower90Pct": _num(raw.get("residualAlphaLower90Pct")),
                "independentDecisions": int(_num(cell.get("independentDecisions")) or 0),
                "distinctSignalDates": int(_num(cell.get("distinctSignalDates")) or 0),
            },
            "productScope": product_scope.product_scope(),
        })

    decision_order = {"TAKE": 0, "WAIT": 1, "REJECT": 2}
    items.sort(key=lambda row: (decision_order.get(row["decision"], 3), -float(_num(row.get("maxRecommendedWeight")) or 0.0), row["symbol"]))
    bounded_limit = max(1, min(int(limit or 20), 100))
    limited = items[:bounded_limit]
    return {
        "status": "OK" if items else "EMPTY",
        "contractVersion": CONTRACT_VERSION,
        "generatedAt": now_utc.isoformat(),
        "market": normalized_market,
        "productScope": product_scope.product_scope(),
        "summary": {
            "candidates": len(items),
            "take": sum(1 for row in items if row["decision"] == "TAKE"),
            "wait": sum(1 for row in items if row["decision"] == "WAIT"),
            "reject": sum(1 for row in items if row["decision"] == "REJECT"),
        },
        "items": limited,
    }


def advisory_recommendations(market: str = "all", limit: int = 20) -> dict[str, Any]:
    meta = _read_json(META_GATE_JSON)
    execution = quant_execution_plan.execution_plan(market)
    operating = quant_operating_governor.operating_status(market)
    return build_advisory(meta, execution, operating, market=market, limit=limit)
