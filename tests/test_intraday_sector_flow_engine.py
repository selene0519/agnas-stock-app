from __future__ import annotations

import json

import pandas as pd

import core.intraday_sector_flow_engine as engine


def test_sector_up_ratio_and_avg_change():
    candidates = pd.DataFrame([
        {"symbol": "A", "market": "한국주식", "sector": "반도체", "intraday_change_pct": 2.0, "intraday_trading_value_ratio": 1.5},
        {"symbol": "B", "market": "한국주식", "sector": "반도체", "intraday_change_pct": -1.0, "intraday_trading_value_ratio": 1.2},
        {"symbol": "C", "market": "한국주식", "sector": "반도체", "intraday_change_pct": 1.0, "intraday_trading_value_ratio": 1.3},
    ])
    out = engine.calculate_sector_intraday_strength(candidates)
    row = out.iloc[0]
    assert round(float(row["sector_up_ratio"]), 2) == 0.67
    assert round(float(row["sector_avg_intraday_change_pct"]), 2) == 0.67
    assert 0 <= int(row["sector_money_flow_score"]) <= 100


def test_small_sample_warning():
    candidates = pd.DataFrame([
        {"symbol": "A", "market": "한국주식", "sector": "바이오", "intraday_change_pct": 1.0, "intraday_trading_value_ratio": 1.0},
    ])
    out = engine.calculate_sector_intraday_strength(candidates)
    assert out.iloc[0]["sector_flow_label"] == "표본 부족"


def test_sector_report_and_summary(tmp_path, monkeypatch):
    candidate = tmp_path / "swing_candidates_kr_A_top3.csv"
    pd.DataFrame([
        {"symbol": "005930", "market": "한국주식", "grade": "A", "sector": "반도체",
         "intraday_price_change_pct": 1.5, "intraday_trading_value_ratio": 1.4},
        {"symbol": "000660", "market": "한국주식", "grade": "A", "sector": "반도체",
         "intraday_price_change_pct": 0.5, "intraday_trading_value_ratio": 1.1},
    ]).to_csv(candidate, index=False, encoding="utf-8-sig")
    monkeypatch.setattr(engine, "SWING_CANDIDATE_FILES", [candidate])
    report_path = tmp_path / "sector.csv"
    summary_path = tmp_path / "sector_summary.json"
    report = engine.save_intraday_sector_flow_report(report_path)
    assert report["status"] == "OK"
    summary = engine.save_intraday_sector_flow_summary(summary_path)
    assert summary["sector_count"] >= 1
    assert json.loads(summary_path.read_text(encoding="utf-8"))["overall_status"]
