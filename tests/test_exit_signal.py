from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import exit_signal  # noqa: E402


def test_exit_signals_reads_items_from_user_data_payload(monkeypatch):
    monkeypatch.setattr(
        "app.services.user_data.get_holdings",
        lambda market: {
            "status": "OK",
            "items": [{"market": market, "symbol": "005930", "name": "Samsung", "avgPrice": 100, "targetPrice": 110}],
        },
    )
    monkeypatch.setattr(
        exit_signal,
        "_compute_indicators",
        lambda market, symbol: {"currentPrice": 108, "rsi14": 78, "ma5BelowMa10": False, "volumeRatio": 1.2},
    )

    out = exit_signal.get_exit_signals("kr")

    assert out["status"] == "OK"
    assert out["totalHoldings"] == 1
    assert out["signals"][0]["signal"] == "SELL_STRONG"


def test_exit_signals_uses_personal_holdings_when_user_id_is_present(monkeypatch):
    monkeypatch.setattr(
        "app.db.get_holdings",
        lambda user_id, market: [
            {"market": market, "symbol": "AAPL", "name": "Apple", "avgPrice": 100, "targetPrice": 120}
        ],
    )
    monkeypatch.setattr(
        exit_signal,
        "_compute_indicators",
        lambda market, symbol: {"currentPrice": 101, "rsi14": 55, "ma5BelowMa10": True, "volumeRatio": 1.0},
    )

    out = exit_signal.get_exit_signals("us", user_id="user-1")

    assert out["status"] == "OK"
    assert out["totalHoldings"] == 1
    assert out["signals"][0]["symbol"] == "AAPL"
    assert out["signals"][0]["signal"] == "MONITOR"
