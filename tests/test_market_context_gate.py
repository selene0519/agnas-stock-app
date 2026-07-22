from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
loaded_app = sys.modules.get("app")
if loaded_app is not None and not hasattr(loaded_app, "__path__"):
    sys.modules.pop("app", None)

from app.services import market_context_gate as gate


def _write(path: Path, closes: list[float]) -> None:
    path.write_text("date,close\n" + "\n".join(f"2026-01-{i + 1:02d},{value}" for i, value in enumerate(closes)), encoding="utf-8")


def test_local_breadth_labels_sample_and_calculates_score(tmp_path: Path):
    for number in range(20):
        _write(tmp_path / f"us_T{number}_daily.csv", [100 + day + number for day in range(60)])
    result = gate.market_breadth("us", directory=tmp_path)
    assert result["status"] == "OK"
    assert result["sampleCount"] == 20
    assert result["basis"] == "local_tracked_universe_only"
    assert result["score"] == 100.0


def test_local_breadth_fails_closed_below_minimum_sample(tmp_path: Path):
    for number in range(19):
        _write(tmp_path / f"us_T{number}_daily.csv", [100 + day for day in range(60)])
    result = gate.market_breadth("us", directory=tmp_path)
    assert result["status"] == "INSUFFICIENT_LOCAL_UNIVERSE"
    assert result["score"] is None


def test_pre_trade_gate_blocks_unknown_context_and_performance_block():
    result = gate.pre_trade_gate({"isRegimePerformanceBlocked": True}, {"status": "CASH_UNTIL_BREADTH_AVAILABLE", "recommendedExposureMultiplier": 0})
    assert result["status"] == "NO_TRADE"
    assert "MARKET_BREADTH_UNAVAILABLE" in result["reasonCodes"]
    assert "PERFORMANCE_GATE_BLOCKED" in result["reasonCodes"]
