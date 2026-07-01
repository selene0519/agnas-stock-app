"""Tests for cold-start / coverage-gap performance gate fix.

Validates that:
- Genuine poor performance still triggers BLOCKED_LOW_WIN_RATE (gate preserved)
- Low sample count (< 30) → CAUTION_LOW_SAMPLE, no block
- Coverage-gap state (many close_exit placeholders, few meaningful rows) → COVERAGE_GAP, no block
- COVERAGE_GAP downgrade: "오늘 진입" items lose that bucket label → "관찰"
- _public_quant_verdict skips strategy hard-gates in data-gap statuses
- ev=None in data-gap → caution, not reason
- US recommendations use the same gate logic without KR-specific side-effects
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.engine.mone_v65_api_stabilizer import (  # noqa: E402
    _apply_recommendation_performance_safety,
    _is_placeholder_completion,
    _public_quant_verdict,
    _recommendation_performance_safety,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _dashboard(
    completed: int,
    wins: int,
    avg_return: float,
    meaningful_completed: int | None = None,
    placeholder_count: int | None = None,
    meaningful_win_rate: float | None = None,
    meaningful_avg_return: float | None = None,
) -> dict[str, Any]:
    """Build a minimal dashboard payload with one key (balanced_swing)."""
    mc = meaningful_completed if meaningful_completed is not None else completed
    pc = placeholder_count if placeholder_count is not None else 0
    win_rate = round(wins / completed * 100, 1) if completed else None
    mwr = meaningful_win_rate if meaningful_win_rate is not None else win_rate
    mar = meaningful_avg_return if meaningful_avg_return is not None else avg_return
    return {
        "stats": {
            "balanced_swing": {
                "completed": completed,
                "wins": wins,
                "winRate": win_rate,
                "avgReturn": avg_return,
                "meaningfulCompleted": mc,
                "placeholderCount": pc,
                "meaningfulWinRate": mwr,
                "meaningfulAvgReturn": mar,
                "sampleStatus": "SUFFICIENT" if completed >= 30 else "LOW_SAMPLE",
            }
        }
    }


def _perf(status: str, blocked: bool, **extra) -> dict[str, Any]:
    return {"status": status, "isTradeBlocked": blocked, "completed": 30, "meaningfulCompleted": 10, **extra}


def _item(**kwargs) -> dict[str, Any]:
    base = {
        "symbol": "005930",
        "decisionBucket": "오늘 진입",
        "entry": 70000,
        "stop": 66500,
        "target": 80000,
        "isTradeBlocked": False,
    }
    base.update(kwargs)
    return base


# ── _is_placeholder_completion ────────────────────────────────────────────────

def test_placeholder_detection_close_exit_tiny_return():
    r = {"result": "close_exit", "returnPct": -0.09}
    assert _is_placeholder_completion(r) is True


def test_placeholder_detection_real_loss_not_flagged():
    r = {"result": "close_exit", "returnPct": -1.41}
    assert _is_placeholder_completion(r) is False


def test_placeholder_detection_stop_hit_not_flagged():
    r = {"result": "stop_hit", "returnPct": -0.09}
    assert _is_placeholder_completion(r) is False


def test_placeholder_detection_win_not_flagged():
    r = {"result": "target_hit", "returnPct": 3.5}
    assert _is_placeholder_completion(r) is False


# ── _recommendation_performance_safety ───────────────────────────────────────

MODULE = "app.engine.mone_v65_api_stabilizer._validation_dashboard_payload"


def test_gate_low_sample_no_block():
    """completed < 30 → CAUTION_LOW_SAMPLE, no trade block."""
    with patch(MODULE, return_value=_dashboard(10, 4, -0.5)):
        result = _recommendation_performance_safety("kr", "balanced", "swing")
    assert result["status"] == "CAUTION_LOW_SAMPLE"
    assert result["isTradeBlocked"] is False


def test_gate_coverage_gap_no_block():
    """completed >= 30 but meaningfulCompleted < 10 → COVERAGE_GAP, no block."""
    with patch(MODULE, return_value=_dashboard(
        completed=98, wins=10, avg_return=-0.09,
        meaningful_completed=2, placeholder_count=96,
        meaningful_win_rate=None, meaningful_avg_return=None,
    )):
        result = _recommendation_performance_safety("kr", "balanced", "swing")
    assert result["status"] == "COVERAGE_GAP"
    assert result["isTradeBlocked"] is False


def test_gate_ok_passes():
    """Healthy data → OK, no block."""
    with patch(MODULE, return_value=_dashboard(
        completed=50, wins=22, avg_return=1.2,
        meaningful_completed=50, placeholder_count=0,
        meaningful_win_rate=44.0, meaningful_avg_return=1.2,
    )):
        result = _recommendation_performance_safety("kr", "balanced", "swing")
    assert result["status"] == "OK"
    assert result["isTradeBlocked"] is False


def test_gate_genuine_poor_performance_blocks():
    """Real poor performance (winRate < 35, avg < -1) → BLOCKED_LOW_WIN_RATE."""
    with patch(MODULE, return_value=_dashboard(
        completed=60, wins=18, avg_return=-2.5,
        meaningful_completed=55, placeholder_count=5,
        meaningful_win_rate=30.0, meaningful_avg_return=-2.5,
    )):
        result = _recommendation_performance_safety("kr", "balanced", "swing")
    assert result["status"] == "BLOCKED_LOW_WIN_RATE"
    assert result["isTradeBlocked"] is True


def test_gate_tiny_negative_avg_return_not_blocked():
    """avgReturn = -0.09% (placeholder noise) must NOT trigger block.
    Even if meaningfulCompleted is adequate, threshold is -1.0%, not 0."""
    with patch(MODULE, return_value=_dashboard(
        completed=50, wins=20, avg_return=-0.09,
        meaningful_completed=30, placeholder_count=20,
        meaningful_win_rate=40.0, meaningful_avg_return=0.5,
    )):
        result = _recommendation_performance_safety("kr", "balanced", "swing")
    assert result["isTradeBlocked"] is False


def test_gate_exception_returns_unknown_status():
    """If dashboard raises, gate must return CAUTION_PERFORMANCE_UNKNOWN (no block)."""
    with patch(MODULE, side_effect=RuntimeError("file missing")):
        result = _recommendation_performance_safety("kr", "balanced", "swing")
    assert result["status"] == "CAUTION_PERFORMANCE_UNKNOWN"
    assert result["isTradeBlocked"] is False


# ── _apply_recommendation_performance_safety ──────────────────────────────────

def test_apply_coverage_gap_no_hard_block_and_downgrade():
    """COVERAGE_GAP → no block, '오늘 진입' → '관찰'."""
    payload = {
        "items": [
            _item(decisionBucket="오늘 진입"),
            _item(decisionBucket="관찰"),
        ]
    }
    with patch(MODULE, return_value=_dashboard(
        completed=98, wins=10, avg_return=-0.09,
        meaningful_completed=2, placeholder_count=96,
    )):
        result = _apply_recommendation_performance_safety(payload, "kr", "balanced", "swing")

    items = result["items"]
    assert items[0]["decisionBucket"] == "관찰"
    assert items[0].get("decisionBucketOriginal") == "오늘 진입"
    assert items[1]["decisionBucket"] == "관찰"  # already 관찰, unchanged
    assert result.get("blockedCount", 0) == 0
    for item in items:
        assert not item.get("isTradeBlocked")
        assert item["performanceGateStatus"] == "COVERAGE_GAP"
        assert item["performanceFallbackApplied"] is True


def test_apply_blocked_sets_is_trade_blocked():
    """BLOCKED_LOW_WIN_RATE → all items get isTradeBlocked=True."""
    payload = {"items": [_item(), _item(symbol="000660")]}
    with patch(MODULE, return_value=_dashboard(
        completed=60, wins=18, avg_return=-2.5,
        meaningful_completed=55, placeholder_count=5,
        meaningful_win_rate=30.0, meaningful_avg_return=-2.5,
    )):
        result = _apply_recommendation_performance_safety(payload, "kr", "balanced", "swing")

    for item in result["items"]:
        assert item["isTradeBlocked"] is True
        assert item["tradeBlockStatus"] == "PERFORMANCE_GATE_BLOCK"


def test_apply_ok_status_no_block():
    """OK → items pass through without isTradeBlocked."""
    payload = {"items": [_item()]}
    with patch(MODULE, return_value=_dashboard(
        completed=50, wins=22, avg_return=1.2,
        meaningful_completed=50, placeholder_count=0,
        meaningful_win_rate=44.0, meaningful_avg_return=1.2,
    )):
        result = _apply_recommendation_performance_safety(payload, "kr", "balanced", "swing")

    assert not result["items"][0].get("isTradeBlocked")
    assert result["items"][0]["performanceFallbackApplied"] is False


# ── _public_quant_verdict ─────────────────────────────────────────────────────

def _trade_safety_ok() -> dict[str, Any]:
    return {"status": "OK", "isTradeBlocked": False, "reviewOnly": False, "reason": ""}


def test_quant_verdict_coverage_gap_skips_strategy_gates():
    """COVERAGE_GAP performance → no hard strategy reasons, only caution."""
    performance = _perf("COVERAGE_GAP", False, winRate=None, avgReturn=None,
                        meaningfulCompleted=2)
    item = _item(expectedValue=None, calibrationCount=0)
    verdict = _public_quant_verdict(item, performance, _trade_safety_ok(), cash=10_000_000)
    strategy_hard_reasons = [
        r for r in verdict["reasons"]
        if "strategy sample" in r or "strategy win rate" in r or "strategy average return" in r
    ]
    assert not strategy_hard_reasons, f"Unexpected strategy hard reasons: {strategy_hard_reasons}"
    assert any("COVERAGE_GAP" in c for c in verdict["cautions"])


def test_quant_verdict_ev_none_in_coverage_gap_is_caution():
    """ev=None in COVERAGE_GAP → caution, not reason."""
    performance = _perf("COVERAGE_GAP", False, winRate=None, avgReturn=None,
                        meaningfulCompleted=2)
    item = _item(expectedValue=None, calibrationCount=0)
    verdict = _public_quant_verdict(item, performance, _trade_safety_ok(), cash=10_000_000)
    ev_reasons = [r for r in verdict["reasons"] if "expected value" in r]
    ev_cautions = [c for c in verdict["cautions"] if "expected value" in c]
    assert not ev_reasons, f"ev=None should not be a reason in COVERAGE_GAP: {ev_reasons}"
    assert ev_cautions, "ev=None should surface as caution in COVERAGE_GAP"


def test_quant_verdict_ev_none_outside_gap_is_reason():
    """ev=None when data is sufficient → still a hard reason."""
    performance = _perf("OK", False, winRate=45.0, avgReturn=1.2, meaningfulCompleted=50)
    item = _item(expectedValue=None, calibrationCount=0)
    verdict = _public_quant_verdict(item, performance, _trade_safety_ok(), cash=10_000_000)
    ev_reasons = [r for r in verdict["reasons"] if "expected value" in r]
    assert ev_reasons, "ev=None should be a reason when performance is OK"


def test_quant_verdict_low_sample_skips_strategy_gates():
    """CAUTION_LOW_SAMPLE → same skip behavior as COVERAGE_GAP."""
    performance = _perf("CAUTION_LOW_SAMPLE", False, winRate=None, avgReturn=None,
                        meaningfulCompleted=5)
    item = _item(expectedValue=None, calibrationCount=0)
    verdict = _public_quant_verdict(item, performance, _trade_safety_ok(), cash=10_000_000)
    strategy_hard = [r for r in verdict["reasons"]
                     if "strategy sample" in r or "strategy win rate" in r]
    assert not strategy_hard


def test_quant_verdict_genuine_block_still_blocks():
    """BLOCKED_LOW_WIN_RATE with real data → remains blocked via isTradeBlocked."""
    performance = _perf("BLOCKED_LOW_WIN_RATE", True, winRate=30.0, avgReturn=-2.5,
                        meaningfulCompleted=55, reason="winRate below gate")
    item = _item(isTradeBlocked=True, tradeBlockReason="performance gate block",
                 tradeBlockStatus="PERFORMANCE_GATE_BLOCK", expectedValue=1.5, calibrationCount=35,
                 calibratedWinRate=46.0)
    verdict = _public_quant_verdict(item, performance, _trade_safety_ok(), cash=10_000_000)
    assert verdict["status"] == "NO_TRADE"
    assert any("performance gate block" in r.lower() or "trade block" in r.lower()
               for r in verdict["reasons"])


def test_quant_verdict_us_not_affected_by_coverage_gap():
    """US OK status → no COVERAGE_GAP caution injection."""
    performance = _perf("OK", False, winRate=48.0, avgReturn=1.5, meaningfulCompleted=60)
    item = _item(expectedValue=1.2, calibrationCount=35, calibratedWinRate=47.0)
    verdict = _public_quant_verdict(item, performance, _trade_safety_ok(), cash=10_000_000)
    gap_cautions = [c for c in verdict["cautions"] if "COVERAGE_GAP" in c]
    assert not gap_cautions
