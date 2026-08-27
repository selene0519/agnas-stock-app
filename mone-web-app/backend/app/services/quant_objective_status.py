"""Read-only multi-objective north-star status for the advisory quant system."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services import product_scope


REPO_ROOT = Path(__file__).resolve().parents[4]
REPORTS = REPO_ROOT / "reports"
CHAMPION_CHALLENGER_JSON = REPORTS / "champion_challenger.json"
RESIDUAL_ALPHA_JSON = REPORTS / "shadow_residual_alpha.json"
VERSION = "quant-objectives-v1"
MIN_PAYOFF_RATIO = 1.0
MIN_PROFIT_FACTOR = 1.0
REQUIRED_CHAMPION_POLICY_VERSION = "champion-challenger-v1.4.0"
REQUIRED_RESIDUAL_POLICY_VERSION = "shadow-residual-alpha-v1.1.2"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _num(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except (TypeError, ValueError):
        return None


def _ci(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 2:
        return None
    low, high = _num(value[0]), _num(value[1])
    return [low, high] if low is not None and high is not None else None


def build_objective_status(
    champion_challenger: dict[str, Any],
    residual_alpha: dict[str, Any],
) -> dict[str, Any]:
    comparison = champion_challenger.get("comparison") if isinstance(champion_challenger.get("comparison"), dict) else {}
    comparison_policy = champion_challenger.get("policy") if isinstance(champion_challenger.get("policy"), dict) else {}
    comparison_policy_current = comparison_policy.get("version") == REQUIRED_CHAMPION_POLICY_VERSION
    champion = comparison.get("champion") if isinstance(comparison.get("champion"), dict) else {}
    challenger = comparison.get("challenger") if isinstance(comparison.get("challenger"), dict) else {}
    completed_dates = int(_num(comparison.get("completedSignalDates")) or 0)
    mature = completed_dates >= 60 and int(_num(challenger.get("selectedEvaluatedTrades")) or 0) >= 120

    expectancy = _num(challenger.get("afterCostExpectancyPct") or challenger.get("avgDailyReturnPct"))
    expectancy_ci = _ci(challenger.get("afterCostExpectancyBootstrapCi95"))
    if not comparison_policy_current or not mature:
        expectancy_state = "WAIT"
    elif expectancy_ci and expectancy_ci[0] > 0:
        expectancy_state = "PASS"
    elif mature and expectancy is not None and expectancy <= 0:
        expectancy_state = "BLOCKED"
    else:
        expectancy_state = "WAIT"

    payoff = _num(challenger.get("payoffRatio"))
    profit_factor = _num(challenger.get("profitFactor"))
    if not comparison_policy_current or not mature:
        payoff_state = "WAIT"
    elif payoff is not None and payoff >= MIN_PAYOFF_RATIO and profit_factor is not None and profit_factor > MIN_PROFIT_FACTOR:
        payoff_state = "PASS"
    elif mature and (payoff is None or payoff < MIN_PAYOFF_RATIO or profit_factor is None or profit_factor <= MIN_PROFIT_FACTOR):
        payoff_state = "BLOCKED"
    else:
        payoff_state = "WAIT"

    champion_drawdown = _num(champion.get("maxDrawdownPct"))
    challenger_drawdown = _num(challenger.get("maxDrawdownPct"))
    if not comparison_policy_current or not mature:
        drawdown_state = "WAIT"
    elif champion_drawdown is not None and challenger_drawdown is not None and challenger_drawdown <= champion_drawdown:
        drawdown_state = "PASS"
    elif mature and champion_drawdown is not None and challenger_drawdown is not None:
        drawdown_state = "BLOCKED"
    else:
        drawdown_state = "WAIT"

    validation = residual_alpha.get("validation") if isinstance(residual_alpha.get("validation"), dict) else {}
    residual_policy = residual_alpha.get("policy") if isinstance(residual_alpha.get("policy"), dict) else {}
    residual_policy_current = residual_policy.get("version") == REQUIRED_RESIDUAL_POLICY_VERSION
    residual_ci = _ci(validation.get("selectedBlockBootstrapCi95"))
    residual_evidence = str(validation.get("evidenceStatus") or "MISSING").upper()
    if not residual_policy_current or not mature:
        residual_state = "WAIT"
    elif residual_evidence == "PASS" and residual_ci and residual_ci[0] > 0:
        residual_state = "PASS"
    elif residual_evidence == "REJECT" or (residual_ci and residual_ci[1] <= 0):
        residual_state = "BLOCKED"
    else:
        residual_state = "WAIT"

    objectives = {
        "afterCostExpectancy": {
            "status": expectancy_state,
            "valuePct": expectancy,
            "bootstrapCi95": expectancy_ci,
            "rule": "bootstrap lower 95% > 0",
        },
        "payoff": {
            "status": payoff_state,
            "payoffRatio": payoff,
            "profitFactor": profit_factor,
            "rule": "payoff >= 1.0 and profit factor > 1.0",
        },
        "drawdown": {
            "status": drawdown_state,
            "championMaxDrawdownPct": champion_drawdown,
            "challengerMaxDrawdownPct": challenger_drawdown,
            "rule": "challenger max drawdown <= champion",
        },
        "residualAlpha": {
            "status": residual_state,
            "evidenceStatus": residual_evidence,
            "selectedBlockBootstrapCi95": residual_ci,
            "oosPredictions": validation.get("oosPredictions"),
            "oosSignalDates": validation.get("oosSignalDates"),
            "rule": "validated residual alpha lower confidence bound > 0",
        },
    }
    states = [row["status"] for row in objectives.values()]
    overall = "PASS" if all(state == "PASS" for state in states) else ("BLOCKED" if "BLOCKED" in states else "WAIT")
    return {
        "status": "OK",
        "version": VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "allObjectivesPassed": overall == "PASS",
        "completedSignalDates": completed_dates,
        "evaluatedChallengerTrades": int(_num(challenger.get("selectedEvaluatedTrades")) or 0),
        "evidenceMature": mature,
        "requiredSignalDates": 60,
        "requiredEvaluatedTrades": 120,
        "policyLineage": {
            "comparisonPolicyVersion": comparison_policy.get("version"),
            "requiredComparisonPolicyVersion": REQUIRED_CHAMPION_POLICY_VERSION,
            "comparisonPolicyCurrent": comparison_policy_current,
            "residualPolicyVersion": residual_policy.get("version"),
            "requiredResidualPolicyVersion": REQUIRED_RESIDUAL_POLICY_VERSION,
            "residualPolicyCurrent": residual_policy_current,
        },
        "objectives": objectives,
        "productScope": product_scope.product_scope(),
    }


def objective_status() -> dict[str, Any]:
    return build_objective_status(
        _read_json(CHAMPION_CHALLENGER_JSON),
        _read_json(RESIDUAL_ALPHA_JSON),
    )
