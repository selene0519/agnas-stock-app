import pandas as pd

from core.aggressive_sector_engine import (
    apply_aggressive_sector_scores,
    calculate_aggressive_sector_scores,
)


def test_weak_market_strong_sector_flag_can_be_true():
    df = pd.DataFrame(
        [
            {"sector": "AI", "change_pct": 2.0, "volume_ratio": 2.0, "near_high_score": 85},
            {"sector": "AI", "change_pct": 1.5, "volume_ratio": 1.8, "near_high_score": 80},
            {"sector": "BIO", "change_pct": -2.0, "volume_ratio": 0.8, "near_high_score": 40},
        ]
    )

    out = calculate_aggressive_sector_scores(df, {"market_score": -3, "candidate_avg_change_pct": -1.5})
    ai = out[out["sector"].eq("AI")].iloc[0]

    assert bool(ai["weak_market_strong_sector_flag"]) is True
    assert 0 <= int(ai["sector_momentum_score"]) <= 100


def test_sector_scores_include_required_columns():
    df = pd.DataFrame([{"sector": "A", "change_pct": 1.0, "volume_ratio": 1.2}])

    out = calculate_aggressive_sector_scores(df, {"market_score": 0})

    for col in [
        "sector_momentum_score",
        "sector_relative_strength_score",
        "sector_breadth_score",
        "sector_money_flow_score",
        "weak_market_strong_sector_flag",
        "sector_attack_reasons",
    ]:
        assert col in out.columns


def test_apply_aggressive_sector_scores_keeps_existing_columns():
    df = pd.DataFrame([{"symbol": "ABC", "sector": "A", "change_pct": 1.0}])

    out = apply_aggressive_sector_scores(df, {"market_score": -2})

    assert "symbol" in out.columns
    assert "sector_momentum_score" in out.columns
