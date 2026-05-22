import pandas as pd

from core.stock_quality_engine import apply_stock_attractiveness, calculate_stock_attractiveness


def test_stock_attractiveness_high_for_leader_with_volume():
    result = calculate_stock_attractiveness(
        {
            "sector_strength": 3,
            "leader_score": 90,
            "earnings_growth_score": 82,
            "news_momentum_score": 80,
            "relative_strength_score": 88,
            "near_high_score": 75,
            "volume_ratio": "2.1배",
            "trading_value": 20_000_000_000,
            "catalyst_score": 85,
        }
    )

    assert result["stock_attractiveness_score"] >= 70
    assert result["stock_quality_level"] in {"높음", "매우 높음"}


def test_stock_attractiveness_score_is_clipped_0_100():
    result = calculate_stock_attractiveness(
        {
            "sector_strength": 999,
            "leader_score": 999,
            "earnings_growth_score": 999,
            "news_momentum_score": 999,
            "relative_strength_score": 999,
            "near_high_score": 999,
            "volume_ratio": "9배",
            "trading_value": 999_000_000_000,
            "catalyst_score": 999,
        }
    )

    assert 0 <= result["stock_attractiveness_score"] <= 100


def test_apply_stock_attractiveness_keeps_existing_columns():
    df = pd.DataFrame([{"symbol": "ABC", "leader_score": 90}])

    out = apply_stock_attractiveness(df)

    assert "symbol" in out.columns
    assert "stock_attractiveness_score" in out.columns
