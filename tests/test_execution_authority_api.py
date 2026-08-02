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


def _tradeable_authority(market: str, user_id: str = "") -> dict:
    return {
        "market": market,
        "operatingState": "RECOMMENDATION_READY",
        "recommendationActionable": True,
        "entryAllowed": True,
        "paperEntryAllowed": True,
        "exitAllowed": True,
        "executionPlan": {
            "status": "AUTHORIZED",
            "maxGrossExposure": 0.30,
            "positions": [{
                "decisionId": "decision-a",
                "candidateKey": "candidate-a",
                "market": "us",
                "symbol": "AAPL",
                "entryPrice": 100.0,
                "stopPrice": 95.0,
                "weight": 0.10,
            }],
        },
    }


def test_direct_paper_buy_rejects_symbol_outside_execution_plan(monkeypatch) -> None:
    monkeypatch.setattr(governor, "entry_authority", _tradeable_authority)
    ledger_reads: list[bool] = []
    monkeypatch.setattr(paper_trading, "_load_balance", lambda: ledger_reads.append(True) or {"us": 1_000.0})

    result = paper_trading.buy("MSFT", "us", 1, price=100.0)

    assert result["ok"] is False
    assert result["code"] == "QUANT_EXECUTION_CANDIDATE_GATE"
    assert ledger_reads == []


def test_direct_paper_buy_cannot_exceed_sealed_target_weight(monkeypatch) -> None:
    monkeypatch.setattr(governor, "entry_authority", _tradeable_authority)
    monkeypatch.setattr(paper_trading, "_load_balance", lambda: {"us": 1_000.0})
    monkeypatch.setattr(paper_trading, "_load_trades", lambda: [])
    monkeypatch.setattr(paper_trading, "_enrich_positions", lambda positions: [])

    result = paper_trading.buy("AAPL", "us", 2, price=100.0)

    assert result["ok"] is False
    assert result["code"] == "QUANT_RISK_WEIGHT_EXCEEDED"
    assert result["maxNewNotional"] == 100.0


def test_direct_paper_buy_persists_execution_lineage(monkeypatch) -> None:
    monkeypatch.setattr(governor, "entry_authority", _tradeable_authority)
    monkeypatch.setattr(paper_trading, "_load_balance", lambda: {"us": 1_000.0})
    monkeypatch.setattr(paper_trading, "_load_trades", lambda: [])
    monkeypatch.setattr(paper_trading, "_enrich_positions", lambda positions: [])
    monkeypatch.setattr(paper_trading, "_save_balance", lambda balance: None)
    trades: list[dict] = []
    lineage: list[tuple[dict, dict]] = []
    monkeypatch.setattr(paper_trading, "_append_trade", lambda trade: trades.append(trade))
    monkeypatch.setattr(
        paper_trading,
        "_append_execution_lineage",
        lambda trade, authority: lineage.append((trade, authority)) or {"recordHash": "hash-a"},
    )

    result = paper_trading.buy("AAPL", "us", 0.5, price=100.0)

    assert result["ok"] is True
    assert len(trades) == 1
    assert len(lineage) == 1
    assert lineage[0][1]["candidateKey"] == "candidate-a"
    assert result["executionLineage"]["recordHash"] == "hash-a"


def test_execution_lineage_row_is_hash_sealed(monkeypatch, tmp_path) -> None:
    path = tmp_path / "paper_execution_ledger.csv"
    monkeypatch.setattr(paper_trading, "_EXECUTION_LEDGER_CSV", path)
    trade = {
        "id": "trade-a", "createdAt": "2026-07-31 09:00:00", "market": "us", "symbol": "AAPL",
        "price": 100.0, "quantity": 0.5, "totalValue": 50.0,
    }
    authority = {
        "decisionId": "decision-a", "candidateKey": "candidate-a", "signalDate": "2026-07-31",
        "metaPolicyFingerprint": "meta-a", "riskPolicyVersion": "risk-v1",
        "riskPolicyFingerprint": "risk-a", "allocationFingerprint": "allocation-a", "weight": 0.10,
    }

    row = paper_trading._append_execution_lineage(trade, authority)

    assert path.exists()
    assert len(row["recordHash"]) == 64
    assert "candidate-a" in path.read_text(encoding="utf-8")
