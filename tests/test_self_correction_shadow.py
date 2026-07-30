from __future__ import annotations

import importlib.util
import json
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "update_self_correction_shadow",
    ROOT / "scripts" / "update_self_correction_shadow.py",
)
assert SPEC and SPEC.loader
shadow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(shadow)
from app.engine import self_correction_v2 as live_correction  # noqa: E402


def _candidate() -> dict:
    return {
        "candidateFingerprint": "candidate-a",
        "approvalId": "approval-a",
        "approvalRecordHash": "approval-hash-a",
        "approvedEvidenceFingerprint": "evidence-a",
        "calibrationPolicyVersion": shadow.vtj.AUTO_CALIBRATION_POLICY["version"],
        "calibrationPolicyFingerprint": shadow.vtj._calibration_policy_fingerprint(),
        "market": "us",
        "mode": "balanced",
        "horizon": "swing",
        "sourceType": "FORWARD_PAPER_TRADE",
        "reason": "STOP_TOO_TIGHT",
        "before": {
            "sampleCount": 60,
            "confidence": 0.8,
            "weightAdjustments": {},
            "priceAdjustments": {},
            "filterAdjustments": {},
        },
        "after": {
            "sampleCount": 60,
            "confidence": 0.8,
            "weightAdjustments": {"momentumScore": 0.5},
            "priceAdjustments": {"entryAggressiveness": 0.1, "targetMultiplier": 0.02, "stopAtrMultiplier": 0.1},
            "filterAdjustments": {"minRiskRewardRatio": 0.0},
            "topFailureReasons": ["STOP_TOO_TIGHT"],
        },
        "delta": {
            "weightAdjustments": {"momentumScore": 0.5},
            "priceAdjustments": {"entryAggressiveness": 0.1, "targetMultiplier": 0.02, "stopAtrMultiplier": 0.1},
        },
    }


def _recommendation(signal_date: str = "2026-01-02") -> dict:
    components = {
        "upsideScore": 70.0,
        "momentumScore": 60.0,
        "riskScore": 70.0,
        "entryScore": 65.0,
        "rrScore": 75.0,
        "qualityScore": 60.0,
    }
    weights = {
        "upsideScore": 0.25,
        "riskScore": 0.25,
        "rrScore": 0.20,
        "momentumScore": 0.15,
        "entryScore": 0.10,
        "qualityScore": 0.0,
    }
    return {
        "market": "us",
        "mode": "balanced",
        "horizon": "swing",
        "symbol": "TEST",
        "name": "Test",
        "generatedAt": f"{signal_date}T21:00:00+00:00",
        "recommendationSource": "test.csv",
        "correctionInputContractVersion": shadow.INPUT_CONTRACT_VERSION,
        "rawEntry": 100,
        "rawStop": 90,
        "rawTarget": 120,
        "rawModelScore": 60,
        "scoreComponentsJson": json.dumps(components),
        "scoreWeightsJson": json.dumps(weights),
        "entry": "$100.00",
        "stop": "$90.00",
        "target": "$120.00",
        "finalRankScore": 60,
        "expectedValue": 1.0,
        "dataStatus": "NORMAL",
        "currentPrice": 100.0,
    }


def _write_ohlcv(path: Path, dates: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "date,open,high,low,close,volume\n"
        + "".join(f"{day},100,101,99,100,1000\n" for day in dates),
        encoding="utf-8",
    )


def _registry_row() -> dict:
    row = {field: "" for field in shadow.REGISTRY_FIELDS}
    row.update({
        "candidate_fingerprint": "candidate-a",
        "approval_id": "approval-a",
        "approval_record_hash": "approval-hash-a",
        "calibration_policy_version": shadow.vtj.AUTO_CALIBRATION_POLICY["version"],
        "calibration_policy_fingerprint": shadow.vtj._calibration_policy_fingerprint(),
        "approved_evidence_fingerprint": "evidence-a",
        "market": "us",
        "mode": "balanced",
        "horizon": "swing",
    })
    row["record_hash"] = shadow._registry_hash(row)
    return row


def test_explicit_correction_candidate_changes_scores_and_prices_without_global_state() -> None:
    candidate = _candidate()
    result = shadow.apply_correction_params(
        {"momentumScore": 60.0, "riskScore": 70.0},
        100.0,
        120.0,
        90.0,
        "us",
        candidate["after"],
    )

    assert result["correctionApplied"] is True
    assert result["adjustedScores"]["momentumScore"] == 65.0
    assert result["adjustedEntry"] == 100.1
    assert result["adjustedTarget"] == 122.4
    assert result["adjustedStop"] == 89.1


def test_live_correction_defaults_off_and_quarantines_unpromoted_legacy(monkeypatch) -> None:
    legacy = _candidate()["after"]
    monkeypatch.setattr(live_correction.correction_store, "load_params", lambda: {"version": 372})
    monkeypatch.setattr(live_correction.correction_store, "load_correction", lambda *_args: legacy)
    monkeypatch.delenv("SELF_CORRECTION_ENABLED", raising=False)

    default_off = live_correction.apply_correction(
        {"momentumScore": 60.0}, 100.0, 120.0, 90.0, "us", "balanced", "swing"
    )
    monkeypatch.setenv("SELF_CORRECTION_ENABLED", "true")
    legacy_blocked = live_correction.apply_correction(
        {"momentumScore": 60.0}, 100.0, 120.0, 90.0, "us", "balanced", "swing"
    )
    promoted = {
        **legacy,
        "journalCalibrationPromoted": True,
        "promotionCertificateHash": "certificate-a",
        "candidateFingerprint": "candidate-a",
        "calibrationPolicyFingerprint": "policy-a",
    }
    monkeypatch.setattr(live_correction.correction_store, "load_correction", lambda *_args: promoted)
    promoted_result = live_correction.apply_correction(
        {"momentumScore": 60.0}, 100.0, 120.0, 90.0, "us", "balanced", "swing"
    )

    assert default_off["correctionApplied"] is False
    assert legacy_blocked["correctionApplied"] is False
    assert "quarantined" in legacy_blocked["correctionSummary"]
    assert promoted_result["correctionApplied"] is True


def test_prediction_is_sealed_only_when_raw_contract_and_ohlcv_cutoff_match(tmp_path: Path) -> None:
    prediction_path = tmp_path / "predictions.csv"
    ohlcv_dir = tmp_path / "ohlcv"
    _write_ohlcv(ohlcv_dir / "us_TEST_daily.csv", ["2026-01-01", "2026-01-02"])

    result = shadow.record_predictions(
        [_candidate()],
        [_recommendation()],
        prediction_path,
        ohlcv_dir,
        recorded_at="2026-01-02T22:00:00+00:00",
    )
    rows = shadow._read_csv(prediction_path)

    assert result["appended"] == 1
    assert result["conflicts"] == 0
    assert result["runAt"] == "2026-01-02T22:00:00+00:00"
    assert result["candidateDiagnostics"][0]["matchedRecommendations"] == 1
    assert result["candidateDiagnostics"][0]["sealedOrConfirmed"] == 1
    assert rows[0]["forward_seal_status"] == "SEALED_FORWARD"
    assert rows[0]["record_hash"] == shadow._prediction_hash(rows[0])
    assert float(rows[0]["challenger_score"]) > float(rows[0]["champion_score"])

    future_path = tmp_path / "future.csv"
    _write_ohlcv(ohlcv_dir / "us_TEST_daily.csv", ["2026-01-01", "2026-01-02", "2026-01-03"])
    future = shadow.record_predictions(
        [{**_candidate(), "candidateFingerprint": "candidate-future"}],
        [_recommendation()],
        future_path,
        ohlcv_dir,
    )
    assert future["appended"] == 0
    assert future["skippedForwardSeal"] == 1

    stale_path = tmp_path / "stale.csv"
    _write_ohlcv(ohlcv_dir / "us_TEST_daily.csv", ["2026-01-01", "2026-01-02"])
    stale = shadow.record_predictions(
        [{**_candidate(), "candidateFingerprint": "candidate-stale"}],
        [_recommendation()],
        stale_path,
        ohlcv_dir,
        recorded_at="2026-01-05T12:00:00+00:00",
    )
    assert stale["appended"] == 0
    assert stale["skippedForwardSeal"] == 1


def test_prediction_cannot_be_sealed_after_next_session_opens_even_within_delay_limit(tmp_path: Path) -> None:
    prediction_path = tmp_path / "predictions.csv"
    ohlcv_dir = tmp_path / "ohlcv"
    _write_ohlcv(ohlcv_dir / "us_TEST_daily.csv", ["2026-01-05"])

    result = shadow.record_predictions(
        [_candidate()],
        [_recommendation("2026-01-05")],
        prediction_path,
        ohlcv_dir,
        recorded_at="2026-01-06T15:00:00+00:00",
    )

    assert result["appended"] == 0
    assert result["skippedAfterNextSessionOpen"] == 1
    assert result["candidateDiagnostics"][0]["skippedAfterNextSessionOpen"] == 1


def test_prediction_cannot_be_sealed_before_canonical_signal_close(tmp_path: Path) -> None:
    prediction_path = tmp_path / "predictions.csv"
    ohlcv_dir = tmp_path / "ohlcv"
    _write_ohlcv(ohlcv_dir / "us_TEST_daily.csv", ["2026-01-05"])
    recommendation = {**_recommendation("2026-01-05"), "generatedAt": "2026-01-05T20:00:00+00:00"}

    result = shadow.record_predictions(
        [_candidate()],
        [recommendation],
        prediction_path,
        ohlcv_dir,
        recorded_at="2026-01-05T20:30:00+00:00",
    )

    assert result["appended"] == 0
    assert result["skippedBeforeSignalClose"] == 1


def test_forward_seal_window_is_dst_aware_and_conservative() -> None:
    winter_close, winter_open = shadow._forward_seal_window("2026-01-05", "us")
    summer_close, summer_open = shadow._forward_seal_window("2026-07-30", "us")

    assert winter_close.isoformat() == "2026-01-05T21:00:00+00:00"
    assert winter_open.isoformat() == "2026-01-06T14:30:00+00:00"
    assert summer_close.isoformat() == "2026-07-30T20:00:00+00:00"
    assert summer_open.isoformat() == "2026-07-31T13:30:00+00:00"


def test_market_scoped_recording_does_not_reseal_other_market(tmp_path: Path) -> None:
    prediction_path = tmp_path / "predictions.csv"
    ohlcv_dir = tmp_path / "ohlcv"
    _write_ohlcv(ohlcv_dir / "us_TEST_daily.csv", ["2026-01-05"])
    _write_ohlcv(ohlcv_dir / "kr_005930_daily.csv", ["2026-01-05"])
    us_candidate = _candidate()
    kr_candidate = {
        **_candidate(),
        "candidateFingerprint": "candidate-kr",
        "market": "kr",
    }
    kr_recommendation = {
        **_recommendation("2026-01-05"),
        "market": "kr",
        "symbol": "005930",
        "generatedAt": "2026-01-05T06:40:00+00:00",
    }

    kr_run = shadow.record_predictions(
        [us_candidate, kr_candidate],
        [_recommendation("2026-01-05"), kr_recommendation],
        prediction_path,
        ohlcv_dir,
        recorded_at="2026-01-05T07:00:00+00:00",
        record_market="kr",
    )
    us_run = shadow.record_predictions(
        [us_candidate, kr_candidate],
        [_recommendation("2026-01-05"), kr_recommendation],
        prediction_path,
        ohlcv_dir,
        recorded_at="2026-01-05T22:00:00+00:00",
        record_market="us",
    )

    assert kr_run["appended"] == 1
    assert us_run["appended"] == 1
    assert kr_run["conflicts"] == 0
    assert us_run["conflicts"] == 0
    assert {row["market"] for row in shadow._read_csv(prediction_path)} == {"kr", "us"}
    assert [row["market"] for row in kr_run["candidateDiagnostics"]] == ["kr"]
    assert [row["market"] for row in us_run["candidateDiagnostics"]] == ["us"]


def test_candidate_recording_health_has_grace_then_fails_loudly() -> None:
    registry = _registry_row()
    registry["registered_at"] = "2026-01-01T00:00:00+00:00"
    registry["record_hash"] = shadow._registry_hash(registry)
    failed_run = {
        "runAt": "2026-01-01T01:00:00+00:00",
        "candidateDiagnostics": [{
            "candidateFingerprint": "candidate-a",
            "matchedRecommendations": 2,
            "sealedOrConfirmed": 0,
            "skippedInputContract": 2,
            "skippedForwardSeal": 0,
            "conflicts": 0,
        }],
    }

    warmup = shadow.candidate_recording_health(
        _candidate(), [registry], [], [], failed_run,
        now=shadow._parse_time("2026-01-03T00:00:00+00:00"),
    )
    stalled = shadow.candidate_recording_health(
        _candidate(), [registry], [], [], failed_run,
        now=shadow._parse_time("2026-01-07T00:00:00+00:00"),
    )

    assert warmup["status"] == "WARMUP"
    assert warmup["healthy"] is True
    assert warmup["lastAttemptReason"] == "INPUT_CONTRACT_REJECTED"
    assert stalled["status"] == "STALLED"
    assert stalled["requiresAttention"] is True
    assert stalled["blockingReason"] == "INPUT_CONTRACT_REJECTED_AFTER_GRACE"


def test_candidate_recording_health_detects_prediction_silence() -> None:
    registry = _registry_row()
    registry["registered_at"] = "2026-01-01T00:00:00+00:00"
    registry["record_hash"] = shadow._registry_hash(registry)
    prediction = {field: "" for field in shadow.PREDICTION_FIELDS}
    prediction.update({
        "prediction_id": "prediction-a",
        "candidate_fingerprint": "candidate-a",
        "recorded_at": "2026-01-02T00:00:00+00:00",
    })

    health = shadow.candidate_recording_health(
        _candidate(), [registry], [prediction], [], None,
        now=shadow._parse_time("2026-01-08T00:00:00+00:00"),
    )

    assert health["status"] == "STALLED"
    assert health["blockingReason"] == "PREDICTION_SILENCE_EXCEEDED"
    assert health["sealedPredictions"] == 1


def test_settlement_only_build_preserves_last_recording_diagnostics(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "shadow.json"
    promotion = tmp_path / "promotion.json"
    previous_run = {
        "runAt": "2026-01-02T00:00:00+00:00",
        "candidateDiagnostics": [{
            "candidateFingerprint": "candidate-a",
            "matchedRecommendations": 2,
            "skippedInputContract": 2,
        }],
    }
    output.write_text(json.dumps({"lastRecordingRun": previous_run}), encoding="utf-8")
    monkeypatch.setattr(shadow.vtj, "calibration_shadow_candidates", lambda: {
        "status": "SHADOW_ONLY",
        "policyVersion": shadow.vtj.AUTO_CALIBRATION_POLICY["version"],
        "policyFingerprint": shadow.vtj._calibration_policy_fingerprint(),
        "items": [],
        "blocked": [],
        "readiness": {"readyForReview": 0, "eligibleSuggestions": 0, "items": []},
    })

    payload = shadow.build(
        registry_path=tmp_path / "registry.csv",
        prediction_path=tmp_path / "predictions.csv",
        settlement_path=tmp_path / "settlements.csv",
        output_path=output,
        promotion_path=promotion,
        record=False,
        settle=False,
    )

    assert payload["lastRecordingRun"] == previous_run
    assert payload["predictionRun"]["appended"] == 0


def test_operational_exit_code_fails_integrity_and_registration_not_normal_warmup() -> None:
    healthy = {
        "integrity": {"predictionHashViolations": 0},
        "candidates": [{"recordingHealth": {"status": "WARMUP"}}],
    }
    stalled = {
        "integrity": {"predictionHashViolations": 0},
        "candidates": [{"recordingHealth": {"status": "STALLED"}}],
    }
    corrupt = {
        "integrity": {"predictionHashViolations": 1},
        "candidates": [{"recordingHealth": {"status": "COLLECTING"}}],
    }
    missing_registry = {
        "integrity": {"predictionHashViolations": 0},
        "candidates": [{"recordingHealth": {"status": "ERROR"}}],
    }

    assert shadow.operational_exit_code(healthy) == 0
    assert shadow.operational_exit_code(stalled) == 0
    assert shadow.operational_exit_code(corrupt) == 2
    assert shadow.operational_exit_code(missing_registry) == 2


def test_settlement_rejects_tampered_prediction(monkeypatch, tmp_path: Path) -> None:
    prediction_path = tmp_path / "predictions.csv"
    settlement_path = tmp_path / "settlements.csv"
    row = {
        field: "" for field in shadow.PREDICTION_FIELDS
    }
    row.update({
        "prediction_id": "prediction-a",
        "candidate_fingerprint": "candidate-a",
        "signal_date": "2026-01-02",
        "market": "us",
        "mode": "balanced",
        "horizon": "swing",
        "symbol": "TEST",
        "forward_seal_status": "SEALED_FORWARD",
        "input_contract_version": shadow.INPUT_CONTRACT_VERSION,
        "champion_entry": 100,
        "champion_stop": 90,
        "champion_target": 120,
        "challenger_entry": 100,
        "challenger_stop": 90,
        "challenger_target": 120,
    })
    row["record_hash"] = shadow._prediction_hash(row)
    row["champion_target"] = 999
    shadow._write_csv(prediction_path, [row], shadow.PREDICTION_FIELDS)
    monkeypatch.setattr(shadow, "_arm_evaluation", lambda *_args: {"status": "EVALUATED", "outcome": "TARGET_HIT", "net_pnl_pct": 1.0})

    result = shadow.settle_predictions(prediction_path, settlement_path)

    assert result["appended"] == 0
    assert result["invalidPredictions"] == 1
    assert not settlement_path.exists()


def test_rehashed_prediction_cannot_escape_cross_ledger_lineage_audit() -> None:
    prediction = {field: "" for field in shadow.PREDICTION_FIELDS}
    prediction.update({
        "prediction_id": "prediction-a",
        "candidate_fingerprint": "candidate-a",
        "approval_id": "different-approval",
        "approval_record_hash": "approval-hash-a",
        "calibration_policy_fingerprint": shadow.vtj._calibration_policy_fingerprint(),
        "shadow_policy_version": shadow.POLICY_VERSION,
        "shadow_policy_fingerprint": shadow._policy_fingerprint(),
        "recorded_at": "2026-01-02T22:00:00+00:00",
        "generated_at": "2026-01-02T21:00:00+00:00",
        "signal_date": "2026-01-02",
        "ohlcv_last_date": "2026-01-02",
        "market": "us",
        "forward_seal_status": "SEALED_FORWARD",
        "input_contract_version": shadow.INPUT_CONTRACT_VERSION,
    })
    prediction["record_hash"] = shadow._prediction_hash(prediction)

    integrity = shadow._integrity([_registry_row()], [prediction], [])

    assert integrity["predictionHashViolations"] == 0
    assert integrity["predictionLineageViolations"] == 1


def test_date_block_comparison_can_issue_exact_promotion_certificate() -> None:
    predictions = []
    settlements = []
    signal_days = []
    current_day = date(2026, 1, 1)
    while len(signal_days) < 60:
        if current_day.weekday() < 5:
            signal_days.append(current_day)
        current_day += timedelta(days=1)
    for day_index, signal_day in enumerate(signal_days):
        signal_date = signal_day.isoformat()
        for symbol_index in range(2):
            prediction_id = f"p-{day_index}-{symbol_index}"
            prediction = {
                field: "" for field in shadow.PREDICTION_FIELDS
            }
            prediction.update({
                "prediction_id": prediction_id,
                "candidate_fingerprint": "candidate-a",
                "approval_id": "approval-a",
                "approval_record_hash": "approval-hash-a",
                "calibration_policy_fingerprint": shadow.vtj._calibration_policy_fingerprint(),
                "shadow_policy_version": shadow.POLICY_VERSION,
                "shadow_policy_fingerprint": shadow._policy_fingerprint(),
                "recorded_at": f"{signal_date}T22:00:00+00:00",
                "generated_at": f"{signal_date}T21:00:00+00:00",
                "signal_date": signal_date,
                "ohlcv_last_date": signal_date,
                "market": "us",
                "symbol": f"S{symbol_index}",
                "champion_eligible": True,
                "challenger_eligible": True,
                "champion_score": 60 + symbol_index,
                "challenger_score": 61 + symbol_index,
                "forward_seal_status": "SEALED_FORWARD",
                "input_contract_version": shadow.INPUT_CONTRACT_VERSION,
            })
            prediction["record_hash"] = shadow._prediction_hash(prediction)
            predictions.append(prediction)
            settlement = {
                field: "" for field in shadow.SETTLEMENT_FIELDS
            }
            settlement.update({
                "settlement_id": f"s-{prediction_id}",
                "prediction_id": prediction_id,
                "candidate_fingerprint": "candidate-a",
                "signal_date": signal_date,
                "champion_net_pnl_pct": 1.0,
                "challenger_net_pnl_pct": 2.0,
            })
            settlement["record_hash"] = shadow._settlement_hash(settlement)
            settlements.append(settlement)

    comparison = shadow.compare_candidate("candidate-a", predictions, settlements)
    integrity = shadow._integrity([_registry_row()], predictions, settlements)
    decision, certificate = shadow._promotion(_candidate(), comparison, integrity)

    assert comparison["completedSignalDates"] == 60
    assert comparison["challenger"]["selectedEvaluatedTrades"] == 120
    assert comparison["pairedUplift"]["bootstrapCi95"][0] > 0
    assert decision["promotionEligible"] is True
    assert certificate is not None
    assert certificate["candidateFingerprint"] == "candidate-a"
    assert certificate["recordHash"] == shadow.vtj._promotion_certificate_hash(certificate)

    losing_settlements = []
    for row in settlements:
        losing = {**row, "challenger_net_pnl_pct": -1.0}
        losing["record_hash"] = shadow._settlement_hash(losing)
        losing_settlements.append(losing)
    losing_comparison = shadow.compare_candidate("candidate-a", predictions, losing_settlements)
    rejected, rejected_certificate = shadow._promotion(
        _candidate(), losing_comparison, shadow._integrity([_registry_row()], predictions, losing_settlements)
    )

    assert rejected["evidenceMature"] is True
    assert rejected["terminalFailure"] is True
    assert rejected["decision"] == "REJECT_CHALLENGER"
    assert rejected["suggestedAction"] == "REJECT_PRECOMMITTED_CANDIDATE"
    assert rejected_certificate is None


def test_clustered_single_date_never_qualifies_for_promotion() -> None:
    predictions = []
    settlements = []
    for index in range(120):
        prediction = {field: "" for field in shadow.PREDICTION_FIELDS}
        prediction.update({
            "prediction_id": f"p-{index}",
            "candidate_fingerprint": "candidate-a",
            "approval_id": "approval-a",
            "approval_record_hash": "approval-hash-a",
            "calibration_policy_fingerprint": shadow.vtj._calibration_policy_fingerprint(),
            "shadow_policy_version": shadow.POLICY_VERSION,
            "shadow_policy_fingerprint": shadow._policy_fingerprint(),
            "recorded_at": "2026-01-02T22:00:00+00:00",
            "generated_at": "2026-01-02T21:00:00+00:00",
            "signal_date": "2026-01-02",
            "ohlcv_last_date": "2026-01-02",
            "market": "us",
            "champion_eligible": True,
            "challenger_eligible": True,
            "champion_score": index,
            "challenger_score": index,
            "forward_seal_status": "SEALED_FORWARD",
            "input_contract_version": shadow.INPUT_CONTRACT_VERSION,
        })
        prediction["record_hash"] = shadow._prediction_hash(prediction)
        predictions.append(prediction)
        settlement = {field: "" for field in shadow.SETTLEMENT_FIELDS}
        settlement.update({
            "settlement_id": f"s-{index}",
            "prediction_id": f"p-{index}",
            "candidate_fingerprint": "candidate-a",
            "signal_date": "2026-01-02",
            "champion_net_pnl_pct": 1,
            "challenger_net_pnl_pct": 2,
        })
        settlement["record_hash"] = shadow._settlement_hash(settlement)
        settlements.append(settlement)

    comparison = shadow.compare_candidate("candidate-a", predictions, settlements)
    decision, certificate = shadow._promotion(
        _candidate(), comparison, shadow._integrity([_registry_row()], predictions, settlements)
    )

    assert comparison["completedSignalDates"] == 1
    assert decision["promotionEligible"] is False
    assert "LOW_PROMOTION_SIGNAL_DATES" in decision["blockingReasons"]
    assert certificate is None


def test_workflows_seal_before_settlement_and_commit_all_shadow_evidence() -> None:
    accumulator = (ROOT / ".github" / "workflows" / "mone-auto-accumulator.yml").read_text(encoding="utf-8")
    settlement = (ROOT / ".github" / "workflows" / "mone-settle-validations.yml").read_text(encoding="utf-8")
    commit_script = (ROOT / "scripts" / "ci_commit_app_data.sh").read_text(encoding="utf-8")

    assert accumulator.index("scripts/generate_us_recommendations.py") < accumulator.index(
        "scripts/update_self_correction_shadow.py --no-settle"
    )
    assert '--record-market "${RECORD_MARKET}"' in accumulator
    assert "scripts/update_self_correction_shadow.py --no-record" in settlement
    assert "data/self_correction_candidate_registry.csv" in commit_script
    assert "data/self_correction_shadow_predictions.csv" in commit_script
    assert "data/self_correction_shadow_settlements.csv" in commit_script
    assert "reports/self_correction_shadow.json" in commit_script
    assert "reports/self_correction_promotion.json" in commit_script


def test_recommendation_generators_emit_raw_shadow_input_contract() -> None:
    kr = (ROOT / "scripts" / "generate_kr_recommendations.py").read_text(encoding="utf-8")
    us = (ROOT / "scripts" / "generate_us_recommendations.py").read_text(encoding="utf-8")

    for source in (kr, us):
        assert '"rawEntry"' in source
        assert '"rawStop"' in source
        assert '"rawTarget"' in source
        assert '"rawModelScore"' in source
        assert '"scoreComponentsJson"' in source
        assert '"scoreWeightsJson"' in source
        assert '"asOfDate": c["as_of_date"]' in source
        assert '"as_of_date": max(' in source
        assert '"correctionInputContractVersion": "correction-shadow-input-v1"' in source
        assert "datetime.now(timezone.utc).isoformat()" in source

    assert shadow.vtj.AUTO_CALIBRATION_POLICY["maxActiveShadowCandidates"] == 1
    assert shadow.vtj.CALIBRATION_SHADOW_POLICY["maxActiveCandidates"] == 1
    assert shadow.vtj.CALIBRATION_SHADOW_POLICY["requiresSealAfterCanonicalClose"] is True
    assert shadow.vtj.CALIBRATION_SHADOW_POLICY["requiresSealBeforeNextSessionOpen"] is True
