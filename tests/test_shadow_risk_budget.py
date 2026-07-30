from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_shadow_risk_budget",
    ROOT / "scripts" / "build_shadow_risk_budget.py",
)
assert SPEC and SPEC.loader
risk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(risk)


def _candidate(symbol: str, sector: str = "Tech", beta: float | None = 1.0) -> dict:
    return {
        "decision": "TAKE",
        "symbol": symbol,
        "market": "us",
        "sector": sector,
        "entryPrice": 100,
        "stopPrice": 95,
        "beta": beta,
        "score": 80,
    }


def test_stop_distance_caps_equity_loss_per_trade() -> None:
    result = risk.allocate([_candidate("A")])

    assert result["positions"][0]["weightPct"] == pytest.approx(10.0)
    assert result["positions"][0]["lossAtStopPctOfEquity"] == pytest.approx(0.5)


def test_sector_and_gross_clamps_leave_removed_exposure_in_cash() -> None:
    result = risk.allocate([
        _candidate("A", "Tech"),
        _candidate("B", "Tech"),
        _candidate("C", "Health"),
        _candidate("D", "Energy"),
    ])

    assert result["grossExposurePct"] <= 30.0
    assert result["sectorWeights"]["Tech"] <= 0.15
    assert result["cashWeightPct"] >= 70.0
    assert sum(position["weight"] for position in result["positions"]) == pytest.approx(result["grossExposure"])


def test_missing_stop_blocks_allocation() -> None:
    candidate = _candidate("A")
    candidate["stopPrice"] = None

    result = risk.allocate([candidate])

    assert result["positions"] == []
    assert result["cashWeightPct"] == 100.0
    assert result["rejected"][0]["reason"] == "INVALID_OR_MISSING_STOP_DISTANCE"


def test_no_take_candidates_means_full_cash() -> None:
    result = risk.allocate([{"decision": "REJECT", "symbol": "A"}])

    assert result["positions"] == []
    assert result["grossExposurePct"] == 0.0
    assert result["cashWeightPct"] == 100.0
