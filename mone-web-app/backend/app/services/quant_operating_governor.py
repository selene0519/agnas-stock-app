"""Fail-closed operating decision for MONE's research and paper-trading stack.

This module deliberately does not place orders. It turns evidence already
collected by the application into one auditable state so the UI never presents
a weak or unverified signal as a ready-to-trade recommendation.
"""

from __future__ import annotations

from typing import Any

from app.engine import data_quality, session
from app.services import (
    ai_paper_trader,
    portfolio_risk_budget,
    quant_execution_plan,
    quant_shadow_status,
    product_scope,
    virtual_trade_journal,
)


_MARKETS = ("kr", "us")


def _market_list(market: str) -> list[str]:
    normalized = str(market or "all").lower()
    return list(_MARKETS if normalized == "all" else (normalized if normalized in _MARKETS else "kr",))


def _decision_reason(code: str) -> str:
    english_labels = {
        "QUANT_SHADOW_NOT_APPROVED": "Quant V2 evidence has not approved a new entry.",
        "QUANT_EVIDENCE_INTEGRITY_NOT_READY": "Quant V2 evidence reports are missing, stale, or invalid.",
        "OPERATING_AUTHORITY_UNAVAILABLE": "Operating authority unavailable; new entries fail closed.",
        "QUANT_EXECUTION_PLAN_INVALID": "Candidate-level execution lineage or risk allocation is not valid.",
    }
    if code in english_labels:
        return english_labels[code]
    labels = {
        "INSUFFICIENT_REALIZED_SAMPLES": "실현 평가 표본이 최소 기준에 도달하지 않았습니다.",
        "REALIZED_WIN_RATE_BELOW_GATE": "실현 승률이 운용 기준보다 낮습니다.",
        "NEGATIVE_REALIZED_EXPECTANCY": "실현 평균 수익률이 양수로 확인되지 않았습니다.",
        "WALK_FORWARD_DATA_NOT_READY": "독립 워크포워드 검증 데이터가 준비되지 않았습니다.",
        "WALK_FORWARD_NOT_PROVEN": "독립 워크포워드에서 우위가 아직 증명되지 않았습니다.",
        "JOURNAL_INTEGRITY_NOT_READY": "AI 추천일지 기록 또는 평가 무결성을 먼저 복구해야 합니다.",
        "PORTFOLIO_RISK_BUDGET_EXCEEDED": "보유 포트폴리오의 손실 예산 또는 집중도가 한도를 넘었습니다.",
        "DATA_QUALITY_KILL_SWITCH": "데이터 품질 안전장치가 켜져 있어 신규 진입을 멈췄습니다.",
        "NO_ELIGIBLE_CANDIDATE": "현재 기준을 모두 통과한 후보가 없습니다.",
        "MARKET_CLOSED_REVIEW": "장 마감 상태입니다. 다음 개장 전까지는 관찰과 검증만 합니다.",
    }
    return labels.get(code, "운용 안전장치가 추가 검증을 요구합니다.")


def _govern_market(market: str, user_id: str = "", shadow: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build one conservative decision. Dependency failures fail closed."""
    reasons: list[str] = []
    try:
        paper_status = ai_paper_trader.status(market).get("markets", {}).get(market, {})
        performance_gate = dict(paper_status.get("entryPerformanceGate") or {})
    except Exception:
        paper_status, performance_gate = {}, {"allowed": False, "reason": "WALK_FORWARD_DATA_NOT_READY"}

    try:
        quality = data_quality.data_quality(market, mode="quick")
    except Exception:
        quality = {"status": "ERROR", "killSwitch": True}
    price_session = session.get_price_session(market)

    if shadow is None:
        try:
            shadow = quant_shadow_status.shadow_status()
        except Exception:
            shadow = {
                "status": "ERROR",
                "decision": "ABSTAIN",
                "liveTradingAllowed": False,
                "missingReports": list(quant_shadow_status.REPORT_FILES),
                "staleReports": list(quant_shadow_status.REPORT_FILES),
                "decisionReasons": ["SHADOW_STATUS_UNAVAILABLE"],
            }
    shadow_missing = list(shadow.get("missingReports") or [])
    shadow_stale = list(shadow.get("staleReports") or [])
    shadow_integrity_ready = (
        not shadow_missing
        and not shadow_stale
        and str(shadow.get("status") or "").upper() != "ERROR"
    )
    shadow_signal_ready = (
        shadow_integrity_ready
        and str(shadow.get("status") or "").upper() == "OK"
        and str(shadow.get("decision") or "").upper() == "SHADOW_TAKE"
    )

    if proof_ready := bool(performance_gate.get("allowed")):
        try:
            execution_plan = quant_execution_plan.execution_plan(market)
        except Exception as exc:
            execution_plan = {
                "status": "BLOCKED",
                "positions": [],
                "blockingReasons": ["EXECUTION_PLAN_UNAVAILABLE"],
                "error": repr(exc),
            }
        active_agent = paper_status.get("activeAgent") if isinstance(paper_status.get("activeAgent"), dict) else {}
        active_mode = str(active_agent.get("mode") or "").lower()
        active_horizon = str(active_agent.get("horizon") or "").lower()
        if active_mode and active_horizon and execution_plan.get("positions"):
            execution_plan = {
                **execution_plan,
                "positions": [
                    row for row in execution_plan.get("positions", [])
                    if str(row.get("mode") or "").lower() == active_mode
                    and str(row.get("horizon") or "").lower() == active_horizon
                ],
            }
            if not execution_plan["positions"]:
                execution_plan["status"] = "BLOCKED"
                execution_plan["blockingReasons"] = ["NO_EXECUTABLE_POSITION_FOR_ACTIVE_AGENT"]
        execution_ready = execution_plan.get("status") == "AUTHORIZED" and bool(execution_plan.get("positions"))
    else:
        execution_plan = {
            "status": "DEFERRED",
            "positions": [],
            "blockingReasons": ["Execution plan is evaluated after independent performance evidence passes."],
        }
        execution_ready = True

    data_ready = not bool(quality.get("killSwitch"))
    is_review_session = bool(price_session.get("isReviewMode"))

    # The full journal operations board includes calibration analytics over a
    # large ledger. When independent evidence already prohibits entry, defer
    # it; this keeps market switching responsive without weakening the gate.
    if proof_ready:
        try:
            journal = virtual_trade_journal.ops_dashboard(market=market)
        except Exception:
            journal = {"status": "ERROR", "recordingStatus": "CHECK", "evaluationStatus": "CHECK"}
        operational_journal = journal.get("operational") or journal
        journal_ready = (
            str(operational_journal.get("status") or "").upper() not in {"ERROR", "ATTENTION"}
            and str(operational_journal.get("recordingStatus") or "").upper() == "OK"
            and str(operational_journal.get("evaluationStatus") or "").upper() == "OK"
        )
    else:
        journal = {"journal": {}}
        operational_journal = {"status": "DEFERRED", "recordingStatus": "DEFERRED", "evaluationStatus": "DEFERRED"}
        journal_ready = True

    # Correlation analysis reads a large set of OHLCV files. Until the
    # evidence gate passes, an entry is already prohibited, so defer that
    # expensive work instead of slowing every page load for no decision gain.
    if proof_ready:
        try:
            risk_budget = portfolio_risk_budget.risk_budget(market=market, user_id=user_id)
        except Exception:
            risk_budget = {"status": "ERROR", "warnings": ["portfolio risk budget unavailable"]}
        risk_ready = str(risk_budget.get("status") or "").upper() == "OK"
    else:
        risk_budget = {
            "status": "DEFERRED",
            "policy": portfolio_risk_budget.POLICY,
            "warnings": ["Risk budget is evaluated when independent performance evidence passes."],
        }
        risk_ready = True

    if not journal_ready:
        reasons.append("JOURNAL_INTEGRITY_NOT_READY")
    if not risk_ready:
        reasons.append("PORTFOLIO_RISK_BUDGET_EXCEEDED")
    if not data_ready:
        reasons.append("DATA_QUALITY_KILL_SWITCH")
    if not proof_ready:
        reasons.append(str(performance_gate.get("reason") or "WALK_FORWARD_DATA_NOT_READY"))
    if not shadow_integrity_ready:
        reasons.append("QUANT_EVIDENCE_INTEGRITY_NOT_READY")
    if not shadow_signal_ready:
        reasons.append("QUANT_SHADOW_NOT_APPROVED")
    if not execution_ready:
        reasons.append("QUANT_EXECUTION_PLAN_INVALID")

    raw_candidate_count = int(paper_status.get("rawCandidateCount") or paper_status.get("activeRawCandidateCount") or paper_status.get("candidateCount") or 0)
    candidate_count = len(execution_plan.get("positions") or []) if execution_ready and raw_candidate_count > 0 else 0
    if not reasons and candidate_count <= 0:
        reasons.append("NO_ELIGIBLE_CANDIDATE")

    if not journal_ready or not risk_ready or not data_ready or not shadow_integrity_ready or not execution_ready:
        operating_state = "BLOCKED"
    elif not proof_ready or not shadow_signal_ready or candidate_count <= 0:
        operating_state = "ABSTAIN"
    elif is_review_session:
        operating_state = "WATCH"
        reasons.append("MARKET_CLOSED_REVIEW")
    else:
        operating_state = "RECOMMENDATION_READY"

    checks = [
        {"id": "evidence", "label": "실현·독립 검증", "passed": proof_ready, "detail": performance_gate.get("reason")},
        {"id": "journal", "label": "AI 일지 무결성", "passed": None if operational_journal.get("status") == "DEFERRED" else journal_ready, "detail": operational_journal.get("status")},
        {"id": "portfolio", "label": "포트폴리오 위험예산", "passed": risk_ready, "detail": risk_budget.get("status")},
        {"id": "data", "label": "데이터 품질", "passed": data_ready, "detail": quality.get("status")},
    ]
    checks.append({"id": "quantShadow", "label": "Quant V2 evidence", "passed": shadow_signal_ready, "detail": shadow.get("decision")})
    checks.append({"id": "executionPlan", "label": "Candidate execution lineage", "passed": execution_ready, "detail": execution_plan.get("status")})
    recommendation_actionable = operating_state == "RECOMMENDATION_READY"
    # Discovery paper capital exists to generate forward evidence. It remains
    # strictly separate from recommendation/live promotion authority and only
    # runs with current candidates, healthy source data, and an active session.
    paper_research_ready = bool(
        ai_paper_trader.PAPER_DISCOVERY_ENABLED
        and data_ready
        and raw_candidate_count > 0
        and not is_review_session
    )
    scope = product_scope.product_scope()
    return {
        "market": market,
        "operatingState": operating_state,
        "recommendationActionable": recommendation_actionable,
        # Backward-compatible advisory alias. This never grants broker authority.
        "entryAllowed": recommendation_actionable,
        "paperEntryAllowed": recommendation_actionable,
        "paperResearchEntryAllowed": paper_research_ready,
        "exitAllowed": True,
        "liveOrderAllowed": product_scope.live_order_allowed(),
        "productScope": scope,
        "candidateCount": candidate_count if proof_ready and shadow_signal_ready else 0,
        "rawCandidateCount": raw_candidate_count,
        "paperResearch": {
            "enabled": ai_paper_trader.PAPER_DISCOVERY_ENABLED,
            "entryAllowed": paper_research_ready,
            "purpose": "forward evidence collection only",
            "promotionAuthority": False,
            "blockedReasons": list(dict.fromkeys(
                ([] if data_ready else ["DATA_QUALITY_KILL_SWITCH"])
                + ([] if raw_candidate_count > 0 else ["NO_ELIGIBLE_CANDIDATE"])
                + (["MARKET_CLOSED_REVIEW"] if is_review_session else [])
            )),
        },
        "reasonCodes": list(dict.fromkeys(reasons)),
        "reasons": [_decision_reason(code) for code in dict.fromkeys(reasons)],
        "checks": checks,
        "performanceGate": performance_gate,
        "proofBoard": paper_status.get("proofBoard") or {},
        "journal": {
            "status": operational_journal.get("status"),
            "recordingStatus": operational_journal.get("recordingStatus"),
            "evaluationStatus": operational_journal.get("evaluationStatus"),
            "integrity": operational_journal.get("integrity") or {},
            "journal": journal.get("journal") or {},
        },
        "riskBudget": {
            "status": risk_budget.get("status"),
            "actualHoldingCount": risk_budget.get("actualHoldingCount", 0),
            "totalLossBudgetPct": risk_budget.get("totalLossBudgetPct", 0),
            "maxPortfolioLossPct": (risk_budget.get("policy") or {}).get("maxPortfolioLossPct"),
            "warnings": risk_budget.get("warnings") or [],
        },
        "executionPlan": execution_plan,
        "dataQuality": {"status": quality.get("status") or quality.get("dataStatus"), "killSwitch": bool(quality.get("killSwitch"))},
        "priceSession": price_session,
        "quantShadow": {
            "status": shadow.get("status"),
            "mode": shadow.get("mode"),
            "decision": shadow.get("decision"),
            "decisionReasons": shadow.get("decisionReasons") or [],
            "missingReports": shadow_missing,
            "staleReports": shadow_stale,
            "liveTradingAllowed": False,
        },
    }


def operating_status(market: str = "all", user_id: str = "") -> dict[str, Any]:
    try:
        shadow = quant_shadow_status.shadow_status()
    except Exception:
        shadow = {
            "status": "ERROR",
            "decision": "ABSTAIN",
            "liveTradingAllowed": False,
            "missingReports": list(quant_shadow_status.REPORT_FILES),
            "staleReports": list(quant_shadow_status.REPORT_FILES),
            "decisionReasons": ["SHADOW_STATUS_UNAVAILABLE"],
        }
    markets = {mk: _govern_market(mk, user_id=user_id, shadow=shadow) for mk in _market_list(market)}
    scope = product_scope.product_scope()
    return {
        "status": "OK",
        "market": market,
        "executionMode": scope["executionMode"],
        "productScope": scope,
        "disclaimer": "Quant recommendation and Paper-validation aid. MONE never sends broker orders; the user decides and executes separately.",
        "markets": markets,
        "recommendationReadyMarketCount": sum(1 for row in markets.values() if row["recommendationActionable"]),
        "tradeableMarketCount": 0,
    }


def entry_authority(market: str, user_id: str = "") -> dict[str, Any]:
    """Return the canonical authority for a new position; failures deny entry."""
    normalized = _market_list(market)[0]
    try:
        return operating_status(normalized, user_id=user_id)["markets"][normalized]
    except Exception as exc:
        return {
            "market": normalized,
            "operatingState": "BLOCKED",
            "recommendationActionable": False,
            "entryAllowed": False,
            "paperEntryAllowed": False,
            "exitAllowed": True,
            "liveOrderAllowed": False,
            "productScope": product_scope.product_scope(),
            "reasonCodes": ["OPERATING_AUTHORITY_UNAVAILABLE"],
            "reasons": [_decision_reason("OPERATING_AUTHORITY_UNAVAILABLE")],
            "error": repr(exc),
        }


def apply_entry_authority(payload: dict[str, Any], market: str, user_id: str = "") -> dict[str, Any]:
    """Keep research candidates visible while making denied entries unmistakably non-tradeable."""
    authority = entry_authority(market, user_id=user_id)
    payload["operatingAuthority"] = authority
    payload["entryAllowed"] = bool(authority.get("entryAllowed"))
    payload["recommendationActionable"] = bool(authority.get("recommendationActionable", authority.get("entryAllowed")))
    payload["liveOrderAllowed"] = False
    payload["productScope"] = authority.get("productScope") or product_scope.product_scope()
    if authority.get("entryAllowed"):
        return payload

    reason_codes = list(authority.get("reasonCodes") or ["OPERATING_AUTHORITY_BLOCK"])
    reason_text = "; ".join(reason_codes)
    payload["reviewOnly"] = True
    safety = dict(payload.get("tradeSafety") or {})
    safety.update({
        "status": "BLOCKED",
        "reviewOnly": True,
        "isTradeBlocked": True,
        "operatingState": authority.get("operatingState"),
        "reasonCodes": reason_codes,
    })
    safety["reason"] = str(safety.get("reason") or reason_text)
    payload["tradeSafety"] = safety
    blocked_items: list[Any] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            blocked_items.append(item)
            continue
        row = dict(item)
        row["isTradeBlocked"] = True
        existing = str(row.get("tradeBlockStatus") or "").upper()
        if existing in {"", "OK", "NORMAL"}:
            row["tradeBlockStatus"] = "QUANT_OPERATING_GATE"
        row["tradeBlockReason"] = row.get("tradeBlockReason") or reason_text
        row["reviewOnly"] = True
        row["entryAllowed"] = False
        blocked_items.append(row)
    payload["items"] = blocked_items
    payload["blockedCount"] = sum(1 for item in blocked_items if isinstance(item, dict) and item.get("isTradeBlocked"))
    return payload
