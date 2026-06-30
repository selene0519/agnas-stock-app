from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import entry_timing_safety as ets  # noqa: E402
from app.services import virtual_trade_journal as vtj  # noqa: E402


def _journal_row(
    journal_id: str,
    market: str = "kr",
    mode: str = "balanced",
    horizon: str = "swing",
    action: str = "BUY",
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
        "decision_bucket": "TODAY_ENTRY" if action in {"BUY", "STRONG_BUY"} else "WATCH_ENTRY",
        "entry_type": "LIMIT_TOUCH",
        "entry_price": 100,
        "stop_price": 95,
        "target_price": 110,
        "data_status": "NORMAL",
        "data_confidence": "HIGH",
        "market_regime_at_signal": "RISK_ON",
        "raw_recommendation_json": json.dumps(
            {
                "action": action,
                "setupScore": setup_score,
                "overextensionRisk": overextension_risk,
                "momentumContinuationScore": momentum_score,
                "finalScore": 72,
                "decisionBucket": "TODAY_ENTRY" if action in {"BUY", "STRONG_BUY"} else "WATCH_ENTRY",
            }
        ),
    }


def _eval_row(
    journal_id: str,
    reason: str,
    status: str = "EVALUATED",
    net: float | str = -4,
    mfe: float | str = 2,
    mae: float | str = -8,
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


def test_entry_timing_diagnostics_excludes_pending_and_data_quality_rows() -> None:
    vtj._write_rows(vtj.JOURNAL_CSV, [_journal_row(f"e{i}") for i in range(4)], vtj.JOURNAL_COLS)
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            _eval_row("e0", "STOP_TOO_TIGHT"),
            _eval_row("e1", "PENDING_EVALUATION", status="PENDING", net="", mfe="", mae="", stop_touched=False),
            _eval_row("e2", "NO_FUTURE_BARS_YET", status="DATA_PENDING", net="", mfe="", mae="", stop_touched=False),
            _eval_row("e3", "DATA_MISSING", status="DATA_PENDING", net="", mfe="", mae="", stop_touched=False),
        ],
        vtj.EVALUATION_COLS,
    )

    out = ets.build_entry_timing_diagnostics(market="kr")

    assert out["summary"]["totalEvaluatedTrades"] == 1
    assert out["summary"]["entryTimingRiskTrades"] == 1
    assert out["summary"]["stopFailureTrades"] == 1


def test_stop_reasons_and_overextension_raise_high_risk_and_wait_pullback_preview() -> None:
    vtj._write_rows(vtj.JOURNAL_CSV, [_journal_row("risk", action="BUY", overextension_risk=90, momentum_score=20)], vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, [_eval_row("risk", "STOP_TOO_TIGHT", mfe=1, mae=-9)], vtj.EVALUATION_COLS)

    out = ets.build_entry_timing_diagnostics(market="kr")
    trade = out["affectedTrades"][0]

    assert trade["entryTimingRiskScore"] >= 4
    assert trade["entryTimingRiskLevel"] == "HIGH"
    assert trade["recommendedSafetyAction"] == "WAIT_PULLBACK"
    assert trade["entryTimingGuardApplied"] is False
    assert out["shouldModifyTradingLogicNow"] is False


def test_market_gap_is_kept_as_entry_timing_risk_reason() -> None:
    row = {**_journal_row("gap", action="WATCH"), **_eval_row("gap", "MARKET_GAP", mfe=2, mae=-7)}

    risk = ets.compute_entry_timing_risk(row)

    assert "MARKET_GAP" in risk["entryTimingRiskReasons"]
    assert risk["entryTimingRiskLevel"] in {"MEDIUM", "HIGH"}


def test_low_risk_action_is_not_changed() -> None:
    row = {**_journal_row("ok", action="WATCH", overextension_risk=10, momentum_score=80), **_eval_row("ok", "TARGET_BEFORE_STOP", net=7, mfe=9, mae=-1, stop_touched=False, target_touched=True, target_before_stop=True)}

    risk = ets.compute_entry_timing_risk(row)

    assert risk["entryTimingRiskLevel"] == "LOW"
    assert risk["adjustedAction"] == risk["originalAction"]
    assert risk["recommendedSafetyAction"] == "NONE"


def test_before_after_replay_is_safe_and_keeps_guard_diagnostic_only_for_small_samples() -> None:
    vtj._write_rows(
        vtj.JOURNAL_CSV,
        [
            _journal_row("r0", action="BUY", overextension_risk=90),
            _journal_row("r1", action="WATCH", overextension_risk=85),
            _journal_row("r2", action="BUY", overextension_risk=10),
        ],
        vtj.JOURNAL_COLS,
    )
    vtj._write_rows(
        vtj.EVALUATION_CSV,
        [
            _eval_row("r0", "STOP_BEFORE_TARGET", mfe=1, mae=-8),
            _eval_row("r1", "OVEREXTENDED_ENTRY", mfe=3, mae=-7, stop_touched=False),
            _eval_row("r2", "TARGET_BEFORE_STOP", net=8, mfe=10, mae=-1, stop_touched=False, target_touched=True, target_before_stop=True),
        ],
        vtj.EVALUATION_COLS,
    )

    out = ets.build_entry_timing_diagnostics(market="kr")

    assert out["beforeAfterReplay"]["evaluatedTrades"] == 3
    assert out["beforeAfterReplay"]["actionDowngradeCount"] >= 1
    assert out["appliedGuard"] is False
    assert out["guardMode"] == "diagnostic_only"
    assert "표본" in out["activationReason"]


def test_entry_timing_api_empty_response_is_safe() -> None:
    import app.main as main

    vtj._write_rows(vtj.JOURNAL_CSV, [], vtj.JOURNAL_COLS)
    vtj._write_rows(vtj.EVALUATION_CSV, [], vtj.EVALUATION_COLS)

    out = main.api_virtual_entry_timing_diagnostics(market="kr", mode="balanced", horizon="swing")

    assert out["status"] == "OK"
    assert out["summary"]["totalEvaluatedTrades"] == 0
    assert out["appliedGuard"] is False
    assert out["shouldModifyTradingLogicNow"] is False
