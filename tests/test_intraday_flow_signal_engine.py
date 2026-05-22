from __future__ import annotations

import pandas as pd

from core.intraday_flow_signal_engine import (
    apply_intraday_flow_to_candidates,
    calculate_intraday_flow_score,
    classify_intraday_flow_action,
)


def _row(**kwargs):
    base = {
        "symbol": "ABC",
        "market": "한국주식",
        "flow_data_available": True,
        "intraday_change_pct": 1.5,
        "strategy_trade_allowed": True,
    }
    base.update(kwargs)
    return base


def test_foreign_institution_buy_is_friendly():
    result = classify_intraday_flow_action(_row(foreign_net_buy=1000, institution_net_buy=800, program_net_buy=100))
    assert result["intraday_flow_label"] == "수급 우호"


def test_program_sell_with_weak_price_is_risk():
    result = classify_intraday_flow_action(_row(program_net_buy=-500, intraday_change_pct=-2.0))
    assert result["intraday_flow_label"] == "수급 위험"


def test_individual_overheat_is_chase_caution():
    result = classify_intraday_flow_action(_row(individual_net_buy=900, intraday_change_pct=8.0))
    assert result["intraday_flow_label"] == "추격 주의"


def test_sector_strong_with_stock_up_is_watch():
    result = classify_intraday_flow_action(_row(
        sector_flow_label="섹터 장중 강세",
        sector_intraday_strength_score=75,
        intraday_change_pct=1.2,
        foreign_net_buy=0,
        institution_net_buy=0,
    ))
    assert result["intraday_flow_label"] == "관찰 강화"


def test_no_data_holds_decision():
    result = classify_intraday_flow_action(_row(flow_data_available=False))
    assert result["intraday_flow_label"] == "수급 판단 보류"


def test_c_excluded_stays_blocked():
    candidates = pd.DataFrame([{"symbol": "ABC", "market": "한국주식", "grade": "C", "strategy_trade_allowed": False}])
    flow = pd.DataFrame([{
        "symbol": "ABC",
        "market": "한국주식",
        "foreign_net_buy": 1000,
        "institution_net_buy": 1000,
        "flow_data_available": True,
        "flow_fetch_status": "success",
    }])
    out = apply_intraday_flow_to_candidates(candidates, flow)
    assert out["intraday_flow_label"].iloc[0] == "신규매수 금지 유지"


def test_flow_scores_in_range():
    scores = calculate_intraday_flow_score(_row(foreign_net_buy=9_999_999, institution_net_buy=-9_999_999))
    for key in ["foreign_flow_score", "institution_flow_score", "program_flow_score", "intraday_flow_score"]:
        assert 0 <= scores[key] <= 100
