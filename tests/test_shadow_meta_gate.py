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

    decision, reasons = gate._candidate_decision(candidate, cell)

    assert decision == "REJECT"
    assert "NON_POSITIVE_AFTER_COST_EXPECTANCY" in reasons


def test_insufficient_but_not_negative_evidence_waits() -> None:
    candidate = {"dataStatus": "NORMAL", "expectedValue": 2, "rrActual": 2.0}
    cell = {
        "evidenceStatus": "WAIT",
        "blockingReasons": ["LOW_DISTINCT_SIGNAL_DATES"],
    }

    decision, _ = gate._candidate_decision(candidate, cell)

    assert decision == "WAIT"


def test_only_proven_positive_cell_can_take() -> None:
    candidate = {"dataStatus": "NORMAL", "expectedValue": 2, "rrActual": 2.0}
    cell = {"evidenceStatus": "PASS", "blockingReasons": []}

    decision, reasons = gate._candidate_decision(candidate, cell)

    assert decision == "TAKE"
    assert reasons == []


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
