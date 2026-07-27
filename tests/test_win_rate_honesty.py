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


def test_market_calibrations_do_not_mix_kr_and_us_results(monkeypatch):
    kr_rows = [
        {"market": "kr", "mode": "balanced", "horizon": "swing", "result": "LOSS", "returnPct": "-1.0"}
        for _ in range(20)
    ]
    us_rows = [
        {"market": "us", "mode": "balanced", "horizon": "swing", "result": "WIN", "returnPct": "1.0"}
        for _ in range(20)
    ]
    monkeypatch.setattr(
        updater,
        "_read_csv",
        lambda path: kr_rows + us_rows if path == updater.VALIDATION_CSV else [],
    )

    rates = updater.calculate_win_rates()

    assert rates["observedWinRates"]["balanced_swing"] == 0.5
    assert rates["byMarket"]["kr"]["observedWinRates"]["balanced_swing"] == 0.0
    assert rates["byMarket"]["us"]["observedWinRates"]["balanced_swing"] == 1.0


def test_same_day_close_exit_cost_row_is_not_a_strategy_outcome(monkeypatch):
    rows = [
        {"market": "us", "mode": "balanced", "horizon": "swing", "result": "close_exit", "returnPct": "-0.09"}
        for _ in range(20)
    ]
    monkeypatch.setattr(
        updater,
        "_read_csv",
        lambda path: rows if path == updater.VALIDATION_CSV else [],
    )

    rates = updater.calculate_win_rates()

    assert rates["sampleCounts"]["balanced_swing"] == 0
    assert rates["performanceDataPolicy"]["excludedRows"]["SAME_DAY_CLOSE_PLACEHOLDER"] == 20
