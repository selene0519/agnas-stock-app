from __future__ import annotations

from scripts import update_win_rates as updater


def test_observed_losing_strategy_is_not_raised_to_a_probability_floor(monkeypatch):
    rows = [
        {
            "mode": "balanced",
            "horizon": "swing",
            "result": "WIN" if index < 2 else "LOSS",
            "returnPct": "2.0" if index < 2 else "-1.0",
        }
        for index in range(20)
    ]

    monkeypatch.setattr(
        updater,
        "_read_csv",
        lambda path: rows if path == updater.VALIDATION_CSV else [],
    )

    rates = updater.calculate_win_rates()

    assert rates["sampleCounts"]["balanced_swing"] == 20
    assert rates["observedWinRates"]["balanced_swing"] == 0.1
    assert rates["winRates"]["balanced_swing"] == 0.1
    assert rates["averageReturnPct"]["balanced_swing"] == -0.7


def test_stop_label_without_a_realized_return_is_excluded_from_performance_gate(monkeypatch):
    rows = [
        {"mode": "balanced", "horizon": "swing", "result": "STOP"},
        {"mode": "balanced", "horizon": "swing", "result": "TARGET", "returnPct": "3.0"},
    ]

    monkeypatch.setattr(
        updater,
        "_read_csv",
        lambda path: rows if path == updater.VALIDATION_CSV else [],
    )

    rates = updater.calculate_win_rates()

    assert rates["sampleCounts"]["balanced_swing"] == 1
    assert rates["observedWinRates"]["balanced_swing"] == 1.0
    assert rates["performanceDataPolicy"]["excludedRows"]["MISSING_REALIZED_RETURN"] == 1
