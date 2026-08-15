from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import portfolio_risk_budget as prb  # noqa: E402
from app.engine import mone_v77_holdings_risk as holdings_risk  # noqa: E402


def test_risk_budget_flags_oversized_position_loss(monkeypatch) -> None:
    monkeypatch.setattr(
        prb,
        "_holding_rows",
        lambda market, user_id="": [
            {
                "market": "kr",
                "symbol": "005930",
                "name": "Samsung",
                "quantity": 100,
                "currentPrice": 100,
                "stopPrice": 90,
                "sector": "TECH",
                "mode": "balanced",
                "horizon": "swing",
            },
            {
                "market": "kr",
                "symbol": "000660",
                "name": "Hynix",
                "quantity": 20,
                "currentPrice": 100,
                "stopPrice": 96,
                "sector": "TECH",
                "mode": "balanced",
                "horizon": "swing",
            },
        ],
    )
    monkeypatch.setattr(prb, "_load_kelly", lambda: {"balanced_swing": {"recommendedPct": 12}})

    out = prb.risk_budget("kr")

    assert out["status"] == "OVER_BUDGET"
    assert out["totalLossBudgetPct"] > 6
    assert out["items"][0]["symbol"] == "005930"
    assert out["items"][0]["action"] == "REDUCE"
    assert out["items"][0]["recommendedWeightPct"] == 12


def test_risk_budget_uses_default_stop_when_missing(monkeypatch) -> None:
    # This test targets the generic-%% fallback path specifically (no explicit
    # stop AND no ATR available), independent of whatever real OHLCV happens to
    # be on disk for AAPL - depending on real data made this test flaky when the
    # backfill deepened AAPL's history and let the ATR path succeed instead.
    monkeypatch.setattr(holdings_risk, "derive_fallback_stop", lambda market, symbol, current: 0.0)
    monkeypatch.setattr(
        prb,
        "_holding_rows",
        lambda market, user_id="": [
            {"market": "us", "symbol": "AAPL", "name": "Apple", "quantity": 10, "currentPrice": 100}
        ],
    )
    monkeypatch.setattr(prb, "_load_kelly", lambda: {})

    out = prb.risk_budget("us")

    assert out["missingStopCount"] == 1
    assert "default stop used" in out["items"][0]["reasons"]
    assert out["items"][0]["stopPrice"] == 92.0


def test_empty_personal_ledger_never_falls_back_to_shared_holdings(monkeypatch) -> None:
    from app import db

    monkeypatch.setattr(db, "get_holdings", lambda user_id, market: [])
    monkeypatch.setattr(
        prb,
        "_csv_holding_rows",
        lambda market: (_ for _ in ()).throw(AssertionError("shared CSV fallback must not run")),
    )

    rows = prb._holding_rows("all", user_id="authenticated-user")
