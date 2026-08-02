from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_shadow_meta_gate",
    ROOT / "scripts" / "build_shadow_meta_gate.py",
)
assert SPEC and SPEC.loader
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def test_negative_expectancy_cell_rejects_even_high_score_candidate() -> None:
    candidate = {"dataStatus": "NORMAL", "expectedValue": 10, "rrActual": 3.0}
    cell = {
        "evidenceStatus": "REJECT",
        "blockingReasons": ["NON_POSITIVE_AFTER_COST_EXPECTANCY"],
    }

    decision, reasons = gate._candidate_decision(
        candidate, cell, {"status": "PREDICTED", "predictionLower90Pct": 1.0, "forwardSealStatus": "SEALED_FORWARD"}, "PASS"
    )

    assert decision == "REJECT"
    assert "NON_POSITIVE_AFTER_COST_EXPECTANCY" in reasons


def test_insufficient_but_not_negative_evidence_waits() -> None:
    candidate = {"dataStatus": "NORMAL", "expectedValue": 2, "rrActual": 2.0}
    cell = {
        "evidenceStatus": "WAIT",
        "blockingReasons": ["LOW_DISTINCT_SIGNAL_DATES"],
    }

    decision, _ = gate._candidate_decision(
        candidate, cell, {"status": "PREDICTED", "predictionLower90Pct": 1.0, "forwardSealStatus": "SEALED_FORWARD"}, "PASS"
    )

    assert decision == "WAIT"


def test_only_proven_positive_cell_can_take() -> None:
    candidate = {"dataStatus": "NORMAL", "expectedValue": 2, "rrActual": 2.0}
    cell = {"evidenceStatus": "PASS", "blockingReasons": []}

    decision, reasons = gate._candidate_decision(
        candidate, cell, {"status": "PREDICTED", "predictionLower90Pct": 1.0, "forwardSealStatus": "SEALED_FORWARD"}, "PASS"
    )

    assert decision == "TAKE"
    assert reasons == []


def test_unproven_residual_alpha_model_cannot_take() -> None:
    candidate = {"dataStatus": "NORMAL", "expectedValue": 2, "rrActual": 2.0}
    cell = {"evidenceStatus": "PASS", "blockingReasons": []}

    decision, reasons = gate._candidate_decision(candidate, cell, None, "WAIT")

    assert decision == "WAIT"
    assert "RESIDUAL_ALPHA_MODEL_NOT_PROVEN" in reasons


def test_recomputed_but_unsealed_prediction_cannot_take() -> None:
    candidate = {"dataStatus": "NORMAL", "expectedValue": 2, "rrActual": 2.0}
    cell = {"evidenceStatus": "PASS", "blockingReasons": []}

    decision, reasons = gate._candidate_decision(
        candidate, cell, {"status": "PREDICTED", "predictionLower90Pct": 1.0, "forwardSealStatus": "UNSEALED"}, "PASS"
    )

    assert decision == "WAIT"
    assert "RESIDUAL_ALPHA_PREDICTION_NOT_FORWARD_SEALED" in reasons


def test_nonpositive_residual_alpha_lower_bound_rejects() -> None:
    candidate = {"dataStatus": "NORMAL", "expectedValue": 2, "rrActual": 2.0}
    cell = {"evidenceStatus": "PASS", "blockingReasons": []}

    decision, reasons = gate._candidate_decision(
        candidate, cell, {"status": "PREDICTED", "predictionLower90Pct": -0.01, "forwardSealStatus": "SEALED_FORWARD"}, "PASS"
    )

    assert decision == "REJECT"
    assert "RESIDUAL_ALPHA_NOT_POSITIVE" in reasons


def test_probability_calibration_exposes_overconfidence() -> None:
    rows = [
        {"probability": 80, "net_pnl_pct": -1.0},
        {"probability": 80, "net_pnl_pct": -2.0},
        {"probability": 80, "net_pnl_pct": 1.0},
        {"probability": 80, "net_pnl_pct": -3.0},
    ]

    bins, brier = gate._calibration_bins(rows)

    assert bins[0]["actualWinRate"] == 0.25
    assert bins[0]["calibrationGap"] == 0.55
    assert brier is not None and brier > 0.4


def test_policy_fingerprint_and_decision_id_are_stable() -> None:
    row = {"market": "kr", "mode": "balanced", "horizon": "short", "symbol": "005930"}

    assert gate._policy_fingerprint() == gate._policy_fingerprint()
    assert gate._decision_id(row, "2026-07-30") == gate._decision_id(row, "2026-07-30")
    assert gate._decision_id(row, "2026-07-30") != gate._decision_id(row, "2026-07-31")


def test_meta_policy_and_decision_cohort_bind_to_residual_model_fingerprint() -> None:
    row = {"market": "kr", "mode": "balanced", "horizon": "short", "symbol": "005930"}

    assert gate._policy_fingerprint("model-a") != gate._policy_fingerprint("model-b")
    assert gate._decision_id(row, "2026-07-30", "model-a") != gate._decision_id(row, "2026-07-30", "model-b")


def test_stale_recommendation_is_rejected_even_without_cell_evidence() -> None:
    candidate = {"dataStatus": "NORMAL", "expectedValue": 2, "rrActual": 2.0}

    decision, reasons = gate._candidate_decision(
        candidate,
        None,
        {"status": "PREDICTED", "predictionLower90Pct": 1.0, "forwardSealStatus": "SEALED_FORWARD"},
        "PASS",
        ["RECOMMENDATION_STALE"],
    )

    assert decision == "REJECT"
    assert "RECOMMENDATION_STALE" in reasons


def test_recommendation_time_must_include_timezone() -> None:
    assert gate._parse_time("2026-07-31 09:00:00") is None
    assert gate._parse_time("2026-07-31T09:00:00+09:00") is not None
    assert gate._policy()["requiresTimezoneAwareRecommendationTime"] is True
