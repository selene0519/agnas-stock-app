import pandas as pd

from core.review_learning_engine import classify_failure_reason, classify_prediction_result
from core.strategy_performance_engine import summarize_decision_performance


BASE_ROW = {
    "ticker": "TEST",
    "risk_final_decision": "눌림목 매수 가능",
    "preferred_entry": 100,
    "stop_loss": 95,
    "take_profit1": 110,
    "take_profit2": 120,
    "actual_open": 101,
    "actual_high": 112,
    "actual_low": 98,
    "actual_close": 108,
}


def test_tp1_touched_when_high_reaches_target():
    result = classify_prediction_result(BASE_ROW)
    assert result["tp1_touched"] is True


def test_stop_touched_when_low_breaks_stop():
    row = {**BASE_ROW, "actual_high": 104, "actual_low": 94, "actual_close": 96}
    result = classify_prediction_result(row)
    assert result["stop_touched"] is True


def test_buy_decision_stop_without_tp1_is_fail():
    row = {**BASE_ROW, "actual_high": 104, "actual_low": 94, "actual_close": 96}
    result = classify_prediction_result(row)
    assert result["prediction_result"] == "fail"
    assert result["decision_success"] is False


def test_buy_decision_tp1_is_success():
    result = classify_prediction_result(BASE_ROW)
    assert result["prediction_result"] == "success"
    assert result["decision_success"] is True


def test_wait_decision_large_drop_is_loss_avoidance_success():
    row = {
        **BASE_ROW,
        "risk_final_decision": "관망 우위",
        "actual_high": 101,
        "actual_low": 93,
        "actual_close": 94,
    }
    result = classify_prediction_result(row)
    assert result["prediction_result"] == "success"
    assert result["decision_success"] is True


def test_missing_actual_data_is_not_enough_data():
    row = {**BASE_ROW, "actual_high": "", "actual_low": "", "actual_close": ""}
    result = classify_prediction_result(row)
    assert result["prediction_result"] == "not_enough_data"


def test_failure_reason_priority_market_crash_overheat_rr_news():
    row = {
        **BASE_ROW,
        "market_regime": "급락장",
        "actual_close": 90,
        "overheat_level": "매우 높음",
        "rr_level": "부족",
        "sell_the_news_risk": True,
    }
    assert classify_failure_reason(row) == "시장 급락"


def test_failure_reason_overheat_rr_news():
    assert classify_failure_reason({**BASE_ROW, "overheat_level": "높음"}) == "과열 추격"
    assert classify_failure_reason({**BASE_ROW, "rr_level": "불량"}) == "손익비 부족"
    assert classify_failure_reason({**BASE_ROW, "sell_the_news_risk": True}) == "뉴스 선반영"


def test_summarize_decision_performance_success_rate():
    rows = [
        BASE_ROW,
        {**BASE_ROW, "actual_high": 104, "actual_low": 94, "actual_close": 96},
        {**BASE_ROW, "actual_high": "", "actual_low": "", "actual_close": ""},
    ]
    summary = summarize_decision_performance(pd.DataFrame(rows))
    row = summary[summary["risk_final_decision"].eq("눌림목 매수 가능")].iloc[0]
    assert row["total_count"] == 3
    assert row["reviewed_count"] == 2
    assert row["success_count"] == 1
    assert row["fail_count"] == 1
    assert row["success_rate"] == 50.0
