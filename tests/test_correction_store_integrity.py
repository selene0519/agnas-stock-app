from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.engine import correction_store  # noqa: E402


def _certificate() -> dict:
    certificate = {
        "version": correction_store.REQUIRED_PROMOTION_CERTIFICATE_VERSION,
        "approvalId": "approval-a",
        "approvalRecordHash": "approval-hash-a",
        "evidenceFingerprint": "evidence-a",
        "candidateFingerprint": "candidate-a",
        "calibrationPolicyFingerprint": "calibration-a",
        "shadowPolicyFingerprint": "shadow-a",
        "shadowPolicyVersion": correction_store.REQUIRED_SHADOW_POLICY_VERSION,
        "evaluationPolicyFingerprint": "evaluation-a",
        "residualAlphaModelFingerprint": "residual-a",
        "residualAlphaPolicyVersion": correction_store.REQUIRED_RESIDUAL_ALPHA_POLICY_VERSION,
        "afterCostExpectancyBootstrapCi95": [0.01, 0.2],
        "pairedUpliftCi95": [0.01, 0.2],
        "residualAlphaSelectedCi95": [0.01, 0.2],
        "profitFactor": 1.3,
        "payoffRatio": 1.2,
        "championMaxDrawdownPct": 8.0,
        "challengerMaxDrawdownPct": 6.0,
        "promotionEligible": True,
        "decision": "READY_FOR_HUMAN_REVIEW",
    }
    certificate["recordHash"] = correction_store.promotion_certificate_hash(certificate)
    return certificate


def _promoted_correction() -> dict:
    certificate = _certificate()
    return {
        "journalCalibrationPromoted": True,
        "promotionCertificateHash": certificate["recordHash"],
        "promotionCertificate": certificate,
        "candidateFingerprint": certificate["candidateFingerprint"],
        "calibrationPolicyFingerprint": certificate["calibrationPolicyFingerprint"],
    }


def test_sealed_params_detect_payload_and_certificate_tampering() -> None:
    params = correction_store.seal_params({
        "version": 1,
        "markets": {"kr_balanced_swing": _promoted_correction()},
    })
    assert correction_store.validate_params_integrity(params) is True
    assert correction_store.params_lineage_verdict(params)["valid"] is True

    payload_tampered = json.loads(json.dumps(params))
    payload_tampered["version"] = 2
    assert correction_store.validate_params_integrity(payload_tampered) is False

    obsolete = _promoted_correction()
    obsolete["promotionCertificate"]["version"] = "vtj-calibration-promotion-v1"
    obsolete["promotionCertificate"]["recordHash"] = correction_store.promotion_certificate_hash(
        obsolete["promotionCertificate"]
    )
    obsolete["promotionCertificateHash"] = obsolete["promotionCertificate"]["recordHash"]
    verdict = correction_store.promoted_correction_lineage_verdict(obsolete)
    assert verdict["valid"] is False
    assert "PROMOTION_CERTIFICATE_VERSION_MISMATCH" in verdict["blockingReasons"]

    certificate_tampered = json.loads(json.dumps(params))
    certificate_tampered["markets"]["kr_balanced_swing"]["promotionCertificate"]["promotionEligible"] = False
    certificate_tampered = correction_store.seal_params(certificate_tampered)
    verdict = correction_store.params_lineage_verdict(certificate_tampered)
    assert verdict["valid"] is False
    assert any("PROMOTION_CERTIFICATE_HASH_MISMATCH" in reason for reason in verdict["blockingReasons"])


def test_hash_only_promotion_cannot_be_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(correction_store, "_reports_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="INVALID_SELF_CORRECTION_LINEAGE"):
        correction_store.save_params({
            "version": 1,
            "markets": {
                "kr_balanced_swing": {
                    "journalCalibrationPromoted": True,
                    "promotionCertificateHash": "fake",
                    "candidateFingerprint": "fake",
                    "calibrationPolicyFingerprint": "fake",
                }
            },
        })
    assert not correction_store._params_path().exists()


def test_save_seals_current_and_prior_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(correction_store, "_reports_dir", lambda: tmp_path)
    correction_store.save_params({"version": 0, "markets": {}})
    correction_store.save_params({
        "version": 1,
        "markets": {"kr_balanced_swing": _promoted_correction()},
    })
    current = correction_store.load_params()
    backup = json.loads((tmp_path / "self_correction_params_v0.json").read_text(encoding="utf-8"))
    assert correction_store.params_lineage_verdict(current)["valid"] is True
    assert correction_store.params_lineage_verdict(backup)["valid"] is True
    assert current["paramsIntegrity"]["version"] == correction_store.PARAMS_INTEGRITY_VERSION
