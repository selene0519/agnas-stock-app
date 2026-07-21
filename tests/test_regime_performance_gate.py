from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
loaded_app = sys.modules.get("app")
if loaded_app is not None and not hasattr(loaded_app, "__path__"):
    sys.modules.pop("app", None)

from app.engine import mone_v65_api_stabilizer as stabilizer  # noqa: E402
from app.services import regime_performance_gate as gate  # noqa: E402


def _rows(return_value: float, count: int = 20) -> tuple[list[dict], list[dict]]:
    journal = []
    evaluations = []
    for index in range(count):
        journal_id = f"j-{index}"
        journal.append({
            "journal_id": journal_id,
            "source_type": "FORWARD_PAPER_TRADE",
            "market": "us",
            "mode": "balanced",
            "horizon": "swing",
            "market_regime_at_signal": "RISK_OFF",
        })
        evaluations.append({
            "journal_id": journal_id,
            "status": "EVALUATED",
            "net_pnl_pct": str(return_value),
            "regime_at_entry": "RISK_OFF",
        })
    return journal, evaluations


def test_bear_gate_blocks_negative_forward_net_returns() -> None:
    journal, evaluations = _rows(-0.4)
    index = gate.build_index(journal, evaluations)

    verdict = gate.evaluate("us", "balanced", "swing", "BEAR", index=index)

    assert verdict["status"] == "REGIME_PERFORMANCE_BLOCKED"
    assert verdict["isTradeBlocked"] is True
    assert verdict["averageNetReturnPct"] == -0.4


def test_regime_gate_refuses_to_infer_profitability_from_small_samples() -> None:
    journal, evaluations = _rows(1.2, count=19)
    index = gate.build_index(journal, evaluations)

    verdict = gate.evaluate("us", "balanced", "swing", "RISK_OFF", index=index)

    assert verdict["status"] == "INSUFFICIENT_REGIME_SAMPLES"
    assert verdict["isTradeBlocked"] is True


def test_public_gate_turns_regime_loss_into_no_trade() -> None:
    item = {
        "symbol": "LOSSY",
        "currentPrice": 100,
        "entry": 100,
        "stop": 95,
        "target": 110,
        "expectedValue": 2.0,
        "rrActual": 2.0,
        "calibratedWinRate": 55.0,
        "calibrationCount": 40,
        "regimePerformanceGate": {
            "status": "REGIME_PERFORMANCE_BLOCKED",
            "isTradeBlocked": True,
            "reason": "BEAR balanced_swing is not profitable after costs.",
        },
    }
    performance = {"status": "PERFORMANCE_OK", "isPerformanceHardBlocked": False}
    trade_safety = {"status": "OK", "isTradeBlocked": False}

    verdict = stabilizer._public_quant_verdict(item, performance, trade_safety, 1_000_000)

    assert verdict["status"] == "NO_TRADE"
    assert any("not profitable after costs" in reason for reason in verdict["reasons"])
