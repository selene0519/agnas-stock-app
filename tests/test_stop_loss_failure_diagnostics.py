from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import stop_loss_failure_diagnostics as sld  # noqa: E402
from app.services import virtual_trade_journal as vtj  # noqa: E402


def _journal_row(
    journal_id: str,
    market: str = "kr",
    mode: str = "balanced",
    horizon: str = "swing",
    setup_score: float = 70,
    overextension_risk: float = 20,
    momentum_score: float = 65,
) -> dict:
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
        "raw_recommendation_json": json.dumps(
            {
                "setupScore": setup_score,
                "overextensionRisk": overextension_risk,
                "momentumContinuationScore": momentum_score,
                "finalScore": 72,
                "decisionBucket": "TODAY_ENTRY",
            }
        ),
    }


def _eval_row(
    journal_id: str,
    reason: str,
    status: str = "EVALUATED",
    net: float | str = -4,
    mfe: float | str = 3,
    mae: float | str = -7,
    entry_touched: bool = True,
    target_touched: bool = False,
    stop_touched: bool = True,
    target_before_stop: bool = False,
) -> dict:
    return {
        "journal_id": journal_id,
        "status": status,
        "outcome": reason,
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


def test_stop_loss_diagnostics_excludes_pending_and_data_quality_rows() -> None:
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [_journal_row(f"r{i}") for i in range(5)],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            _eval_row("r0", "STOP_TOO_TIGHT"),
            _eval_row("r1", "TARGET_BEFORE_STOP", net=8, mfe=10, mae=-1, target_touched=True, stop_touched=False, target_before_stop=True),
            _eval_row("r2", "INSUFFICIENT_HOLDING_PERIOD", status="PENDING", net="", mfe=2, mae=-1, stop_touched=False),
            _eval_row("r3", "NO_FUTURE_BARS_YET", status="DATA_PENDING", net="", mfe="", mae="", stop_touched=False),
            _eval_row("r4", "DATA_MISSING", status="DATA_PENDING", net="", mfe="", mae="", stop_touched=False),
        ],
        vtj.EVALUATION_COLS,
    )

    out = sld.build_stop_loss_diagnostics(market="kr")

    assert out["status"] == "OK"
    assert out["summary"]["totalEvaluatedTrades"] == 2
    assert out["summary"]["stopFailureTrades"] == 1
    assert out["summary"]["stopTooTightCount"] == 1
    assert out["summary"]["stopBeforeTargetCount"] == 0


def test_stop_loss_diagnostics_counts_only_stop_failure_reasons() -> None:
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [_journal_row(f"s{i}") for i in range(5)],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            _eval_row("s0", "STOP_TOO_TIGHT"),
            _eval_row("s1", "STOP_BEFORE_TARGET"),
            _eval_row("s2", "MARKET_GAP"),
            _eval_row("s3", "OVEREXTENDED_ENTRY"),
            _eval_row("s4", "TARGET_NOT_REACHED", net=1, mfe=6, mae=-3, stop_touched=False),
        ],
        vtj.EVALUATION_COLS,
    )

    out = sld.build_stop_loss_diagnostics(market="kr")

    assert out["summary"]["totalEvaluatedTrades"] == 5
    assert out["summary"]["stopFailureTrades"] == 2
    assert out["summary"]["stopFailureRate"] == 0.4
    assert out["summary"]["stopTooTightRate"] == 0.2
    assert out["summary"]["stopBeforeTargetRate"] == 0.2


def test_stop_loss_diagnostics_calculates_gap_and_overextension_associations() -> None:
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [
            _journal_row("h0", overextension_risk=90),
            _journal_row("h1", overextension_risk=85),
            _journal_row("h2", overextension_risk=10),
            _journal_row("h3", overextension_risk=15),
        ],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            _eval_row("h0", "STOP_TOO_TIGHT"),
            _eval_row("h1", "STOP_BEFORE_TARGET"),
            _eval_row("h2", "MARKET_GAP"),
            _eval_row("h3", "TARGET_BEFORE_STOP", net=8, mfe=10, mae=-1, target_touched=True, stop_touched=False, target_before_stop=True),
        ],
        vtj.EVALUATION_COLS,
    )

    out = sld.build_stop_loss_diagnostics(market="kr")
    overextension_high = next(row for row in out["dimensions"]["byOverextensionRisk"] if row["overextensionRisk"] == "high")
    market_gap = next(row for row in out["dimensions"]["byMarketGap"] if row["marketGap"] == "true")

    assert overextension_high["count"] == 2
    assert overextension_high["stopFailureRate"] == 1.0
    assert market_gap["count"] == 1
    assert market_gap["stopFailureRate"] == 0.0


def test_stop_loss_diagnostics_keeps_patch_disabled_without_validation() -> None:
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [_journal_row(f"p{i}", overextension_risk=90) for i in range(6)],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [_eval_row(f"p{i}", "STOP_TOO_TIGHT") for i in range(6)],
        vtj.EVALUATION_COLS,
    )

    out = sld.build_stop_loss_diagnostics(market="kr")

    assert out["appliedPatch"] is False
    assert out["patchType"] == "diagnostic_only"
    assert out["shouldModifyTradingLogicNow"] is False
    assert out["patch"]["backtest"]["actionDowngradeCount"] == 0


def test_stop_loss_diagnostics_api_empty_response_is_safe() -> None:
    import app.main as main

    out = main.api_virtual_stop_loss_diagnostics(market="kr", mode="balanced", horizon="swing")

    assert out["status"] == "OK"
    assert out["summary"]["totalEvaluatedTrades"] == 0
    assert out["appliedPatch"] is False
