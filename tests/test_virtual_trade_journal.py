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
    monkeypatch.setattr(vtj, "AUTO_CAPTURE_STATUS_JSON", tmp_path / "status.json")
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
