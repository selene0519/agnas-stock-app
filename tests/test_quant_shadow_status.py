from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import quant_shadow_status as status


def _write(root: Path, name: str, payload: dict) -> None:
    (root / status.REPORT_FILES[name]).write_text(json.dumps(payload), encoding="utf-8")


def test_shadow_status_fails_closed_when_evidence_is_not_positive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(status, "REPORTS_DIR", tmp_path)
    _write(tmp_path, "cohort", {"status": "OK", "summary": {"independentDecisions": 306}})
    _write(tmp_path, "alpha", {
        "status": "OK",
        "windows": {"D+20": {"blockMeanCarPct": -3.4, "bootstrapCi95": [-7.7, 0.6], "independentMarketDateBlocks": 13, "significanceUsable": False}},
    })
    _write(tmp_path, "residualAlpha", {
        "status": "SHADOW_ONLY",
        "policy": {"implementationFingerprint": "implementation-a"},
        "validation": {
            "evidenceStatus": "WAIT",
            "oosPredictions": 0,
            "oosSignalDates": 0,
            "selectedBlockBootstrapCi95": None,
        },
        "forwardEvidence": {
            "modelFingerprint": "model-a",
            "modelRegistry": {"existingRows": 1, "appendedRows": 0, "versionReuseConflicts": 0},
            "integrityBlockingReasons": [],
        },
        "predictions": [{"modelInstanceFingerprint": "instance-a", "trainingDataFingerprint": "training-a"}],
    })
    _write(tmp_path, "sleeve", {
        "status": "OK",
        "ranking": ["balanced_short"],
        "sleeves": {"balanced_short": {"totalReturnPct": -3.8, "profitFactor": 0.6}},
    })
    _write(tmp_path, "metaGate", {"status": "SHADOW_ONLY", "summary": {"candidates": 20, "take": 0, "wait": 0, "reject": 20, "abstain": True}})
    _write(tmp_path, "riskBudget", {
        "status": "SHADOW_ONLY",
        "policy": {"fingerprint": "risk-a"},
        "lineage": {"valid": True, "blockingReasons": [], "allocationFingerprint": "allocation-a"},
        "grossExposurePct": 0,
        "cashWeightPct": 100,
        "portfolioBeta": 0,
    })
    _write(tmp_path, "championChallenger", {
        "status": "SHADOW_ONLY",
        "comparison": {"completedSignalDates": 0},
        "riskAllocationGate": {"passed": True},
        "promotion": {"promotionEligible": False, "decision": "KEEP_CHALLENGER_SHADOW", "blockingReasons": ["LOW_COMPLETE_SIGNAL_DATES"]},
    })
    _write(tmp_path, "selfCorrection", {
        "status": "SHADOW_ONLY",
        "summary": {
            "activeCandidates": 1,
            "sealedPredictions": 10,
            "settledPredictions": 4,
            "promotionEligible": 0,
            "recordingHealthy": False,
            "stalledCandidates": 1,
        },
        "candidates": [{
            "recordingHealth": {
                "status": "STALLED",
                "requiresAttention": True,
                "blockingReason": "PREDICTION_SILENCE_EXCEEDED",
            },
            "promotion": {
                "promotionEligible": False,
                "blockingReasons": ["LOW_PROMOTION_SIGNAL_DATES"],
            },
        }],
    })
    _write(tmp_path, "walkForward", {"status": "WARN", "promotionGrade": False})

    result = status.shadow_status()

    assert result["status"] == "WARN"
    assert result["decision"] == "ABSTAIN"
    assert result["liveTradingAllowed"] is False
    assert result["summary"]["cashWeightPct"] == 100.0
    assert result["summary"]["residualAlphaForwardModelFingerprint"] == "model-a"
    assert result["summary"]["residualAlphaImplementationFingerprint"] == "implementation-a"
    assert result["summary"]["residualAlphaCurrentModelInstanceFingerprint"] == "instance-a"
    assert result["summary"]["residualAlphaCurrentTrainingDataFingerprint"] == "training-a"
    assert result["summary"]["residualAlphaRegisteredModels"] == 1
    assert result["summary"]["residualAlphaModelVersionReuseConflicts"] == 0
    assert result["summary"]["riskAllocationLineageValid"] is True
    assert result["summary"]["riskPolicyFingerprint"] == "risk-a"
    assert result["summary"]["riskAllocationFingerprint"] == "allocation-a"
    assert result["summary"]["championRiskAllocationGatePassed"] is True
    assert result["summary"]["selfCorrectionActiveCandidates"] == 1
    assert result["summary"]["selfCorrectionSealedPredictions"] == 10
    assert result["summary"]["selfCorrectionBlockingReasons"] == [
        "LOW_PROMOTION_SIGNAL_DATES",
        "PREDICTION_SILENCE_EXCEEDED",
    ]
    assert result["summary"]["selfCorrectionRecordingHealthy"] is False
    assert result["summary"]["selfCorrectionStalledCandidates"] == 1
    assert "ALPHA_NOT_PROVEN" in result["decisionReasons"]
    assert "RESIDUAL_ALPHA_MODEL_NOT_PROVEN" in result["decisionReasons"]
    assert "NO_POSITIVE_SLEEVE" in result["decisionReasons"]
    assert "SELF_CORRECTION_NOT_PROMOTABLE" in result["decisionReasons"]
    assert "SELF_CORRECTION_EVIDENCE_STALLED" in result["decisionReasons"]


def test_missing_reports_never_look_healthy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(status, "REPORTS_DIR", tmp_path)

    result = status.shadow_status()

    assert result["status"] == "WARN"
    assert result["decision"] == "ABSTAIN"
    assert len(result["missingReports"]) == len(status.REPORT_FILES)
    assert "RISK_ALLOCATION_INTEGRITY_NOT_PROVEN" in result["decisionReasons"]
    assert "CHAMPION_RISK_ALLOCATION_NOT_PROVEN" in result["decisionReasons"]


def test_report_freshness_rejects_old_or_undated_evidence(monkeypatch) -> None:
    monkeypatch.setenv("MONE_QUANT_REPORT_MAX_AGE_HOURS", "48")
    now = datetime(2026, 7, 31, 0, 0, tzinfo=timezone.utc)

    old = status._report_freshness({"generatedAt": "2026-07-28T23:59:00+00:00"}, now)
    undated = status._report_freshness({"status": "OK"}, now)

    assert old["fresh"] is False
    assert old["reason"] == "REPORT_TOO_OLD"
    assert undated["fresh"] is False
    assert undated["reason"] == "MISSING_GENERATED_AT"
