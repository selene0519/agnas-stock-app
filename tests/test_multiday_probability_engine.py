import pandas as pd

from core.multiday_probability_engine import (
    apply_multiday_probability,
    calculate_multiday_probability,
)


PROB_COLS = [
    "prob_up_1d",
    "prob_up_3d",
    "prob_up_5d",
    "prob_up_10d",
    "prob_down_5d",
    "prob_tp1_5d",
    "prob_stop_5d",
    "prob_tp_first",
    "prob_stop_first",
    "prob_market_outperform_5d",
    "prob_sector_outperform_5d",
]


def _base_row(**overrides):
    row = {
        "strategy_mode": "상승장",
        "strategy_adjusted_grade": "B",
        "strategy_trade_allowed": True,
        "risk_confidence_score": 75,
        "stock_attractiveness_score": 65,
        "trade_fit_score": 65,
        "entry_position_score": 65,
        "rr": 2.0,
        "rr_pass": True,
        "entry": 100,
        "stop": 94,
        "tp1": 112,
        "last_price": 100,
        "volume_ratio": 1.4,
        "actual_review_ready": True,
    }
    row.update(overrides)
    return row


def test_probability_values_are_0_100():
    result = calculate_multiday_probability(_base_row())

    for col in PROB_COLS:
        assert 0 <= result[col] <= 100


def test_rr_pass_false_increases_stop_probability():
    good = calculate_multiday_probability(_base_row(rr=2.0, rr_pass=True))
    bad = calculate_multiday_probability(_base_row(rr=1.0, rr_pass=False))

    assert bad["prob_stop_5d"] > good["prob_stop_5d"]


def test_risk_mode_does_not_return_buy_label():
    result = calculate_multiday_probability(
        _base_row(strategy_mode="위험장", strategy_adjusted_grade="A", strategy_trade_allowed=False)
    )

    assert result["forecast_label"] != "매수 가능 후보"


def test_high_relative_strength_in_risk_mode_can_be_strong_watch():
    result = calculate_multiday_probability(
        _base_row(
            strategy_mode="위험장",
            strategy_trade_allowed=False,
            aggressive_score=88,
            market_relative_strength=4,
            sector_relative_strength=2,
            weak_market_leader_flag=True,
        )
    )

    assert result["forecast_label"] in {"강한 관찰 후보", "시장 약세 속 역행 후보"}


def test_chase_risk_increases_stop_probability_and_blocks_label():
    normal = calculate_multiday_probability(_base_row(chase_risk=False))
    chase = calculate_multiday_probability(_base_row(chase_risk=True))

    assert chase["prob_stop_5d"] > normal["prob_stop_5d"]
    assert chase["forecast_label"] == "추격매수 금지 후보"


def test_a_grade_has_higher_basic_prob_up_5d_than_b_or_c():
    a = calculate_multiday_probability(_base_row(strategy_adjusted_grade="A"))
    b = calculate_multiday_probability(_base_row(strategy_adjusted_grade="B"))
    c = calculate_multiday_probability(_base_row(strategy_adjusted_grade="C", strategy_trade_allowed=False))

    assert a["prob_up_5d"] > b["prob_up_5d"] > c["prob_up_5d"]


def test_forecast_confidence_is_valid_choice():
    result = calculate_multiday_probability(_base_row())

    assert result["forecast_confidence"] in {"낮음", "보통", "높음"}


def test_data_shortage_sets_low_confidence():
    result = calculate_multiday_probability({"symbol": "ABC"})

    assert result["forecast_confidence"] == "낮음"


def test_apply_multiday_probability_keeps_existing_columns():
    df = pd.DataFrame([{"symbol": "ABC", **_base_row()}])

    out = apply_multiday_probability(df)

    assert "symbol" in out.columns
    assert "prob_up_5d" in out.columns


def test_forecast_warnings_has_default_text_when_no_warning():
    result = calculate_multiday_probability(_base_row())

    assert result["forecast_warnings"]
    assert result["forecast_warnings"] != [""]


def test_excluded_high_probability_explains_immediate_buy_block():
    result = calculate_multiday_probability(
        _base_row(
            strategy_adjusted_grade="C",
            strategy_trade_allowed=False,
            stock_attractiveness_score=95,
            trade_fit_score=90,
            entry_position_score=90,
            aggressive_score=90,
        )
    )

    assert result["prob_up_5d"] >= 55
    assert result["forecast_label"] == "완전 제외 후보"
    assert any("즉시매수 금지" in warning or "방어 필터 우선" in warning for warning in result["forecast_warnings"])
