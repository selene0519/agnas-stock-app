from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import virtual_trade_journal as vtj  # noqa: E402


@pytest.fixture()
def isolated_vtj(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(vtj, "JOURNAL_CSV", tmp_path / "journal.csv")
    monkeypatch.setattr(vtj, "EVALUATION_CSV", tmp_path / "evaluations.csv")
    monkeypatch.setattr(vtj, "CALIBRATION_APPROVALS_CSV", tmp_path / "approvals.csv")
    monkeypatch.setattr(vtj, "AUTO_CAPTURE_STATUS_JSON", tmp_path / "status.json")
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


def test_entry_efficiency_stats_tracks_fill_rate_slippage_and_days(isolated_vtj: Path) -> None:
    journal_rows = [
        {
            "journal_id": "jid-fill-1",
            "source_type": "FORWARD_PAPER_TRADE",
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
    by_key = {(row["mode"], row["horizon"]): row for row in out["adjustments"]}
    assert by_key[("balanced", "swing")]["direction"] == "BOOST"
    assert by_key[("aggressive", "short")]["direction"] == "REDUCE"
    assert (isolated_vtj / "attribution_feedback.json").exists()
