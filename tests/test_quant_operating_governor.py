import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import quant_operating_governor as governor


def _stub_dependencies(monkeypatch, *, allowed=True, journal_status="RUNNING", risk_status="OK", kill_switch=False, review=False, candidates=2):
    monkeypatch.setattr(governor.ai_paper_trader, "status", lambda market: {"markets": {market: {"candidateCount": candidates, "entryPerformanceGate": {"allowed": allowed, "reason": "REALIZED_AND_OOS_EDGE_CONFIRMED"}, "proofBoard": {"status": "OK"}}}})
    monkeypatch.setattr(governor.virtual_trade_journal, "ops_dashboard", lambda market: {"status": "OK", "operational": {"status": journal_status, "recordingStatus": "OK", "evaluationStatus": "OK"}})
    monkeypatch.setattr(governor.portfolio_risk_budget, "risk_budget", lambda market, user_id="": {"status": risk_status, "policy": {"maxPortfolioLossPct": 6.0}})
    monkeypatch.setattr(governor.data_quality, "data_quality", lambda market, mode: {"status": "OK", "killSwitch": kill_switch})
    monkeypatch.setattr(governor.session, "get_price_session", lambda market: {"isReviewMode": review, "priceSession": f"{market}_closed" if review else f"{market}_intraday"})


def test_governor_allows_only_when_every_gate_passes(monkeypatch) -> None:
    _stub_dependencies(monkeypatch)
    result = governor.operating_status("kr")["markets"]["kr"]
    assert result["operatingState"] == "TRADEABLE"
    assert result["entryAllowed"] is True


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
