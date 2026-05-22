import pandas as pd

from core.trade_fit_engine import apply_trade_fit, calculate_trade_fit


def test_rr_pass_false_makes_trade_fit_low():
    result = calculate_trade_fit(
        {
            "last_price": 105,
            "entry": 100,
            "stop": 95,
            "tp1": 108,
            "rr": 1.2,
            "rr_pass": False,
        }
    )

    assert result["trade_fit_score"] < 50
    assert result["price_fit_level"] in {"나쁨", "부족"}


def test_entry_gap_warns_chasing_when_current_price_far_above_entry():
    result = calculate_trade_fit(
        {
            "last_price": 110,
            "entry": 100,
            "stop": 94,
            "tp1": 125,
            "rr": 2.5,
            "rr_pass": True,
        }
    )

    assert result["entry_gap_pct"] >= 10
    assert any("추격" in warning for warning in result["trade_fit_warnings"])


def test_trade_fit_score_is_clipped_0_100():
    high = calculate_trade_fit(
        {
            "last_price": 100,
            "entry": 100,
            "stop": 94,
            "tp1": 140,
            "rr": 10,
            "rr_pass": True,
            "support_holding": True,
            "volume_confirmed": True,
            "pullback_confirmed": True,
        }
    )
    low = calculate_trade_fit({"last_price": 150, "entry": 100, "rr": 0.5, "rr_pass": False})

    assert 0 <= high["trade_fit_score"] <= 100
    assert 0 <= low["trade_fit_score"] <= 100


def test_apply_trade_fit_keeps_existing_columns():
    df = pd.DataFrame([{"symbol": "ABC", "last_price": 100, "entry": 100, "rr": 2.0, "rr_pass": True}])

    out = apply_trade_fit(df)

    assert "symbol" in out.columns
    assert "trade_fit_score" in out.columns
