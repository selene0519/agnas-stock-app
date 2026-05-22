from __future__ import annotations

import json

import pandas as pd

import core.intraday_data_coverage_diagnosis as diagnosis
from core.swing_candidate_io import read_swing_candidate_csv


def _write_snapshots(tmp_path, monkeypatch):
    quote = pd.DataFrame([
        {
            "symbol": "005930",
            "market": "한국주식",
            "intraday_data_available": "True",
            "intraday_fetch_status": "success",
            "intraday_failure_reason": "",
            "intraday_market_session": "regular",
        },
        {
            "symbol": "AAPL",
            "market": "미국주식",
            "intraday_data_available": "False",
            "intraday_fetch_status": "market_closed",
            "intraday_failure_reason": "market_closed",
            "intraday_market_session": "closed",
        },
    ])
    orderbook = pd.DataFrame([
        {
            "symbol": "005930",
            "market": "한국주식",
            "orderbook_data_available": "True",
            "orderbook_fetch_status": "success",
            "orderbook_failure_reason": "",
        },
        {
            "symbol": "AAPL",
            "market": "미국주식",
            "orderbook_data_available": "False",
            "orderbook_fetch_status": "unsupported_market",
            "orderbook_failure_reason": "unsupported_market",
        },
    ])
    flow = pd.DataFrame([
        {
            "symbol": "005930",
            "market": "한국주식",
            "flow_data_available": "True",
            "flow_fetch_status": "success",
            "flow_failure_reason": "",
        },
        {
            "symbol": "AAPL",
            "market": "미국주식",
            "flow_data_available": "False",
            "flow_fetch_status": "unsupported_market",
            "flow_failure_reason": "unsupported_market",
        },
    ])
    sector = pd.DataFrame([
        {"sector": "반도체", "sector_target_count": "3", "sector_intraday_strength_score": "60"},
    ])
    candidate = tmp_path / "swing_candidates_kr_A_top3.csv"
    pd.DataFrame([
        {"symbol": "005930", "market": "한국주식", "grade": "A", "sector": "반도체", "strategy_trade_allowed": "False"},
    ]).to_csv(candidate, index=False, encoding="utf-8-sig")
    c_candidate = tmp_path / "swing_candidates_us_C_excluded.csv"
    pd.DataFrame([
        {"symbol": "AAPL", "market": "미국주식", "grade": "C", "strategy_trade_allowed": "False", "intraday_entry_confirmed": "False"},
    ]).to_csv(c_candidate, index=False, encoding="utf-8-sig")

    paths = {
        "realtime_snapshot": tmp_path / "intraday_realtime_snapshot.csv",
        "orderbook_snapshot": tmp_path / "intraday_orderbook_snapshot.csv",
        "flow_snapshot": tmp_path / "intraday_flow_snapshot.csv",
        "sector_report": tmp_path / "intraday_sector_flow_report.csv",
        "realtime_summary": tmp_path / "intraday_realtime_summary.json",
        "orderbook_summary": tmp_path / "intraday_orderbook_summary.json",
        "flow_summary": tmp_path / "intraday_flow_summary.json",
        "sector_summary": tmp_path / "intraday_sector_flow_summary.json",
    }
    quote.to_csv(paths["realtime_snapshot"], index=False, encoding="utf-8-sig")
    orderbook.to_csv(paths["orderbook_snapshot"], index=False, encoding="utf-8-sig")
    flow.to_csv(paths["flow_snapshot"], index=False, encoding="utf-8-sig")
    sector.to_csv(paths["sector_report"], index=False, encoding="utf-8-sig")
    for p in paths.values():
        if p.suffix == ".json":
            p.write_text(json.dumps({"overall_status": "OK", "target_count": 2}), encoding="utf-8")

    monkeypatch.setattr(diagnosis, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(diagnosis, "COVERAGE_DIAGNOSIS_JSON", tmp_path / "intraday_data_coverage_diagnosis.json")
    monkeypatch.setattr(diagnosis, "COVERAGE_DIAGNOSIS_CSV", tmp_path / "intraday_data_coverage_diagnosis.csv")
    monkeypatch.setattr(diagnosis, "UNSUPPORTED_SYMBOLS_CSV", tmp_path / "intraday_unsupported_symbols.csv")
    monkeypatch.setattr(diagnosis, "IMPROVEMENT_SUGGESTIONS_JSON", tmp_path / "intraday_data_improvement_suggestions.json")
    for key, path in paths.items():
        monkeypatch.setitem(diagnosis.REPORT_PATHS, key, path)
    monkeypatch.setitem(diagnosis.CANDIDATE_PATHS, "kr_a", candidate)
    monkeypatch.setitem(diagnosis.CANDIDATE_PATHS, "us_c", c_candidate)
    return paths


def test_summarize_orderbook_flow_reception_counts():
    ob = pd.DataFrame([
        {"market": "한국주식", "orderbook_data_available": "True"},
        {"market": "한국주식", "orderbook_data_available": "False", "orderbook_failure_reason": "api_response_empty"},
        {
            "market": "미국주식",
            "orderbook_data_available": "False",
            "kis_us_orderbook_attempted": "True",
            "orderbook_failure_reason": "no_orderbook_fields",
        },
    ])
    fl = pd.DataFrame([
        {"market": "한국주식", "flow_data_available": "True", "kr_flow_attempted": "True"},
        {"market": "한국주식", "flow_data_available": "False", "flow_failure_reason": "endpoint_not_configured", "kr_flow_attempted": "True"},
        {"market": "미국주식", "flow_data_available": "True"},
    ])
    stats = diagnosis.summarize_orderbook_flow_reception(ob, fl)
    assert stats["kr_orderbook_success"] == 1
    assert stats["kr_orderbook_fail"] == 1
    assert stats["us_orderbook_no_fields"] == 1
    assert stats["kr_flow_success"] == 1
    assert stats["kr_flow_endpoint_not_configured"] == 1
    assert stats["us_alt_flow_success"] == 1


def test_build_coverage_table_from_snapshots(tmp_path, monkeypatch):
    _write_snapshots(tmp_path, monkeypatch)
    reports = diagnosis.load_intraday_reports()
    df = diagnosis.build_symbol_coverage_table(reports)
    assert len(df) == 2
    assert "quote_available" in df.columns
    kr = df.loc[df["symbol"] == "005930"].iloc[0]
    assert str(kr["quote_available"]).lower() in {"true", "1"}
    assert kr["recoverable"] == "False"
    assert kr["likely_root_cause"] == "data_available"
    assert diagnosis.is_recoverable_issue(kr.to_dict()) is False


def test_all_three_available_not_counted_as_recoverable_issue():
    row = {
        "quote_available": True,
        "quote_full_available": True,
        "quote_partial_available": False,
        "orderbook_available": True,
        "flow_available": True,
        "sector_flow_available": True,
        "market": "한국주식",
        "market_session": "regular",
        "symbol": "105560",
        "normalized_symbol": "105560",
        "symbol_format_valid": True,
    }
    out = diagnosis.classify_missing_reason(row)
    assert out["recoverable"] == "False"
    assert out["likely_root_cause"] == "data_available"
    assert diagnosis.is_recoverable_issue({**row, **out}) is False


def test_quote_only_missing_is_recoverable_quote_issue():
    row = {
        "quote_available": False,
        "orderbook_available": True,
        "flow_available": True,
        "sector_flow_available": False,
        "market": "한국주식",
        "symbol": "131970",
        "normalized_symbol": "131970",
        "symbol_format_valid": True,
        "quote_failure_reason": "api_response_empty",
        "orderbook_failure_reason": "",
        "flow_failure_reason": "",
        "quote_status": "no_data",
        "orderbook_status": "success",
        "flow_status": "success",
        "market_session": "regular",
    }
    out = diagnosis.classify_missing_reason(row)
    assert out["likely_root_cause"] == "quote_api_response_empty"
    assert out["recoverable"] == "True"
    assert "quote API" in out["recommended_action"]


def test_recoverable_issue_count_excludes_healthy_rows(tmp_path, monkeypatch):
    _write_snapshots(tmp_path, monkeypatch)
    quote = pd.read_csv(diagnosis.REPORT_PATHS["realtime_snapshot"])
    extra = pd.DataFrame([
        {
            "symbol": "105560",
            "market": "한국주식",
            "intraday_data_available": "True",
            "intraday_fetch_status": "success",
            "intraday_failure_reason": "",
            "intraday_market_session": "regular",
        },
        {
            "symbol": "131970",
            "market": "한국주식",
            "intraday_data_available": "False",
            "intraday_fetch_status": "no_data",
            "intraday_failure_reason": "API 응답 없음",
            "intraday_market_session": "regular",
        },
    ])
    quote = pd.concat([quote, extra], ignore_index=True)
    quote.to_csv(diagnosis.REPORT_PATHS["realtime_snapshot"], index=False, encoding="utf-8-sig")
    ob = pd.read_csv(diagnosis.REPORT_PATHS["orderbook_snapshot"])
    flow = pd.read_csv(diagnosis.REPORT_PATHS["flow_snapshot"])
    for sym, include_ob in [("105560", True), ("131970", False)]:
        flow = pd.concat([flow, pd.DataFrame([{
            "symbol": sym, "market": "한국주식",
            "flow_data_available": "True", "flow_fetch_status": "success", "flow_failure_reason": "",
        }])], ignore_index=True)
        if include_ob:
            ob = pd.concat([ob, pd.DataFrame([{
                "symbol": sym, "market": "한국주식",
                "orderbook_data_available": "True", "orderbook_fetch_status": "success", "orderbook_failure_reason": "",
                "best_bid": "50000", "best_ask": "50100",
            }])], ignore_index=True)
    ob.to_csv(diagnosis.REPORT_PATHS["orderbook_snapshot"], index=False, encoding="utf-8-sig")
    flow.to_csv(diagnosis.REPORT_PATHS["flow_snapshot"], index=False, encoding="utf-8-sig")
    result = diagnosis.save_intraday_data_coverage_diagnosis()
    assert result["recoverable_issue_count"] == 1
    healthy = pd.read_csv(diagnosis.COVERAGE_DIAGNOSIS_CSV)
    row_105560 = healthy.loc[healthy["symbol"].astype(str) == "105560"].iloc[0]
    assert str(row_105560["recoverable"]).lower() in {"false", "0"}
    assert row_105560["likely_root_cause"] == "data_available"
    assert "data_available" not in result.get("root_cause_counts", {})


def test_quote_partial_fallback_not_recoverable_issue():
    row = {
        "quote_available": True,
        "quote_partial_available": True,
        "quote_full_available": False,
        "orderbook_available": True,
        "flow_available": True,
        "market": "한국주식",
        "quote_source": "fallback_orderbook_mid",
    }
    out = diagnosis.classify_missing_reason(row)
    assert out["likely_root_cause"] == "quote_partial_fallback"
    assert out["recoverable"] == "False"
    assert diagnosis.is_recoverable_issue({**row, **out}) is False


def test_unsupported_market_not_recoverable(tmp_path, monkeypatch):
    _write_snapshots(tmp_path, monkeypatch)
    df = diagnosis.build_symbol_coverage_table()
    us = df.loc[df["symbol"] == "AAPL"].iloc[0]
    assert us["orderbook_failure_reason"] == "unsupported_market"
    classified = diagnosis.classify_missing_reason(us.to_dict())
    assert classified["recoverable"] == "False"
    assert diagnosis.classify_quote_root_cause(us.to_dict()) == "market_closed"
    assert diagnosis.classify_orderbook_root_cause(us.to_dict()) == "market_closed"


def test_us_quote_failure_separate_from_unsupported_market():
    row = {
        "quote_available": False,
        "quote_full_available": False,
        "quote_partial_available": False,
        "orderbook_available": False,
        "flow_available": False,
        "market": "미국주식",
        "market_session": "regular",
        "symbol": "AAPL",
        "symbol_format_valid": True,
        "quote_failure_reason": "api_response_empty",
        "orderbook_failure_reason": "unsupported_market",
        "flow_failure_reason": "unsupported_market",
        "quote_status": "no_data",
        "orderbook_status": "unsupported_market",
        "flow_status": "unsupported_market",
    }
    classified = diagnosis.classify_missing_reason(row)
    assert classified["likely_root_cause"] == "us_quote_api_response_empty"
    assert classified["recoverable"] == "True"
    assert diagnosis.classify_quote_root_cause(row) == "us_quote_api_response_empty"
    assert diagnosis.classify_orderbook_root_cause(row) == "unsupported_market"
    assert diagnosis.classify_flow_root_cause(row) == "unsupported_market"


def test_typed_root_cause_counts_in_summary(tmp_path, monkeypatch):
    _write_snapshots(tmp_path, monkeypatch)
    quote = pd.read_csv(diagnosis.REPORT_PATHS["realtime_snapshot"])
    extra = pd.DataFrame([
        {
            "symbol": "MSFT",
            "market": "미국주식",
            "intraday_data_available": "False",
            "intraday_fetch_status": "no_data",
            "intraday_failure_reason": "미국주식 현재가 API 응답 없음",
            "quote_failure_reason": "api_response_empty",
            "intraday_market_session": "regular",
        },
    ])
    quote = pd.concat([quote, extra], ignore_index=True)
    quote.to_csv(diagnosis.REPORT_PATHS["realtime_snapshot"], index=False, encoding="utf-8-sig")
    ob = pd.read_csv(diagnosis.REPORT_PATHS["orderbook_snapshot"])
    flow = pd.read_csv(diagnosis.REPORT_PATHS["flow_snapshot"])
    for sym in ["MSFT"]:
        ob = pd.concat([ob, pd.DataFrame([{
            "symbol": sym, "market": "미국주식",
            "orderbook_data_available": "False", "orderbook_fetch_status": "unsupported_market",
            "orderbook_failure_reason": "unsupported_market",
        }])], ignore_index=True)
        flow = pd.concat([flow, pd.DataFrame([{
            "symbol": sym, "market": "미국주식",
            "flow_data_available": "False", "flow_fetch_status": "unsupported_market",
            "flow_failure_reason": "unsupported_market",
        }])], ignore_index=True)
    ob.to_csv(diagnosis.REPORT_PATHS["orderbook_snapshot"], index=False, encoding="utf-8-sig")
    flow.to_csv(diagnosis.REPORT_PATHS["flow_snapshot"], index=False, encoding="utf-8-sig")
    result = diagnosis.save_intraday_data_coverage_diagnosis()
    assert result["quote_root_cause_counts"].get("us_quote_api_response_empty", 0) >= 1
    assert result["orderbook_root_cause_counts"].get("unsupported_market", 0) >= 1
    assert result["flow_root_cause_counts"].get("unsupported_market", 0) >= 1
    assert "unsupported_market" not in result.get("quote_root_cause_counts", {})


def test_invalid_symbol_recoverable():
    row = {
        "quote_available": False,
        "orderbook_available": False,
        "flow_available": False,
        "symbol_format_valid": False,
        "market": "한국주식",
        "market_session": "regular",
        "quote_failure_reason": "invalid_symbol",
        "orderbook_failure_reason": "",
        "flow_failure_reason": "",
        "quote_status": "invalid_symbol",
        "orderbook_status": "",
        "flow_status": "",
        "sector_flow_available": False,
    }
    out = diagnosis.classify_missing_reason(row)
    assert out["likely_root_cause"] == "invalid_symbol"
    assert out["recoverable"] in {"True", "Unknown"}


def test_market_closed_is_notice_not_error(tmp_path, monkeypatch):
    _write_snapshots(tmp_path, monkeypatch)
    result = diagnosis.save_intraday_data_coverage_diagnosis()
    assert result["overall_status"] in {"OK", "NOTICE", "WARNING"}
    assert result["overall_status"] != "ERROR"
    assert result["market_closed_count"] >= 1


def test_save_all_reports(tmp_path, monkeypatch):
    _write_snapshots(tmp_path, monkeypatch)
    result = diagnosis.save_intraday_data_coverage_diagnosis()
    assert (tmp_path / "intraday_data_coverage_diagnosis.json").exists()
    assert (tmp_path / "intraday_data_coverage_diagnosis.csv").exists()
    assert (tmp_path / "intraday_unsupported_symbols.csv").exists()
    assert (tmp_path / "intraday_data_improvement_suggestions.json").exists()
    assert result["total_symbol_count"] == 2


def test_daily_system_check_reads_diagnosis(tmp_path, monkeypatch):
    import daily_system_check as dsc

    _write_snapshots(tmp_path, monkeypatch)
    diagnosis.save_intraday_data_coverage_diagnosis()
    monkeypatch.setattr(dsc, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(dsc, "COVERAGE_DIAGNOSIS_JSON", tmp_path / "intraday_data_coverage_diagnosis.json")
    monkeypatch.setattr(dsc, "UNSUPPORTED_SYMBOLS_CSV", tmp_path / "intraday_unsupported_symbols.csv")
    monkeypatch.setattr(dsc, "IMPROVEMENT_SUGGESTIONS_JSON", tmp_path / "intraday_data_improvement_suggestions.json")
    status = dsc._intraday_coverage_diagnosis_status()
    assert status["diagnosis_report_exists"] is True
    assert status["intraday_coverage_diagnosis_status"] in {"OK", "NOTICE", "WARNING"}


def test_c_excluded_trade_allowed_stays_zero(tmp_path, monkeypatch):
    _write_snapshots(tmp_path, monkeypatch)
    c_path = diagnosis.CANDIDATE_PATHS["us_c"]
    df = read_swing_candidate_csv(c_path)
    true_count = int(df["strategy_trade_allowed"].astype(str).str.lower().isin(["true", "1", "1.0"]).sum())
    assert true_count == 0
