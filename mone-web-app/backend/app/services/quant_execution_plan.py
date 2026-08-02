"""Fail-closed candidate-level Paper allocation authority for Quant V2.

The operating governor answers whether the system may consider a new entry.
This module answers the stricter question: *which exact candidate and weight*
may enter the Paper evidence ledger. It independently verifies the meta-gate
and risk-allocation reports so a global TAKE cannot accidentally authorize an
unrelated raw recommendation or an oversized simulated position. It grants no
broker or live-order authority.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
REPORTS = REPO_ROOT / "reports"
META_GATE_JSON = REPORTS / "shadow_meta_gate.json"
RISK_BUDGET_JSON = REPORTS / "shadow_risk_budget.json"
RESIDUAL_ALPHA_JSON = REPORTS / "shadow_residual_alpha.json"

META_POLICY_VERSION = "shadow-meta-v1.2.3"
RESIDUAL_ALPHA_POLICY_VERSION = "shadow-residual-alpha-v1.1.2"
RISK_POLICY_VERSION = "shadow-risk-budget-v1.2.0"
MAX_REPORT_AGE_HOURS = 36.0
MAX_PIPELINE_GAP_HOURS = 6.0
MAX_ENTRY_SLIPPAGE_PCT = 0.01

EXPECTED_RISK_POLICY = {
    "baseWeight": 0.10,
    "maxPositionWeight": 0.10,
    "maxGrossExposure": 0.30,
    "maxSectorExposure": 0.15,
    "maxPortfolioBeta": 0.30,
    "accountRiskPerTrade": 0.005,
    "removedExposureStaysCash": True,
    "redistributionAllowed": False,
    "uniqueMarketSymbol": True,
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    try:
        raw = _text(value).replace(",", "").replace("%", "").replace("$", "")
        value_float = float(raw)
        return value_float if math.isfinite(value_float) else None
    except (TypeError, ValueError):
        return None


def _fingerprint(payload: Any, length: int | None = 20) -> str:
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return digest[:length] if length else digest


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


def _expected_meta_policy(residual_model_fingerprint: str) -> dict[str, Any]:
    return {
        "version": META_POLICY_VERSION,
        "maxTake": 3,
        "minIndependentDecisions": 100,
        "minDistinctSignalDates": 30,
        "minRiskRewardRatio": 1.5,
        "requiresPositiveAfterCostExpectancy": True,
        "requiresProfitFactorAboveOne": True,
        "requiresValidatedResidualAlphaModel": True,
        "requiresPositiveResidualAlphaLower90": True,
        "residualAlphaPolicyVersion": RESIDUAL_ALPHA_POLICY_VERSION,
        "residualAlphaModelFingerprint": residual_model_fingerprint,
        "uncalibratedProbabilityCanTriggerTake": False,
        "maxRecommendationAgeHours": MAX_REPORT_AGE_HOURS,
        "requiresTimezoneAwareRecommendationTime": True,
    }


def _expected_risk_policy(meta_policy_fingerprint: str) -> dict[str, Any]:
    return {
        "version": RISK_POLICY_VERSION,
        "metaPolicyFingerprint": meta_policy_fingerprint,
        **EXPECTED_RISK_POLICY,
    }


def _allocation_evidence(risk: dict[str, Any]) -> dict[str, Any]:
    policy = risk.get("policy") if isinstance(risk.get("policy"), dict) else {}
    positions = risk.get("positions") if isinstance(risk.get("positions"), list) else []
    rejected = risk.get("rejected") if isinstance(risk.get("rejected"), list) else []
    position_rows = [
        {
            "decisionId": _text(row.get("decisionId")),
            "candidateKey": _text(row.get("candidateKey")),
            "symbol": _text(row.get("symbol")),
            "market": _text(row.get("market")),
            "sector": _text(row.get("sector")),
            "weight": round(float(_num(row.get("weight")) or 0.0), 8),
            "stopDistancePct": round(float(_num(row.get("stopDistancePct")) or 0.0), 8),
            "lossAtStopPctOfEquity": round(float(_num(row.get("lossAtStopPctOfEquity")) or 0.0), 8),
            "beta": round(float(_num(row.get("beta")) or 0.0), 8),
            "betaSource": _text(row.get("betaSource")),
            "clamps": sorted(_text(value) for value in (row.get("clamps") or [])),
        }
        for row in positions if isinstance(row, dict)
    ]
    rejected_rows = [
        {
            "decisionId": _text(row.get("decisionId")),
            "candidateKey": _text(row.get("candidateKey")),
            "symbol": _text(row.get("symbol")),
            "market": _text(row.get("market")),
            "reason": _text(row.get("reason")),
            "clamps": sorted(_text(value) for value in (row.get("clamps") or [])),
        }
        for row in rejected if isinstance(row, dict)
    ]
    return {
        "policyFingerprint": _text(policy.get("fingerprint")),
        "metaPolicyFingerprint": _text(policy.get("metaPolicyFingerprint")),
        "positions": sorted(position_rows, key=lambda row: (row["decisionId"], row["symbol"])),
        "rejected": sorted(rejected_rows, key=lambda row: (row["decisionId"], row["symbol"], row["reason"])),
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def validate_reports(
    meta: dict[str, Any],
    risk: dict[str, Any],
    residual: dict[str, Any],
    *,
    now: datetime | None = None,
    enforce_freshness: bool = True,
) -> dict[str, Any]:
    """Validate exact policy lineage and return executable positions only."""
    blockers: list[str] = []
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    meta_policy = meta.get("policy") if isinstance(meta.get("policy"), dict) else {}
    risk_policy = risk.get("policy") if isinstance(risk.get("policy"), dict) else {}
    lineage = risk.get("lineage") if isinstance(risk.get("lineage"), dict) else {}
    take = meta.get("take") if isinstance(meta.get("take"), list) else []
    positions = risk.get("positions") if isinstance(risk.get("positions"), list) else []
    rejected = risk.get("rejected") if isinstance(risk.get("rejected"), list) else []

    if _text(meta.get("status")) != "SHADOW_ONLY":
        blockers.append("META_GATE_STATUS_INVALID")
    if _text(risk.get("status")) != "SHADOW_ONLY":
        blockers.append("RISK_BUDGET_STATUS_INVALID")
    if _text(residual.get("status")) != "SHADOW_ONLY":
        blockers.append("RESIDUAL_ALPHA_STATUS_INVALID")

    residual_policy = residual.get("policy") if isinstance(residual.get("policy"), dict) else {}
    residual_validation = residual.get("validation") if isinstance(residual.get("validation"), dict) else {}
    residual_fingerprint = _text(residual_policy.get("fingerprint"))
    declared_residual_fingerprint = _text(meta_policy.get("residualAlphaModelFingerprint"))
    residual_definition = {key: value for key, value in residual_policy.items() if key != "fingerprint"}
    if residual_policy.get("version") != RESIDUAL_ALPHA_POLICY_VERSION:
        blockers.append("RESIDUAL_ALPHA_POLICY_VERSION_MISMATCH")
    if not residual_fingerprint or residual_fingerprint != _fingerprint(residual_definition):
        blockers.append("RESIDUAL_ALPHA_POLICY_FINGERPRINT_MISMATCH")
    if declared_residual_fingerprint != residual_fingerprint:
        blockers.append("META_RESIDUAL_ALPHA_FINGERPRINT_MISMATCH")
    if residual_validation.get("evidenceStatus") != "PASS":
        blockers.append("RESIDUAL_ALPHA_MODEL_NOT_PROVEN")
    expected_meta = _expected_meta_policy(residual_fingerprint)
    meta_fingerprint = _text(meta_policy.get("fingerprint"))
    if not residual_fingerprint or residual_fingerprint == "MISSING":
        blockers.append("RESIDUAL_MODEL_FINGERPRINT_MISSING")
    if {key: value for key, value in meta_policy.items() if key != "fingerprint"} != expected_meta:
        blockers.append("META_POLICY_DEFINITION_MISMATCH")
    if not meta_fingerprint or meta_fingerprint != _fingerprint(expected_meta):
        blockers.append("META_POLICY_FINGERPRINT_MISMATCH")

    expected_risk = _expected_risk_policy(meta_fingerprint)
    risk_fingerprint = _text(risk_policy.get("fingerprint"))
    if {key: value for key, value in risk_policy.items() if key != "fingerprint"} != expected_risk:
        blockers.append("RISK_POLICY_DEFINITION_MISMATCH")
    if not risk_fingerprint or risk_fingerprint != _fingerprint(expected_risk):
        blockers.append("RISK_POLICY_FINGERPRINT_MISMATCH")
    if lineage.get("valid") is not True:
        blockers.extend(lineage.get("blockingReasons") or ["RISK_LINEAGE_NOT_VALID"])
    declared_allocation = _text(lineage.get("allocationFingerprint"))
    if not declared_allocation or declared_allocation != _fingerprint(_allocation_evidence(risk), None):
        blockers.append("RISK_ALLOCATION_FINGERPRINT_MISMATCH")

    residual_time = _parse_time(residual.get("generatedAt"))
    meta_time = _parse_time(meta.get("generatedAt"))
    risk_time = _parse_time(risk.get("generatedAt"))
    if residual_time is None or meta_time is None or risk_time is None:
        blockers.append("EXECUTION_REPORT_TIME_INVALID")
    else:
        if (
            meta_time < residual_time
            or risk_time < meta_time
            or (meta_time - residual_time).total_seconds() > MAX_PIPELINE_GAP_HOURS * 3600
            or (risk_time - meta_time).total_seconds() > MAX_PIPELINE_GAP_HOURS * 3600
        ):
            blockers.append("EXECUTION_REPORT_SEQUENCE_INVALID")
        if enforce_freshness and (
            (now_utc - residual_time).total_seconds() < 0
            or (now_utc - meta_time).total_seconds() < 0
            or (now_utc - risk_time).total_seconds() < 0
            or (now_utc - residual_time).total_seconds() > MAX_REPORT_AGE_HOURS * 3600
            or (now_utc - meta_time).total_seconds() > MAX_REPORT_AGE_HOURS * 3600
            or (now_utc - risk_time).total_seconds() > MAX_REPORT_AGE_HOURS * 3600
        ):
            blockers.append("EXECUTION_REPORT_STALE")

    take_by_id: dict[str, dict[str, Any]] = {}
    candidate_keys: set[str] = set()
    residual_predictions = residual.get("predictions") if isinstance(residual.get("predictions"), list) else []
    predictions_by_candidate: dict[str, dict[str, Any]] = {}
    duplicate_prediction_keys: set[str] = set()
    for prediction in residual_predictions:
        if not isinstance(prediction, dict) or not _text(prediction.get("candidateKey")):
            continue
        key = _text(prediction.get("candidateKey"))
        if key in predictions_by_candidate:
            duplicate_prediction_keys.add(key)
        predictions_by_candidate[key] = prediction
    if duplicate_prediction_keys:
        blockers.append("DUPLICATE_RESIDUAL_ALPHA_PREDICTION")
    for row in take:
        if not isinstance(row, dict):
            blockers.append("INVALID_META_TAKE_ROW")
            continue
        decision_id = _text(row.get("decisionId"))
        candidate_key = _text(row.get("candidateKey"))
        if (
            not decision_id
            or not candidate_key
            or _text(row.get("decision")).upper() != "TAKE"
            or _text(row.get("policyFingerprint")) != meta_fingerprint
        ):
            blockers.append("INVALID_META_TAKE_ROW")
            continue
        if decision_id in take_by_id or candidate_key in candidate_keys:
            blockers.append("DUPLICATE_META_TAKE_IDENTITY")
            continue
        take_by_id[decision_id] = row
        candidate_keys.add(candidate_key)
        prediction = predictions_by_candidate.get(candidate_key, {})
        recommendation_time = _parse_time(row.get("generatedAt"))
        if (
            not prediction
            or _text(prediction.get("status")).upper() != "PREDICTED"
            or _text(prediction.get("forwardSealStatus")).upper() != "SEALED_FORWARD"
            or (_num(prediction.get("predictionLower90Pct")) or 0.0) <= 0
            or _text(prediction.get("modelFingerprint")) != residual_fingerprint
            or _text(prediction.get("predictionId")) != _text(row.get("residualAlphaPredictionId"))
            or _text(prediction.get("modelInstanceFingerprint")) != _text(row.get("residualAlphaModelInstanceFingerprint"))
            or _text(row.get("residualAlphaModelFingerprint")) != residual_fingerprint
            or _text(row.get("residualAlphaForwardSealStatus")).upper() != "SEALED_FORWARD"
            or _text(prediction.get("signalDate"))[:10] != _text(row.get("signalDate"))[:10]
            or _text(prediction.get("market")).lower() != _text(row.get("market")).lower()
            or _text(prediction.get("mode")).lower() != _text(row.get("mode")).lower()
            or _text(prediction.get("horizon")).lower() != _text(row.get("horizon")).lower()
            or _text(prediction.get("symbol")).upper() != _text(row.get("symbol")).upper()
            or recommendation_time is None
            or (now_utc - recommendation_time).total_seconds() < 0
            or (now_utc - recommendation_time).total_seconds() > MAX_REPORT_AGE_HOURS * 3600
        ):
            blockers.append("RESIDUAL_ALPHA_PREDICTION_LINEAGE_MISMATCH")

    outcome_rows = [row for row in positions + rejected if isinstance(row, dict)]
    outcome_ids = [_text(row.get("decisionId")) for row in outcome_rows]
    if set(outcome_ids) != set(take_by_id) or len(outcome_ids) != len(set(outcome_ids)):
        blockers.append("RISK_ALLOCATION_DECISION_SET_MISMATCH")
    if any(
        _text(take_by_id.get(_text(row.get("decisionId")), {}).get("candidateKey"))
        != _text(row.get("candidateKey"))
        for row in outcome_rows
    ):
        blockers.append("RISK_ALLOCATION_CANDIDATE_MISMATCH")
    if any(
        _text(take_by_id.get(_text(row.get("decisionId")), {}).get("symbol")).upper()
        != _text(row.get("symbol")).upper()
        or _text(take_by_id.get(_text(row.get("decisionId")), {}).get("market")).lower()
        != _text(row.get("market")).lower()
        for row in outcome_rows
    ):
        blockers.append("RISK_ALLOCATION_MARKET_SYMBOL_MISMATCH")

    weights: dict[str, float] = {}
    market_symbols: set[tuple[str, str]] = set()
    computed_beta = 0.0
    computed_sectors: dict[str, float] = defaultdict(float)
    executable: list[dict[str, Any]] = []
    for row in positions:
        if not isinstance(row, dict):
            blockers.append("INVALID_RISK_POSITION")
            continue
        decision_id = _text(row.get("decisionId"))
        meta_row = take_by_id.get(decision_id, {})
        market = _text(row.get("market")).lower()
        symbol = _text(row.get("symbol")).upper()
        weight = _num(row.get("weight"))
        beta = _num(row.get("beta"))
        stop_distance_pct = _num(row.get("stopDistancePct"))
        loss_at_stop_pct = _num(row.get("lossAtStopPctOfEquity"))
        sector = _text(row.get("sector"))
        identity = (market, symbol)
        if identity in market_symbols:
            blockers.append("DUPLICATE_MARKET_SYMBOL_ALLOCATION")
        market_symbols.add(identity)
        if (
            not decision_id
            or not meta_row
            or market not in {"kr", "us"}
            or not symbol
            or market != _text(meta_row.get("market")).lower()
            or symbol != _text(meta_row.get("symbol")).upper()
            or weight is None or weight <= 0
            or beta is None or beta <= 0
            or stop_distance_pct is None or stop_distance_pct <= 0
            or loss_at_stop_pct is None or loss_at_stop_pct < 0
            or not sector
        ):
            blockers.append("INVALID_RISK_POSITION")
            continue
        if (
            weight > EXPECTED_RISK_POLICY["maxPositionWeight"] + 1e-12
            or loss_at_stop_pct > EXPECTED_RISK_POLICY["accountRiskPerTrade"] * 100.0 + 1e-6
        ):
            blockers.append("RISK_POSITION_LIMIT_VIOLATION")
            continue
        weights[decision_id] = float(weight)
        computed_beta += float(weight) * float(beta)
        computed_sectors[sector] += float(weight)
        executable.append({
            **row,
            "market": market,
            "symbol": symbol,
            "mode": _text(meta_row.get("mode")).lower(),
            "horizon": _text(meta_row.get("horizon")).lower(),
            "signalDate": _text(meta_row.get("signalDate"))[:10],
            "entryPrice": _num(meta_row.get("entryPrice")),
            "stopPrice": _num(meta_row.get("stopPrice")),
            "targetPrice": _num(meta_row.get("targetPrice")),
            "metaPolicyFingerprint": meta_fingerprint,
            "riskPolicyVersion": RISK_POLICY_VERSION,
            "riskPolicyFingerprint": risk_fingerprint,
            "allocationFingerprint": declared_allocation,
        })

    gross = sum(weights.values())
    reported_sectors = risk.get("sectorWeights") if isinstance(risk.get("sectorWeights"), dict) else {}
    aggregates_match = (
        math.isclose(float(_num(risk.get("grossExposure")) or 0.0), gross, abs_tol=1e-6)
        and math.isclose(float(_num(risk.get("cashWeight")) or 0.0), 1.0 - gross, abs_tol=1e-6)
        and math.isclose(float(_num(risk.get("portfolioBeta")) or 0.0), computed_beta, abs_tol=1e-5)
        and set(reported_sectors) == set(computed_sectors)
        and all(
            math.isclose(float(_num(reported_sectors.get(sector)) or 0.0), weight, abs_tol=1e-6)
            for sector, weight in computed_sectors.items()
        )
    )
    if not aggregates_match:
        blockers.append("RISK_ALLOCATION_AGGREGATE_MISMATCH")
    if gross > EXPECTED_RISK_POLICY["maxGrossExposure"] + 1e-12:
        blockers.append("RISK_GROSS_LIMIT_VIOLATION")
    if computed_beta > EXPECTED_RISK_POLICY["maxPortfolioBeta"] + 1e-6:
        blockers.append("RISK_BETA_LIMIT_VIOLATION")
    if any(weight > EXPECTED_RISK_POLICY["maxSectorExposure"] + 1e-12 for weight in computed_sectors.values()):
        blockers.append("RISK_SECTOR_LIMIT_VIOLATION")

    unique_blockers = list(dict.fromkeys(_text(reason) for reason in blockers if _text(reason)))
    if unique_blockers:
        executable = []
    return {
        "status": "AUTHORIZED" if executable and not unique_blockers else "BLOCKED",
        "valid": not unique_blockers,
        "blockingReasons": unique_blockers or ([] if executable else ["NO_EXECUTABLE_POSITION"]),
        "generatedAt": risk.get("generatedAt"),
        "metaPolicyFingerprint": meta_fingerprint,
        "riskPolicyVersion": RISK_POLICY_VERSION,
        "riskPolicyFingerprint": risk_fingerprint,
        "allocationFingerprint": declared_allocation,
        "maxGrossExposure": EXPECTED_RISK_POLICY["maxGrossExposure"],
        "positions": executable,
    }


def execution_plan(market: str = "all", *, now: datetime | None = None) -> dict[str, Any]:
    meta = _read_json(META_GATE_JSON)
    risk = _read_json(RISK_BUDGET_JSON)
    residual = _read_json(RESIDUAL_ALPHA_JSON)
    plan = validate_reports(meta, risk, residual, now=now)
    normalized = _text(market).lower()
    if normalized in {"kr", "us"} and plan["positions"]:
        plan["positions"] = [row for row in plan["positions"] if row.get("market") == normalized]
        if not plan["positions"]:
            plan["status"] = "BLOCKED"
            plan["blockingReasons"] = ["NO_EXECUTABLE_POSITION_FOR_MARKET"]
    plan["market"] = normalized or "all"
    return plan


def authorization_for(
    market: str,
    symbol: str,
    *,
    candidate_key: str = "",
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_plan = plan or execution_plan(market)
    normalized_market = _text(market).lower()
    normalized_symbol = _text(symbol).upper()
    matches = [
        row for row in (active_plan.get("positions") or [])
        if _text(row.get("market")).lower() == normalized_market
        and _text(row.get("symbol")).upper() == normalized_symbol
        and (not candidate_key or _text(row.get("candidateKey")) == _text(candidate_key))
    ]
    if active_plan.get("status") != "AUTHORIZED" or len(matches) != 1:
        return {
            "allowed": False,
            "reason": "EXECUTION_CANDIDATE_NOT_AUTHORIZED",
            "blockingReasons": active_plan.get("blockingReasons") or [],
        }
    return {"allowed": True, "reason": "EXACT_CANDIDATE_AND_RISK_WEIGHT_AUTHORIZED", **matches[0]}
