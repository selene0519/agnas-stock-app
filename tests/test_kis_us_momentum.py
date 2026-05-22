from __future__ import annotations

import math

import core.kis_us_momentum as momentum


def test_us_momentum_normalize_success():
    raw = {
        "symbol": "AAPL",
        "market": "미국주식",
        "flow_mode": "us_momentum",
        "flow_fetch_status": "success",
        "flow_data_available": True,
        "last_price": 180.0,
        "intraday_change_pct": 1.2,
        "intraday_volume": 1000,
        "execution_strength": 62.0,
        "orderbook_pressure": 0.1,
        "intraday_momentum_score": 68.0,
        "flow_data_source": "kis_us_quote+kis_us_orderbook",
    }
    import core.intraday_flow_engine as flow_engine

    out = flow_engine.normalize_intraday_flow_data(raw)
    assert out["flow_mode"] == "us_momentum"
    assert out["foreign_net_buy"] is None
    assert out["flow_data_available"] is True
    assert out["intraday_momentum_score"] == 68.0


def test_fetch_intraday_us_momentum_flow_uses_quote(monkeypatch):
    monkeypatch.setattr(
        momentum,
        "fetch_kis_us_quote_api",
        lambda symbol, target_row=None: {
            "ok": True,
            "last_price": 42.0,
            "intraday_change_pct": 0.5,
            "intraday_volume": 100.0,
            "intraday_trading_value": 4200.0,
            "quote_source": "kis_us_quote",
        },
    )
    monkeypatch.setattr(momentum.UsMomentumRankingCache, "lookup", lambda self, symbol, excd: {})
    monkeypatch.setattr(
        momentum,
        "fetch_kis_us_ccnl_metrics",
        lambda symbol, excd: {"execution_strength": math.nan},
    )
    out = momentum.fetch_intraday_us_momentum_flow("AAPL", "미국주식")
    assert out["flow_fetch_status"] == "success"
    assert out["last_price"] == 42.0
    assert "kis_us_quote" in str(out.get("flow_data_source", ""))
