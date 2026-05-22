from __future__ import annotations

import json
from typing import Any

import pandas as pd

import core.intraday_realtime_engine as engine


def test_normalize_intraday_data_parses_core_fields():
    out = engine.normalize_intraday_data({
        "symbol": "ABC",
        "market": "미국주식",
        "last_price": "$12.30",
        "change_pct": "2.5%",
        "volume": "1,000",
        "turnover": "2,000,000",
        "volume_ratio": "1.4배",
        "intraday_data_source": "unit",
    })
    assert out["symbol"] == "ABC"
    assert out["intraday_data_available"] is True
    assert out["last_price"] == 12.3
    assert out["intraday_volume_ratio"] == 1.4
    assert out["intraday_fetch_status"] == "success"


def test_missing_intraday_data_does_not_crash_and_records_reason():
    out = engine.normalize_intraday_data({"symbol": "ABC", "market": "미국주식", "intraday_data_available": False})
    assert out["intraday_data_available"] is False
    assert out["intraday_fetch_status"] in {"no_data", "market_closed", "unknown"}
    assert out["intraday_failure_reason"]


def test_no_targets_returns_empty_snapshot_and_no_targets_summary(monkeypatch):
    monkeypatch.setattr(engine, "SWING_CANDIDATE_FILES", [])
    monkeypatch.setattr(engine, "HOLDING_FILES", [])
    df = engine.build_intraday_realtime_snapshot(candidate_files=[])
    assert df.empty
    summary = engine._summary_from_snapshot(df)
    assert summary["overall_status"] == "NO_TARGETS"


def test_snapshot_csv_created(tmp_path, monkeypatch):
    candidate = tmp_path / "swing_candidates_us_A_top3.csv"
    pd.DataFrame([{
        "symbol": "ABC",
        "market": "미국주식",
        "grade": "A",
        "last_price": "$10.00",
        "turnover": "1000000",
        "volume_ratio": "1.5배",
        "strategy_trade_allowed": True,
    }]).to_csv(candidate, index=False, encoding="utf-8-sig")
    monkeypatch.setattr(engine, "HOLDING_FILES", [])
    monkeypatch.setattr(engine, "SWING_CANDIDATE_FILES", [candidate])
    path = tmp_path / "snapshot.csv"
    result = engine.save_intraday_realtime_snapshot(path)
    assert result["status"] == "OK"
    assert path.exists()
    saved = pd.read_csv(path)
    assert saved.shape[0] == 1
    assert "intraday_fetch_status" in saved.columns


def test_summary_json_created(tmp_path, monkeypatch):
    snapshot = pd.DataFrame([{
        "symbol": "ABC",
        "market": "미국주식",
        "intraday_data_available": True,
        "intraday_trading_value_ratio": 1.5,
        "intraday_change_pct": 1.0,
        "intraday_warning": "",
        "intraday_fetch_status": "success",
        "intraday_failure_reason": "",
    }])
    path = tmp_path / "summary.json"
    monkeypatch.setattr(engine, "SNAPSHOT_PATH", tmp_path / "missing_snapshot.csv")
    monkeypatch.setattr(engine, "build_intraday_realtime_snapshot", lambda candidate_files=None: snapshot)
    result = engine.save_intraday_realtime_summary(path)
    assert result["overall_status"] == "OK"
    assert json.loads(path.read_text(encoding="utf-8"))["target_count"] == 1


def test_kr_symbol_stays_six_digits(monkeypatch):
    code, valid = engine._normalize_kr_symbol("5930")
    assert code == "005930"
    assert valid is True
    monkeypatch.setattr(engine, "_market_session", lambda market, now=None: "regular")
    monkeypatch.setattr(engine, "_fetch_kis_kr_quote_api", lambda code: {"ok": False, "failure_reason": "api_response_empty"})
    out = engine.fetch_intraday_quote("5930", "한국주식")
    assert out["symbol"] == "005930"


def test_quote_api_empty_retries_then_fallback_from_orderbook(monkeypatch):
    monkeypatch.setattr(engine, "_market_session", lambda market, now=None: "regular")
    calls = {"n": 0}

    def fake_api(code: str) -> dict[str, Any]:
        calls["n"] += 1
        return {"ok": False, "failure_reason": "api_response_empty"}

    monkeypatch.setattr(engine, "_fetch_kis_kr_quote_api", fake_api)
    out = engine.fetch_intraday_quote(
        "131970",
        "한국주식",
        orderbook={"best_bid": 1000, "best_ask": 1100, "orderbook_data_available": True},
    )
    assert calls["n"] == 2
    assert out["quote_fallback_used"] is True
    assert out["quote_partial_available"] is True
    assert out["quote_full_available"] is False
    assert out["intraday_volume"] == 0.0
    assert out["intraday_trading_value"] == 0.0
    assert out["last_price"] == 1050.0


def test_quote_api_success_sets_full_available(monkeypatch):
    monkeypatch.setattr(engine, "_market_session", lambda market, now=None: "regular")
    monkeypatch.setattr(
        engine,
        "_fetch_kis_kr_quote_api",
        lambda code: {
            "ok": True,
            "last_price": 70000.0,
            "intraday_change_pct": 1.2,
            "intraday_volume": 1000.0,
            "intraday_trading_value": 5000000.0,
            "quote_full_available": True,
            "quote_partial_available": False,
            "quote_source": "kis_inquire_price",
        },
    )
    out = engine.fetch_intraday_quote("105560", "한국주식")
    assert out["quote_full_available"] is True
    assert out["intraday_data_available"] is True
    assert out["quote_failure_reason"] == ""


def test_us_quote_kis_success_before_finnhub(monkeypatch):
    monkeypatch.setattr(engine, "_market_session", lambda market, now=None: "regular")
    monkeypatch.setattr(
        engine,
        "fetch_kis_us_quote_api",
        lambda sym, target_row=None: {
            "ok": True,
            "last_price": 180.0,
            "intraday_change_pct": 2.0,
            "intraday_volume": 50000.0,
            "intraday_trading_value": 9000000.0,
            "quote_full_available": True,
            "quote_partial_available": False,
            "quote_source": "kis_us_quote",
            "kis_quote_attempted": True,
            "kis_quote_success": True,
            "kis_quote_error": "",
            "kis_exchange_code": "NAS",
        },
    )
    monkeypatch.setattr(engine, "load_finnhub_api_key", lambda: "should-not-be-called")
    out = engine.fetch_intraday_quote("AAPL", "미국주식")
    assert out["quote_source"] == "kis_us_quote"
    assert out["quote_source_label"] == "KIS 해외 현재가"
    assert out["kis_quote_success"] is True
    assert out["last_price"] == 180.0
    assert out["quote_full_available"] is True
    assert out["intraday_volume"] == 50000.0


def test_us_quote_finnhub_success_after_kis_fail(monkeypatch):
    monkeypatch.setattr(engine, "_market_session", lambda market, now=None: "regular")
    monkeypatch.setattr(
        engine,
        "fetch_kis_us_quote_api",
        lambda sym, target_row=None: {
            "ok": False,
            "failure_reason": "api_response_empty",
            "kis_quote_attempted": True,
            "kis_quote_success": False,
            "kis_quote_error": "EXCD=NAS | msg_cd=OPSQ2001",
            "kis_exchange_code": "NAS",
        },
    )
    monkeypatch.setattr(engine, "load_finnhub_api_key", lambda: "test-key")
    monkeypatch.setattr(engine, "is_finnhub_quote_symbol", lambda s: True)
    monkeypatch.setattr(
        engine,
        "fetch_finnhub_intraday_quote",
        lambda sym, key=None: {
            "ok": True,
            "last_price": 150.0,
            "intraday_change_pct": 1.1,
            "intraday_volume": 0.0,
            "intraday_trading_value": 0.0,
            "quote_full_available": False,
            "quote_partial_available": True,
            "quote_source": "finnhub_quote",
        },
    )
    out = engine.fetch_intraday_quote("AAPL", "미국주식")
    assert out["quote_available"] is True
    assert out["last_price"] == 150.0
    assert out["quote_source"] == "finnhub_quote"
    assert out["kis_quote_success"] is False
    assert out["kis_quote_error"]
    assert "KIS" in str(out.get("intraday_warning", "")) or "Finnhub" in str(out.get("intraday_warning", ""))
    assert out["intraday_volume"] == 0.0


def test_us_quote_api_empty_uses_candidate_fallback(monkeypatch):
    monkeypatch.setattr(engine, "_market_session", lambda market, now=None: "regular")
    monkeypatch.setattr(
        engine,
        "fetch_kis_us_quote_api",
        lambda sym, target_row=None: {
            "ok": False,
            "failure_reason": "api_response_empty",
            "kis_quote_attempted": True,
            "kis_quote_success": False,
            "kis_quote_error": "EXCD=NAS | api_response_empty",
            "kis_exchange_code": "NAS",
        },
    )
    monkeypatch.setattr(engine, "load_finnhub_api_key", lambda: "")
    out = engine.fetch_intraday_quote(
        "AAPL",
        "미국주식",
        target_row={"last_price": 12.5, "intraday_change_pct": 0.5},
    )
    assert out["quote_fallback_used"] is True
    assert out["last_price"] == 12.5
    assert out["quote_source"] == "csv_fallback"
    assert out["quote_failure_reason"] == "fallback_used"


def test_us_quote_api_empty_without_fallback(monkeypatch):
    monkeypatch.setattr(engine, "_market_session", lambda market, now=None: "regular")
    monkeypatch.setattr(
        engine,
        "fetch_kis_us_quote_api",
        lambda sym, target_row=None: {
            "ok": False,
            "failure_reason": "api_response_empty",
            "kis_quote_attempted": True,
            "kis_quote_success": False,
            "kis_quote_error": "EXCD=NAS | rt_cd=1 | msg_cd=OPSQ2001",
            "kis_exchange_code": "NAS",
        },
    )
    monkeypatch.setattr(engine, "load_finnhub_api_key", lambda: "")
    monkeypatch.setattr(
        engine,
        "fetch_finnhub_intraday_quote",
        lambda sym, key=None: {"ok": False, "failure_reason": "api_response_empty"},
    )
    out = engine.fetch_intraday_quote("AAPL", "미국주식")
    assert out["quote_available"] is False
    assert out["quote_source"] == "missing"
    assert out["kis_quote_attempted"] is True
    assert out["kis_quote_success"] is False
    assert out["kis_quote_error"]
    assert out["quote_failure_reason"] == "api_response_empty"
    assert "미국주식 현재가" in str(out["intraday_failure_reason"])


def test_missing_data_report_counts_reasons():
    snapshot = pd.DataFrame([
        {"symbol": "ABC", "intraday_data_available": False, "intraday_fetch_status": "no_data", "intraday_failure_reason": "장중 데이터 미수신"},
        {"symbol": "DEF", "intraday_data_available": False, "intraday_fetch_status": "market_closed", "intraday_failure_reason": "장 마감 또는 장전 시간"},
    ])
    report = engine.build_intraday_missing_data_report(snapshot)
    assert report["intraday_missing_symbols"] == ["ABC", "DEF"]
    assert report["market_closed_count"] == 1
    assert report["intraday_failure_reason_counts"]["장중 데이터 미수신"] == 1
