from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import quant_execution_plan as plan


def _reports(now: datetime | None = None) -> tuple[dict, dict, dict]:
    now = now or datetime.now(timezone.utc)
    residual_definition = {"version": plan.RESIDUAL_ALPHA_POLICY_VERSION, "label": "TEST_RESIDUAL_MODEL"}
    residual_fingerprint = plan._fingerprint(residual_definition)
    meta_definition = plan._expected_meta_policy(residual_fingerprint)
    meta_fingerprint = plan._fingerprint(meta_definition)
    decision = {
        "decisionId": "decision-a",
        "candidateKey": "candidate-a",
        "policyFingerprint": meta_fingerprint,
        "signalDate": now.date().isoformat(),
        "generatedAt": (now - timedelta(hours=1)).isoformat(),
        "market": "us",
        "mode": "balanced",
        "horizon": "mid",
        "symbol": "AAPL",
        "decision": "TAKE",
        "entryPrice": 100.0,
        "stopPrice": 95.0,
        "targetPrice": 110.0,
        "residualAlphaModelFingerprint": residual_fingerprint,
        "residualAlphaModelInstanceFingerprint": "instance-a",
        "residualAlphaPredictionId": "prediction-a",
        "residualAlphaForwardSealStatus": "SEALED_FORWARD",
    }
    meta = {
        "status": "SHADOW_ONLY",
        "generatedAt": (now - timedelta(hours=1)).isoformat(),
        "policy": {**meta_definition, "fingerprint": meta_fingerprint},
        "take": [decision],
    }
    risk_definition = plan._expected_risk_policy(meta_fingerprint)
    risk_fingerprint = plan._fingerprint(risk_definition)
    position = {
        "decisionId": "decision-a",
        "candidateKey": "candidate-a",
        "symbol": "AAPL",
        "market": "us",
        "sector": "Technology",
        "weight": 0.10,
        "stopDistancePct": 5.0,
        "lossAtStopPctOfEquity": 0.5,
        "beta": 1.0,
        "betaSource": "CANDIDATE",
        "clamps": [],
    }
    risk = {
        "status": "SHADOW_ONLY",
        "generatedAt": (now - timedelta(minutes=30)).isoformat(),
        "policy": {**risk_definition, "fingerprint": risk_fingerprint},
        "lineage": {"valid": True, "blockingReasons": []},
        "positions": [position],
        "rejected": [],
        "grossExposure": 0.10,
        "cashWeight": 0.90,
        "portfolioBeta": 0.10,
        "sectorWeights": {"Technology": 0.10},
    }
    risk["lineage"]["allocationFingerprint"] = plan._fingerprint(plan._allocation_evidence(risk), None)
    residual = {
        "status": "SHADOW_ONLY",
        "generatedAt": (now - timedelta(hours=1, minutes=30)).isoformat(),
        "policy": {**residual_definition, "fingerprint": residual_fingerprint},
        "validation": {"evidenceStatus": "PASS"},
        "predictions": [{
            "candidateKey": "candidate-a",
            "signalDate": now.date().isoformat(),
            "market": "us",
            "mode": "balanced",
            "horizon": "mid",
            "symbol": "AAPL",
            "status": "PREDICTED",
            "forwardSealStatus": "SEALED_FORWARD",
            "predictionLower90Pct": 0.1,
            "modelFingerprint": residual_fingerprint,
            "modelInstanceFingerprint": "instance-a",
            "predictionId": "prediction-a",
        }],
    }
    return meta, risk, residual


def test_exact_candidate_and_weight_are_authorized() -> None:
    now = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)
    meta, risk, residual = _reports(now)

    result = plan.validate_reports(meta, risk, residual, now=now)
    auth = plan.authorization_for("us", "AAPL", candidate_key="candidate-a", plan=result)

    assert result["status"] == "AUTHORIZED"
    assert auth["allowed"] is True
    assert auth["weight"] == 0.10
    assert auth["entryPrice"] == 100.0
    assert auth["targetPrice"] == 110.0
    assert auth["riskPolicyVersion"] == plan.RISK_POLICY_VERSION


def test_global_take_never_authorizes_unrelated_symbol() -> None:
    now = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)
    meta, risk, residual = _reports(now)
    result = plan.validate_reports(meta, risk, residual, now=now)

    auth = plan.authorization_for("us", "MSFT", plan=result)

    assert auth["allowed"] is False
    assert auth["reason"] == "EXECUTION_CANDIDATE_NOT_AUTHORIZED"


def test_allocation_tamper_blocks_every_position() -> None:
    now = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)
    meta, risk, residual = _reports(now)
    risk["positions"][0]["weight"] = 0.30

    result = plan.validate_reports(meta, risk, residual, now=now)

    assert result["status"] == "BLOCKED"
    assert result["positions"] == []
    assert "RISK_ALLOCATION_FINGERPRINT_MISMATCH" in result["blockingReasons"]


def test_rehashed_duplicate_symbol_allocation_still_blocks() -> None:
    now = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)
    meta, risk, residual = _reports(now)
    second_decision = {
        **meta["take"][0],
        "decisionId": "decision-b",
        "candidateKey": "candidate-b",
        "mode": "aggressive",
    }
    second_position = {
        **risk["positions"][0],
        "decisionId": "decision-b",
        "candidateKey": "candidate-b",
        "weight": 0.05,
        "lossAtStopPctOfEquity": 0.25,
    }
    meta["take"].append(second_decision)
    risk["positions"].append(second_position)
    risk["grossExposure"] = 0.15
    risk["cashWeight"] = 0.85
    risk["portfolioBeta"] = 0.15
    risk["sectorWeights"] = {"Technology": 0.15}
    risk["lineage"]["allocationFingerprint"] = plan._fingerprint(plan._allocation_evidence(risk), None)

    result = plan.validate_reports(meta, risk, residual, now=now)

    assert result["status"] == "BLOCKED"
    assert "DUPLICATE_MARKET_SYMBOL_ALLOCATION" in result["blockingReasons"]


def test_stale_execution_reports_fail_closed() -> None:
    now = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)
    meta, risk, residual = _reports(now - timedelta(hours=48))

    result = plan.validate_reports(meta, risk, residual, now=now)

    assert result["status"] == "BLOCKED"
    assert "EXECUTION_REPORT_STALE" in result["blockingReasons"]


def test_rehashed_rejection_cannot_change_market_or_symbol() -> None:
    now = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)
    meta, risk, residual = _reports(now)
    risk["positions"] = []
    risk["rejected"] = [{
        "decisionId": "decision-a",
        "candidateKey": "candidate-a",
        "market": "us",
        "symbol": "MSFT",
        "reason": "NO_RISK_BUDGET_REMAINING",
        "clamps": [],
    }]
    risk["grossExposure"] = 0.0
    risk["cashWeight"] = 1.0
    risk["portfolioBeta"] = 0.0
    risk["sectorWeights"] = {}
    risk["lineage"]["allocationFingerprint"] = plan._fingerprint(plan._allocation_evidence(risk), None)

    result = plan.validate_reports(meta, risk, residual, now=now)

    assert "RISK_ALLOCATION_MARKET_SYMBOL_MISMATCH" in result["blockingReasons"]


def test_meta_take_must_match_current_sealed_residual_prediction() -> None:
    now = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)
    meta, risk, residual = _reports(now)
    residual["predictions"][0]["predictionId"] = "different-prediction"

    result = plan.validate_reports(meta, risk, residual, now=now)

    assert result["status"] == "BLOCKED"
    assert "RESIDUAL_ALPHA_PREDICTION_LINEAGE_MISMATCH" in result["blockingReasons"]


def test_unproven_residual_model_blocks_execution_even_with_take() -> None:
    now = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)
    meta, risk, residual = _reports(now)
    residual["validation"]["evidenceStatus"] = "WAIT"

    result = plan.validate_reports(meta, risk, residual, now=now)

    assert result["status"] == "BLOCKED"
    assert "RESIDUAL_ALPHA_MODEL_NOT_PROVEN" in result["blockingReasons"]
