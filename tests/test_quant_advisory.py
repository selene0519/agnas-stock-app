from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main  # noqa: E402
from app.services import quant_advisory  # noqa: E402


NOW = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)


def _inputs(*, source_decision: str = "TAKE") -> tuple[dict, dict, dict]:
    generated = (NOW - timedelta(hours=1)).isoformat()
    decision = {
        "decisionId": "decision-a",
        "candidateKey": "candidate-a",
        "signalDate": "2026-08-01",
        "generatedAt": generated,
        "market": "us",
        "mode": "balanced",
        "horizon": "swing",
        "symbol": "AAPL",
        "name": "Apple",
        "decision": source_decision,
        "reasons": [],
        "expectedValue": 1.2,
        "riskRewardRatio": 2.0,
        "entryPrice": 100.0,
        "stopPrice": 95.0,
        "targetPrice": 110.0,
        "modelProbabilityDisplayOnly": 61.0,
        "residualAlphaLower90Pct": 0.2,
    }
    meta = {
        "decisions": [decision],
        "cellEvidence": {
            "us|balanced|swing": {
                "evidenceStatus": "PASS",
                "independentDecisions": 120,
                "distinctSignalDates": 40,
            }
        },
    }
    execution = {
        "status": "AUTHORIZED",
        "positions": [{
            "candidateKey": "candidate-a",
            "market": "us",
            "symbol": "AAPL",
            "weight": 0.075,
        }],
    }
    operating = {
        "markets": {
            "us": {"recommendationActionable": True},
        }
    }
    return meta, execution, operating


def test_complete_take_contract_is_bounded_and_human_decided() -> None:
    meta, execution, operating = _inputs()

    payload = quant_advisory.build_advisory(meta, execution, operating, market="us", now=NOW)
    item = payload["items"][0]

    assert item["decision"] == "TAKE"
    assert item["recommendationActionable"] is True
    assert item["userAction"] == "REVIEW_MANUALLY"
    assert item["entryPrice"] == 100.0
    assert item["stopPrice"] == 95.0
    assert item["targetPrice"] == 110.0
    assert item["maxRecommendedWeightPct"] == 7.5
    assert item["validUntil"] == (NOW - timedelta(hours=1) + timedelta(hours=36)).isoformat()
    assert item["rationale"]
    assert item["counterEvidence"]
    assert item["uncertainty"]["calibratedWinProbabilityAvailable"] is False
    assert item["productScope"]["liveOrderAllowed"] is False


def test_take_is_downgraded_when_exact_risk_allocation_is_missing() -> None:
    meta, execution, operating = _inputs()
    execution["status"] = "BLOCKED"
    execution["positions"] = []

    item = quant_advisory.build_advisory(meta, execution, operating, market="us", now=NOW)["items"][0]

    assert item["decision"] == "WAIT"
    assert item["recommendationActionable"] is False
    assert item["maxRecommendedWeight"] == 0.0
    assert "NO_VERIFIED_RISK_ALLOCATION" in item["reasonCodes"]


def test_take_is_downgraded_when_operating_gate_is_not_ready() -> None:
    meta, execution, operating = _inputs()
    operating["markets"]["us"]["recommendationActionable"] = False

    item = quant_advisory.build_advisory(meta, execution, operating, market="us", now=NOW)["items"][0]

    assert item["decision"] == "WAIT"
    assert "OPERATING_GATES_NOT_READY" in item["reasonCodes"]


def test_invalid_or_expired_price_plan_rejects_take() -> None:
    meta, execution, operating = _inputs()
    meta["decisions"][0]["targetPrice"] = 99.0
    meta["decisions"][0]["generatedAt"] = (NOW - timedelta(hours=40)).isoformat()

    item = quant_advisory.build_advisory(meta, execution, operating, market="us", now=NOW)["items"][0]

    assert item["decision"] == "REJECT"
    assert "INVALID_PRICE_PLAN" in item["reasonCodes"]
    assert "RECOMMENDATION_STALE" in item["reasonCodes"]


def test_public_advisory_api_uses_complete_contract(monkeypatch) -> None:
    meta, execution, operating = _inputs()
    expected = quant_advisory.build_advisory(meta, execution, operating, market="us", limit=1, now=NOW)
    monkeypatch.setattr(quant_advisory, "advisory_recommendations", lambda market="all", limit=20: expected)

    with TestClient(main.app) as client:
        response = client.get("/api/quant/advisory-recommendations", params={"market": "us", "limit": 1})

    assert response.status_code == 200
    assert response.json() == expected
