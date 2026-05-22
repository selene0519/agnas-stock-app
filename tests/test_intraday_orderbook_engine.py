from __future__ import annotations

import json

import pandas as pd

import core.intraday_orderbook_engine as engine


def test_compute_spread_fields_uses_mid_ref():
    spread = engine._compute_spread_fields(100.0, 100.5)
    assert spread["bid_ask_spread"] == 0.5
    assert round(spread["bid_ask_spread_pct"], 4) == round(0.5 / 100.25 * 100, 4)


def test_normalize_orderbook_data_calculates_ratios():
    out = engine.normalize_orderbook_data({
        "symbol": "ABC",
        "market": "미국주식",
        "bid_total_volume": 200,
        "ask_total_volume": 100,
        "best_bid": 10,
        "best_ask": 10.1,
        "execution_strength": 120,
        "orderbook_data_available": True,
    })
    assert out["orderbook_data_available"] is True
    assert out["bid_ask_ratio"] == 2
    assert round(out["orderbook_imbalance"], 4) == 0.3333
    assert round(out["spread_pct"], 2) == 1.0


def test_orderbook_no_data_does_not_crash():
    out = engine.normalize_orderbook_data({"symbol": "ABC", "market": "미국주식", "orderbook_data_available": False})
    assert out["orderbook_data_available"] is False
    assert out["orderbook_fetch_status"] == "no_data"
    assert out["orderbook_failure_reason"] == "unknown"
    assert out["orderbook_warning"]


def test_kr_symbol_normalization():
    code, valid = engine._normalize_kr_symbol("5930")
    assert code == "005930"
    assert valid is True


def test_us_orderbook_calls_kis_api(monkeypatch):
    monkeypatch.setattr(engine, "_kis_configured", lambda: True)
    monkeypatch.setattr(
        engine,
        "fetch_kis_us_orderbook_api",
        lambda symbol, target_row=None: {
            "ok": True,
            "orderbook_data_source": "kis_us_orderbook",
            "bid_total_volume": 10.0,
            "ask_total_volume": 5.0,
            "best_bid": 100.0,
            "best_ask": 100.5,
            "bid_ask_ratio": 2.0,
            "orderbook_imbalance": 0.33,
        },
    )
    out = engine.fetch_intraday_orderbook("AAPL", "미국주식")
    assert out["orderbook_data_available"] is True
    assert out["orderbook_data_source"] == "kis_us_orderbook"
    assert out["orderbook_fetch_status"] == "success"


def test_empty_api_response_safe():
    out = engine.normalize_orderbook_data({
        "symbol": "005930",
        "market": "한국주식",
        "orderbook_fetch_status": "no_data",
        "orderbook_failure_reason": "api_response_empty",
        "orderbook_data_available": False,
    })
    assert out["orderbook_data_available"] is False
    assert out["orderbook_failure_reason"] == "api_response_empty"


def test_orderbook_snapshot_csv_created(tmp_path, monkeypatch):
    candidate = tmp_path / "swing_candidates_us_A_top3.csv"
    pd.DataFrame([{"symbol": "ABC", "market": "미국주식", "grade": "A"}]).to_csv(candidate, index=False, encoding="utf-8-sig")
    monkeypatch.setattr(engine, "SWING_CANDIDATE_FILES", [candidate])
    path = tmp_path / "orderbook.csv"
    result = engine.save_intraday_orderbook_snapshot(path)
    assert result["status"] == "OK"
    assert path.exists()
    df = pd.read_csv(path)
    assert "orderbook_fetch_status" in df.columns
    assert df["orderbook_failure_reason"].astype(str).str.strip().ne("").all()


def test_orderbook_summary_has_market_split(tmp_path, monkeypatch):
    snapshot = pd.DataFrame([
        {
            "symbol": "005930",
            "market": "한국주식",
            "orderbook_data_available": False,
            "orderbook_fetch_status": "endpoint_not_configured",
            "orderbook_failure_reason": "endpoint_not_configured",
            "orderbook_warning": "KIS 호가 endpoint 미설정",
        },
        {
            "symbol": "AAPL",
            "market": "미국주식",
            "orderbook_data_available": False,
            "orderbook_fetch_status": "unsupported_market",
            "orderbook_failure_reason": "unsupported_market",
            "orderbook_warning": "미국주식 호가 API 미지원",
        },
    ])
    path = tmp_path / "orderbook_summary.json"
    monkeypatch.setattr(engine, "ORDERBOOK_SNAPSHOT_PATH", tmp_path / "missing_orderbook.csv")
    monkeypatch.setattr(engine, "build_intraday_orderbook_snapshot", lambda candidate_files=None: snapshot)
    result = engine.save_intraday_orderbook_summary(path)
    assert result["overall_status"] == "UNSUPPORTED"
    assert result["kr_target_count"] == 1
    assert result["us_target_count"] == 1
    assert "kr_data_available_rate" in result
    assert json.loads(path.read_text(encoding="utf-8"))["orderbook_failure_reason_counts"]
