from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.engine import walkforward_backtest
from app.services import ai_paper_trader


def _trade(exit_date: str, pnl: float, status: str = "기간종료") -> dict:
    return {
        "symbol": exit_date,
        "executionStatus": "체결",
        "exitStatus": status,
        "netPnlPct": pnl,
        "entryDate": exit_date,
        "exitDate": exit_date,
        "holdingDays": 1,
    }


def test_walkforward_mdd_uses_chronological_fixed_notional_equity() -> None:
    # Chronological equity: 100 -> 200 -> 125 -> 50, so MDD is -75%.
    # The old additive-PnL drawdown incorrectly reported -150%.
    results = [
        _trade("2026-01-03", -75.0),
        _trade("2026-01-01", 100.0, "목표도달"),
        _trade("2026-01-02", -75.0),
    ]

    stats = walkforward_backtest._agg_stats(results)

    assert stats["mddPct"] == -75.0
    assert -100.0 <= stats["mddPct"] <= 0.0
    assert stats["mddMethod"] == "fixed_notional_equity_100"


def test_paper_proof_board_normalizes_legacy_impossible_mdd(monkeypatch) -> None:
    profile = {
        "id": "ml_rank_balanced_mid",
        "label": "Balanced Mid",
        "mode": "balanced",
        "horizon": "mid",
    }
    monkeypatch.setattr(ai_paper_trader, "AGENT_POOL", [profile])
    monkeypatch.setattr(
        ai_paper_trader,
        "_read_csv",
        lambda _path: [
            {
                "window": "2026-01-01",
                "windowIndex": 1,
                "mode": "balanced",
                "horizon": "mid",
                "strategy": "corrected",
                "executionCount": 40,
                "winCount": 20,
                "avgNetPnlPct": 1.0,
                "mddPct": -198.0,
            }
        ],
    )

    board = ai_paper_trader._walkforward_proof_board("kr", profile["id"])

    assert board["rows"][0]["mddPct"] == -100.0
    assert board["rows"][0]["mddNormalized"] is True
    assert board["legacyMddNormalized"] is True
    assert board["mddMethod"] == "fixed_notional_equity_100"