from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import portfolio_risk_budget as prb  # noqa: E402


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
