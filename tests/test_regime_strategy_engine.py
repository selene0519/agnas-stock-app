import pandas as pd

from core.regime_strategy_engine import (
    apply_regime_strategy_to_candidates,
    apply_regime_strategy_to_row,
    detect_strategy_mode,
)


VERY_HIGH = "매우 높음"
PULLBACK = "눌림목 매수 가능"
BREAKOUT = "돌파 확인 후 접근"


def test_very_high_market_risk_is_risk_mode():
    result = detect_strategy_mode({"market_risk_level": VERY_HIGH, "market_score": 5})

    assert result["strategy_mode"] == "위험장"


def test_market_score_three_or_more_is_uptrend():
    result = detect_strategy_mode({"market_score": 3})

    assert result["strategy_mode"] == "상승장"


def test_market_score_minus_four_or_less_is_risk_mode():
    result = detect_strategy_mode({"market_score": -4})

    assert result["strategy_mode"] == "위험장"


def test_risk_mode_disallows_trade():
    result = apply_regime_strategy_to_row({"score": 90, "market_score": -4, "rr_pass": True})

    assert result["strategy_trade_allowed"] is False
    assert result["strategy_adjusted_grade"] == "금지"


def test_downtrend_penalizes_breakout_access():
    result = apply_regime_strategy_to_row(
        {"score": 90, "market_score": -2, "risk_final_decision": BREAKOUT, "rr_pass": True}
    )

    assert result["strategy_mode"] == "하락장"
    assert result["strategy_adjustment_score"] < 0
    assert result["strategy_adjusted_score"] < 90


def test_box_mode_prefers_pullback_over_breakout():
    pullback = apply_regime_strategy_to_row(
        {"score": 70, "market_score": 0, "risk_final_decision": PULLBACK, "rr_pass": True}
    )
    breakout = apply_regime_strategy_to_row(
        {"score": 70, "market_score": 0, "risk_final_decision": BREAKOUT, "rr_pass": True}
    )

    assert pullback["strategy_mode"] == "박스장"
    assert pullback["strategy_adjusted_score"] > breakout["strategy_adjusted_score"]


def test_rr_pass_false_forces_forbidden_grade():
    result = apply_regime_strategy_to_row({"score": 95, "market_score": 3, "rr_pass": False})

    assert result["strategy_adjusted_grade"] == "금지"
    assert result["strategy_trade_allowed"] is False


def test_very_high_overheat_forces_forbidden_grade():
    result = apply_regime_strategy_to_row(
        {"score": 95, "market_score": 3, "rr_pass": True, "overheat_level": VERY_HIGH}
    )

    assert result["strategy_adjusted_grade"] == "금지"
    assert result["strategy_trade_allowed"] is False


def test_strategy_adjusted_score_is_clipped_to_0_100():
    high = apply_regime_strategy_to_row({"score": 130, "market_score": 3, "rr_pass": True})
    low = apply_regime_strategy_to_row({"score": -20, "market_score": -2, "rr_pass": True})

    assert 0 <= high["strategy_adjusted_score"] <= 100
    assert 0 <= low["strategy_adjusted_score"] <= 100


def test_existing_columns_are_not_removed():
    candidate_df = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "grade": "B",
                "score": 70,
                "risk_final_decision": PULLBACK,
                "rr_pass": True,
                "custom_col": "keep",
            }
        ]
    )

    out = apply_regime_strategy_to_candidates(candidate_df, {"market_score": 0})

    assert "custom_col" in out.columns
    assert out.loc[0, "custom_col"] == "keep"
    assert "strategy_adjusted_score" in out.columns


def test_regime_strategy_does_not_promote_existing_excluded_candidate():
    candidate_df = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "grade": "C",
                "score": 95,
                "risk_final_decision": PULLBACK,
                "rr_pass": True,
            }
        ]
    )

    out = apply_regime_strategy_to_candidates(candidate_df, {"market_score": 3})

    assert out.loc[0, "strategy_adjusted_grade"] == "A"
    assert out.loc[0, "grade"] == "C"


def test_c_or_forbidden_candidate_trade_allowed_is_false():
    candidate_df = pd.DataFrame(
        [
            {"symbol": "C1", "grade": "C", "score": 90, "risk_final_decision": PULLBACK, "rr_pass": True},
            {"symbol": "F1", "grade": "B", "score": 90, "risk_final_decision": PULLBACK, "rr_pass": False},
        ]
    )

    out = apply_regime_strategy_to_candidates(candidate_df, {"market_score": 0})

    assert bool(out.loc[0, "strategy_trade_allowed"]) is False
    assert bool(out.loc[1, "strategy_trade_allowed"]) is False


def test_risk_final_decision_falls_back_from_final_decision():
    candidate_df = pd.DataFrame(
        [
            {
                "symbol": "PB",
                "grade": "B",
                "score": 70,
                "risk_final_decision": "",
                "final_decision": "성장 관찰 후보·눌림 대기·돌파 확인 후 접근",
                "rr_pass": True,
            }
        ]
    )

    out = apply_regime_strategy_to_candidates(candidate_df, {"market_score": 0})

    assert out.loc[0, "risk_final_decision"] == BREAKOUT


def test_strategy_reasons_are_not_default_box_only():
    result = apply_regime_strategy_to_row(
        {"score": 70, "market_score": 0, "risk_final_decision": PULLBACK, "rr_pass": True}
    )

    joined = " / ".join(result["strategy_reasons"])
    assert joined != "default box"
    assert "박스장" in joined
