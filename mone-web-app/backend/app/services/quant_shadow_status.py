from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services import data_loader as data


REPORTS_DIR = data.REPO_ROOT / "reports"
REPORT_FILES = {
    "cohort": "strategy_cohort_audit.json",
    "alpha": "recommendation_alpha.json",
    "residualAlpha": "shadow_residual_alpha.json",
    "sleeve": "strategy_sleeve_nav_v2.json",
    "metaGate": "shadow_meta_gate.json",
    "riskBudget": "shadow_risk_budget.json",
    "championChallenger": "champion_challenger.json",
    "selfCorrection": "self_correction_shadow.json",
    "walkForward": "walkforward_integrity.json",
}
DEFAULT_MAX_REPORT_AGE_HOURS = 72.0


def _read_report(name: str) -> dict[str, Any]:
    path = REPORTS_DIR / REPORT_FILES[name]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return {**payload, "_source": f"reports/{path.name}"}
    except Exception:
        pass
    return {"status": "MISSING", "_source": f"reports/{path.name}"}


def _report_freshness(report: dict[str, Any], now: datetime) -> dict[str, Any]:
    raw_timestamp = str(report.get("generatedAt") or report.get("updatedAt") or report.get("createdAt") or "").strip()
    try:
        max_age_hours = max(1.0, float(os.environ.get("MONE_QUANT_REPORT_MAX_AGE_HOURS", DEFAULT_MAX_REPORT_AGE_HOURS)))
    except (TypeError, ValueError):
        max_age_hours = DEFAULT_MAX_REPORT_AGE_HOURS
    if not raw_timestamp:
        return {
            "fresh": False,
            "reason": "MISSING_GENERATED_AT",
            "generatedAt": "",
            "ageHours": None,
            "maxAgeHours": max_age_hours,
        }
    try:
        parsed = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_hours = (now - parsed.astimezone(timezone.utc)).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return {
            "fresh": False,
            "reason": "INVALID_GENERATED_AT",
            "generatedAt": raw_timestamp,
            "ageHours": None,
            "maxAgeHours": max_age_hours,
        }
    if age_hours < -0.1:
        reason = "FUTURE_GENERATED_AT"
        fresh = False
    elif age_hours > max_age_hours:
        reason = "REPORT_TOO_OLD"
        fresh = False
    else:
        reason = ""
        fresh = True
    return {
        "fresh": fresh,
        "reason": reason,
        "generatedAt": raw_timestamp,
        "ageHours": round(max(age_hours, 0.0), 2),
        "maxAgeHours": max_age_hours,
    }


def shadow_status() -> dict[str, Any]:
    reports = {name: _read_report(name) for name in REPORT_FILES}
    now = datetime.now(timezone.utc)
    report_freshness = {name: _report_freshness(report, now) for name, report in reports.items()}
    stale_reports = [name for name, freshness in report_freshness.items() if not freshness["fresh"]]
    meta = reports["metaGate"]
    risk = reports["riskBudget"]
    alpha = reports["alpha"]
    residual_alpha = reports["residualAlpha"]
    sleeve = reports["sleeve"]
    cohort = reports["cohort"]
    champion_challenger = reports["championChallenger"]
    self_correction = reports["selfCorrection"]
    walk_forward = reports["walkForward"]

    missing = [name for name, report in reports.items() if report.get("status") == "MISSING"]
    summary = meta.get("summary") if isinstance(meta.get("summary"), dict) else {}
    windows = alpha.get("windows") if isinstance(alpha.get("windows"), dict) else {}
    d20 = windows.get("D+20") if isinstance(windows.get("D+20"), dict) else {}
    ranking = sleeve.get("ranking") if isinstance(sleeve.get("ranking"), list) else []
    sleeves = sleeve.get("sleeves") if isinstance(sleeve.get("sleeves"), dict) else {}
    top_name = ranking[0] if ranking else None
    top_sleeve = sleeves.get(top_name) if top_name and isinstance(sleeves.get(top_name), dict) else None

    take = int(summary.get("take") or 0)
    raw_decision = "ABSTAIN" if bool(summary.get("abstain", take == 0)) else "SHADOW_TAKE"
    decision = "ABSTAIN" if missing or stale_reports else raw_decision
    reasons: list[str] = []
    if missing:
        reasons.append("MISSING_REPORTS")
    if stale_reports:
        reasons.append("STALE_EVIDENCE_REPORTS")
    if not bool(d20.get("significanceUsable")):
        reasons.append("ALPHA_NOT_PROVEN")
    residual_validation = residual_alpha.get("validation") if isinstance(residual_alpha.get("validation"), dict) else {}
    residual_research_validation = residual_alpha.get("researchValidation") if isinstance(residual_alpha.get("researchValidation"), dict) else {}
    forward_evidence = residual_alpha.get("forwardEvidence") if isinstance(residual_alpha.get("forwardEvidence"), dict) else {}
    model_registry = forward_evidence.get("modelRegistry") if isinstance(forward_evidence.get("modelRegistry"), dict) else {}
    residual_policy = residual_alpha.get("policy") if isinstance(residual_alpha.get("policy"), dict) else {}
    residual_predictions = residual_alpha.get("predictions") if isinstance(residual_alpha.get("predictions"), list) else []
    current_residual_prediction = next((row for row in residual_predictions if isinstance(row, dict)), {})
    if residual_validation.get("evidenceStatus") != "PASS":
        reasons.append("RESIDUAL_ALPHA_MODEL_NOT_PROVEN")
    if not top_sleeve or float(top_sleeve.get("totalReturnPct") or 0.0) <= 0:
        reasons.append("NO_POSITIVE_SLEEVE")
    if float(risk.get("grossExposurePct") or 0.0) <= 0:
        reasons.append("NO_APPROVED_RISK_EXPOSURE")
    risk_lineage = risk.get("lineage") if isinstance(risk.get("lineage"), dict) else {}
    risk_policy = risk.get("policy") if isinstance(risk.get("policy"), dict) else {}
    if risk_lineage.get("valid") is not True:
        reasons.append("RISK_ALLOCATION_INTEGRITY_NOT_PROVEN")
    promotion = champion_challenger.get("promotion") if isinstance(champion_challenger.get("promotion"), dict) else {}
    comparison = champion_challenger.get("comparison") if isinstance(champion_challenger.get("comparison"), dict) else {}
    risk_gate = champion_challenger.get("riskAllocationGate") if isinstance(champion_challenger.get("riskAllocationGate"), dict) else {}
    if risk_gate.get("passed") is not True:
        reasons.append("CHAMPION_RISK_ALLOCATION_NOT_PROVEN")
    if not bool(promotion.get("promotionEligible")):
        reasons.append("CHALLENGER_NOT_PROMOTABLE")
    self_correction_summary = self_correction.get("summary") if isinstance(self_correction.get("summary"), dict) else {}
    self_correction_candidates = self_correction.get("candidates") if isinstance(self_correction.get("candidates"), list) else []
    self_correction_promotions = [
        row.get("promotion") for row in self_correction_candidates
        if isinstance(row, dict) and isinstance(row.get("promotion"), dict)
    ]
    self_correction_recording_health = [
        row.get("recordingHealth") for row in self_correction_candidates
        if isinstance(row, dict) and isinstance(row.get("recordingHealth"), dict)
    ]
    self_correction_blockers = list(dict.fromkeys(
        reason
        for promotion_row in self_correction_promotions
        for reason in (promotion_row.get("blockingReasons") or [])
    ))
    if int(self_correction_summary.get("activeCandidates") or 0) <= 0:
        self_correction_blockers.append("NO_ACTIVE_CANDIDATE")
    recording_blockers = [
        str(row.get("blockingReason"))
        for row in self_correction_recording_health
        if row.get("requiresAttention") and row.get("blockingReason")
    ]
    self_correction_blockers.extend(recording_blockers)
    self_correction_blockers = list(dict.fromkeys(self_correction_blockers))
    if recording_blockers:
        reasons.append("SELF_CORRECTION_EVIDENCE_STALLED")
    if int(self_correction_summary.get("terminalFailureCandidates") or 0) > 0:
        reasons.append("SELF_CORRECTION_CANDIDATE_FAILED")
    if int(self_correction_summary.get("promotionEligible") or 0) <= 0:
        reasons.append("SELF_CORRECTION_NOT_PROMOTABLE")
    if not bool(walk_forward.get("promotionGrade")):
        reasons.append("WALKFORWARD_NOT_PROMOTION_GRADE")

    return {
        "status": "WARN" if reasons else "OK",
        "mode": "SHADOW_ONLY",
        "liveTradingAllowed": False,
        "decision": decision,
        "rawDecision": raw_decision,
        "decisionReasons": reasons,
        "summary": {
            "candidates": int(summary.get("candidates") or 0),
            "take": take,
            "wait": int(summary.get("wait") or 0),
            "reject": int(summary.get("reject") or 0),
            "grossExposurePct": float(risk.get("grossExposurePct") or 0.0),
            "cashWeightPct": float(risk.get("cashWeightPct") or 100.0),
            "portfolioBeta": float(risk.get("portfolioBeta") or 0.0),
            "riskAllocationLineageValid": risk_lineage.get("valid") is True,
            "riskAllocationIntegrityBlockers": risk_lineage.get("blockingReasons") or [],
            "riskPolicyFingerprint": risk_policy.get("fingerprint"),
            "riskAllocationFingerprint": risk_lineage.get("allocationFingerprint"),
            "championRiskAllocationGatePassed": risk_gate.get("passed") is True,
            "d20BlockMeanCarPct": d20.get("blockMeanCarPct"),
            "d20AlphaCi95": d20.get("bootstrapCi95"),
            "independentAlphaBlocks": d20.get("independentMarketDateBlocks"),
            "residualAlphaModelEvidence": residual_validation.get("evidenceStatus"),
            "residualAlphaOosPredictions": residual_validation.get("oosPredictions"),
            "residualAlphaOosSignalDates": residual_validation.get("oosSignalDates"),
            "residualAlphaForwardSettledPredictions": residual_validation.get("oosPredictions"),
            "residualAlphaForwardSettledSignalDates": residual_validation.get("oosSignalDates"),
            "residualAlphaResearchOosPredictions": residual_research_validation.get("oosPredictions"),
            "residualAlphaResearchOosSignalDates": residual_research_validation.get("oosSignalDates"),
            "residualAlphaForwardModelFingerprint": forward_evidence.get("modelFingerprint"),
            "residualAlphaImplementationFingerprint": residual_policy.get("implementationFingerprint"),
            "residualAlphaCurrentModelInstanceFingerprint": current_residual_prediction.get("modelInstanceFingerprint"),
            "residualAlphaCurrentTrainingDataFingerprint": current_residual_prediction.get("trainingDataFingerprint"),
            "residualAlphaRegisteredModels": int(model_registry.get("existingRows") or 0) + int(model_registry.get("appendedRows") or 0),
            "residualAlphaModelVersionReuseConflicts": int(model_registry.get("versionReuseConflicts") or 0),
            "residualAlphaForwardIntegrityBlockers": forward_evidence.get("integrityBlockingReasons") or [],
            "residualAlphaSelectedCi95": residual_validation.get("selectedBlockBootstrapCi95"),
            "topSleeve": top_name,
            "topSleeveReturnPct": top_sleeve.get("totalReturnPct") if top_sleeve else None,
            "topSleeveProfitFactor": top_sleeve.get("profitFactor") if top_sleeve else None,
            "independentDecisions": (cohort.get("summary") or {}).get("independentDecisions"),
            "challengerPromotionDecision": promotion.get("decision"),
            "challengerBlockingReasons": promotion.get("blockingReasons") or [],
            "completedComparisonDates": comparison.get("completedSignalDates"),
            "selfCorrectionActiveCandidates": int(self_correction_summary.get("activeCandidates") or 0),
            "selfCorrectionSealedPredictions": int(self_correction_summary.get("sealedPredictions") or 0),
            "selfCorrectionSettledPredictions": int(self_correction_summary.get("settledPredictions") or 0),
            "selfCorrectionPromotionEligible": int(self_correction_summary.get("promotionEligible") or 0),
            "selfCorrectionReadyForReview": int(self_correction_summary.get("readyForReview") or 0),
            "selfCorrectionEligibleSuggestions": int(self_correction_summary.get("eligibleSuggestions") or 0),
            "selfCorrectionRecordingHealthy": bool(self_correction_summary.get("recordingHealthy", True)),
            "selfCorrectionStalledCandidates": int(self_correction_summary.get("stalledCandidates") or 0),
            "selfCorrectionTerminalFailureCandidates": int(self_correction_summary.get("terminalFailureCandidates") or 0),
            "selfCorrectionRecordingHealth": self_correction_recording_health,
            "selfCorrectionBlockingReasons": self_correction_blockers,
            "walkForwardPromotionGrade": bool(walk_forward.get("promotionGrade")),
        },
        "sources": {name: report.get("_source") for name, report in reports.items()},
        "missingReports": missing,
        "staleReports": stale_reports,
        "reportFreshness": report_freshness,
        "reports": reports,
    }
