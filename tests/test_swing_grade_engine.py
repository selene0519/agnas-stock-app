from __future__ import annotations

import pandas as pd

from app import enforce_strict_swing_grades, setup_grade_engine


BASE_PROFILE = {
    "rr": 2.2,
    "rr_pass": True,
    "risk_confidence_score": 75,
    "market_risk_level": "보통",
    "overheat_level": "보통",
    "chase_risk": False,
    "sell_the_news_risk": False,
    "risk_final_decision": "눌림목 매수 가능",
    "prediction_result": "success",
    "decision_success": "True",
    "failure_reason": "",
}


def test_rr_below_2_cannot_be_a_grade():
    override, c_reasons, a_missing = setup_grade_engine({}, {**BASE_PROFILE, "rr": 1.99})

    assert override is None
    assert not c_reasons
    assert "rr >= 2.0" in a_missing


def test_rr_pass_false_is_excluded():
    override, c_reasons, _ = setup_grade_engine({}, {**BASE_PROFILE, "rr_pass": False})

    assert override == "C"
    assert "rr_pass=False" in c_reasons


def test_low_risk_confidence_cannot_be_a_grade():
    override, c_reasons, a_missing = setup_grade_engine({}, {**BASE_PROFILE, "risk_confidence_score": 69})

    assert override is None
    assert not c_reasons
    assert "risk_confidence_score 70 이상" in a_missing


def test_very_high_overheat_is_excluded():
    override, c_reasons, _ = setup_grade_engine({}, {**BASE_PROFILE, "overheat_level": "매우 높음"})

    assert override == "C"
    assert "overheat_level=매우 높음" in c_reasons


def test_very_high_market_risk_is_excluded():
    override, c_reasons, _ = setup_grade_engine({}, {**BASE_PROFILE, "market_risk_level": "매우 높음"})

    assert override == "C"
    assert "market_risk_level=매우 높음" in c_reasons


def test_a_grade_csv_filter_removes_rr_below_2():
    df = pd.DataFrame(
        [
            {**BASE_PROFILE, "symbol": "LOWRR", "grade": "A", "score": 90, "rr": 1.91},
            {**BASE_PROFILE, "symbol": "GOOD", "grade": "A", "score": 91, "rr": 2.1},
        ]
    )

    out = enforce_strict_swing_grades(df)
    a_rows = out[out["grade"].astype(str).eq("A")]

    assert not a_rows.empty
    assert pd.to_numeric(a_rows["rr"], errors="coerce").ge(2.0).all()
    assert out.loc[out["symbol"].eq("LOWRR"), "grade"].iloc[0] == "B"
    for col in ["trade_allowed", "high_probability_candidate", "실전등급", "실전등급점수", "실전등급사유", "실전경고"]:
        assert col in out.columns
