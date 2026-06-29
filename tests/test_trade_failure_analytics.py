from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import trade_failure_analytics as tfa  # noqa: E402
from app.services import virtual_trade_journal as vtj  # noqa: E402


def _journal_row(journal_id: str, market: str, mode: str, horizon: str, setup_score: float) -> dict:
    return {
        "journal_id": journal_id,
        "source_type": "FORWARD_PAPER_TRADE",
        "journal_session": "AFTER_CLOSE_TRADE",
        "as_of_date": "2026-06-20",
        "generated_at": "2026-06-20T16:00:00",
        "captured_at": "2026-06-20T16:05:00",
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "symbol": journal_id.upper(),
        "name": journal_id.upper(),
        "decision_bucket": "TODAY_ENTRY",
        "entry_type": "LIMIT_TOUCH",
        "entry_price": 100,
        "stop_price": 95,
        "target_price": 110,
        "data_status": "NORMAL",
        "data_confidence": "HIGH",
        "market_regime_at_signal": "RISK_ON",
        "raw_recommendation_json": json.dumps({"setupScore": setup_score, "decisionBucket": "TODAY_ENTRY"}),
    }


def _eval_row(
    journal_id: str,
    status: str,
    outcome: str,
    failure_reason: str,
    net: float | str,
    mfe: float | str,
    mae: float | str,
    holding_days: int,
    entry_touched: bool,
    target_touched: bool,
    stop_touched: bool,
    target_before_stop: bool,
) -> dict:
    return {
        "journal_id": journal_id,
        "status": status,
        "outcome": outcome,
        "net_pnl_pct": net,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "bars_held": holding_days,
        "failure_reason": failure_reason,
        "entryTouched": entry_touched,
        "targetTouched": target_touched,
        "stopTouched": stop_touched,
        "targetBeforeStop": target_before_stop,
        "maxFavorableExcursion": mfe,
        "maxAdverseExcursion": mae,
        "holdingDays": holding_days,
        "failureReason": failure_reason,
        "regime_at_entry": "RISK_ON",
        "evaluated_at": "2026-06-21T16:00:00",
    }


def test_failure_analytics_summarizes_touch_reasons() -> None:
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [
            _journal_row("j1", "kr", "balanced", "swing", 82),
            _journal_row("j2", "kr", "balanced", "swing", 44),
            _journal_row("j3", "us", "aggressive", "short", 62),
            _journal_row("j4", "kr", "conservative", "mid", 55),
        ],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            _eval_row("j1", "EVALUATED", "TARGET_HIT", "TARGET_BEFORE_STOP", 8, 10, -1, 4, True, True, False, True),
            _eval_row("j2", "EVALUATED", "STOP_HIT", "STOP_BEFORE_TARGET", -4, 2, -6, 2, True, False, True, False),
            _eval_row("j3", "CANCELLED", "CANCELLED_NOT_FILLED", "ENTRY_NOT_TOUCHED", "", "", "", 0, False, False, False, False),
            _eval_row("j4", "DATA_PENDING", "DATA_PENDING", "DATA_MISSING", "", "", "", 0, False, False, False, False),
        ],
        vtj.EVALUATION_COLS,
    )

    out = tfa.build_failure_analytics(market="all")

    assert out["status"] == "OK"
    assert out["summary"]["totalTrades"] == 4
    assert out["summary"]["evaluatedTrades"] == 3
    assert out["summary"]["entryTouchedTrades"] == 2
    assert out["summary"]["targetBeforeStopTrades"] == 1
    assert out["summary"]["stopBeforeTargetTrades"] == 1
    assert out["summary"]["entryNotTouchedTrades"] == 2
    assert out["summary"]["dataIssueTrades"] == 1
    assert out["summary"]["entryTouchedRate"] == 0.5
    assert out["summary"]["targetBeforeStopRate"] == 0.25
    assert out["summary"]["stopBeforeTargetRate"] == 0.25
    assert out["summary"]["avgMFE"] == 6.0
    assert out["summary"]["avgMAE"] == -3.5

    by_reason = {row["failureReason"]: row for row in out["failureReasons"]}
    assert by_reason["TARGET_BEFORE_STOP"]["avgReturn"] == 8.0
    assert by_reason["STOP_BEFORE_TARGET"]["winRate"] == 0.0
    assert by_reason["ENTRY_NOT_TOUCHED"]["entryTouchedRate"] == 0.0
    assert any(row["market"] == "kr" and row["mode"] == "balanced" and row["setupBucket"] == "setup_high" for row in out["groups"])


def test_failure_analytics_filters_market_and_mode() -> None:
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [
            _journal_row("kr1", "kr", "balanced", "swing", 80),
            _journal_row("us1", "us", "balanced", "swing", 80),
        ],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            _eval_row("kr1", "EVALUATED", "STOP_HIT", "STOP_BEFORE_TARGET", -2, 1, -4, 2, True, False, True, False),
            _eval_row("us1", "EVALUATED", "TARGET_HIT", "TARGET_BEFORE_STOP", 5, 7, -1, 3, True, True, False, True),
        ],
        vtj.EVALUATION_COLS,
    )

    out = tfa.build_failure_analytics(market="kr", mode="balanced")

    assert out["summary"]["totalTrades"] == 1
    assert out["summary"]["stopBeforeTargetTrades"] == 1
    assert out["summary"]["targetBeforeStopTrades"] == 0
    assert out["failureReasons"][0]["failureReason"] == "STOP_BEFORE_TARGET"


def test_failure_reason_labels_are_specific_and_safe() -> None:
    assert tfa.failure_reason_label("UNKNOWN") == "원인 미분류"
    assert tfa.failure_reason_label("STOP_TOO_TIGHT") == "손절폭 과소"
    assert tfa.failure_reason_label("OVEREXTENDED_ENTRY") == "과열 구간 진입"
    assert tfa.failure_reason_label("MARKET_GAP") == "갭 변동 영향"
    assert tfa.failure_reason_label("BRAND_NEW_REASON") == "미정의 원인 (BRAND_NEW_REASON)"


def test_failure_analytics_labels_new_diagnostic_reasons() -> None:
    reasons = ["STOP_TOO_TIGHT", "OVEREXTENDED_ENTRY", "MARKET_GAP", "UNKNOWN"]
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [_journal_row(f"l{i}", "kr", "balanced", "swing", 70) for i, _ in enumerate(reasons)],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            _eval_row(f"l{i}", "EVALUATED", reason, reason, -2, 3, -4, 2, True, False, True, False)
            for i, reason in enumerate(reasons)
        ],
        vtj.EVALUATION_COLS,
    )

    out = tfa.build_failure_analytics(market="kr")
    labels = {row["failureReason"]: row["label"] for row in out["failureReasons"]}

    assert labels["UNKNOWN"] == "원인 미분류"
    assert labels["STOP_TOO_TIGHT"] == "손절폭 과소"
    assert labels["OVEREXTENDED_ENTRY"] == "과열 구간 진입"
    assert labels["MARKET_GAP"] == "갭 변동 영향"
    assert labels["STOP_TOO_TIGHT"] != labels["UNKNOWN"]


def test_failure_analytics_handles_missing_columns_without_500() -> None:
    vtj.JOURNAL_CSV.parent.mkdir(parents=True, exist_ok=True)
    vtj.EVALUATION_CSV.parent.mkdir(parents=True, exist_ok=True)
    vtj.JOURNAL_CSV.write_text("journal_id,market,mode,horizon,source_type,journal_session\nm1,kr,balanced,swing,FORWARD_PAPER_TRADE,AFTER_CLOSE_TRADE\n", encoding="utf-8")
    vtj.EVALUATION_CSV.write_text("journal_id,status,outcome\nm1,DATA_PENDING,DATA_PENDING\n", encoding="utf-8")

    out = tfa.build_failure_analytics(market="kr")

    assert out["status"] == "OK"
    assert out["summary"]["totalTrades"] == 1
    assert out["summary"]["dataIssueTrades"] == 1
    assert out["failureReasons"][0]["failureReason"] == "DATA_MISSING"


def test_failure_analytics_api_returns_safe_empty_response() -> None:
    import app.main as main

    out = main.api_virtual_failure_analytics(market="kr", mode="balanced", horizon="swing")

    assert out["status"] == "OK"
    assert "summary" in out
    assert out["summary"]["totalTrades"] == 0
