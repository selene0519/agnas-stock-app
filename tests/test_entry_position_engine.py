import pandas as pd

from core.entry_position_engine import apply_entry_position, classify_entry_position


def test_chase_risk_entry_position_type_is_exact():
    result = classify_entry_position(
        {
            "last_price": 108,
            "entry": 100,
            "stop": 95,
            "chase_risk": True,
            "overheat_level": "보통",
        }
    )

    assert result["entry_position_type"] == "추격매수 위험"
    assert result["entry_position_score"] < 40


def test_pullback_confirmed_gets_high_entry_score():
    result = classify_entry_position(
        {
            "last_price": 101,
            "entry": 100,
            "stop": 95,
            "pullback_confirmed": True,
            "volume_confirmed": True,
        }
    )

    assert result["entry_position_type"] == "눌림 확인 완료"
    assert result["entry_position_score"] >= 80


def test_entry_position_score_is_clipped_0_100():
    result = classify_entry_position({"last_price": 100, "entry": 100})

    assert 0 <= result["entry_position_score"] <= 100


def test_apply_entry_position_keeps_existing_columns():
    df = pd.DataFrame([{"symbol": "ABC", "last_price": 100, "entry": 100}])

    out = apply_entry_position(df)

    assert "symbol" in out.columns
    assert "entry_position_type" in out.columns


def test_high_quality_low_price_fit_is_not_buy_candidate():
    import app

    df = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "grade": "A",
                "score": 90,
                "sector_strength": 3,
                "leader_score": 95,
                "earnings_growth_score": 90,
                "news_momentum_score": 90,
                "relative_strength_score": 95,
                "near_high_score": 80,
                "volume_ratio": "2배",
                "trading_value": 20_000_000_000,
                "catalyst_score": 90,
                "last_price": 120,
                "entry": 100,
                "stop": 95,
                "tp1": 125,
                "rr": 1.2,
                "rr_pass": False,
            }
        ]
    )

    out = app.apply_quality_trade_entry_columns(df)

    assert out.loc[0, "stock_attractiveness_score"] >= 70
    assert out.loc[0, "trade_fit_score"] < 50
    assert out.loc[0, "grade"] != "A"
