from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
loaded_app = sys.modules.get("app")
if loaded_app is not None and not hasattr(loaded_app, "__path__"):
    sys.modules.pop("app", None)

from app.services.regime_trade_plan import build_trade_plan


def _item(**overrides):
    item = {
        "entry": 100.0,
        "stop": 96.0,
        "target": 108.0,
        "newsRiskPenalty": 0.0,
        "supplySignal": "INST_BUY",
        "riskFlags": [],
        "indicators": {
            "atr14": 2.0,
            "rsi14": 35.0,
            "bbPercentB": 0.2,
            "distanceToMa20": -1.0,
            "volumeRatio20": 1.1,
            "ma20": 104.0,
        },
    }
    item.update(overrides)
    return item


def test_sideways_mean_reversion_requires_oversold_structure_and_uses_ma20_target():
    plan = build_trade_plan(_item(target=115.0), market="kr", mode="balanced", horizon="swing", regime="SIDE")

    assert plan["status"] == "READY"
    assert plan["strategy"] == "RANGE_MEAN_REVERSION"
    assert plan["target"] == 104.0
    assert plan["entryZone"] == {"low": 99.5, "high": 100.3}
    assert plan["riskFractionMultiplier"] == 0.5


def test_bear_market_is_cash_only_without_oversold_positive_supply_confirmation():
    plan = build_trade_plan(
        _item(supplySignal="DISTRIBUTION"), market="kr", mode="balanced", horizon="short", regime="BEAR"
    )

    assert plan["status"] == "CASH_ONLY"
    assert "NEGATIVE_SUPPLY" in plan["reasonCodes"]
    assert "BEAR_RALLY_SUPPLY_NOT_CONFIRMED" in plan["reasonCodes"]
    assert plan["riskFractionMultiplier"] == 0.0


def test_event_or_disclosure_risk_never_becomes_ready():
    plan = build_trade_plan(
        _item(newsRiskPenalty=12.0), market="us", mode="balanced", horizon="swing", regime="SIDE"
    )

    assert plan["status"] == "WATCH"
    assert "EVENT_OR_DISCLOSURE_RISK" in plan["reasonCodes"]


def test_macro_event_score_is_considered_even_when_news_penalty_is_zero():
    plan = build_trade_plan(
        _item(newsRiskPenalty=0.0, eventRiskScore=10.0), market="us", mode="balanced", horizon="swing", regime="SIDE"
    )

    assert plan["status"] == "WATCH"
    assert plan["evidence"]["eventRisk"] == 10.0
    assert "EVENT_OR_DISCLOSURE_RISK" in plan["reasonCodes"]


def test_missing_stop_or_target_blocks_even_when_indicators_are_favourable():
    plan = build_trade_plan(_item(stop=None), market="us", mode="balanced", horizon="swing", regime="BULL")

    assert plan["status"] == "WATCH"
    assert "INVALID_STOP" in plan["reasonCodes"]


def test_investment_mode_and_horizon_reduce_exposure_for_conservative_short_term_plan():
    item = _item(
        indicators={
            "atr14": 2.0,
            "rsi14": 50.0,
            "bbPercentB": 0.5,
            "distanceToMa20": 0.0,
            "volumeRatio20": 1.1,
            "ma20": 104.0,
        }
    )

    plan = build_trade_plan(item, market="us", mode="conservative", horizon="short", regime="BULL")

    assert plan["status"] == "READY"
    assert plan["riskFractionMultiplier"] == 0.45
    assert plan["riskSizingProfile"]["entryZoneWidthMultiplier"] == 0.75
