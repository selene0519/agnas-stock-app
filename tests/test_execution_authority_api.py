from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main  # noqa: E402
from app.engine import mone_v65_api_stabilizer as stabilizer  # noqa: E402
from app.services import quant_operating_governor as governor  # noqa: E402
from app.services import paper_trading  # noqa: E402


def _denied_authority(market: str, user_id: str = "") -> dict:
    return {
        "market": market,
        "operatingState": "ABSTAIN",
        "entryAllowed": False,
        "paperEntryAllowed": False,
        "exitAllowed": True,
        "liveOrderAllowed": False,
        "reasonCodes": ["QUANT_SHADOW_NOT_APPROVED"],
    }


def test_active_recommendation_api_exposes_candidates_as_review_only_when_denied(monkeypatch) -> None:
    monkeypatch.setattr(governor, "entry_authority", _denied_authority)
    monkeypatch.setattr(
        stabilizer,
        "_recommendations_payload",
        lambda market, mode, horizon, cash, limit, watch_only: governor.apply_entry_authority(
            {"status": "OK", "count": 1, "items": [{"symbol": "AAPL", "tradeBlockStatus": "OK"}]},
            market,
        ),
    )

    with TestClient(main.app) as client:
        response = client.get("/api/final/recommendations?market=us&mode=balanced&horizon=swing&limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["entryAllowed"] is False
    assert payload["reviewOnly"] is True
    assert payload["items"][0]["isTradeBlocked"] is True
    assert payload["items"][0]["tradeBlockStatus"] == "QUANT_OPERATING_GATE"


def test_unauthenticated_direct_ai_paper_run_is_rejected_before_execution(monkeypatch) -> None:
    monkeypatch.setattr(main, "_admin_auth_configured", lambda: True)
    monkeypatch.setattr(main, "_verify_admin_token", lambda token: False)
    executed: list[bool] = []

    from app.services import ai_paper_trader

    monkeypatch.setattr(ai_paper_trader, "run_cycle", lambda **kwargs: executed.append(True) or {"status": "OK"})
    main._rate_limit_store.clear()

    with TestClient(main.app) as client:
        response = client.post("/api/paper/ai/run", json={"market": "kr", "dryRun": False})

    assert response.status_code == 401
    assert response.json()["code"] == "ADMIN_AUTH_REQUIRED"
    assert executed == []


def test_paper_mutation_fails_closed_when_admin_credentials_are_not_configured(monkeypatch) -> None:
    for name in (
        "MONE_ADMIN_ID",
        "MONE_ADMIN_USERNAME",
        "MONE_ADMIN_PASSWORD",
        "MONE_ADMIN_PASSWORD_SHA256",
    ):
        monkeypatch.delenv(name, raising=False)
    executed: list[bool] = []

    from app.services import ai_paper_trader

    monkeypatch.setattr(ai_paper_trader, "run_cycle", lambda **kwargs: executed.append(True) or {"status": "OK"})
    main._rate_limit_store.clear()

    with TestClient(main.app) as client:
        response = client.post("/api/paper/ai/run", json={"market": "kr", "dryRun": False})

    assert response.status_code == 503
    assert response.json()["code"] == "ADMIN_AUTH_NOT_CONFIGURED"
    assert executed == []


def test_direct_paper_buy_service_cannot_bypass_operating_authority(monkeypatch) -> None:
    monkeypatch.setattr(governor, "entry_authority", _denied_authority)
    ledger_reads: list[bool] = []
    monkeypatch.setattr(paper_trading, "_load_balance", lambda: ledger_reads.append(True) or {"us": 100_000.0})

    result = paper_trading.buy("AAPL", "us", 1, price=200.0)

    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert result["code"] == "QUANT_OPERATING_GATE"
    assert ledger_reads == []
