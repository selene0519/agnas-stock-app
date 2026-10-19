from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import virtual_trade_journal as vtj  # noqa: E402


def _verdict(monkeypatch, run: dict) -> dict:
    monkeypatch.setattr(
        vtj,
        "_read_auto_status",
        lambda: {"status": "OK", "enabled": True, "lastRunAt": "now", "runs": [run]},
    )
    journal = [{"journal_id": "j1", "status": "EVALUATED", "source_type": "FORWARD_PAPER_TRADE"}]
    evaluations = [{"journal_id": "j1", "status": "EVALUATED", "evaluated_at": "now"}]
    return vtj._journal_operational_verdict(
        raw_journal_rows=journal,
        merged_rows=journal,
        evaluation_rows=evaluations,
        warnings=[],
        self_status={"status": "OK"},
        perf_gate={"status": "PASS"},
    )


def test_duplicate_only_capture_is_not_reported_as_market_closed(monkeypatch) -> None:
    result = _verdict(
        monkeypatch,
        {"status": "OK", "selected": 0, "researchSelected": 4, "added": 0, "items": [{"duplicates": 4}]},
    )
    assert result["captureActivity"]["status"] == "ALREADY_RECORDED"
    assert result["captureActivity"]["pipelineStatus"] == "OK"


def test_closed_market_is_reported_only_for_closed_market_status(monkeypatch) -> None:
    result = _verdict(monkeypatch, {"status": "SKIPPED_MARKET_CLOSED", "added": 0})
    assert result["captureActivity"]["status"] == "MARKET_CLOSED"


def test_exchange_calendar_excludes_korean_and_us_holidays() -> None:
    assert vtj._is_trading_day("kr", "2026-10-09") is False
    assert vtj._is_trading_day("us", "2026-06-19") is False
    assert vtj._is_trading_day("kr", "2026-10-19") is True


def test_learning_progress_does_not_confuse_successful_run_with_applied_correction() -> None:
    quality = {"currentIdentityWindowSamples": 1, "distinctSignalDates": 1, "gates": [
        {"name": "effective_samples", "status": "LOW_SAMPLE", "value": 1, "target": 40},
        {"name": "fingerprint", "status": "PASS", "value": 1, "target": 0.95},
    ]}
    progress = vtj._learning_progress(quality, [{"reason": "LOW_HOLDOUT"}, {"reason": "LOW_HOLDOUT"}], 0, 0, True)
    assert progress["state"] == "COLLECTING_EVIDENCE"
    assert progress["identityWindowSamples"] == 1
    assert progress["suggestionBlockers"] == [{"reason": "LOW_HOLDOUT", "count": 2}]
    assert [gate["name"] for gate in progress["gateBlockers"]] == ["effective_samples"]
    assert vtj._learning_progress(quality, [], 1, 0, True)["state"] == "AWAITING_PROMOTION"
    assert vtj._learning_progress(quality, [], 0, 1, True)["state"] == "APPLIED"
