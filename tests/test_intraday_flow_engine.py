from __future__ import annotations

import json

import pandas as pd

import core.intraday_flow_engine as engine


def test_normalize_intraday_flow_data_scores():
    out = engine.normalize_intraday_flow_data({
        "symbol": "005930",
        "market": "한국주식",
        "foreign_net_buy": 1_000_000,
        "institution_net_buy": 500_000,
        "individual_net_buy": -200_000,
        "program_net_buy": 0,
        "flow_fetch_status": "success",
        "flow_data_available": True,
    })
    assert out["flow_data_available"] is True
    assert 0 <= out["intraday_flow_score"] <= 100


def test_endpoint_not_configured_keeps_none_net_fields():
    out = engine.normalize_intraday_flow_data({
        "symbol": "005930",
        "market": "한국주식",
        "flow_fetch_status": "endpoint_not_configured",
        "flow_failure_reason": "endpoint_not_configured",
        "flow_data_available": False,
    })
    assert out["foreign_net_buy"] is None
    assert out["institution_net_buy"] is None
    assert out["flow_failure_reason"] == "endpoint_not_configured"


def test_missing_flow_data_does_not_crash():
    out = engine.normalize_intraday_flow_data({"symbol": "ABC", "market": "미국주식", "flow_data_available": False})
    assert out["flow_data_available"] is False
    assert out["flow_failure_reason"]
    assert out["flow_warning"]


def test_us_momentum_flow_normalize():
    out = engine.normalize_intraday_flow_data({
        "symbol": "AAPL",
        "market": "미국주식",
        "flow_mode": "us_momentum",
        "flow_fetch_status": "success",
        "flow_data_available": True,
        "last_price": 10.0,
        "flow_data_source": "kis_us_quote",
    })
    assert out["flow_mode"] == "us_momentum"
    assert out["foreign_net_buy"] is None


def test_flow_snapshot_and_summary(tmp_path, monkeypatch):
    candidate = tmp_path / "swing_candidates_kr_A_top3.csv"
    pd.DataFrame([{"symbol": "005930", "market": "한국주식", "grade": "A", "sector": "반도체"}]).to_csv(
        candidate, index=False, encoding="utf-8-sig"
    )
    import core.swing_candidate_io as swing_io

    monkeypatch.setattr(engine, "SWING_CANDIDATE_FILES", [candidate])
    monkeypatch.setattr(swing_io, "SWING_CANDIDATE_FILES", [candidate])
    monkeypatch.setattr(engine, "update_candidate_files_with_flow", lambda flow_df, sector_flow_df=None: {"updated_files": []})
    snap_path = tmp_path / "flow.csv"
    sum_path = tmp_path / "flow_summary.json"
    detail_path = tmp_path / "flow_failure_detail.csv"
    monkeypatch.setattr(engine, "FLOW_FAILURE_DETAIL_PATH", detail_path)
    monkeypatch.setattr(engine, "fetch_intraday_investor_flow", lambda symbol, market: {
        "foreign_net_buy": 100,
        "institution_net_buy": 50,
        "individual_net_buy": -10,
        "flow_fetch_status": "success",
        "flow_failure_reason": "",
        "flow_data_source": "kis_inquire_investor",
        "kr_flow_attempted": True,
        "kr_flow_success": True,
    })
    monkeypatch.setattr(engine, "fetch_intraday_program_flow", lambda symbol, market: {
        "program_net_buy": None,
        "program_fetch_status": "endpoint_not_configured",
        "program_failure_reason": "endpoint_not_configured",
    })
    result = engine.save_intraday_flow_snapshot(snap_path)
    assert result["status"] == "OK"
    assert snap_path.exists()
    snap = pd.read_csv(snap_path)
    reason = str(snap.loc[0, "flow_failure_reason"]).strip().lower()
    assert reason in {"", "nan", "none"}
    assert str(snap.loc[0, "flow_data_available"]).strip().lower() in {"true", "1", "1.0", "yes"}
    summary = engine.save_intraday_flow_summary(sum_path)
    assert summary["target_count"] >= 1
    summary_json = json.loads(sum_path.read_text(encoding="utf-8"))

    assert "flow_failure_reason_counts" in summary_json
    assert isinstance(summary_json["flow_failure_reason_counts"], dict)
    assert summary_json["flow_failure_reason_counts"] == {}

    assert summary_json.get("kr_flow_attempt_count", 0) >= 1
    assert summary_json.get("kr_flow_success_count", 0) >= 1
    assert summary_json.get("kr_flow_fail_count", 0) == 0
    assert summary_json.get("kr_flow_failure_reason_counts", {}) == {}

    assert "kr_market_session_status" in summary_json
    assert isinstance(summary_json["kr_market_session_status"], str)
    assert summary_json["kr_market_session_status"].strip()

    assert "kr_flow_failure_detail_path" in summary_json
    assert summary_json["kr_flow_failure_detail_path"] == str(detail_path)


def test_flow_snapshot_and_summary_failure_reason_counts(tmp_path, monkeypatch):
    """수급 조회 실패 시 failure reason 집계가 summary에 반영되는지 확인."""
    candidate = tmp_path / "swing_candidates_kr_A_top3.csv"
    pd.DataFrame([{"symbol": "005930", "market": "한국주식", "grade": "A", "sector": "반도체"}]).to_csv(
        candidate, index=False, encoding="utf-8-sig"
    )
    import core.swing_candidate_io as swing_io

    monkeypatch.setattr(engine, "SWING_CANDIDATE_FILES", [candidate])
    monkeypatch.setattr(swing_io, "SWING_CANDIDATE_FILES", [candidate])
    monkeypatch.setattr(engine, "update_candidate_files_with_flow", lambda flow_df, sector_flow_df=None: {"updated_files": []})
    snap_path = tmp_path / "flow.csv"
    sum_path = tmp_path / "flow_summary.json"
    monkeypatch.setattr(engine, "FLOW_FAILURE_DETAIL_PATH", tmp_path / "flow_failure_detail.csv")
    failure_reason = "kr_flow_response_empty"
    monkeypatch.setattr(engine, "fetch_intraday_investor_flow", lambda symbol, market: {
        "foreign_net_buy": None,
        "institution_net_buy": None,
        "individual_net_buy": None,
        "flow_fetch_status": failure_reason,
        "flow_failure_reason": failure_reason,
        "flow_data_source": "unsupported_safe",
        "kr_flow_attempted": True,
        "kr_flow_success": False,
        "kr_flow_error": "empty_output",
    })
    monkeypatch.setattr(engine, "fetch_intraday_program_flow", lambda symbol, market: {
        "program_net_buy": None,
        "program_fetch_status": "endpoint_not_configured",
        "program_failure_reason": "endpoint_not_configured",
    })
    result = engine.save_intraday_flow_snapshot(snap_path)
    assert result["status"] == "OK"
    engine.save_intraday_flow_summary(sum_path)
    summary_json = json.loads(sum_path.read_text(encoding="utf-8"))

    assert summary_json.get("kr_flow_fail_count", 0) >= 1
    assert summary_json["flow_failure_reason_counts"].get(failure_reason, 0) >= 1
    assert summary_json["kr_flow_failure_reason_counts"].get(failure_reason, 0) >= 1
