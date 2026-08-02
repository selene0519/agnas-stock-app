from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "update_champion_challenger",
    ROOT / "scripts" / "update_champion_challenger.py",
)
assert SPEC and SPEC.loader
cc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cc)

RISK_SPEC = importlib.util.spec_from_file_location(
    "build_shadow_risk_budget_for_champion_test",
    ROOT / "scripts" / "build_shadow_risk_budget.py",
)
assert RISK_SPEC and RISK_SPEC.loader
risk_builder = importlib.util.module_from_spec(RISK_SPEC)
RISK_SPEC.loader.exec_module(risk_builder)


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _decision(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "decisionId": "decision-a",
        "candidateKey": "candidate-a",
        "policyFingerprint": "meta-policy-a",
        "signalDate": "2026-07-30",
        "generatedAt": "2026-07-30T08:00:00+09:00",
        "market": "kr",
        "mode": "balanced",
        "horizon": "short",
        "symbol": "005930",
        "name": "Samsung",
        "score": 80.0,
        "decision": "TAKE",
        "reasons": ["LOW_DISTINCT_SIGNAL_DATES"],
    }
    row.update(overrides)
    return row


def _risk_report(meta_fingerprint: str = "meta-policy-a", weight: float = 0.06) -> dict:
    policy = {
        "version": cc.RISK_BUDGET_POLICY_VERSION,
        "metaPolicyFingerprint": meta_fingerprint,
        **cc.EXPECTED_RISK_POLICY,
    }
    policy["fingerprint"] = cc._fingerprint(policy)
    report = {
        "policy": policy,
        "positions": [{
            "decisionId": "decision-a",
            "candidateKey": "candidate-a",
            "symbol": "005930",
            "market": "kr",
            "sector": "Tech",
            "weight": weight,
            "stopDistancePct": 5.0,
            "lossAtStopPctOfEquity": weight * 5.0,
            "beta": 1.0,
            "betaSource": "CANDIDATE",
            "clamps": [],
        }],
        "rejected": [],
        "grossExposure": weight,
        "cashWeight": 1.0 - weight,
        "portfolioBeta": weight,
        "sectorWeights": {"Tech": weight},
        "lineage": {"valid": True, "blockingReasons": []},
    }
    report["lineage"]["allocationFingerprint"] = cc._full_fingerprint(cc._allocation_evidence(report))
    return report


def test_decision_journal_is_append_only_and_idempotent(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.csv"
    decision = _decision()
    meta = {"policy": {"fingerprint": "meta-policy-a"}, "decisions": [decision], "take": [decision]}
    risk_context = cc._risk_context(meta, _risk_report())

    first = cc.record_decisions(meta, ledger, "2026-07-30T00:00:00+00:00", risk_context=risk_context)
    second = cc.record_decisions(meta, ledger, "2026-07-31T00:00:00+00:00", risk_context=risk_context)
    conflict = cc.record_decisions(
        {"decisions": [_decision(score=99.0)]},
        ledger,
        "2026-08-01T00:00:00+00:00",
        risk_context=risk_context,
    )

    assert first["appended"] == 1
    assert second["appended"] == 0
    assert conflict["conflicts"] == 1
    rows = cc._read_csv(ledger)
    assert len(rows) == 1
    assert rows[0]["score"] == "80.0"
    assert rows[0]["recorded_at"] == "2026-07-30T00:00:00+00:00"
    assert len(rows[0]["record_hash"]) == 64
    assert rows[0]["record_hash"] == cc._record_hash(rows[0])


def test_comparison_keeps_abstained_exposure_in_cash() -> None:
    rows = [
        {"decision_id": "a", "signal_date": "2026-07-01", "market": "kr", "mode": "balanced", "horizon": "short", "symbol": "A", "score": "90", "challenger_decision": "TAKE", "challenger_weight": "0.06"},
        {"decision_id": "b", "signal_date": "2026-07-01", "market": "kr", "mode": "balanced", "horizon": "short", "symbol": "B", "score": "80", "challenger_decision": "REJECT", "challenger_weight": "0"},
        {"decision_id": "c", "signal_date": "2026-07-02", "market": "kr", "mode": "balanced", "horizon": "short", "symbol": "C", "score": "90", "challenger_decision": "REJECT", "challenger_weight": "0"},
    ]
    outcomes = {
        cc._decision_key(rows[0]): {"net_pnl_pct": 10.0},
        cc._decision_key(rows[1]): {"net_pnl_pct": -10.0},
        cc._decision_key(rows[2]): {"net_pnl_pct": -5.0},
    }

    result = cc.compare(rows, outcomes)

    assert result["completedSignalDates"] == 2
    assert result["daily"][0]["championReturnPct"] == 0.0
    assert result["daily"][0]["challengerReturnPct"] == 0.6
    assert result["daily"][0]["challengerGrossExposurePct"] == 6.0
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
    integrity = {"immutableConflicts": 0, "timeIntegrityViolations": 0, "fingerprintCoverage": 1.0, "riskLineageCoverage": 1.0}

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


def test_risk_allocation_tamper_is_rejected_even_when_lineage_claims_valid() -> None:
    decision = _decision()
    meta = {"policy": {"fingerprint": "meta-policy-a"}, "take": [decision]}
    report = _risk_report(weight=0.06)
    report["positions"][0]["weight"] = 0.10

    context = cc._risk_context(meta, report)

    assert context["valid"] is False
    assert "RISK_ALLOCATION_FINGERPRINT_MISMATCH" in context["blockingReasons"]
    assert context["weights"] == {}


def test_risk_builder_keeps_only_highest_ranked_copy_of_market_symbol() -> None:
    candidates = [
        {
            "decisionId": "high",
            "candidateKey": "candidate-high",
            "decision": "TAKE",
            "market": "us",
            "symbol": "AAPL",
            "score": 90,
            "entryPrice": 100,
            "stopPrice": 95,
            "sector": "Technology",
            "beta": 1.0,
        },
        {
            "decisionId": "low",
            "candidateKey": "candidate-low",
            "decision": "TAKE",
            "market": "us",
            "symbol": "AAPL",
            "score": 80,
            "entryPrice": 100,
            "stopPrice": 95,
            "sector": "Technology",
            "beta": 1.0,
        },
    ]

    allocation = risk_builder.allocate(candidates)

    assert [row["decisionId"] for row in allocation["positions"]] == ["high"]
    assert allocation["rejected"][0]["decisionId"] == "low"
    assert allocation["rejected"][0]["reason"] == "DUPLICATE_SYMBOL_LOWER_RANK"


def test_rehashed_risk_limit_violation_still_fails_closed() -> None:
    decision = _decision()
    meta = {"policy": {"fingerprint": "meta-policy-a"}, "take": [decision]}
    report = _risk_report(weight=0.06)
    report["positions"][0]["lossAtStopPctOfEquity"] = 5.0
    report["lineage"]["allocationFingerprint"] = cc._full_fingerprint(cc._allocation_evidence(report))

    context = cc._risk_context(meta, report)

    assert context["valid"] is False
    assert "RISK_POSITION_LIMIT_VIOLATION" in context["blockingReasons"]


def test_risk_aggregate_tamper_fails_closed() -> None:
    decision = _decision()
    meta = {"policy": {"fingerprint": "meta-policy-a"}, "take": [decision]}
    report = _risk_report(weight=0.06)
    report["grossExposure"] = 0.30

    context = cc._risk_context(meta, report)

    assert context["valid"] is False
    assert "RISK_ALLOCATION_AGGREGATE_MISMATCH" in context["blockingReasons"]


def test_active_cohort_requires_current_risk_policy() -> None:
    rows = [
        {"policy_fingerprint": "champion-a", "meta_policy_fingerprint": "meta-current", "risk_policy_fingerprint": "risk-old"},
        {"policy_fingerprint": "champion-a", "meta_policy_fingerprint": "meta-current", "risk_policy_fingerprint": "risk-current"},
    ]

    selected = cc._active_policy_rows(
        rows,
        {"policy": {"fingerprint": "meta-current"}},
        "champion-a",
        "risk-current",
    )

    assert selected == [rows[1]]


def test_settlement_workflow_builds_risk_budget_before_champion() -> None:
    workflow = (ROOT / ".github" / "workflows" / "mone-settle-validations.yml").read_text(encoding="utf-8")

    assert workflow.index("scripts/build_shadow_meta_gate.py") < workflow.index("scripts/build_shadow_risk_budget.py")
    assert workflow.index("scripts/build_shadow_risk_budget.py") < workflow.index("scripts/update_champion_challenger.py")


def test_champion_accepts_exact_report_emitted_by_risk_builder(tmp_path: Path, monkeypatch) -> None:
    decision = {
        **_decision(),
        "entryPrice": 100,
        "stopPrice": 95,
        "sector": "Tech",
        "beta": 1.0,
    }
    meta = {
        "policy": {"fingerprint": "meta-policy-a"},
        "decisions": [decision],
        "take": [decision],
    }
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setattr(risk_builder, "META_GATE", meta_path)

    report = risk_builder.build()
    context = cc._risk_context(meta, report)

    assert context["valid"] is True
    assert context["weights"] == {"decision-a": 0.1}


def test_tampered_champion_ledger_row_is_excluded_and_blocks_promotion(tmp_path: Path) -> None:
    decision = _decision(entryPrice=100, stopPrice=95, sector="Tech", beta=1.0)
    meta = {
        "policy": {"fingerprint": "meta-policy-a"},
        "decisions": [decision],
        "take": [decision],
    }
    paths = {name: tmp_path / name for name in (
        "meta.json", "risk.json", "alpha.json", "residual.json",
        "journal.csv", "evaluations.csv", "ledger.csv",
    )}
    paths["meta.json"].write_text(json.dumps(meta), encoding="utf-8")
    paths["risk.json"].write_text(json.dumps(_risk_report(weight=0.06)), encoding="utf-8")
    paths["alpha.json"].write_text("{}", encoding="utf-8")
    paths["residual.json"].write_text("{}", encoding="utf-8")
    first = cc.build(
        paths["meta.json"], paths["alpha.json"], paths["journal.csv"],
        paths["evaluations.csv"], paths["ledger.csv"],
        residual_path=paths["residual.json"], risk_path=paths["risk.json"],
    )
    assert first["integrity"]["recordHashViolations"] == 0
    assert first["policyCohort"]["validActiveRows"] == 1

    rows = cc._read_csv(paths["ledger.csv"])
    rows[0]["score"] = "99"
    cc._write_ledger(paths["ledger.csv"], rows)
    second = cc.build(
        paths["meta.json"], paths["alpha.json"], paths["journal.csv"],
        paths["evaluations.csv"], paths["ledger.csv"],
        residual_path=paths["residual.json"], risk_path=paths["risk.json"],
        record=False,
    )

    assert second["integrity"]["recordHashViolations"] == 1
    assert second["policyCohort"]["validActiveRows"] == 0
    assert "CHAMPION_LEDGER_RECORD_HASH_VIOLATION" in second["promotion"]["blockingReasons"]
