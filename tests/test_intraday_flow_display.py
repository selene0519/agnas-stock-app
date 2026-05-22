"""수급·프로그램 화면 표시 — 미지원/미수신 vs 실제 0 구분."""
from __future__ import annotations

import pandas as pd

import app


def test_us_flow_unavailable_shows_mijiwon_not_zero():
    raw = pd.DataFrame([{
        "symbol": "ASML",
        "market": "미국주식",
        "foreign_net_buy": 0.0,
        "institution_net_buy": 0.0,
        "individual_net_buy": 0.0,
        "program_net_buy": 0.0,
        "flow_data_available": False,
        "intraday_flow_label": "",
        "intraday_flow_warning": "",
    }])
    out = app.prepare_intraday_flow_display(raw)
    assert out.iloc[0]["외국인 수급"] == "미지원"
    assert out.iloc[0]["수급 상태"] == "수급 데이터 제한"


def test_kr_flow_unavailable_shows_misusin():
    raw = pd.DataFrame([{
        "symbol": "005930",
        "market": "한국주식",
        "foreign_net_buy": 0.0,
        "flow_data_available": False,
    }])
    out = app.prepare_intraday_flow_display(raw)
    assert out.iloc[0]["외국인 수급"] == "미수신"
    assert out.iloc[0]["수급 상태"] == "수급 판단 보류"


def test_flow_available_zero_shows_numeric():
    raw = pd.DataFrame([{
        "symbol": "005930",
        "market": "한국주식",
        "foreign_net_buy": 0.0,
        "flow_data_available": True,
        "intraday_flow_label": "중립",
        "intraday_flow_warning": "",
    }])
    out = app.prepare_intraday_flow_display(raw)
    assert out.iloc[0]["외국인 수급"] in {"0", "0.0", "0.00"}
