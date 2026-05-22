from __future__ import annotations

import pandas as pd

from core.intraday_order_strength_engine import (
    apply_order_strength_to_candidates,
    calculate_execution_strength_score,
    calculate_orderbook_imbalance_score,
    classify_order_strength_action,
)


def _row(**kwargs):
    base = {
        "symbol": "ABC",
        "market": "미국주식",
        "orderbook_data_available": True,
        "bid_total_volume": 2000,
        "ask_total_volume": 1000,
        "bid_ask_ratio": 2.0,
        "orderbook_imbalance": 0.33,
        "spread_pct": 0.1,
        "execution_strength": 120,
        "strategy_trade_allowed": True,
        "trade_allowed": True,
    }
    base.update(kwargs)
    return base


def test_bid_imbalance_and_good_execution_is_buy_pressure():
    result = classify_order_strength_action(_row())
    assert result["order_strength_label"] == "매수세 우위"
    assert result["order_strength_score"] > 60


def test_ask_pressure_holds_entry():
    result = classify_order_strength_action(_row(bid_total_volume=500, ask_total_volume=2000, orderbook_imbalance=-0.6, execution_strength=70))
    assert result["order_strength_label"] == "진입 보류"


def test_wide_spread_is_liquidity_warning():
    result = classify_order_strength_action(_row(spread_pct=1.5))
    assert result["order_strength_label"] == "유동성 주의"
    assert "스프레드" in result["order_strength_warning"]


def test_missing_orderbook_holds_decision():
    result = classify_order_strength_action(_row(orderbook_data_available=False))
    assert result["order_strength_label"] == "호가 판단 보류"


def test_c_excluded_never_becomes_buy_allowed_from_order_strength():
    candidates = pd.DataFrame([{"symbol": "ABC", "market": "미국주식", "grade": "C", "strategy_trade_allowed": False}])
    orderbook = pd.DataFrame([_row(symbol="ABC")])
    out = apply_order_strength_to_candidates(candidates, orderbook)
    assert out["order_strength_label"].iloc[0] == "신규매수 금지 유지"
    assert "today_buy_allowed" not in out.columns or str(out["today_buy_allowed"].iloc[0]).lower() not in {"true", "1", "1.0"}


def test_scores_are_in_0_100_range():
    row = _row(orderbook_imbalance=2, execution_strength=300)
    imbalance = calculate_orderbook_imbalance_score(row)
    execution = calculate_execution_strength_score(row)
    action = classify_order_strength_action(row)
    for value in [
        imbalance["orderbook_imbalance_score"],
        execution["execution_strength_score"],
        action["order_strength_score"],
    ]:
        assert 0 <= value <= 100
