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


def test_improvement_priorities_treat_pending_reasons_as_evaluation_coverage() -> None:
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [_journal_row(f"wait{i}") for i in range(4)],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            _eval_row("wait0", "NO_FUTURE_BARS_YET", "", "", "", False, False, False),
            _eval_row("wait1", "PENDING_EVALUATION", "", "", "", False, False, False),
            _eval_row("wait2", "INSUFFICIENT_HOLDING_PERIOD", "", 4, -1, True, False, False),
            _eval_row("wait3", "TARGET_BEFORE_STOP", 6, 8, -1, True, True, False, True),
        ],
        vtj.EVALUATION_COLS,
    )

    out = tip.build_improvement_priorities(market="kr")
    first = out["priorities"][0]

    assert first["issueType"] == "EVALUATION_COVERAGE_PENDING"
    assert first["affectedArea"] == "evaluationCoverage"
    assert first["evidence"]["ratio"] == 0.75
    assert first["shouldModifyTradingLogicNow"] is False


def test_improvement_priorities_use_evaluated_only_ratios_for_outcome_issues() -> None:
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [_journal_row(f"s{i}") for i in range(10)],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            *[_eval_row(f"s{i}", "INSUFFICIENT_HOLDING_PERIOD", "", "", "", False, False, False) for i in range(5)],
            _eval_row("s5", "STOP_TOO_TIGHT", -3, 2, -6, True, False, True),
            _eval_row("s6", "STOP_TOO_TIGHT", -2, 3, -5, True, False, True),
            _eval_row("s7", "STOP_TOO_TIGHT", -4, 1, -7, True, False, True),
            _eval_row("s8", "STOP_BEFORE_TARGET", -5, 2, -8, True, False, True),
            _eval_row("s9", "TARGET_BEFORE_STOP", 8, 10, -1, True, True, False, True),
        ],
        vtj.EVALUATION_COLS,
    )

    out = tip.build_improvement_priorities(market="kr")
    stop_issue = next(item for item in out["priorities"] if item["issueType"] == "STOP_BEFORE_TARGET_HIGH")

    assert out["summary"]["totalTrades"] == 10
    assert out["summary"]["evaluatedTrades"] == 5
    assert out["summary"]["pendingTrades"] == 5
    assert stop_issue["evidence"]["count"] == 4
    assert stop_issue["evidence"]["conditionRate"] == 0.8
    assert stop_issue["evidence"]["overallRatio"] == 0.4
    assert stop_issue["safeNextStep"].startswith("추천 로직을 바꾸지 말고")
    assert stop_issue["shouldModifyTradingLogicNow"] is False


def test_improvement_priorities_groups_new_data_quality_reasons() -> None:
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [_journal_row(f"dq{i}") for i in range(3)],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            _eval_row("dq0", "MISSING_ENTRY_PRICE", "", "", "", False),
            _eval_row("dq1", "MISSING_TARGET_OR_STOP", "", "", "", False),
            _eval_row("dq2", "SYMBOL_OR_DATE_MISMATCH", "", "", "", False),
        ],
        vtj.EVALUATION_COLS,
    )

    out = tip.build_improvement_priorities(market="kr")
    data_issue = next(item for item in out["priorities"] if item["issueType"] == "DATA_QUALITY_PROBLEM")

    assert data_issue["evidence"]["count"] == 3
    assert data_issue["recommendation"] == "가격/결과 데이터 수집 품질 점검 필요"
    assert data_issue["shouldModifyTradingLogicNow"] is False


def test_improvement_priority_evidence_splits_overall_and_condition_ratios() -> None:
    total = 484
    evaluated = 99
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [_journal_row(f"p{i}") for i in range(total)],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            _eval_row(
                f"p{i}",
                "UNKNOWN",
                net=-1,
                mfe=5.5,
                mae=-6.0,
                entry_touched=True,
                target_touched=False,
                stop_touched=False,
                target_before_stop=False,
            )
            for i in range(evaluated)
        ],
        vtj.EVALUATION_COLS,
    )

    out = tip.build_improvement_priorities(market="kr")
    missed = next(item for item in out["priorities"] if item["issueType"] == "MISSED_PROFIT_CAPTURE")
    evidence = missed["evidence"]

    assert evidence["count"] == evaluated
    assert evidence["ratio"] == 1.0
    assert evidence["conditionRate"] == 1.0
    assert evidence["overallRatio"] == 0.2045
    assert evidence["totalTrades"] == total
    assert evidence["evaluatedTrades"] == evaluated


def test_improvement_priority_evidence_handles_zero_total() -> None:
    evidence = tip._evidence({"count": 99, "ratio": 1.0}, {"totalTrades": 0, "evaluatedTrades": 0})

    assert evidence["overallRatio"] == 0.0
    assert evidence["conditionRate"] == 1.0
    assert evidence["totalTrades"] == 0


def test_improvement_priorities_empty_api_response_is_safe() -> None:
    import app.main as main

    out = main.api_virtual_improvement_priorities(market="kr", mode="balanced", horizon="swing")

    assert out["status"] == "OK"
    assert out["priorities"] == []
    assert out["summary"]["shouldModifyTradingLogicNow"] is False
