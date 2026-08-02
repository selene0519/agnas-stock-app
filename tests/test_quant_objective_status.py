from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main  # noqa: E402
from app.services import quant_objective_status as objective  # noqa: E402


def _passing_reports() -> tuple[dict, dict]:
    comparison = {
        "policy": {"version": objective.REQUIRED_CHAMPION_POLICY_VERSION},
        "comparison": {
            "completedSignalDates": 60,
            "champion": {"maxDrawdownPct": 8.0, "payoffRatio": 1.1},
            "challenger": {
                "selectedEvaluatedTrades": 120,
                "afterCostExpectancyPct": 0.15,
                "afterCostExpectancyBootstrapCi95": [0.02, 0.3],
                "payoffRatio": 1.3,
                "profitFactor": 1.4,
                "maxDrawdownPct": 6.0,
            },
        }
    }
    residual = {
        "policy": {"version": objective.REQUIRED_RESIDUAL_POLICY_VERSION},
        "validation": {
            "evidenceStatus": "PASS",
            "selectedBlockBootstrapCi95": [0.01, 0.2],
            "oosPredictions": 150,
            "oosSignalDates": 40,
        }
    }
    return comparison, residual


def test_all_four_north_star_objectives_must_pass_together() -> None:
    comparison, residual = _passing_reports()

    result = objective.build_objective_status(comparison, residual)

    assert result["overall"] == "PASS"
    assert result["allObjectivesPassed"] is True
    assert {row["status"] for row in result["objectives"].values()} == {"PASS"}
    assert result["productScope"]["liveOrderAllowed"] is False


def test_high_win_optics_cannot_hide_bad_payoff_or_drawdown() -> None:
    comparison, residual = _passing_reports()
    comparison["comparison"]["challenger"].update({
        "payoffRatio": 0.7,
        "profitFactor": 1.2,
        "maxDrawdownPct": 9.0,
    })

    result = objective.build_objective_status(comparison, residual)

    assert result["overall"] == "BLOCKED"
    assert result["objectives"]["payoff"]["status"] == "BLOCKED"
    assert result["objectives"]["drawdown"]["status"] == "BLOCKED"


def test_low_sample_or_missing_confidence_bounds_waits_instead_of_claiming_pass() -> None:
    comparison, residual = _passing_reports()
    comparison["comparison"]["completedSignalDates"] = 5
    comparison["comparison"]["challenger"]["selectedEvaluatedTrades"] = 10
    comparison["comparison"]["challenger"]["afterCostExpectancyBootstrapCi95"] = None
    comparison["comparison"]["challenger"]["payoffRatio"] = None
    residual["validation"] = {"evidenceStatus": "WAIT", "oosPredictions": 3, "oosSignalDates": 1}

    result = objective.build_objective_status(comparison, residual)

    assert result["overall"] == "WAIT"
    assert result["allObjectivesPassed"] is False
    assert result["objectives"]["afterCostExpectancy"]["status"] == "WAIT"
    assert result["objectives"]["payoff"]["status"] == "WAIT"
    assert result["objectives"]["residualAlpha"]["status"] == "WAIT"


def test_obsolete_policy_evidence_cannot_report_pass() -> None:
    comparison, residual = _passing_reports()
    comparison["policy"]["version"] = "champion-challenger-old"

    result = objective.build_objective_status(comparison, residual)

    assert result["overall"] == "WAIT"
    assert result["policyLineage"]["comparisonPolicyCurrent"] is False
    assert result["objectives"]["afterCostExpectancy"]["status"] == "WAIT"
    assert result["objectives"]["payoff"]["status"] == "WAIT"
    assert result["objectives"]["drawdown"]["status"] == "WAIT"


def test_public_objective_status_api_returns_the_same_contract(monkeypatch) -> None:
    comparison, residual = _passing_reports()
    expected = objective.build_objective_status(comparison, residual)
    monkeypatch.setattr(objective, "objective_status", lambda: expected)

    with TestClient(main.app) as client:
        response = client.get("/api/quant/objective-status")

    assert response.status_code == 200
    assert response.json() == expected
