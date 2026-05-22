import pandas as pd

from core.position_sizing_engine import apply_position_sizing, calculate_position_sizing


def test_risk_mode_position_size_is_zero():
    result = calculate_position_sizing(
        {"strategy_mode": "위험장", "strategy_adjusted_grade": "A", "strategy_trade_allowed": True, "rr_pass": True}
    )

    assert result["position_size_pct"] == 0


def test_rr_pass_false_position_size_is_zero():
    result = calculate_position_sizing(
        {"strategy_mode": "상승장", "strategy_adjusted_grade": "A", "strategy_trade_allowed": True, "rr_pass": False}
    )

    assert result["position_size_pct"] == 0


def test_stop_first_position_size_is_zero():
    result = calculate_position_sizing(
        {
            "strategy_mode": "상승장",
            "strategy_adjusted_grade": "A",
            "strategy_trade_allowed": True,
            "rr_pass": True,
            "risk_final_decision": "손절 우선",
        }
    )

    assert result["position_size_pct"] == 0


def test_b_grade_position_size_is_between_20_and_50():
    result = calculate_position_sizing(
        {
            "strategy_mode": "박스장",
            "strategy_adjusted_grade": "B",
            "strategy_trade_allowed": True,
            "rr_pass": True,
            "rr": 2.5,
        }
    )

    assert 20 <= result["position_size_pct"] <= 50


def test_c_or_forbidden_position_size_is_between_0_and_20():
    result = calculate_position_sizing(
        {
            "strategy_mode": "박스장",
            "strategy_adjusted_grade": "C",
            "strategy_trade_allowed": True,
            "rr_pass": True,
            "rr": 2.5,
        }
    )

    assert 0 <= result["position_size_pct"] <= 20


def test_position_size_is_clipped_to_0_100():
    result = calculate_position_sizing(
        {
            "strategy_mode": "상승장",
            "strategy_adjusted_grade": "A",
            "strategy_trade_allowed": True,
            "rr_pass": True,
            "rr": 10,
            "risk_confidence_score": 100,
            "risk_final_decision": "눌림목 매수 가능",
        }
    )

    assert 0 <= result["position_size_pct"] <= 100


def test_apply_position_sizing_keeps_existing_columns():
    df = pd.DataFrame(
        [
            {
                "symbol": "A",
                "strategy_mode": "박스장",
                "strategy_adjusted_grade": "B",
                "strategy_trade_allowed": True,
                "rr_pass": True,
                "rr": 2.5,
            }
        ]
    )

    out = apply_position_sizing(df)

    assert "symbol" in out.columns
    assert "position_size_pct" in out.columns
