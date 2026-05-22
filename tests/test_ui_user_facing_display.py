"""사용자 화면용 라벨·표시 변환 테스트."""
from __future__ import annotations

import pandas as pd

import app


def test_format_user_facing_status_ok_with_notice():
    assert app.format_user_facing_status_label("OK_WITH_NOTICE") == "정상 · 주의 있음"


def test_historical_display_hides_condition_key():
    raw = pd.DataFrame([{
        "symbol": "005930",
        "name": "삼성",
        "market": "한국주식",
        "historical_condition_key": "score_80|rr_2.0|entry_near",
        "historical_sample_count": 0,
    }])
    out = app.prepare_historical_pattern_display(raw)
    assert "condition_key" not in " ".join(out.columns)
    assert out.iloc[0]["유사조건 상태"] == "표본 부족"


def test_chase_risk_no_event_label():
    raw = pd.DataFrame([{
        "symbol": "ASML",
        "name": "ASML",
        "market": "미국주식",
        "has_major_event": "N",
        "event_type": "NORMAL",
        "event_result": "unknown",
        "event_timing": "none",
        "market_reaction_score": 55,
        "sector_reaction_score": 72,
        "intraday_chase_risk": "true",
        "risk_final_decision": "관망 우위",
    }])
    out = app.prepare_chase_risk_display(raw)
    assert out.iloc[0]["이벤트 상태"] == "특이 이벤트 없음"
    assert out.iloc[0]["시장 반응"] == "보통"
    assert out.iloc[0]["섹터 반응"] == "양호"
    assert "has_major_event" not in " ".join(out.columns)


def test_api_warning_usable_label():
    api_q = {
        "overall_status": "WARNING",
        "kis_available": True,
        "dart_available": True,
        "finnhub_available": True,
        "sec_available": True,
        "missing_env_keys": [],
        "fallback_used": False,
    }
    assert app._api_overall_user_label(api_q) == "조회 가능 · 주의 있음"


def test_intraday_rate_market_closed_label():
    cov = {"target_count": 42, "market_closed_count": 42}
    label = app.format_intraday_reception_rate(0.0, cov)
    assert "장마감" in label
    assert "0.0%" in label
