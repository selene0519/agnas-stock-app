from __future__ import annotations

import pandas as pd

from core.intraday_signal_engine import (
    apply_intraday_signals_to_candidates,
    calculate_intraday_money_flow_score,
    calculate_order_strength_score,
    classify_intraday_action,
)


def _row(**kwargs):
    base = {
        "symbol": "ABC",
        "market": "미국주식",
        "intraday_data_available": True,
        "intraday_change_pct": 2.5,
        "intraday_volume": 1000,
        "intraday_trading_value": 2_000_000_000,
        "intraday_volume_ratio": 1.5,
        "intraday_trading_value_ratio": 1.7,
        "strategy_trade_allowed": True,
        "trade_allowed": True,
    }
    base.update(kwargs)
    return base


def test_money_flow_up_with_value_increase_is_watch_strengthened():
    result = classify_intraday_action(_row())
    assert result["intraday_action_label"] == "관찰 강화"
    assert result["intraday_money_flow_score"] > 60


def test_money_flow_increase_with_price_down_is_risk_warning():
    result = classify_intraday_action(_row(intraday_change_pct=-2.1, intraday_trading_value_ratio=1.5))
    assert result["intraday_action_label"] == "위험 경고"
    assert result["intraday_entry_confirmed"] is False


def test_price_surge_and_overheated_value_is_chase_warning():
    result = classify_intraday_action(_row(intraday_change_pct=8.2, intraday_trading_value_ratio=2.5))
    assert result["intraday_action_label"] == "추격매수 경고"
    assert result["intraday_chase_risk"] is True


def test_low_trading_value_holds_entry():
    result = classify_intraday_action(_row(intraday_trading_value=0, intraday_trading_value_ratio=0.2))
    assert result["intraday_action_label"] == "진입 보류"
    assert result["intraday_entry_confirmed"] is False


def test_missing_intraday_data_holds_decision():
    result = classify_intraday_action(_row(intraday_data_available=False))
    assert result["intraday_action_label"] == "장중 판단 보류"
    assert result["intraday_entry_confirmed"] is False


def test_c_excluded_never_becomes_buy_allowed_from_intraday_data():
    candidates = pd.DataFrame([{"symbol": "ABC", "market": "미국주식", "grade": "C", "strategy_trade_allowed": False}])
    intraday = pd.DataFrame([_row(symbol="ABC", intraday_change_pct=3, intraday_trading_value_ratio=2.5)])
    out = apply_intraday_signals_to_candidates(candidates, intraday)
    assert out["intraday_entry_confirmed"].iloc[0] is False
    assert out["intraday_action_label"].iloc[0] == "신규매수 금지 유지"
    assert out["intraday_final_label"].iloc[0] == "신규매수 금지 유지"


def test_scores_are_in_0_100_range():
    row = _row(intraday_change_pct=30, intraday_trading_value_ratio=10, intraday_volume_ratio=10, execution_strength=300)
    money = calculate_intraday_money_flow_score(row)
    order = calculate_order_strength_score(row)
    action = classify_intraday_action(row)
    for value in [
        money["intraday_money_flow_score"],
        order["intraday_order_strength_score"],
        action["intraday_signal_score"],
        action["intraday_composite_score"],
    ]:
        assert 0 <= value <= 100


def test_composite_uses_orderbook_strength():
    result = classify_intraday_action(_row(orderbook_data_available=True, order_strength_score=82, order_strength_label="매수세 우위"))
    assert result["intraday_final_label"] == "관찰 강화"
    assert "매수세 우위" in result["intraday_final_reason"]
