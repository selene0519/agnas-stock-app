from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import trade_improvement_priorities as tip  # noqa: E402
from app.services import virtual_trade_journal as vtj  # noqa: E402


def _journal_row(journal_id: str, market: str = "kr", mode: str = "balanced", regime: str = "RISK_ON", bucket: str = "TODAY_ENTRY") -> dict:
    return {
        "journal_id": journal_id,
        "source_type": "FORWARD_PAPER_TRADE",
        "journal_session": "AFTER_CLOSE_TRADE",
        "as_of_date": "2026-06-20",
        "generated_at": "2026-06-20T16:00:00",
        "captured_at": "2026-06-20T16:05:00",
        "market": market,
        "mode": mode,
        "horizon": "swing",
        "symbol": journal_id.upper(),
        "name": journal_id.upper(),
        "decision_bucket": bucket,
        "entry_type": "LIMIT_TOUCH",
        "entry_price": 100,
        "stop_price": 95,
        "target_price": 110,
        "data_status": "NORMAL",
        "data_confidence": "HIGH",
        "market_regime_at_signal": regime,
        "raw_recommendation_json": json.dumps({"setupScore": 72, "decisionBucket": bucket}),
    }


def _eval_row(
    journal_id: str,
    reason: str,
    net: float | str = -2,
    mfe: float | str = 3,
    mae: float | str = -4,
    entry_touched: bool = True,
    target_touched: bool = False,
    stop_touched: bool = False,
    target_before_stop: bool = False,
) -> dict:
    return {
        "journal_id": journal_id,
        "status": "CANCELLED" if reason == "ENTRY_NOT_TOUCHED" else "EVALUATED",
        "outcome": "CANCELLED_NOT_FILLED" if reason == "ENTRY_NOT_TOUCHED" else reason,
        "net_pnl_pct": net,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "bars_held": 4,
        "failure_reason": reason,
        "entryTouched": entry_touched,
        "targetTouched": target_touched,
        "stopTouched": stop_touched,
        "targetBeforeStop": target_before_stop,
        "maxFavorableExcursion": mfe,
        "maxAdverseExcursion": mae,
        "holdingDays": 4,
        "failureReason": reason,
        "regime_at_entry": "RISK_ON",
        "evaluated_at": "2026-06-21T16:00:00",
    }


def test_improvement_priorities_create_entry_miss_report() -> None:
    journals = [_journal_row(f"e{i}") for i in range(6)]
    evals = [
        _eval_row("e0", "ENTRY_NOT_TOUCHED", "", "", "", False),
        _eval_row("e1", "ENTRY_NOT_TOUCHED", "", "", "", False),
        _eval_row("e2", "ENTRY_NOT_TOUCHED", "", "", "", False),
        _eval_row("e3", "STOP_BEFORE_TARGET", -5, 2, -7, True, False, True),
        _eval_row("e4", "TARGET_NOT_REACHED", 1, 6, -2, True, False, False),
        _eval_row("e5", "TARGET_BEFORE_STOP", 8, 10, -1, True, True, False, True),
    ]
    vtj._write_rows(vtj.JOURNAL_CSV, journals, vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, evals, vtj.EVALUATION_COLS)

    out = tip.build_improvement_priorities(market="kr")

    assert out["status"] == "OK"
    assert out["summary"]["priorityCount"] >= 3
    entry_issue = next(item for item in out["priorities"] if item["issueType"] == "ENTRY_PRICE_TOO_DEEP")
    assert entry_issue["shouldModifyTradingLogicNow"] is False
    assert entry_issue["evidence"]["count"] == 3


def test_improvement_priorities_filter_regime_and_recommendation_bucket() -> None:
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [
            _journal_row("r1", regime="RISK_ON", bucket="TODAY_ENTRY"),
            _journal_row("r2", regime="RISK_OFF", bucket="WATCH"),
        ],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            _eval_row("r1", "STOP_BEFORE_TARGET", -4, 1, -6, True, False, True),
            _eval_row("r2", "ENTRY_NOT_TOUCHED", "", "", "", False),
        ],
        vtj.EVALUATION_COLS,
    )

    out = tip.build_improvement_priorities(market="kr", regime="RISK_ON", recommendation_bucket="TODAY_ENTRY")

    assert out["summary"]["totalTrades"] == 1
    issue_types = {item["issueType"] for item in out["priorities"]}
    assert "STOP_BEFORE_TARGET_HIGH" in issue_types
    assert "HIGH_DRAWDOWN_BEFORE_SUCCESS" in issue_types
    assert "ENTRY_PRICE_TOO_DEEP" not in issue_types


def test_improvement_priorities_handles_missing_columns() -> None:
    vtj.JOURNAL_CSV.parent.mkdir(parents=True, exist_ok=True)
    vtj.EVALUATION_CSV.parent.mkdir(parents=True, exist_ok=True)
    vtj.JOURNAL_CSV.write_text("journal_id,market,mode,horizon,source_type,journal_session\nm1,kr,balanced,swing,FORWARD_PAPER_TRADE,AFTER_CLOSE_TRADE\n", encoding="utf-8")
    vtj.EVALUATION_CSV.write_text("journal_id,status,outcome\nm1,DATA_PENDING,DATA_PENDING\n", encoding="utf-8")

    out = tip.build_improvement_priorities(market="kr")

    assert out["status"] == "OK"
    assert out["priorities"][0]["issueType"] == "DATA_QUALITY_PROBLEM"
    assert out["priorities"][0]["shouldModifyTradingLogicNow"] is False


def test_improvement_priorities_empty_api_response_is_safe() -> None:
    import app.main as main

    out = main.api_virtual_improvement_priorities(market="kr", mode="balanced", horizon="swing")

    assert out["status"] == "OK"
    assert out["priorities"] == []
    assert out["summary"]["shouldModifyTradingLogicNow"] is False
