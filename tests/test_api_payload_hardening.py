from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.services import portfolio_risk_budget as prb  # noqa: E402
from app.services import virtual_trade_journal as vtj  # noqa: E402


def _items() -> list[dict]:
    return [
        {"symbol": "AAPL", "title": "Apple", "raw": {"oversized": "secret-source-row"}},
        {"symbol": "MSFT", "title": "Microsoft", "raw": {"oversized": "secret-source-row"}},
    ]


def test_news_endpoint_filters_symbol_limit_and_internal_raw(monkeypatch) -> None:
    monkeypatch.setattr(main.data, "news_rows", lambda market: {"status": "OK", "items": _items(), "count": 2})

    result = main.api_news("us", False, None, "AAPL", 1)

    assert result["count"] == 1
    assert result["items"][0]["symbol"] == "AAPL"
    assert "raw" not in result["items"][0]


def test_disclosures_endpoint_filters_symbol_limit_and_internal_raw(monkeypatch) -> None:
    monkeypatch.setattr(main.data, "disclosure_rows", lambda market: {"status": "OK", "items": _items(), "count": 2})

    result = main.api_disclosures("us", False, None, "AAPL", 1)

    assert result["count"] == 1
    assert result["items"][0]["symbol"] == "AAPL"
    assert "raw" not in result["items"][0]


def test_anonymous_risk_budget_does_not_run_shared_portfolio(monkeypatch) -> None:
    monkeypatch.setattr(
        prb,
        "risk_budget",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("shared risk calculation must not run")),
    )

    result = main.api_portfolio_risk_budget("all", "", "")

    assert result["status"] == "OK"
    assert result["authRequired"] is True
    assert result["actualHoldingCount"] == 0


def test_holdings_user_header_must_match_signed_token(monkeypatch) -> None:
    monkeypatch.delenv("MONE_ANON_HOLDINGS", raising=False)
    token, _, user_id = main._create_user_token("kakao", "subject-1", "owner@example.com", "Owner")

    valid = main._authenticated_holdings_uid(user_id, f"Bearer {token}")
    forged = main._authenticated_holdings_uid("another-user", f"Bearer {token}")
    unsigned = main._authenticated_holdings_uid(user_id, "")

    assert valid == main._sanitize_uid(user_id)
    assert forged == ""
    assert unsigned == ""


def test_symbol_search_route_returns_items_without_server_error() -> None:
    with TestClient(main.app) as client:
        response = client.get("/api/symbols", params={"market": "us", "q": "AAPL", "limit": 20})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "OK"
    assert isinstance(payload["items"], list)


def test_health_only_embeds_journal_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        vtj,
        "auto_capture_status",
        lambda: {
            "status": "OK",
            "enabled": True,
            "lastRunAt": "2026-08-15T08:00:00+09:00",
            "journalSession": "AFTER_CLOSE_TRADE",
            "evaluation": {"status": "OK", "items": [{"large": "x" * 100_000}]},
            "completedKeys": ["one"],
            "runs": [{"status": "OK", "added": 1}],
        },
    )
    main._HEALTH_CACHE.update({"ts": 0.0, "payload": None})

    payload = main._build_health_payload()

    assert payload["journalCapture"]["evaluationStatus"] == "OK"
