import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import ai_paper_trader as trader


def _agent() -> dict[str, str]:
    return {"id": "test", "label": "Test", "mode": "balanced", "horizon": "mid"}


def test_realized_performance_gate_blocks_negative_expectancy(monkeypatch, tmp_path) -> None:
    report = {
        "byMarket": {
            "kr": {
                "sampleCounts": {"balanced_mid": 24},
                "observedWinRates": {"balanced_mid": 0.55},
                "averageReturnPct": {"balanced_mid": -0.4},
            }
        }
    }
    monkeypatch.setattr(trader, "REPORTS", tmp_path)
    (tmp_path / "strategy_win_rates.json").write_text(json.dumps(report), encoding="utf-8")

    gate = trader._realized_performance_gate("kr", _agent())

    assert gate["allowed"] is False
    assert gate["reason"] == "NEGATIVE_REALIZED_EXPECTANCY"


def test_realized_performance_gate_allows_positive_edge(monkeypatch, tmp_path) -> None:
    report = {
        "byMarket": {
            "us": {
                "sampleCounts": {"balanced_mid": 24},
                "observedWinRates": {"balanced_mid": 0.55},
                "averageReturnPct": {"balanced_mid": 0.4},
            }
        }
    }
    monkeypatch.setattr(trader, "REPORTS", tmp_path)
    (tmp_path / "strategy_win_rates.json").write_text(json.dumps(report), encoding="utf-8")

    gate = trader._realized_performance_gate("us", _agent())

    assert gate["allowed"] is True
    assert gate["reason"] == "REALIZED_EDGE_CONFIRMED"
