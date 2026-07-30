import json
import sys
from datetime import date, timedelta
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import ai_paper_trader as trader
from app.services import quant_operating_governor as governor


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


def _stub_cycle_views(monkeypatch) -> None:
    monkeypatch.setattr(trader, "_market_list", lambda market: ["kr"])
    monkeypatch.setattr(trader, "_active_context", lambda market: {"agent": _agent(), "agentId": "test", "generation": 1})
    monkeypatch.setattr(trader, "_summary_for_market", lambda market, agent_id: {"portfolioValue": 100.0})
    monkeypatch.setattr(trader, "_live_nav_metrics", lambda market, agent_id, summary: {})
    monkeypatch.setattr(trader, "_survival_state", lambda market, summary: {"state": "ALIVE"})
    monkeypatch.setattr(trader, "_walkforward_proof_board", lambda market, agent_id: {})


def test_run_cycle_denies_new_entries_but_keeps_risk_reducing_exits(monkeypatch) -> None:
    _stub_cycle_views(monkeypatch)
    monkeypatch.setattr(
        governor,
        "entry_authority",
        lambda market: {
            "market": market,
            "operatingState": "ABSTAIN",
            "entryAllowed": False,
            "paperEntryAllowed": False,
            "exitAllowed": True,
            "reasonCodes": ["QUANT_SHADOW_NOT_APPROVED"],
        },
    )
    monkeypatch.setattr(trader, "_sell_triggered_positions", lambda market, dry_run: [{"action": "SELL", "symbol": "005930"}])
    buy_calls: list[str] = []
    monkeypatch.setattr(trader, "_buy_candidates", lambda market, dry_run: buy_calls.append(market) or [{"action": "BUY"}])

    result = trader.run_cycle("kr", dry_run=True)
    actions = result["markets"]["kr"]["actions"]

    assert buy_calls == []
    assert actions[0]["action"] == "SELL"
    assert actions[1]["action"] == "SKIP"
    assert actions[1]["scope"] == "NEW_ENTRY"
    assert result["markets"]["kr"]["operatingAuthority"]["exitAllowed"] is True


def test_run_cycle_calls_buy_leg_only_when_paper_entry_is_authorized(monkeypatch) -> None:
    _stub_cycle_views(monkeypatch)
    monkeypatch.setattr(
        governor,
        "entry_authority",
        lambda market: {
            "market": market,
            "operatingState": "TRADEABLE",
            "entryAllowed": True,
            "paperEntryAllowed": True,
            "exitAllowed": True,
            "reasonCodes": [],
        },
    )
    monkeypatch.setattr(trader, "_sell_triggered_positions", lambda market, dry_run: [])
    monkeypatch.setattr(trader, "_buy_candidates", lambda market, dry_run: [{"action": "BUY", "symbol": "005930"}])

    result = trader.run_cycle("kr", dry_run=True)

    assert result["markets"]["kr"]["actions"] == [{"action": "BUY", "symbol": "005930"}]
