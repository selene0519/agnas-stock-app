from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.engine import correction_store  # noqa: E402
from app.services import virtual_trade_journal as vtj  # noqa: E402


def _valid_recommendation(symbol: str = "TEST") -> dict:
    return {
        "market": "kr",
        "mode": "balanced",
        "horizon": "swing",
        "symbol": symbol,
        "name": symbol,
        "decisionBucket": vtj.TODAY_ENTRY,
        "entry": 100,
        "stop": 95,
        "target": 112,
        "currentPrice": 100,
        "finalRankScore": 80,
        "expectedValue": 3,
        "riskRewardRatio": 2.4,
        "probability": 65,
        "riskScore": 70,
        "eventRiskScore": 30,
        "dataStatus": "NORMAL",
        "tradeBlockStatus": "",
        "priceSource": "pytest",
        "marketRegime": "RISK_ON",
        "generatedAt": "2026-06-18T08:20:00",
    }


@pytest.fixture()
def isolated_vtj(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(vtj, "JOURNAL_CSV", tmp_path / "journal.csv")
    monkeypatch.setattr(vtj, "EVALUATION_CSV", tmp_path / "evaluations.csv")
    monkeypatch.setattr(vtj, "CALIBRATION_APPROVALS_CSV", tmp_path / "approvals.csv")
    monkeypatch.setattr(vtj, "CALIBRATION_APPLICATIONS_CSV", tmp_path / "applications.csv")
    monkeypatch.setattr(vtj, "AUTO_CAPTURE_STATUS_JSON", tmp_path / "status.json")
    monkeypatch.setattr(vtj, "SELF_LEARNING_STATUS_JSON", tmp_path / "self_learning_status.json")
    monkeypatch.setattr(vtj, "_FEEDBACK_JSON", tmp_path / "attribution_feedback.json")
    vtj._ensure()
    return tmp_path


def test_stop_wins_when_target_and_stop_touch_same_daily_candle() -> None:
    holding = pd.DataFrame([{"date": "2026-01-02", "open": 100, "high": 112, "low": 94, "close": 104}])

    out = vtj._find_exit(holding, entry=100, stop=95, target=110, eval_window=5)

    assert out["exit_kind"] == "STOP"
    assert out["exit_price"] == 95
    assert out["exit_date"] == "2026-01-02"


def test_time_exit_taxonomy_keeps_near_target_near_stop_mid_and_flat() -> None:
    assert vtj._outcome("TIME", target_progress=0.85, stop_progress=0.2, net=2.0) == "TIME_EXIT_NEAR_TARGET"
    assert vtj._outcome("TIME", target_progress=0.2, stop_progress=0.85, net=-2.0) == "TIME_EXIT_NEAR_STOP"
    assert vtj._outcome("TIME", target_progress=0.85, stop_progress=0.85, net=1.0) == "TIME_EXIT_MID"
    assert vtj._outcome("TIME", target_progress=0.2, stop_progress=0.2, net=0.1) == "TIME_EXIT_FLAT"


def test_historical_replay_generation_receives_only_cutoff_bars(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_of_date = "2026-03-31"
    full = pd.DataFrame(
        [
            {"date": f"2026-01-{day:02d}", "open": 100 + day, "high": 101 + day, "low": 99 + day, "close": 100 + day}
            for day in range(1, 29)
        ]
        + [
            {"date": f"2026-02-{day:02d}", "open": 128 + day, "high": 129 + day, "low": 127 + day, "close": 128 + day}
            for day in range(1, 29)
        ]
        + [
            {"date": f"2026-03-{day:02d}", "open": 156 + day, "high": 157 + day, "low": 155 + day, "close": 156 + day}
            for day in range(1, 32)
        ]
        + [
            {"date": "2026-04-01", "open": 220, "high": 230, "low": 210, "close": 225},
        ]
    )
    full["_date_ts"] = pd.to_datetime(full["date"], errors="coerce").dt.normalize()

    monkeypatch.setattr(vtj, "_ohlcv_symbols_for_market", lambda market: ["TEST"])
    monkeypatch.setattr(vtj, "_load_ohlcv", lambda market, symbol: (full.copy(), str(isolated_vtj / "test.csv"), "actual_ohlcv"))

    def fake_item(symbol, market, mode, horizon, cutoff_date, cutoff, source):
        assert str(cutoff["_date_ts"].max().date()) == as_of_date
        assert "2026-04-01" not in set(cutoff["date"].astype(str))
        return {
            "market": market,
            "mode": mode,
            "horizon": horizon,
            "symbol": symbol,
            "name": symbol,
            "decisionBucket": vtj.TODAY_ENTRY,
            "entry": 188,
            "stop": 178,
            "target": 208,
            "currentPrice": 188,
            "finalRankScore": 80,
            "expectedValue": 3,
            "riskRewardRatio": 2,
            "probability": 65,
            "riskScore": 70,
            "eventRiskScore": 30,
            "dataStatus": "NORMAL",
            "tradeBlockStatus": "",
            "priceSource": "test_cutoff",
            "marketRegime": "RISK_ON",
            "generatedAt": f"{cutoff_date}T23:59:00",
        }

    monkeypatch.setattr(vtj, "_historical_item_from_cutoff", fake_item)

    out = vtj.historical_replay("kr", "balanced", "swing", as_of_date=as_of_date, limit=1, evaluate_after=False)

    assert out["status"] == "OK"
    assert out["added"] == 1
    assert out["syntheticCutoffReplay"] is True
    assert out["replayMethod"] == vtj.HISTORICAL_REPLAY_METHOD


def test_premarket_and_after_close_sessions_are_separate_journal_rows(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vtj, "_source_recommendation_items", lambda *args, **kwargs: [_valid_recommendation()])

    pre = vtj.capture("kr", "balanced", "swing", journal_session="PREMARKET_PLAN", as_of_date="2026-06-18")
    close = vtj.capture("kr", "balanced", "swing", journal_session="AFTER_CLOSE_TRADE", as_of_date="2026-06-18")
    listed = vtj.list_trades("kr", "balanced", "swing", "FORWARD_PAPER_TRADE", "all", limit=10)

    assert pre["added"] == 1
    assert close["added"] == 1
    assert listed["count"] == 2
    assert {item["journal_session"] for item in listed["items"]} == {"PREMARKET_PLAN", "AFTER_CLOSE_TRADE"}
    pre_row = next(item for item in listed["items"] if item["journal_session"] == "PREMARKET_PLAN")
    assert "장전 계획" in pre_row["session_note"]
    assert "추격하지 않는다" in pre_row["session_note"]


def test_premarket_plan_rows_are_never_trade_evaluated(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vtj, "_source_recommendation_items", lambda *args, **kwargs: [_valid_recommendation()])
    vtj.capture("kr", "balanced", "swing", journal_session="PREMARKET_PLAN", as_of_date="2026-06-18")

    evaluated = vtj.evaluate(journal_session="PREMARKET_PLAN", force=True)

    assert evaluated["evaluated"] == 0
    assert vtj._read_rows(vtj.EVALUATION_CSV, vtj.EVALUATION_COLS) == []


def test_us_juneteenth_auto_capture_is_marked_market_closed(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vtj, "_kst_now", lambda: datetime(2026, 6, 20, 8, 0, tzinfo=vtj.ZoneInfo("Asia/Seoul")))
    monkeypatch.setattr(vtj, "_source_recommendation_items", lambda *args, **kwargs: pytest.fail("holiday capture must not load recommendations"))

    out = vtj.run_auto_capture("us", journal_session="AFTER_CLOSE_TRADE", force=True)

    assert out["runs"][0]["tradeDate"] == "2026-06-19"
    assert out["runs"][0]["status"] == "SKIPPED_MARKET_CLOSED"
    assert out["runs"][0]["runKey"] in out["completedKeys"]


def test_us_premarket_auto_capture_uses_same_day_us_trade_date(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vtj, "_kst_now", lambda: datetime(2026, 6, 19, 21, 30, tzinfo=vtj.ZoneInfo("Asia/Seoul")))
    monkeypatch.setattr(vtj, "_source_recommendation_items", lambda *args, **kwargs: pytest.fail("holiday capture must not load recommendations"))

    out = vtj.run_auto_capture("us", journal_session="PREMARKET_PLAN", force=True)

    assert out["runs"][0]["tradeDate"] == "2026-06-19"
    assert out["runs"][0]["journalSession"] == "PREMARKET_PLAN"
    assert out["runs"][0]["status"] == "SKIPPED_MARKET_CLOSED"


def test_market_analog_search_uses_only_cutoff_benchmark_history(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = []
    for idx in range(150):
        close = 100 + idx * 0.2 + (idx % 12 - 6) * 0.4
        rows.append(
            {
                "date": (pd.Timestamp("2025-01-01") + pd.Timedelta(days=idx)).date().isoformat(),
                "open": close * 0.99,
                "high": close * 1.01,
                "low": close * 0.98,
                "close": close,
                "volume": 1000 + (idx % 7) * 10,
            }
        )
    bench = pd.DataFrame(rows)
    bench["_date_ts"] = pd.to_datetime(bench["date"], errors="coerce").dt.normalize()
    cutoff = bench.iloc[130]["date"]
    monkeypatch.setattr(vtj, "_load_benchmark_ohlcv", lambda market: (bench.copy(), "TESTIDX"))

    out = vtj._find_market_analogs("kr", as_of_date=cutoff, limit=3, horizon="swing")

    assert out["status"] == "OK"
    assert out["asOfDate"] == cutoff
    assert out["benchmarkSymbol"] == "TESTIDX"
    assert len(out["items"]) == 3
    assert all(item["date"] < cutoff for item in out["items"])
    assert all("ret_20d_pct" in item["marketVector"] for item in out["items"])


def test_market_analog_replay_summarizes_future_outcomes_after_snapshot(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analog_date = "2026-01-10"

    monkeypatch.setattr(
        vtj,
        "_find_market_analogs",
        lambda *args, **kwargs: {
            "status": "OK",
            "market": "kr",
            "asOfDate": "2026-06-01",
            "benchmarkSymbol": "TESTIDX",
            "currentVector": {"ret_20d_pct": 3.2, "regime": "RISK_ON"},
            "items": [{"date": analog_date, "similarity": 0.91, "distance": 0.3, "marketVector": {"ret_20d_pct": 2.9}}],
        },
    )

    def fake_replay(**kwargs):
        row = vtj._snapshot_from_item(_valid_recommendation("SIM"), "HISTORICAL_REPLAY", analog_date, vtj.DEFAULT_JOURNAL_SESSION)
        vtj._write_rows(vtj.JOURNAL_CSV, [row], vtj.JOURNAL_COLS)
        vtj._write_rows(
            vtj.EVALUATION_CSV,
            [
                {
                    "journal_id": row["journal_id"],
                    "status": "EVALUATED",
                    "outcome": "TIME_EXIT_NEAR_TARGET",
                    "filled": True,
                    "net_pnl_pct": 2.4,
                    "mfe_pct": 5.0,
                    "mae_pct": -1.0,
                    "failure_reason": "TARGET_TOO_FAR",
                    "evaluated_at": "2026-01-31T00:00:00",
                }
            ],
            vtj.EVALUATION_COLS,
        )
        return {"status": "OK", "selected": 1, "added": 1, "duplicates": 0, "replayMethod": vtj.HISTORICAL_REPLAY_METHOD}

    monkeypatch.setattr(vtj, "historical_replay", fake_replay)

    out = vtj.market_analog_replay("kr", "balanced", "swing", analog_limit=1, replay_limit=1)

    assert out["status"] == "OK"
    assert out["items"][0]["outcomeSummary"]["evaluated"] == 1
    assert out["items"][0]["outcomeSummary"]["avgNetPnlPct"] == 2.4
    assert out["items"][0]["outcomeSummary"]["failureCounts"]["TARGET_TOO_FAR"] == 1
    assert "승률" in out["items"][0]["lesson"]


def test_calibration_review_records_decision_but_never_auto_applies(isolated_vtj: Path) -> None:
    journal_rows = []
    eval_rows = []
    for idx in range(30):
        jid = f"jid-{idx}"
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "as_of_date": "2026-01-01",
                "generated_at": "2026-01-01T00:00:00",
                "captured_at": "2026-01-01T00:00:00",
                "market": "kr",
                "mode": "balanced",
                "horizon": "swing",
                "symbol": f"T{idx:03d}",
                "name": f"T{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_type": "NEXT_OPEN",
                "entry_price": 100,
                "stop_price": 95,
                "target_price": 110,
                "current_price_at_signal": 100,
                "final_rank_score": 75,
                "expected_value": 2,
                "risk_reward_ratio": 2,
                "probability": 65,
                "risk_score": 70,
                "event_risk_score": 30,
                "data_status": "NORMAL",
                "data_confidence": "HIGH",
                "price_source": "test",
                "market_regime_at_signal": "RISK_ON",
                "sector": "",
                "reject_reason": "",
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "STOP_HIT",
                "filled": True,
                "net_pnl_pct": -3,
                "mfe_pct": 2,
                "mae_pct": -5,
                "failure_reason": "STOP_TOO_TIGHT" if idx < 6 else "FALSE_SIGNAL",
                "evaluated_at": f"2026-01-02T00:00:{idx:02d}",
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    suggestions = vtj.calibration_suggestions("kr", "balanced", "swing", "FORWARD_PAPER_TRADE")["items"]
    target = next(item for item in suggestions if item.get("reason") == "STOP_TOO_TIGHT")
    reviewed = vtj.review_calibration_suggestion(target["suggestionId"], decision="APPROVED", reviewed_by="pytest")

    assert reviewed["status"] == "OK"
    assert reviewed["applied"] is False
    assert reviewed["approval"]["decision"] == "APPROVED"


def test_approved_calibration_can_be_manually_applied_to_self_correction_params(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(correction_store, "_reports_dir", lambda: isolated_vtj)
    journal_rows = []
    eval_rows = []
    for idx in range(30):
        jid = f"apply-jid-{idx}"
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "journal_session": "AFTER_CLOSE_TRADE",
                "as_of_date": "2026-01-01",
                "generated_at": "2026-01-01T00:00:00",
                "captured_at": "2026-01-01T00:00:00",
                "market": "kr",
                "mode": "balanced",
                "horizon": "swing",
                "symbol": f"A{idx:03d}",
                "name": f"A{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_type": "NEXT_OPEN",
                "entry_price": 100,
                "stop_price": 95,
                "target_price": 110,
                "current_price_at_signal": 100,
                "final_rank_score": 75,
                "expected_value": 2,
                "risk_reward_ratio": 2,
                "probability": 65,
                "risk_score": 70,
                "event_risk_score": 30,
                "data_status": "NORMAL",
                "data_confidence": "HIGH",
                "price_source": "test",
                "market_regime_at_signal": "RISK_ON",
                "sector": "",
                "reject_reason": "",
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "STOP_HIT",
                "filled": True,
                "net_pnl_pct": -3,
                "mfe_pct": 2,
                "mae_pct": -5,
                "failure_reason": "STOP_TOO_TIGHT" if idx < 6 else "FALSE_SIGNAL",
                "evaluated_at": f"2026-01-02T00:00:{idx:02d}",
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    suggestions = vtj.calibration_suggestions("kr", "balanced", "swing", "FORWARD_PAPER_TRADE")["items"]
    target = next(item for item in suggestions if item.get("reason") == "STOP_TOO_TIGHT")
    vtj.review_calibration_suggestion(target["suggestionId"], decision="APPROVED", reviewed_by="pytest")
    applied = vtj.apply_approved_calibrations(applied_by="pytest")
    correction = correction_store.load_correction("kr", "balanced", "swing")
    refreshed = vtj.calibration_suggestions("kr", "balanced", "swing", "FORWARD_PAPER_TRADE")["items"]
    refreshed_target = next(item for item in refreshed if item.get("reason") == "STOP_TOO_TIGHT")

    assert applied["status"] == "OK"
    assert applied["applied"] == 1
    assert correction["journalCalibrationApplied"] is True
    assert correction["priceAdjustments"]["stopAtrMultiplier"] > 0
    assert refreshed_target["applicationStatus"] == "APPLIED"


def test_entry_efficiency_stats_tracks_fill_rate_slippage_and_days(isolated_vtj: Path) -> None:
    journal_rows = [
        {
            "journal_id": "jid-fill-1",
            "source_type": "FORWARD_PAPER_TRADE",
            "journal_session": "AFTER_CLOSE_TRADE",
            "as_of_date": "2026-01-01",
            "generated_at": "2026-01-01T09:00:00",
            "captured_at": "2026-01-01T09:00:00",
            "market": "kr",
            "mode": "balanced",
            "horizon": "swing",
            "symbol": "A001",
            "name": "A001",
            "decision_bucket": vtj.TODAY_ENTRY,
            "entry_price": 100,
            "raw_recommendation_json": "{}",
        },
        {
            "journal_id": "jid-fill-2",
            "source_type": "FORWARD_PAPER_TRADE",
            "journal_session": "AFTER_CLOSE_TRADE",
            "as_of_date": "2026-01-01",
            "generated_at": "2026-01-01T09:00:00",
            "captured_at": "2026-01-01T09:00:00",
            "market": "kr",
            "mode": "balanced",
            "horizon": "swing",
            "symbol": "A002",
            "name": "A002",
            "decision_bucket": vtj.TODAY_ENTRY,
            "entry_price": 200,
            "raw_recommendation_json": "{}",
        },
        {
            "journal_id": "jid-miss",
            "source_type": "FORWARD_PAPER_TRADE",
            "journal_session": "AFTER_CLOSE_TRADE",
            "as_of_date": "2026-01-01",
            "generated_at": "2026-01-01T09:00:00",
            "captured_at": "2026-01-01T09:00:00",
            "market": "kr",
            "mode": "balanced",
            "horizon": "short",
            "symbol": "A003",
            "name": "A003",
            "decision_bucket": vtj.TODAY_ENTRY,
            "entry_price": 300,
            "raw_recommendation_json": "{}",
        },
    ]
    eval_rows = [
        {"journal_id": "jid-fill-1", "status": "EVALUATED", "filled": True, "fill_date": "2026-01-02", "fill_price": 101},
        {"journal_id": "jid-fill-2", "status": "EVALUATED", "filled": True, "fill_date": "2026-01-03", "fill_price": 198},
        {"journal_id": "jid-miss", "status": "CANCELLED", "filled": False},
    ]
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    out = vtj.entry_efficiency_stats("kr", "all")

    assert out["status"] == "OK"
    assert out["total"] == 3
    assert out["filled"] == 2
    assert out["fillRate"] == 0.6667
    assert out["avgSlippagePct"] == 0.0
    assert out["avgFillDays"] == 1.5
    swing = next(row for row in out["byHorizon"] if row["horizon"] == "swing")
    assert swing["fillRate"] == 1.0


def test_attribution_feedback_suggests_boost_and_reduce_without_auto_apply(isolated_vtj: Path) -> None:
    journal_rows = []
    eval_rows = []
    for idx in range(12):
        is_winner = idx < 6
        jid = f"jid-feedback-{idx}"
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "journal_session": "AFTER_CLOSE_TRADE",
                "as_of_date": "2026-01-01",
                "generated_at": "2026-01-01T09:00:00",
                "captured_at": "2026-01-01T09:00:00",
                "market": "kr",
                "mode": "balanced" if is_winner else "aggressive",
                "horizon": "swing" if is_winner else "short",
                "symbol": f"A{idx:03d}",
                "name": f"A{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_price": 100,
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "TARGET_HIT" if is_winner else "STOP_HIT",
                "filled": True,
                "fill_date": "2026-01-02",
                "fill_price": 100,
                "net_pnl_pct": 4 if is_winner else -2,
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    out = vtj.attribution_feedback("kr")

    assert out["status"] == "OK"
    assert out["sampleCount"] == 12
    assert out["autoApplied"] is False
    assert out["manualApprovalRequired"] is True
    assert out["calibrationSummary"]["applyEndpoint"] == "/api/journal/calibration/apply-approved"
    by_key = {(row["mode"], row["horizon"]): row for row in out["adjustments"]}
    assert by_key[("balanced", "swing")]["direction"] == "BOOST"
    assert by_key[("aggressive", "short")]["direction"] == "REDUCE"
    assert (isolated_vtj / "attribution_feedback.json").exists()


def test_attribution_analysis_includes_ols_regression_when_sample_is_ready(isolated_vtj: Path) -> None:
    journal_rows = []
    eval_rows = []
    for idx in range(18):
        high_ev = idx % 2 == 0
        jid = f"jid-regression-{idx}"
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "journal_session": "AFTER_CLOSE_TRADE",
                "as_of_date": "2026-01-01",
                "generated_at": "2026-01-01T09:00:00",
                "captured_at": "2026-01-01T09:00:00",
                "market": "kr",
                "mode": "balanced" if high_ev else "aggressive",
                "horizon": "swing",
                "symbol": f"R{idx:03d}",
                "name": f"R{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_type": "NEXT_OPEN",
                "entry_price": 100,
                "expected_value": 4 if high_ev else -1,
                "risk_reward_ratio": 2.4 if high_ev else 1.1,
                "probability": 65 if high_ev else 45,
                "risk_score": 70 if high_ev else 35,
                "event_risk_score": 20,
                "market_regime_at_signal": "RISK_ON" if high_ev else "RISK_OFF",
                "sector": "TECH" if high_ev else "BANK",
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "TARGET_HIT" if high_ev else "STOP_HIT",
                "filled": True,
                "net_pnl_pct": 3.0 if high_ev else -2.0,
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    out = vtj.attribution_analysis("kr", "all", "all")

    assert out["status"] == "OK"
    assert out["regression"]["status"] == "OK"
    assert out["regression"]["sampleCount"] == 18
    assert out["regression"]["coefficients"]


def test_auto_self_calibrate_auto_approves_and_applies_only_policy_eligible_items(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(correction_store, "_reports_dir", lambda: isolated_vtj)
    journal_rows = []
    eval_rows = []
    for idx in range(50):
        jid = f"auto-jid-{idx}"
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "journal_session": "AFTER_CLOSE_TRADE",
                "as_of_date": "2026-01-01",
                "generated_at": "2026-01-01T00:00:00",
                "captured_at": "2026-01-01T00:00:00",
                "market": "kr",
                "mode": "balanced",
                "horizon": "swing",
                "symbol": f"AUTO{idx:03d}",
                "name": f"AUTO{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_type": "NEXT_OPEN",
                "entry_price": 100,
                "stop_price": 95,
                "target_price": 110,
                "current_price_at_signal": 100,
                "final_rank_score": 75,
                "expected_value": 2,
                "risk_reward_ratio": 2,
                "probability": 65,
                "risk_score": 70,
                "event_risk_score": 30,
                "data_status": "NORMAL",
                "data_confidence": "HIGH",
                "price_source": "test",
                "market_regime_at_signal": "RISK_ON",
                "sector": "",
                "reject_reason": "",
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "STOP_HIT",
                "filled": True,
                "net_pnl_pct": -2.5,
                "failure_reason": "ENTRY_TIMING" if idx < 16 or idx >= 45 else "FALSE_SIGNAL",
                "evaluated_at": f"2026-01-02T00:00:{idx % 60:02d}",
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    result = vtj.auto_self_calibrate("kr", apply=True, max_applications=1)
    correction = correction_store.load_correction("kr", "balanced", "swing")
    status = vtj.self_learning_status("kr")

    assert result["status"] == "OK"
    assert result["eligibleCount"] >= 1
    assert result["approvedCount"] == 1
    assert result["applied"] == 1
    assert correction["journalCalibrationApplied"] is True
    assert correction["journalCalibrationAppliedBy"] == "auto_self_learning"
    assert correction["filterAdjustments"]["maxDistanceToEntryPct"] > 0
    assert status["autoApprovalCount"] >= 1
    assert status["quality"]["score"] > 0
    assert status["lastSelfLearningRun"]["applied"] == 1


def test_auto_self_calibrate_blocks_when_holdout_drift_is_detected(isolated_vtj: Path) -> None:
    journal_rows = []
    eval_rows = []
    for idx in range(80):
        jid = f"drift-jid-{idx}"
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "journal_session": "AFTER_CLOSE_TRADE",
                "as_of_date": "2026-01-01",
                "generated_at": "2026-01-01T00:00:00",
                "captured_at": "2026-01-01T00:00:00",
                "market": "kr",
                "mode": "balanced",
                "horizon": "swing",
                "symbol": f"DRIFT{idx:03d}",
                "name": f"DRIFT{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_type": "NEXT_OPEN",
                "entry_price": 100,
                "stop_price": 95,
                "target_price": 110,
                "current_price_at_signal": 100,
                "final_rank_score": 75,
                "expected_value": 2,
                "risk_reward_ratio": 2,
                "probability": 65,
                "risk_score": 70,
                "event_risk_score": 30,
                "data_status": "NORMAL",
                "data_confidence": "HIGH",
                "price_source": "test",
                "market_regime_at_signal": "RISK_ON",
                "sector": "",
                "reject_reason": "",
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "STOP_HIT",
                "filled": True,
                "net_pnl_pct": -2.0,
                "failure_reason": "ENTRY_TIMING" if idx < 30 else "FALSE_SIGNAL",
                "evaluated_at": f"2026-01-{1 + idx // 3:02d}T00:00:00",
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    result = vtj.auto_self_calibrate("kr", apply=True, max_applications=2)

    assert result["status"] == "OK"
    assert result["applied"] == 0
    assert any(row["reason"] == "HOLDOUT_DRIFT" for row in result["blocked"])


def test_self_learning_rollback_restores_previous_correction_version(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(correction_store, "_reports_dir", lambda: isolated_vtj)
    correction_store.save_params({
        "version": 0,
        "generatedAt": "2026-01-01T00:00:00",
        "markets": {"kr_balanced_swing": {"confidence": 0.1}},
    })
    correction_store.save_params({
        "version": 1,
        "generatedAt": "2026-01-02T00:00:00",
        "markets": {"kr_balanced_swing": {"confidence": 0.9}},
    })

    out = vtj.rollback_self_learning(requested_by="pytest")
    restored = correction_store.load_params()

    assert out["status"] == "OK"
    assert out["fromVersion"] == 1
    assert out["toVersion"] == 0
    assert restored["rollbackFromVersion"] == 1
    assert restored["markets"]["kr_balanced_swing"]["confidence"] == 0.1


def test_historical_replay_backfill_steps_cutoff_dates_without_future_peek(
    isolated_vtj: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_replay(**kwargs):
        calls.append(kwargs)
        return {
            "status": "OK",
            "selected": 2,
            "added": 1,
            "duplicates": 1,
            "rejected": {},
            "replayMethod": vtj.HISTORICAL_REPLAY_METHOD,
        }

    monkeypatch.setattr(vtj, "historical_replay", fake_replay)

    out = vtj.historical_replay_backfill(
        market="kr",
        mode="balanced",
        horizon="swing",
        start_date="2025-01-01",
        end_date="2025-02-15",
        step_days=20,
        limit=5,
        max_runs=2,
    )

    assert out["status"] == "OK"
    assert out["runs"] == 2
    assert out["added"] == 2
    assert [call["as_of_date"] for call in calls] == ["2025-01-01", "2025-01-21"]
    assert all(call["evaluate_after"] is True for call in calls)
    assert "ohlcv_date_lte_as_of_date" in out["futureDataPolicy"]


def test_calibration_performance_gate_flags_degraded_applied_correction(isolated_vtj: Path) -> None:
    app_row = {
        "application_id": "app-1",
        "approval_id": "approval-1",
        "suggestion_id": "suggestion-1",
        "applied_by": "pytest",
        "applied_at": "2026-02-01T00:00:00",
        "market": "kr",
        "mode": "balanced",
        "horizon": "swing",
        "source_type": "FORWARD_PAPER_TRADE",
        "journal_session": "AFTER_CLOSE_TRADE",
        "source_weight": 1.0,
        "raw_sample_count": 60,
        "effective_sample_count": 60,
        "reason": "ENTRY_TIMING",
        "before_params_json": "{}",
        "after_params_json": "{}",
        "correction_version": 3,
        "status": "APPLIED",
    }
    vtj._write_rows(vtj.CALIBRATION_APPLICATIONS_CSV, [app_row], vtj.CALIBRATION_APPLICATION_COLS)

    journal_rows = []
    eval_rows = []
    for idx in range(60):
        before = idx < 30
        day = idx + 1 if before else idx - 29
        date = f"2026-01-{day:02d}" if before else f"2026-02-{day:02d}"
        jid = f"gate-{idx}"
        journal_rows.append(
            {
                "journal_id": jid,
                "source_type": "FORWARD_PAPER_TRADE",
                "journal_session": "AFTER_CLOSE_TRADE",
                "as_of_date": date,
                "generated_at": f"{date}T09:00:00",
                "captured_at": f"{date}T09:00:00",
                "market": "kr",
                "mode": "balanced",
                "horizon": "swing",
                "symbol": f"GATE{idx:03d}",
                "name": f"GATE{idx:03d}",
                "decision_bucket": vtj.TODAY_ENTRY,
                "entry_type": "NEXT_OPEN",
                "entry_price": 100,
                "stop_price": 95,
                "target_price": 110,
                "current_price_at_signal": 100,
                "final_rank_score": 75,
                "expected_value": 2,
                "risk_reward_ratio": 2,
                "probability": 65,
                "risk_score": 70,
                "event_risk_score": 30,
                "data_status": "NORMAL",
                "data_confidence": "HIGH",
                "price_source": "test",
                "market_regime_at_signal": "RISK_ON",
                "sector": "",
                "reject_reason": "",
                "raw_recommendation_json": "{}",
            }
        )
        eval_rows.append(
            {
                "journal_id": jid,
                "status": "EVALUATED",
                "outcome": "TARGET_HIT" if before else "STOP_HIT",
                "filled": True,
                "net_pnl_pct": 2.0 if before else -1.5,
                "evaluated_at": f"{date}T18:00:00",
            }
        )
    vtj._write_rows(vtj.JOURNAL_CSV, journal_rows, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, eval_rows, vtj.EVALUATION_COLS)

    out = vtj.calibration_performance_gate("kr")

    assert out["status"] == "ROLLBACK_READY"
    assert out["candidateCount"] == 1
    assert out["items"][0]["before"]["samples"] == 30
    assert out["items"][0]["after"]["samples"] == 30
    assert out["items"][0]["rollbackReady"] is True


def test_ops_dashboard_reports_journal_and_file_health(isolated_vtj: Path) -> None:
    row = {
        **vtj._snapshot_from_item(_valid_recommendation("OPS"), "FORWARD_PAPER_TRADE", "2026-06-18", "AFTER_CLOSE_TRADE"),
        "journal_id": "ops-1",
    }
    vtj._write_rows(vtj.JOURNAL_CSV, [row], vtj.JOURNAL_COLS)

    out = vtj.ops_dashboard("kr")

    assert out["status"] == "OK"
    assert out["journal"]["totalRows"] == 1
    assert out["journal"]["sourceCounts"]["FORWARD_PAPER_TRADE"] == 1
    assert any(str(item["path"]).endswith("journal.csv") and item["exists"] for item in out["files"])
