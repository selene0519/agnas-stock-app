"""미래 확률표·예측 검증 화면 표시 단위 테스트."""

from __future__ import annotations



import pandas as pd



import app





def test_prepare_future_probability_display_korean_columns_and_percent():

    raw = pd.DataFrame([{

        "symbol": "005930",

        "name": "삼성전자",

        "market": "한국주식",

        "prob_up_1d": 52.5,

        "prob_up_3d": 54.1,

        "prob_up_5d": 55.73,

        "prob_up_10d": 58.0,

        "prob_tp1_5d": 48.2,

        "prob_stop_5d": 32.1,

        "expected_return_5d": 0.87,

        "forecast_label": "관망 우위",

        "forecast_confidence": "보통",

        "risk_final_decision": "관망 우위",

        "entry": 70000,

        "stop": 68000,

        "tp1": 75000,

    }])

    out = app.prepare_future_probability_display(raw)

    assert list(out.columns) == [

        "종목코드", "종목명", "시장", "최종 판단", "예측 판단", "예측 신뢰도",

        "1일 상승확률", "3일 상승확률", "5일 상승확률", "10일 상승확률",

        "예상 진입가", "예상 손절가", "예상 목표가", "예상 시초가", "예상 종가",

        "5일 목표가 도달확률", "5일 손절위험", "5일 기대수익률",

    ]

    assert out.iloc[0]["5일 상승확률"] == "55.73%"

    assert out.iloc[0]["5일 기대수익률"] == "+0.87%"

    assert out.iloc[0]["예측 신뢰도"] == "보통"

    assert "70,000" in out.iloc[0]["예상 진입가"]





def test_prepare_future_probability_display_empty():

    assert app.prepare_future_probability_display(pd.DataFrame()).empty





def test_enrich_future_probability_merges_predictions():

    candidates = pd.DataFrame([{

        "symbol": "005930",

        "name": "삼성전자",

        "market": "한국주식",

        "prob_up_5d": 55.0,

        "entry": "",

        "stop": "",

        "tp1": "",

    }])

    preds = pd.DataFrame([{

        "ticker": "005930",

        "market": "한국주식",

        "target_date": "2026-05-19",

        "created_at": "2026-05-19 09:00:00",

        "pred_open_mid": 71000,

        "pred_close_mid": 72000,

        "preferred_entry": 70500,

        "stop_loss": 69000,

        "take_profit1": 74000,

    }])

    enriched = app.enrich_future_probability_with_predictions(candidates, pred_log=preds)

    assert enriched.iloc[0]["preferred_entry"] == 70500

    assert enriched.iloc[0]["pred_open_mid"] == 71000





def test_prepare_prediction_validation_display_from_error_report():

    raw = pd.DataFrame([{

        "ticker": "005930",

        "market": "한국주식",

        "prediction_date": "2026-05-18",

        "target_date": "2026-05-19",

        "predicted_open_mid": 71000,

        "actual_open": 71200,

        "open_error_pct": 0.28,

        "predicted_close_mid": 72000,

        "actual_close": 71500,

        "close_error_pct": -0.69,

        "preferred_entry": 70500,

        "entry_touched": 1,

        "stop_loss": 69000,

        "stop_touched": 0,

        "take_profit1": 74000,

        "tp1_touched": 0,

        "direction_hit": 1,

        "decision_result": "관망 유지",

    }])

    out = app.prepare_prediction_validation_display(raw)

    assert "종목코드" in out.columns

    assert out.iloc[0]["방향 예측 일치 여부"] == "일치"

    assert out.iloc[0]["실제 저가/고가 기준 진입 가능 여부"] == "터치"

    assert "+0.28%" in out.iloc[0]["시초가 오차율"]





def test_format_prob_percent_cell_handles_fraction():

    assert app._format_prob_percent_cell(0.5573) == "55.73%"

