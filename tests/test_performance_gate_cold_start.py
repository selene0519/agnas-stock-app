"""Tests for the performance gate refactor (net win rate + metric mismatch policy).

Gate decision hierarchy:
  Gate 0 COVERAGE_GAP          – placeholder contamination (close_exit at -0.09%)
  Gate 1 INSUFFICIENT_SAMPLES  – VTJ (swj) sampleCount < minSamplesForUpdate
  Gate 2 DATA_SOURCE_MISMATCH  – netWinRate vs csvMetricWinRate gap ≥ 10pp
  Gate 3 PERFORMANCE_BLOCKED   – genuine underperformance (netWinRate < 35%)
  OK     PERFORMANCE_OK        – all gates passed

Hard-block forbidden conditions:
  - insufficient swj samples
  - stale placeholder contamination (COVERAGE_GAP)
  - metric definition mismatch ≥ 10pp
  - EV unavailable / schema gap
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

# ── Patch targets ─────────────────────────────────────────────────────────────
_DASH = "app.engine.mone_v65_api_stabilizer._validation_dashboard_payload"
_SWJ  = "app.engine.mone_v65_api_stabilizer._load_strategy_win_rates"


# ── Builder helpers ───────────────────────────────────────────────────────────

def _dashboard(
    completed: int = 50,
    wins: int = 20,
    avg_return: float = 0.5,
    meaningful_completed: int | None = None,
    placeholder_count: int | None = None,
    meaningful_win_rate: float | None = None,
    meaningful_avg_return: float | None = None,
) -> dict[str, Any]:
    mc  = meaningful_completed if meaningful_completed is not None else completed
    pc  = placeholder_count    if placeholder_count    is not None else 0
    wr  = round(wins / completed * 100, 1) if completed else None
    mwr = meaningful_win_rate  if meaningful_win_rate  is not None else wr
    mar = meaningful_avg_return if meaningful_avg_return is not None else avg_return
    return {
        "stats": {
            "balanced_swing": {
                "completed":          completed,
                "wins":               wins,
                "winRate":            wr,
                "avgReturn":          avg_return,
                "meaningfulCompleted": mc,
                "placeholderCount":   pc,
                "meaningfulWinRate":  mwr,
                "meaningfulAvgReturn": mar,
                "sampleStatus": "OK" if completed >= 30 else "LOW_SAMPLE",
            }
        }
    }


def _swj(
    net_wr: float = 0.425,
    sample: int = 106,
    min_samples: int = 20,
) -> dict[str, Any]:
    return {
        "minSamplesForUpdate": min_samples,
        "winRates":      {"balanced_swing": net_wr},
        "sampleCounts":  {"balanced_swing": sample},
    }


def _perf(
    status: str,
    hard_blocked: bool,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "status": status,
        "performanceGateStatus": status,
        "isTradeBlocked": hard_blocked,
        "isPerformanceHardBlocked": hard_blocked,
        "completed": 50,
        "meaningfulCompleted": 40,
        "netWinRate": 42.5,
        "netWinRateSampleCount": 106,
        "csvMetricWinRate": 32.0,
        "metricDefinitionMismatch": False,
        "metricMismatchPp": 10.5,
        **extra,
    }


def _item(**kwargs: Any) -> dict[str, Any]:
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


def _trade_safety_ok() -> dict[str, Any]:
    return {"status": "OK", "isTradeBlocked": False, "reviewOnly": False, "reason": ""}


# ── _is_placeholder_completion ────────────────────────────────────────────────

def test_placeholder_detection_close_exit_tiny_return():
    assert _is_placeholder_completion({"result": "close_exit", "returnPct": -0.09}) is True


def test_placeholder_detection_zero_return():
    assert _is_placeholder_completion({"result": "close_exit", "returnPct": 0.0}) is True


def test_placeholder_detection_real_loss_not_flagged():
    assert _is_placeholder_completion({"result": "close_exit", "returnPct": -1.41}) is False


def test_placeholder_detection_stop_hit_not_flagged():
    assert _is_placeholder_completion({"result": "stop_hit", "returnPct": -0.09}) is False


def test_placeholder_detection_positive_close_exit_not_flagged():
    assert _is_placeholder_completion({"result": "close_exit", "returnPct": 3.29}) is False


# ── _recommendation_performance_safety — gate ordering ───────────────────────

def test_gate0_coverage_gap_precedes_swj_check():
    """COVERAGE_GAP fires even when swj looks fine, if placeholder ratio is extreme."""
    with patch(_DASH, return_value=_dashboard(
            completed=98, wins=10, avg_return=-0.09,
            meaningful_completed=2, placeholder_count=96)):
        with patch(_SWJ, return_value=_swj(net_wr=0.45, sample=30)):
            r = _recommendation_performance_safety("kr", "balanced", "swing")
    assert r["status"] == "COVERAGE_GAP"
    assert r["isPerformanceHardBlocked"] is False


def test_gate1_insufficient_swj_samples():
    """Too few VTJ measured trades → INSUFFICIENT_SAMPLES, no block."""
    with patch(_DASH, return_value=_dashboard()):
        with patch(_SWJ, return_value=_swj(net_wr=0.42, sample=10, min_samples=20)):
            r = _recommendation_performance_safety("kr", "balanced", "swing")
    assert r["status"] == "INSUFFICIENT_SAMPLES"
    assert r["isPerformanceHardBlocked"] is False
    assert r["netWinRateSampleCount"] == 10


def test_gate1_missing_swj_file():
    """swj file absent → INSUFFICIENT_SAMPLES (not a crash)."""
    with patch(_DASH, return_value=_dashboard()):
        with patch(_SWJ, return_value={}):
            r = _recommendation_performance_safety("kr", "balanced", "swing")
    assert r["status"] == "INSUFFICIENT_SAMPLES"
    assert r["isPerformanceHardBlocked"] is False


def test_gate2_metric_mismatch_no_block():
    """netWinRate vs csvMetricWinRate gap ≥ 10pp → DATA_SOURCE_MISMATCH, no block."""
    with patch(_DASH, return_value=_dashboard(
            meaningful_win_rate=20.0)):  # csvWR = 20%, swjWR = 42.5% → gap = 22.5pp
        with patch(_SWJ, return_value=_swj(net_wr=0.425, sample=106)):
            r = _recommendation_performance_safety("kr", "balanced", "swing")
    assert r["status"] == "DATA_SOURCE_MISMATCH"
    assert r["isPerformanceHardBlocked"] is False
    assert r["metricDefinitionMismatch"] is True
    assert r["metricMismatchPp"] >= 10.0


def test_gate2_small_gap_does_not_trigger_mismatch():
    """Gap < 10pp → mismatch not triggered → proceeds to gate 3."""
    with patch(_DASH, return_value=_dashboard(
            meaningful_win_rate=36.0)):  # csvWR=36%, swjWR=40.5% → gap=4.5pp
        with patch(_SWJ, return_value=_swj(net_wr=0.405, sample=30)):
            r = _recommendation_performance_safety("kr", "balanced", "swing")
    assert r["status"] == "PERFORMANCE_OK"
    assert r["metricDefinitionMismatch"] is False


def test_gate3_genuine_poor_performance_blocks():
    """Low netWinRate + sufficient samples + no mismatch → PERFORMANCE_BLOCKED."""
    with patch(_DASH, return_value=_dashboard(
            meaningful_win_rate=30.0)):  # gap = 20% - 30% = -10 → wait, swj = 20%
        with patch(_SWJ, return_value=_swj(net_wr=0.20, sample=40)):
            # swjWR=20%, csvWR=30% → gap=swj-csv = -10pp (negative → no mismatch)
            r = _recommendation_performance_safety("kr", "balanced", "swing")
    assert r["status"] == "PERFORMANCE_BLOCKED"
    assert r["isPerformanceHardBlocked"] is True
    assert r["isTradeBlocked"] is True


def test_gate3_not_triggered_when_netwr_adequate():
    """netWinRate ≥ 35% with consistent metrics → PERFORMANCE_OK."""
    with patch(_DASH, return_value=_dashboard(
            meaningful_win_rate=36.0)):  # gap=4.5pp
        with patch(_SWJ, return_value=_swj(net_wr=0.405, sample=30)):
            r = _recommendation_performance_safety("kr", "balanced", "swing")
    assert r["status"] == "PERFORMANCE_OK"
    assert r["isPerformanceHardBlocked"] is False


def test_negative_avg_return_alone_does_not_block():
    """avgReturn ≈ -0.09% (placeholder noise) must NOT trigger PERFORMANCE_BLOCKED.
    The gate now uses netWinRate as primary — avgReturn is diagnostic only."""
    with patch(_DASH, return_value=_dashboard(
            avg_return=-0.09, meaningful_win_rate=36.0)):
        with patch(_SWJ, return_value=_swj(net_wr=0.405, sample=30)):
            r = _recommendation_performance_safety("kr", "balanced", "swing")
    assert r["isPerformanceHardBlocked"] is False


def test_exception_returns_unknown_no_block():
    """If anything raises, gate must return CAUTION_PERFORMANCE_UNKNOWN (no block)."""
    with patch(_DASH, side_effect=RuntimeError("file missing")):
        with patch(_SWJ, side_effect=RuntimeError("swj missing")):
            r = _recommendation_performance_safety("kr", "balanced", "swing")
    assert r["status"] == "CAUTION_PERFORMANCE_UNKNOWN"
    assert r["isPerformanceHardBlocked"] is False


# ── _apply_recommendation_performance_safety ──────────────────────────────────

def test_apply_coverage_gap_downgrades_today_entry():
    """COVERAGE_GAP → no hard block; '오늘 진입' downgraded to '관찰'."""
    payload = {"items": [_item(decisionBucket="오늘 진입"), _item(decisionBucket="관찰")]}
    with patch(_DASH, return_value=_dashboard(
            completed=98, wins=10, avg_return=-0.09,
            meaningful_completed=2, placeholder_count=96)):
        with patch(_SWJ, return_value=_swj(net_wr=0.45, sample=30)):
            result = _apply_recommendation_performance_safety(payload, "kr", "balanced", "swing")

    items = result["items"]
    assert items[0]["decisionBucket"] == "관찰"
    assert items[0].get("decisionBucketOriginal") == "오늘 진입"
    assert items[0]["isPerformanceHardBlocked"] is False
    assert items[0]["performanceFallbackApplied"] is True
    assert result.get("blockedCount", 0) == 0


def test_apply_data_source_mismatch_does_not_downgrade():
    """DATA_SOURCE_MISMATCH → no hard block; '오늘 진입' label KEPT (netWinRate is good)."""
    payload = {"items": [_item(decisionBucket="오늘 진입")]}
    with patch(_DASH, return_value=_dashboard(meaningful_win_rate=17.0)):
        with patch(_SWJ, return_value=_swj(net_wr=0.425, sample=106)):
            result = _apply_recommendation_performance_safety(payload, "kr", "balanced", "swing")

    item = result["items"][0]
    assert item["decisionBucket"] == "오늘 진입"       # NOT downgraded
    assert item["isPerformanceHardBlocked"] is False
    assert item["metricDefinitionMismatch"] is True


def test_apply_performance_blocked_sets_trade_blocked():
    """PERFORMANCE_BLOCKED → isTradeBlocked=True on all items."""
    payload = {"items": [_item(), _item(symbol="000660")]}
    with patch(_DASH, return_value=_dashboard(meaningful_win_rate=25.0)):
        with patch(_SWJ, return_value=_swj(net_wr=0.20, sample=40)):
            result = _apply_recommendation_performance_safety(payload, "kr", "balanced", "swing")

    for item in result["items"]:
        assert item["isTradeBlocked"] is True
        assert item["tradeBlockStatus"] == "PERFORMANCE_GATE_BLOCK"


def test_apply_performance_ok_no_block():
    """PERFORMANCE_OK → items pass through, performanceFallbackApplied=False."""
    payload = {"items": [_item()]}
    with patch(_DASH, return_value=_dashboard(meaningful_win_rate=36.0)):
        with patch(_SWJ, return_value=_swj(net_wr=0.405, sample=30)):
            result = _apply_recommendation_performance_safety(payload, "kr", "balanced", "swing")

    item = result["items"][0]
    assert item["isPerformanceHardBlocked"] is False
    assert item["performanceFallbackApplied"] is False
    assert item.get("isTradeBlocked", False) is False


# ── _public_quant_verdict ─────────────────────────────────────────────────────

def test_quant_verdict_coverage_gap_skips_to_caution():
    """COVERAGE_GAP → no hard strategy reasons, single caution."""
    performance = _perf("COVERAGE_GAP", False, netWinRate=None, netWinRateSampleCount=2)
    verdict = _public_quant_verdict(_item(expectedValue=None, calibrationCount=0),
                                    performance, _trade_safety_ok(), cash=10_000_000)
    hard_strategy = [r for r in verdict["reasons"]
                     if "strategy" in r or "netWinRate" in r]
    assert not hard_strategy
    caution_gap = [c for c in verdict["cautions"] if "COVERAGE_GAP" in c]
    assert caution_gap


def test_quant_verdict_insufficient_samples_soft_caution():
    """INSUFFICIENT_SAMPLES → caution not reason."""
    performance = _perf("INSUFFICIENT_SAMPLES", False, netWinRate=None, netWinRateSampleCount=5)
    verdict = _public_quant_verdict(_item(expectedValue=None, calibrationCount=0),
                                    performance, _trade_safety_ok(), cash=10_000_000)
    hard = [r for r in verdict["reasons"] if "strategy" in r]
    assert not hard
    assert any("INSUFFICIENT_SAMPLES" in c for c in verdict["cautions"])


def test_quant_verdict_data_source_mismatch_soft_caution():
    """DATA_SOURCE_MISMATCH → caution not reason."""
    performance = _perf("DATA_SOURCE_MISMATCH", False, netWinRate=42.5, netWinRateSampleCount=106)
    verdict = _public_quant_verdict(_item(expectedValue=None, calibrationCount=0),
                                    performance, _trade_safety_ok(), cash=10_000_000)
    hard = [r for r in verdict["reasons"] if "strategy" in r or "winRate" in r]
    assert not hard
    assert any("DATA_SOURCE_MISMATCH" in c for c in verdict["cautions"])


def test_quant_verdict_performance_ok_no_strategy_gate():
    """PERFORMANCE_OK → gate already verified, no additional strategy reasons."""
    performance = _perf("PERFORMANCE_OK", False, netWinRate=42.5, netWinRateSampleCount=106,
                        metricDefinitionMismatch=False)
    # EV and RR are fine so this should be TRADE_CANDIDATE (no strategy reasons)
    verdict = _public_quant_verdict(
        _item(expectedValue=1.5, calibrationCount=35, calibratedWinRate=47.0),
        performance, _trade_safety_ok(), cash=10_000_000)
    strategy_reasons = [r for r in verdict["reasons"] if "strategy" in r]
    assert not strategy_reasons


def test_quant_verdict_performance_blocked_adds_reason():
    """PERFORMANCE_BLOCKED → isPerformanceHardBlocked=True → reason added."""
    performance = _perf("PERFORMANCE_BLOCKED", True,
                        reason="genuine underperformance: netWinRate=20%")
    item = _item(isTradeBlocked=True, tradeBlockReason="performance gate block",
                 tradeBlockStatus="PERFORMANCE_GATE_BLOCK",
                 expectedValue=1.5, calibrationCount=35, calibratedWinRate=47.0)
    verdict = _public_quant_verdict(item, performance, _trade_safety_ok(), cash=10_000_000)
    assert verdict["status"] == "NO_TRADE"
    assert any("performance" in r.lower() or "underperformance" in r.lower()
               for r in verdict["reasons"])


def test_quant_verdict_ev_none_in_data_uncertain_is_caution():
    """ev=None when gate status is uncertain → caution, not reason."""
    for status in ("COVERAGE_GAP", "INSUFFICIENT_SAMPLES", "DATA_SOURCE_MISMATCH"):
        performance = _perf(status, False, netWinRate=42.5, netWinRateSampleCount=10)
        verdict = _public_quant_verdict(_item(expectedValue=None, calibrationCount=0),
                                        performance, _trade_safety_ok(), cash=10_000_000)
        ev_reasons  = [r for r in verdict["reasons"]  if "expected value" in r]
        ev_cautions = [c for c in verdict["cautions"] if "expected value" in c or "스키마" in c]
        assert not ev_reasons,  f"ev=None should be caution in {status}: got reasons {ev_reasons}"
        assert ev_cautions,     f"ev=None should surface as caution in {status}"


def test_quant_verdict_ev_none_in_performance_ok_is_reason():
    """ev=None when gate is PERFORMANCE_OK → hard reason (EV genuinely missing)."""
    performance = _perf("PERFORMANCE_OK", False, netWinRate=42.5, netWinRateSampleCount=106,
                        metricDefinitionMismatch=False)
    verdict = _public_quant_verdict(_item(expectedValue=None, calibrationCount=0),
                                    performance, _trade_safety_ok(), cash=10_000_000)
    ev_reasons = [r for r in verdict["reasons"] if "expected value" in r]
    assert ev_reasons, "ev=None should be a reason when gate is PERFORMANCE_OK"


def test_quant_verdict_us_performance_ok_no_coverage_gap_caution():
    """US recommendation with PERFORMANCE_OK → no KR-specific COVERAGE_GAP caution."""
    performance = _perf("PERFORMANCE_OK", False, netWinRate=48.0, netWinRateSampleCount=60,
                        metricDefinitionMismatch=False)
    verdict = _public_quant_verdict(
        _item(expectedValue=1.2, calibrationCount=35, calibratedWinRate=47.0),
        performance, _trade_safety_ok(), cash=10_000_000)
    gap_cautions = [c for c in verdict["cautions"] if "COVERAGE_GAP" in c]
    assert not gap_cautions


# ── LOW_ATR guard interaction ─────────────────────────────────────────────────
# The LOW_ATR guard runs after _apply_recommendation_performance_safety.
# If isPerformanceHardBlocked=False, the item reaches the LOW_ATR guard layer.
# This test verifies that DATA_SOURCE_MISMATCH items are NOT hard-blocked by the
# performance gate (so LOW_ATR can still filter them independently).

def test_data_source_mismatch_item_not_blocked_before_low_atr():
    """DATA_SOURCE_MISMATCH items exit the performance gate unblocked."""
    payload = {"items": [_item(decisionBucket="오늘 진입")]}
    with patch(_DASH, return_value=_dashboard(meaningful_win_rate=17.0)):
        with patch(_SWJ, return_value=_swj(net_wr=0.425, sample=106)):
            result = _apply_recommendation_performance_safety(payload, "kr", "balanced", "swing")

    item = result["items"][0]
    assert not item.get("isTradeBlocked")
    assert item["isPerformanceHardBlocked"] is False
    # LOW_ATR guard can still read and act on this item downstream


# ── Score inputs reflect new fields ──────────────────────────────────────────

def test_quant_verdict_score_inputs_has_net_win_rate():
    """scoreInputs now carries netWinRate / performanceGateStatus instead of csv-based fields."""
    performance = _perf("PERFORMANCE_OK", False, netWinRate=42.5, netWinRateSampleCount=106)
    verdict = _public_quant_verdict(
        _item(expectedValue=1.5, calibrationCount=35, calibratedWinRate=47.0),
        performance, _trade_safety_ok(), cash=10_000_000)
    si = verdict["scoreInputs"]
    assert "netWinRate" in si
    assert "performanceGateStatus" in si
    assert "csvMetricWinRate" in si
