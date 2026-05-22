from core.risk_decision_engine import (
    FINAL_DECISIONS,
    final_risk_decision_engine,
    news_quality_filter,
    overheating_filter,
    rr_filter,
)


def test_final_decision_is_limited_to_five_labels():
    result = final_risk_decision_engine({"base_decision": "강력 매수", "confidence_score": 80})
    assert result["risk_final_decision"] in FINAL_DECISIONS


def test_three_or_more_missing_items_force_watch():
    result = final_risk_decision_engine(
        {
            "base_decision": "눌림목 매수 가능",
            "confidence_score": 90,
            "data_missing_items": ["수급", "거래대금", "밸류에이션"],
        }
    )
    assert result["risk_final_decision"] == "관망 우위"


def test_stop_loss_broken_forces_stop_first():
    result = final_risk_decision_engine(
        {
            "base_decision": "눌림목 매수 가능",
            "current_price": 95,
            "stop_loss": 100,
            "confidence_score": 80,
        }
    )
    assert result["risk_final_decision"] == "손절 우선"


def test_rr_unavailable_fails():
    result = rr_filter({"entry_price": 100, "stop_loss": 0, "take_profit1": 120})
    assert result["rr_pass"] is False


def test_rr_below_1_5_blocks_pullback_buy():
    rr = rr_filter({"entry_price": 100, "stop_loss": 90, "take_profit1": 113})
    result = final_risk_decision_engine(
        {
            "base_decision": "눌림목 매수 가능",
            "confidence_score": 85,
            "rr_result": rr,
            "overheat_result": {"overheat_level": "낮음", "chase_risk": False},
            "news_result": {"news_grade": "A", "sell_the_news_risk": False},
        }
    )
    assert rr["rr"] < 1.5
    assert result["risk_final_decision"] != "눌림목 매수 가능"


def test_rsi_80_and_ma5_gap_20_is_overheated():
    result = overheating_filter({"close": 120, "ma5": 100, "rsi": 80})
    assert result["overheat_level"] in {"높음", "매우 높음"}


def test_news_runup_over_30_sets_sell_the_news_risk():
    result = news_quality_filter(
        {
            "news_title": "공급계약 공시",
            "linked_disclosure": True,
            "price_runup_before_news_pct": 31,
            "volume_confirmed": True,
        }
    )
    assert result["sell_the_news_risk"] is True


def test_confidence_below_60_blocks_pullback_buy():
    result = final_risk_decision_engine(
        {
            "base_decision": "눌림목 매수 가능",
            "confidence_score": 59,
            "rr_result": {"rr": 2.0, "rr_level": "우수", "rr_pass": True},
            "overheat_result": {"overheat_level": "낮음", "chase_risk": False},
            "news_result": {"news_grade": "A", "sell_the_news_risk": False},
        }
    )
    assert result["risk_final_decision"] != "눌림목 매수 가능"


def test_very_high_market_risk_blocks_new_buy():
    result = final_risk_decision_engine(
        {
            "base_decision": "돌파 확인 후 접근",
            "confidence_score": 80,
            "market_risk_level": "매우 높음",
        }
    )
    assert result["risk_final_decision"] not in {"눌림목 매수 가능", "돌파 확인 후 접근"}


def test_risk_confidence_stays_in_0_100():
    result = final_risk_decision_engine(
        {
            "base_decision": "눌림목 매수 가능",
            "confidence_score": 999,
            "data_missing_items": ["a", "b", "c", "d"],
        }
    )
    assert 0 <= result["risk_confidence_score"] <= 100

