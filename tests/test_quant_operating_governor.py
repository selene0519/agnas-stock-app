import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import quant_operating_governor as governor


def _stub_dependencies(monkeypatch, *, allowed=True, journal_status="RUNNING", risk_status="OK", kill_switch=False, review=False, candidates=2):
    monkeypatch.setattr(governor.ai_paper_trader, "status", lambda market: {"markets": {market: {"activeAgent": {"mode": "balanced", "horizon": "mid"}, "candidateCount": candidates, "entryPerformanceGate": {"allowed": allowed, "reason": "REALIZED_AND_OOS_EDGE_CONFIRMED"}, "proofBoard": {"status": "OK"}}}})
    monkeypatch.setattr(governor.virtual_trade_journal, "ops_dashboard", lambda market: {"status": "OK", "operational": {"status": journal_status, "recordingStatus": "OK", "evaluationStatus": "OK"}})
    monkeypatch.setattr(governor.portfolio_risk_budget, "risk_budget", lambda market, user_id="": {"status": risk_status, "policy": {"maxPortfolioLossPct": 6.0}})
    monkeypatch.setattr(governor.data_quality, "data_quality", lambda market, mode: {"status": "OK", "killSwitch": kill_switch})
    monkeypatch.setattr(governor.session, "get_price_session", lambda market: {"isReviewMode": review, "priceSession": f"{market}_closed" if review else f"{market}_intraday"})
    monkeypatch.setattr(
        governor.quant_execution_plan,
        "execution_plan",
        lambda market: {"status": "AUTHORIZED", "positions": [{"market": market, "symbol": "005930", "mode": "balanced", "horizon": "mid"}], "blockingReasons": []},
    )
    monkeypatch.setattr(
        governor.quant_shadow_status,
        "shadow_status",
        lambda: {
            "status": "OK",
            "mode": "SHADOW_ONLY",
            "decision": "SHADOW_TAKE",
            "decisionReasons": [],
            "missingReports": [],
            "staleReports": [],
            "liveTradingAllowed": False,
        },
    )


def test_governor_allows_only_when_every_gate_passes(monkeypatch) -> None:
    _stub_dependencies(monkeypatch)
    payload = governor.operating_status("kr")
    result = payload["markets"]["kr"]
    assert result["operatingState"] == "RECOMMENDATION_READY"
    assert result["recommendationActionable"] is True
    assert result["entryAllowed"] is True
    assert result["paperEntryAllowed"] is True
    assert result["exitAllowed"] is True
    assert result["liveOrderAllowed"] is False
    assert result["productScope"]["executionMode"] == "ADVISORY_PAPER_ONLY"
    assert payload["recommendationReadyMarketCount"] == 1
    assert payload["tradeableMarketCount"] == 0


def test_governor_never_grants_live_order_authority_even_if_shadow_payload_requests_it(monkeypatch) -> None:
    _stub_dependencies(monkeypatch)
    monkeypatch.setattr(
        governor.quant_shadow_status,
        "shadow_status",
        lambda: {
            "status": "OK",
            "mode": "SHADOW_ONLY",
            "decision": "SHADOW_TAKE",
            "decisionReasons": [],
            "missingReports": [],
            "staleReports": [],
            "liveTradingAllowed": True,
        },
    )

    result = governor.operating_status("kr")

    assert result["markets"]["kr"]["recommendationActionable"] is True
    assert result["markets"]["kr"]["liveOrderAllowed"] is False
    assert result["markets"]["kr"]["quantShadow"]["liveTradingAllowed"] is False
    assert result["productScope"]["liveBrokerOrdersSupported"] is False


def test_governor_abstains_when_evidence_is_unproven(monkeypatch) -> None:
    _stub_dependencies(monkeypatch, allowed=False)
    result = governor.operating_status("kr")["markets"]["kr"]
    assert result["operatingState"] == "ABSTAIN"
    assert result["entryAllowed"] is False
    assert result["riskBudget"]["status"] == "DEFERRED"


def test_governor_blocks_when_journal_is_not_healthy(monkeypatch) -> None:
    _stub_dependencies(monkeypatch, journal_status="ERROR")
    result = governor.operating_status("kr")["markets"]["kr"]
    assert result["operatingState"] == "BLOCKED"
    assert "JOURNAL_INTEGRITY_NOT_READY" in result["reasonCodes"]


def test_governor_blocks_when_candidate_execution_lineage_is_invalid(monkeypatch) -> None:
    _stub_dependencies(monkeypatch)
    monkeypatch.setattr(
        governor.quant_execution_plan,
        "execution_plan",
        lambda market: {"status": "BLOCKED", "positions": [], "blockingReasons": ["RISK_ALLOCATION_FINGERPRINT_MISMATCH"]},
    )

    result = governor.operating_status("kr")["markets"]["kr"]

    assert result["operatingState"] == "BLOCKED"
    assert result["entryAllowed"] is False
    assert "QUANT_EXECUTION_PLAN_INVALID" in result["reasonCodes"]


def test_governor_does_not_authorize_candidate_from_inactive_agent_cell(monkeypatch) -> None:
    _stub_dependencies(monkeypatch)
    monkeypatch.setattr(
        governor.quant_execution_plan,
        "execution_plan",
        lambda market: {
            "status": "AUTHORIZED",
            "positions": [{"market": market, "symbol": "005930", "mode": "aggressive", "horizon": "short"}],
            "blockingReasons": [],
        },
    )

    result = governor.operating_status("kr")["markets"]["kr"]

    assert result["operatingState"] == "BLOCKED"
    assert "QUANT_EXECUTION_PLAN_INVALID" in result["reasonCodes"]
    assert result["executionPlan"]["blockingReasons"] == ["NO_EXECUTABLE_POSITION_FOR_ACTIVE_AGENT"]


def test_governor_blocks_stale_quant_evidence_even_when_legacy_gate_passes(monkeypatch) -> None:
    _stub_dependencies(monkeypatch)
    monkeypatch.setattr(
        governor.quant_shadow_status,
        "shadow_status",
        lambda: {
            "status": "WARN",
            "mode": "SHADOW_ONLY",
            "decision": "SHADOW_TAKE",
            "decisionReasons": ["STALE_EVIDENCE_REPORTS"],
            "missingReports": [],
            "staleReports": ["residualAlpha"],
            "liveTradingAllowed": False,
        },
    )

    result = governor.operating_status("kr")["markets"]["kr"]

    assert result["operatingState"] == "BLOCKED"
    assert result["entryAllowed"] is False
    assert result["exitAllowed"] is True
    assert "QUANT_EVIDENCE_INTEGRITY_NOT_READY" in result["reasonCodes"]


def test_recommendations_remain_visible_but_are_not_tradeable_when_authority_denies(monkeypatch) -> None:
    monkeypatch.setattr(
        governor,
        "entry_authority",
        lambda market, user_id="": {
            "market": market,
            "operatingState": "ABSTAIN",
            "entryAllowed": False,
            "liveOrderAllowed": False,
            "reasonCodes": ["QUANT_SHADOW_NOT_APPROVED"],
        },
    )
    payload = {"status": "OK", "items": [{"symbol": "AAPL", "tradeBlockStatus": "OK"}]}

    result = governor.apply_entry_authority(payload, "us")

    assert len(result["items"]) == 1
    assert result["reviewOnly"] is True
    assert result["entryAllowed"] is False
    assert result["items"][0]["isTradeBlocked"] is True
    assert result["items"][0]["tradeBlockStatus"] == "QUANT_OPERATING_GATE"
