import json
import sys
from datetime import date, timedelta
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
    monkeypatch.setattr(
        trader,
        "_walkforward_proof_board",
        lambda *_args: {"status": "OK", "verdict": "PROVING_EDGE"},
    )

    gate = trader._realized_performance_gate("us", _agent())

    assert gate["allowed"] is True
    assert gate["reason"] == "REALIZED_AND_OOS_EDGE_CONFIRMED"


def test_walkforward_future_windows_are_not_usable(monkeypatch) -> None:
    future_window = (date.today() + timedelta(days=1)).isoformat()
    monkeypatch.setattr(
        trader,
        "_read_csv",
        lambda _path: [{"window": future_window, "mode": "balanced", "horizon": "mid", "strategy": "corrected"}],
    )

    board = trader._walkforward_proof_board("kr", "ml_rank_balanced_mid")

    assert board["status"] == "INVALID_TEMPORAL_DATA"
    assert board["verdict"] == "UNPROVEN"
