from __future__ import annotations

import csv
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "update_champion_challenger",
    ROOT / "scripts" / "update_champion_challenger.py",
)
assert SPEC and SPEC.loader
cc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cc)


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _decision(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "decisionId": "decision-a",
        "policyFingerprint": "meta-policy-a",
        "signalDate": "2026-07-30",
        "generatedAt": "2026-07-30T08:00:00+09:00",
        "market": "kr",
        "mode": "balanced",
        "horizon": "short",
        "symbol": "005930",
        "name": "Samsung",
        "score": 80.0,
        "decision": "WAIT",
        "reasons": ["LOW_DISTINCT_SIGNAL_DATES"],
    }
    row.update(overrides)
    return row


def test_decision_journal_is_append_only_and_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.csv"
    meta = {"decisions": [_decision()]}

    first = cc.record_decisions(meta, ledger, "2026-07-30T00:00:00+00:00")
    second = cc.record_decisions(meta, ledger, "2026-07-31T00:00:00+00:00")
    conflict = cc.record_decisions(
        {"decisions": [_decision(score=99.0)]},
        ledger,
        "2026-08-01T00:00:00+00:00",
    )

    assert first["appended"] == 1
    assert second["appended"] == 0
    assert conflict["conflicts"] == 1
    rows = cc._read_csv(ledger)
    assert len(rows) == 1
    assert rows[0]["score"] == "80.0"
    assert rows[0]["recorded_at"] == "2026-07-30T00:00:00+00:00"


def test_comparison_keeps_abstained_exposure_in_cash() -> None:
    rows = [
        {"decision_id": "a", "signal_date": "2026-07-01", "market": "kr", "mode": "balanced", "horizon": "short", "symbol": "A", "score": "90", "challenger_decision": "TAKE"},
        {"decision_id": "b", "signal_date": "2026-07-01", "market": "kr", "mode": "balanced", "horizon": "short", "symbol": "B", "score": "80", "challenger_decision": "REJECT"},
        {"decision_id": "c", "signal_date": "2026-07-02", "market": "kr", "mode": "balanced", "horizon": "short", "symbol": "C", "score": "90", "challenger_decision": "REJECT"},
    ]
    outcomes = {
        cc._decision_key(rows[0]): {"net_pnl_pct": 10.0},
        cc._decision_key(rows[1]): {"net_pnl_pct": -10.0},
        cc._decision_key(rows[2]): {"net_pnl_pct": -5.0},
    }

    result = cc.compare(rows, outcomes)

    assert result["completedSignalDates"] == 2
    assert result["daily"][0]["championReturnPct"] == 0.0
    assert result["daily"][0]["challengerReturnPct"] == 1.0
    assert result["daily"][1]["championReturnPct"] == -0.5
    assert result["daily"][1]["challengerReturnPct"] == 0.0
    assert result["challenger"]["selectedEvaluatedTrades"] == 1


def test_time_travel_outcome_is_excluded(tmp_path: Path) -> None:
    journal = tmp_path / "journal.csv"
    evaluations = tmp_path / "evaluations.csv"
    _write_csv(journal, ["journal_id", "as_of_date", "market", "mode", "horizon", "symbol"], [{
        "journal_id": "j1", "as_of_date": "2026-07-30", "market": "kr",
        "mode": "balanced", "horizon": "short", "symbol": "A",
    }])
    _write_csv(evaluations, ["journal_id", "status", "net_pnl_pct", "fill_date", "exit_date", "evaluated_at"], [{
        "journal_id": "j1", "status": "EVALUATED", "net_pnl_pct": "5",
        "fill_date": "2026-07-29", "exit_date": "2026-07-31", "evaluated_at": "2026-07-31T00:00:00",
    }])

    outcomes, violations = cc._latest_outcomes(journal, evaluations)

    assert outcomes == {}
    assert len(violations) == 1


def test_promotion_requires_all_preregistered_gates() -> None:
    comparison = {
        "completedSignalDates": 60,
        "champion": {"maxDrawdownPct": 8.0},
        "challenger": {
            "selectedEvaluatedTrades": 120,
            "avgDailyReturnPct": 0.1,
            "profitFactor": 1.3,
            "maxDrawdownPct": 6.0,
        },
        "pairedUplift": {"bootstrapCi95": [0.01, 0.2]},
    }
    integrity = {"immutableConflicts": 0, "timeIntegrityViolations": 0, "fingerprintCoverage": 1.0}

    passed = cc.promotion_decision(comparison, {"passed": True}, {"passed": True}, integrity)
    blocked = cc.promotion_decision(comparison, {"passed": False}, {"passed": False}, integrity)

    assert passed["promotionEligible"] is True
    assert passed["autoPromotionAllowed"] is False
    assert passed["humanApprovalRequired"] is True
    assert blocked["promotionEligible"] is False
    assert "RESIDUAL_ALPHA_NOT_PROVEN" in blocked["blockingReasons"]
    assert "RESIDUAL_ALPHA_MODEL_NOT_PROVEN" in blocked["blockingReasons"]


def test_residual_model_gate_requires_explicit_pass() -> None:
    missing = cc._residual_model_gate({})
    passing = cc._residual_model_gate({
        "policy": {"fingerprint": "model-a", "version": cc.RESIDUAL_ALPHA_POLICY_VERSION},
        "validation": {"evidenceStatus": "PASS", "oosPredictions": 200, "oosSignalDates": 40},
    })

    assert missing["passed"] is False
    assert passing["passed"] is True
    assert passing["modelFingerprint"] == "model-a"


def test_comparison_cohort_never_pools_prior_meta_policy() -> None:
    rows = [
        {"policy_fingerprint": "champion-a", "meta_policy_fingerprint": "meta-old"},
        {"policy_fingerprint": "champion-a", "meta_policy_fingerprint": "meta-current"},
        {"policy_fingerprint": "champion-old", "meta_policy_fingerprint": "meta-current"},
    ]

    selected = cc._active_policy_rows(
        rows,
        {"policy": {"fingerprint": "meta-current"}},
        "champion-a",
    )

    assert selected == [rows[1]]
