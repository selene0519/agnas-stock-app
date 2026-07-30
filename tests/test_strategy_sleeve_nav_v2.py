from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "update_strategy_sleeve_nav_v2",
    ROOT / "scripts" / "update_strategy_sleeve_nav_v2.py",
)
assert SPEC and SPEC.loader
sleeve = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sleeve)


def _trade(journal_id: str, fill: str, exit_: str, pnl: float) -> dict:
    return {
        "journal_id": journal_id,
        "market": "kr",
        "symbol": journal_id,
        "fill_date": fill,
        "exit_date": exit_,
        "net_pnl_pct": pnl,
    }


def test_simulator_reserves_cash_until_exit() -> None:
    trades = [
        _trade(f"t{index}", "2026-01-01", "2026-01-10", 10.0)
        for index in range(12)
    ]

    result = sleeve._simulate(trades)

    assert result["candidateTrades"] == 12
    assert result["capacityRejectedTrades"] == 2
    assert result["trades"] == 10
    assert result["maxInvestedPct"] == pytest.approx(100.0)


def test_same_day_exit_cash_is_not_recycled_into_new_entry() -> None:
    first_wave = [_trade(f"old{index}", "2026-01-01", "2026-01-05", 0.0) for index in range(10)]
    next_trade = _trade("new", "2026-01-05", "2026-01-06", 5.0)

    result = sleeve._simulate(first_wave + [next_trade])

    assert result["capacityRejectedTrades"] == 1
    assert result["trades"] == 10


def test_net_pnl_drives_capital_curve_without_readding_costs() -> None:
    result = sleeve._simulate([_trade("one", "2026-01-01", "2026-01-02", -10.0)])

    # Ten percent of NAV is allocated; a -10% net trade loses 1% of sleeve NAV.
    assert result["nav"] == pytest.approx(99.0)
    assert result["totalReturnPct"] == pytest.approx(-1.0)
    assert result["maxDrawdownPct"] == pytest.approx(1.0)
