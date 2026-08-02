"""
correction_store.py — self_correction_params JSON 저장/로드/버전 관리 (7-D 지원)

저장 경로: reports/self_correction_params.json
백업 경로: reports/self_correction_params_v{N}.json
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PARAMS_INTEGRITY_VERSION = "self-correction-params-integrity-v1"
PARAMS_INTEGRITY_FIELD = "paramsIntegrity"


def _reports_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "reports"


def _params_path() -> Path:
    return _reports_dir() / "self_correction_params.json"


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _payload_without_integrity(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key != PARAMS_INTEGRITY_FIELD}


def seal_params(params: dict[str, Any]) -> dict[str, Any]:
    """Return an independent copy carrying a hash of the complete parameter payload."""
    sealed = copy.deepcopy(_payload_without_integrity(params))
    sealed[PARAMS_INTEGRITY_FIELD] = {
        "version": PARAMS_INTEGRITY_VERSION,
        "payloadHash": _canonical_hash(sealed),
    }
    return sealed


def validate_params_integrity(params: dict[str, Any]) -> bool:
    integrity = params.get(PARAMS_INTEGRITY_FIELD)
    if not isinstance(integrity, dict) or integrity.get("version") != PARAMS_INTEGRITY_VERSION:
        return False
    expected = str(integrity.get("payloadHash") or "").strip()
    return bool(expected) and expected == _canonical_hash(_payload_without_integrity(params))


def promotion_certificate_hash(certificate: dict[str, Any]) -> str:
    """Use the same canonical contract as the promotion-certificate producer."""
    return _canonical_hash({key: value for key, value in certificate.items() if key != "recordHash"})


def promoted_correction_lineage_verdict(correction: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    if correction.get("journalCalibrationPromoted") is not True:
        blockers.append("NOT_PROMOTED")
    certificate = correction.get("promotionCertificate")
    if not isinstance(certificate, dict):
        blockers.append("MISSING_EMBEDDED_PROMOTION_CERTIFICATE")
        certificate = {}
    record_hash = str(certificate.get("recordHash") or "").strip()
    if not record_hash:
        blockers.append("MISSING_PROMOTION_CERTIFICATE_HASH")
    elif record_hash != promotion_certificate_hash(certificate):
        blockers.append("PROMOTION_CERTIFICATE_HASH_MISMATCH")
    if str(correction.get("promotionCertificateHash") or "").strip() != record_hash:
        blockers.append("CORRECTION_CERTIFICATE_HASH_MISMATCH")
    if str(correction.get("candidateFingerprint") or "").strip() != str(certificate.get("candidateFingerprint") or "").strip():
        blockers.append("PROMOTION_CANDIDATE_FINGERPRINT_MISMATCH")
    if str(correction.get("calibrationPolicyFingerprint") or "").strip() != str(certificate.get("calibrationPolicyFingerprint") or "").strip():
        blockers.append("PROMOTION_POLICY_FINGERPRINT_MISMATCH")
    for field in (
        "approvalId", "approvalRecordHash", "evidenceFingerprint", "candidateFingerprint",
        "calibrationPolicyFingerprint", "shadowPolicyFingerprint", "evaluationPolicyFingerprint",
    ):
        if not str(certificate.get(field) or "").strip():
            blockers.append(f"PROMOTION_CERTIFICATE_MISSING_{field.upper()}")
    if certificate.get("promotionEligible") is not True:
        blockers.append("PROMOTION_NOT_ELIGIBLE")
    if certificate.get("decision") != "READY_FOR_HUMAN_REVIEW":
        blockers.append("PROMOTION_DECISION_NOT_READY")
    return {"valid": not blockers, "blockingReasons": blockers, "certificateHash": record_hash or None}


def promoted_correction_lineage_valid(correction: dict[str, Any]) -> bool:
    return bool(promoted_correction_lineage_verdict(correction).get("valid"))


def params_lineage_verdict(params: dict[str, Any], *, require_integrity: bool = True) -> dict[str, Any]:
    blockers: list[str] = []
    integrity_valid = validate_params_integrity(params)
    if require_integrity and not integrity_valid:
        blockers.append("PARAMS_INTEGRITY_INVALID")
    markets = params.get("markets")
    if not isinstance(markets, dict):
        blockers.append("MARKETS_NOT_OBJECT")
        markets = {}
    promoted_cells: list[str] = []
    for key, correction in markets.items():
        if not isinstance(correction, dict):
            blockers.append(f"INVALID_CORRECTION_CELL:{key}")
            continue
        if correction.get("journalCalibrationPromoted") is True:
            promoted_cells.append(str(key))
            verdict = promoted_correction_lineage_verdict(correction)
            blockers.extend(f"{reason}:{key}" for reason in verdict.get("blockingReasons") or [])
    return {
        "valid": not blockers,
        "integrityValid": integrity_valid,
        "promotedCells": promoted_cells,
        "blockingReasons": blockers,
    }


def load_params() -> dict[str, Any]:
    """현재 보정 파라미터 로드. 없으면 빈 구조 반환."""
    path = _params_path()
    if not path.exists():
        return {"version": 0, "generatedAt": None, "markets": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 0, "generatedAt": None, "markets": {}}


def load_correction(market: str, mode: str, horizon: str) -> dict[str, Any]:
    """market/mode/horizon 조합에 해당하는 보정값 반환. 없으면 기본값."""
    params = load_params()
    key = f"{market}_{mode}_{horizon}"
    return params.get("markets", {}).get(key, _default_correction(market, mode, horizon))


def neutral_correction(market: str, mode: str, horizon: str) -> dict[str, Any]:
    """Return a fresh no-correction baseline for Shadow and quarantine paths."""
    return _default_correction(market, mode, horizon)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def save_params(new_params: dict[str, Any], *, backup_current: bool = True) -> Path:
    """Validate promotion lineage, seal the payload, and preserve a sealed prior version."""
    reports = _reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    path = _params_path()

    candidate = copy.deepcopy(new_params)
    candidate.pop(PARAMS_INTEGRITY_FIELD, None)
    candidate_verdict = params_lineage_verdict(candidate, require_integrity=False)
    if not candidate_verdict["valid"]:
        raise ValueError(
            "INVALID_SELF_CORRECTION_LINEAGE: " + ",".join(candidate_verdict["blockingReasons"])
        )

    if path.exists() and backup_current:
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"INVALID_EXISTING_SELF_CORRECTION_PARAMS: {exc}") from exc
        if not isinstance(old, dict):
            raise ValueError("INVALID_EXISTING_SELF_CORRECTION_PARAMS: root is not an object")
        if PARAMS_INTEGRITY_FIELD in old and not validate_params_integrity(old):
            raise ValueError("INVALID_EXISTING_SELF_CORRECTION_PARAMS: PARAMS_INTEGRITY_INVALID")
        old_verdict = params_lineage_verdict(old, require_integrity=False)
        if not old_verdict["valid"]:
            raise ValueError(
                "INVALID_EXISTING_SELF_CORRECTION_LINEAGE: " + ",".join(old_verdict["blockingReasons"])
            )
        old_ver = int(old.get("version", 0))
        backup = reports / f"self_correction_params_v{old_ver}.json"
        _write_json_atomic(backup, seal_params(old))

    candidate["savedAt"] = datetime.now(timezone.utc).isoformat()
    sealed = seal_params(candidate)
    _write_json_atomic(path, sealed)
    new_params.clear()
    new_params.update(copy.deepcopy(sealed))
    return path


def _default_correction(market: str, mode: str, horizon: str) -> dict[str, Any]:
    """보정값이 없을 때 사용하는 안전한 기본값 (보정 없음)."""
    return {
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "sampleCount": 0,
        "confidence": 0.0,
        "weightAdjustments": {},
        "priceAdjustments": {
            "entryAggressiveness": 0.0,
            "targetMultiplier": 0.0,
            "stopAtrMultiplier": 0.0,
        },
        "filterAdjustments": {
            "maxDistanceToEntryPct": 0.0,
            "minRiskRewardRatio": 0.0,
        },
        "topFailureReasons": [],
        "appliedAt": None,
    }


def list_versions() -> list[dict[str, Any]]:
    """저장된 모든 버전 목록 반환."""
    reports = _reports_dir()
    versions: list[dict[str, Any]] = []
    paths = list(sorted(reports.glob("self_correction_params_v*.json")))
    current_path = _params_path()
    if current_path.exists():
        paths.append(current_path)
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            verdict = params_lineage_verdict(data, require_integrity=True)
            versions.append({
                "version": data.get("version"),
                "generatedAt": data.get("generatedAt"),
                "savedAt": data.get("savedAt"),
                "file": p.name,
                "current": p == current_path,
                "integrityValid": verdict["integrityValid"],
                "lineageValid": verdict["valid"],
                "blockingReasons": verdict["blockingReasons"],
            })
        except Exception:
            pass
    return sorted(versions, key=lambda x: x.get("version") or 0)
