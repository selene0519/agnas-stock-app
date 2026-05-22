import pandas as pd

from core.aggressive_candidate_engine import (
    apply_aggressive_candidate_scores,
    calculate_aggressive_candidate_score,
)


def test_down_market_up_stock_can_be_weak_market_leader():
    result = calculate_aggressive_candidate_score(
        {
            "change_pct": 2.5,
            "candidate_avg_change_pct": -1.5,
            "market_score": -3,
            "sector_avg_change_pct": 0.5,
            "volume_ratio": 2.0,
            "sector_momentum_score": 82,
            "near_high_score": 88,
            "news_momentum_score": 75,
        }
    )

    assert result["weak_market_leader_flag"] is True
    assert result["market_relative_strength"] > 0


def test_aggressive_score_80_or_more_sets_strong_watch_candidate():
    result = calculate_aggressive_candidate_score(
        {
            "change_pct": 5.0,
            "candidate_avg_change_pct": -2.0,
            "market_score": -3,
            "sector_avg_change_pct": 1.0,
            "volume_ratio": 3.0,
            "trading_value": 30_000_000_000,
            "sector_momentum_score": 95,
            "near_high_score": 95,
            "pullback_confirmed": True,
            "news_momentum_score": 90,
        }
    )

    assert result["aggressive_score"] >= 80
    assert result["strong_watch_candidate"] is True


def test_chase_risk_is_not_strong_watch_even_with_high_score():
    result = calculate_aggressive_candidate_score(
        {
            "change_pct": 7.0,
            "candidate_avg_change_pct": -2.0,
            "market_score": -3,
            "sector_avg_change_pct": 1.0,
            "volume_ratio": 3.0,
            "trading_value": 30_000_000_000,
            "sector_momentum_score": 95,
            "near_high_score": 95,
            "pullback_confirmed": True,
            "news_momentum_score": 90,
            "chase_risk": True,
        }
    )

    assert result["strong_watch_candidate"] is False
    assert any("추격" in warning for warning in result["aggressive_warnings"])


def test_aggressive_score_is_clipped_0_100():
    result = calculate_aggressive_candidate_score(
        {
            "change_pct": 100,
            "candidate_avg_change_pct": -100,
            "volume_ratio": 99,
            "sector_momentum_score": 999,
            "news_momentum_score": 999,
        }
    )

    assert 0 <= result["aggressive_score"] <= 100


def test_apply_aggressive_candidate_scores_keeps_existing_columns():
    df = pd.DataFrame([{"symbol": "ABC", "change_pct": 2.0, "market_score": -3}])

    out = apply_aggressive_candidate_scores(df)

    assert "symbol" in out.columns
    assert "aggressive_score" in out.columns


def test_app_aggressive_layer_keeps_risk_mode_trade_disallowed():
    import app

    df = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "grade": "B",
                "strategy_mode": "위험장",
                "strategy_trade_allowed": False,
                "trade_allowed": False,
                "change_pct": 5.0,
                "candidate_avg_change_pct": -2.0,
                "market_score": -3,
                "sector_avg_change_pct": 1.0,
                "volume_ratio": 3.0,
                "trading_value": 30_000_000_000,
                "sector": "AI",
                "near_high_score": 95,
                "news_momentum_score": 90,
            }
        ]
    )

    out = app.apply_aggressive_discovery_columns(df, {"market_score": -3, "strategy_mode": "위험장"})

    assert bool(out.loc[0, "strategy_trade_allowed"]) is False
    assert bool(out.loc[0, "trade_allowed"]) is False
    assert bool(out.loc[0, "strong_watch_candidate"]) is True
