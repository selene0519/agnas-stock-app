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
    monkeypatch.setattr(trader, "_buy_candidates", lambda market, dry_run, execution_plan=None: buy_calls.append(market) or [{"action": "BUY"}])

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
            "operatingState": "RECOMMENDATION_READY",
            "entryAllowed": True,
            "paperEntryAllowed": True,
            "exitAllowed": True,
            "reasonCodes": [],
        },
    )
    monkeypatch.setattr(trader, "_sell_triggered_positions", lambda market, dry_run: [])
    monkeypatch.setattr(trader, "_buy_candidates", lambda market, dry_run, execution_plan=None: [{"action": "BUY", "symbol": "005930"}])

    result = trader.run_cycle("kr", dry_run=True)

    assert result["markets"]["kr"]["actions"] == [{"action": "BUY", "symbol": "005930"}]


def test_buy_leg_executes_only_exact_allocated_candidate_at_target_weight(monkeypatch) -> None:
    agent = _agent()
    monkeypatch.setattr(trader, "_active_context", lambda market: {"agent": agent, "agentId": "test", "generation": 1})
    monkeypatch.setattr(trader, "_summary_for_market", lambda market, agent_id: {"cash": 1_000.0, "portfolioValue": 1_000.0})
    monkeypatch.setattr(trader, "_survival_state", lambda market, summary: {"state": "ALIVE"})
    monkeypatch.setattr(trader, "_realized_performance_gate", lambda market, active: {"allowed": True})
    monkeypatch.setattr(trader, "_position_items", lambda market, agent_id: [])
    recommendations = [
        {
            "market": "us", "mode": "balanced", "horizon": "mid", "symbol": "AAPL", "name": "Apple",
            "candidateKey": "candidate-a", "entry": 100.0, "stop": 95.0, "target": 120.0,
            "expectedValue": 2.0, "score": 80.0, "decision": "today", "source": "test.csv",
        },
        {
            "market": "us", "mode": "balanced", "horizon": "mid", "symbol": "MSFT", "name": "Microsoft",
            "candidateKey": "candidate-b", "entry": 100.0, "stop": 95.0, "target": 120.0,
            "expectedValue": 2.0, "score": 79.0, "decision": "today", "source": "test.csv",
        },
    ]
    monkeypatch.setattr(trader, "_collect_recommendations", lambda market, active: recommendations)
    execution_plan = {
        "status": "AUTHORIZED",
        "maxGrossExposure": 0.30,
        "positions": [{
            "decisionId": "decision-a",
            "candidateKey": "candidate-a",
            "market": "us",
            "symbol": "AAPL",
            "entryPrice": 100.0,
            "stopPrice": 95.0,
            "weight": 0.10,
            "signalDate": "2026-07-31",
            "metaPolicyFingerprint": "meta-a",
            "riskPolicyVersion": "risk-v1",
            "riskPolicyFingerprint": "risk-a",
            "allocationFingerprint": "allocation-a",
        }],
    }

    actions = trader._buy_candidates("us", dry_run=True, execution_plan=execution_plan)

    assert len(actions) == 1
    assert actions[0]["action"] == "BUY"
    assert actions[0]["symbol"] == "AAPL"
    assert actions[0]["quantity"] == 1.0
    assert actions[0]["totalValue"] == 100.0
    assert actions[0]["executionAuthority"]["candidateKey"] == "candidate-a"


def test_execution_weight_never_redistributes_unused_budget() -> None:
    qty = trader._quantity_for_execution_weight(
        "us", cash=1_000.0, equity=1_000.0, entry=100.0, target_weight=0.06, remaining_gross_value=300.0
    )

    assert qty == 0.6

def test_regime_selector_connects_bull_market_to_aggressive_candidate(monkeypatch) -> None:
    monkeypatch.setattr(trader, "_market_regime_snapshot", lambda market: {"regime": "BULL", "label": "강세장"})
    monkeypatch.setattr(trader, "_strategy_realized_stats", lambda market, agent: {"sampleCount": 0, "winRate": 0.0, "avgReturnPct": 0.0})

    def candidates(_market, agent=None):
        if agent and agent["id"] == "ml_rank_aggressive_mid":
            return [{"symbol": "005930", "entry": 100.0, "stop": 95.0, "expectedValue": 2.0, "score": 80.0}]
        return []

    monkeypatch.setattr(trader, "_collect_recommendations", candidates)

    suggestion = trader._suggest_agent("kr")

    assert suggestion["status"] == "SELECTED"
    assert suggestion["regime"] == "BULL"
    assert suggestion["selectedAgent"]["id"] == "ml_rank_aggressive_mid"


def test_discovery_plan_rejects_future_signal_and_caps_risk() -> None:
    agent = {"id": "ml_rank_aggressive_mid", "label": "Aggressive", "mode": "aggressive", "horizon": "mid"}
    today = date.today()
    current = {
        "candidateKey": "current", "market": "kr", "symbol": "005930", "mode": "aggressive", "horizon": "mid",
        "entry": 100.0, "stop": 95.0, "signalDate": today.isoformat(),
    }
    future = {
        "candidateKey": "future", "market": "kr", "symbol": "000660", "mode": "aggressive", "horizon": "mid",
        "entry": 100.0, "stop": 95.0, "signalDate": (today + timedelta(days=1)).isoformat(),
    }

    plan = trader._paper_discovery_plan("kr", agent, [future, current])

    assert plan["status"] == "AUTHORIZED"
    assert [row["symbol"] for row in plan["positions"]] == ["005930"]
    assert plan["positions"][0]["weight"] <= trader.PAPER_DISCOVERY_MAX_POSITION
    assert plan["positions"][0]["researchOnly"] is True
    assert plan["rejected"][0]["reason"] == "PAPER_SIGNAL_FROM_FUTURE"


def test_run_cycle_uses_discovery_lane_without_relaxing_promotion_gate(monkeypatch) -> None:
    _stub_cycle_views(monkeypatch)
    monkeypatch.setattr(
        governor,
        "entry_authority",
        lambda market: {
            "market": market,
            "operatingState": "ABSTAIN",
            "entryAllowed": False,
            "paperEntryAllowed": False,
            "paperResearchEntryAllowed": True,
            "exitAllowed": True,
            "reasonCodes": ["REALIZED_WIN_RATE_BELOW_GATE"],
        },
    )
    monkeypatch.setattr(trader, "_sell_triggered_positions", lambda market, dry_run: [])
    monkeypatch.setattr(
        trader,
        "_suggest_agent",
        lambda market: {"selectedAgent": trader.AGENT_POOL[3], "regime": "BULL", "selectionScore": 10.0},
    )
    monkeypatch.setattr(
        trader,
        "_activate_suggested_agent",
        lambda market, suggestion, dry_run: {"changed": True, "agent": trader.AGENT_POOL[3], "fromAgentId": "test", "toAgentId": trader.AGENT_POOL[3]["id"], "generation": 2, "regime": "BULL", "reason": "FLAT_ACCOUNT_REGIME_CHAMPION_SELECTED"},
    )
    calls = []
    monkeypatch.setattr(
        trader,
        "_buy_candidates",
        lambda market, dry_run, execution_plan=None, **kwargs: calls.append(kwargs) or [{"action": "BUY", "researchMode": kwargs.get("research_mode")}],
    )

    result = trader.run_cycle("kr", dry_run=True)

    assert calls == [{"research_mode": True, "agent_override": trader.AGENT_POOL[3]}]
    assert result["markets"]["kr"]["actions"][0]["action"] == "AGENT_SWITCH"
    assert result["markets"]["kr"]["actions"][1] == {"action": "BUY", "researchMode": True}
    assert result["markets"]["kr"]["operatingAuthority"]["entryAllowed"] is False


def test_closed_trade_metrics_are_net_of_recorded_costs(monkeypatch) -> None:
    monkeypatch.setattr(
        trader,
        "_trades_for",
        lambda market, agent_id: [
            {"createdAt": "2026-01-01", "symbol": "AAPL", "action": "BUY", "price": 100, "quantity": 1, "totalValue": 100, "costAmount": 1},
            {"createdAt": "2026-01-02", "symbol": "AAPL", "action": "SELL", "price": 102, "quantity": 1, "totalValue": 102, "costAmount": 1},
        ],
    )

    metrics = trader._closed_trade_metrics("us", "test")

    assert metrics["closedTradeCount"] == 1
    assert metrics["winRate"] == 0.0
    assert metrics["avgNetPnlPct"] == 0.0

def test_append_csv_migrates_legacy_trade_header(tmp_path) -> None:
    path = tmp_path / "trades.csv"
    path.write_text("id,memo\nold,legacy\n", encoding="utf-8")

    trader._append_csv(path, {"id": "new", "memo": "current", "costAmount": 1.25}, ["id", "costAmount", "memo"])

    rows = trader._read_csv(path)
    assert rows == [
        {"id": "old", "costAmount": "", "memo": "legacy"},
        {"id": "new", "costAmount": "1.25", "memo": "current"},
    ]


def test_regime_lens_is_rejected_when_report_regime_is_stale(monkeypatch, tmp_path) -> None:
    report = {
        "market": "kr",
        "marketRegime": "SIDE",
        "asOfDate": date.today().isoformat(),
        "candidates": [{"symbol": "005930", "setup": "BOTTOM_CATCH", "entryRef": 100, "stop": 95, "target": 110, "rrRatio": 2.0}],
    }
    (tmp_path / "regime_lens_candidates_kr.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(trader, "REPORTS", tmp_path)
    monkeypatch.setattr(trader, "_market_regime_snapshot", lambda market: {"regime": "BULL"})

    assert trader._collect_regime_lens_candidates_kr(trader.AGENT_POOL[0]) == []
