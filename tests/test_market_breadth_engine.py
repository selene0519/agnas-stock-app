import pandas as pd
from pathlib import Path

from core.market_breadth_engine import calculate_candidate_breadth, calculate_sector_internal_strength


SECOND_UPDATE_COLUMNS = [
    "candidate_up_ratio",
    "candidate_down_ratio",
    "candidate_avg_change_pct",
    "candidate_median_change_pct",
    "candidate_volume_strength",
    "breadth_risk_score",
    "market_breadth_warning",
    "sector_internal_strength",
    "sector_spread_score",
    "market_hardblock",
    "hardblock_level",
    "hardblock_reasons",
    "new_buy_blocked",
]


def test_candidate_down_ratio_85_or_more_is_high_risk():
    df = pd.DataFrame(
        [{"change_pct": "-1.0%", "volume_ratio": "1.5배"} for _ in range(9)]
        + [{"change_pct": "+0.5%", "volume_ratio": "0.8배"}]
    )

    result = calculate_candidate_breadth(df)

    assert result["candidate_down_ratio"] >= 0.85
    assert result["breadth_risk_score"] >= 80
    assert "위험회피" in result["market_breadth_warning"]


def test_market_breadth_score_is_clipped_0_100():
    df = pd.DataFrame([{"change_pct": "-5%", "volume_ratio": "5배"} for _ in range(20)])

    result = calculate_candidate_breadth(df)

    assert 0 <= result["breadth_risk_score"] <= 100


def test_negative_average_and_median_add_risk():
    df = pd.DataFrame(
        [
            {"change_pct": "-1%", "volume_ratio": "1배"},
            {"change_pct": "-2%", "volume_ratio": "1배"},
            {"change_pct": "+0.5%", "volume_ratio": "1배"},
        ]
    )

    result = calculate_candidate_breadth(df)

    assert result["candidate_avg_change_pct"] < 0
    assert result["candidate_median_change_pct"] < 0
    assert result["breadth_risk_score"] > 0


def test_sector_internal_strength_returns_spread_score():
    df = pd.DataFrame(
        [
            {"sector": "A", "change_pct": "+1%", "volume_ratio": "1.2배"},
            {"sector": "A", "change_pct": "-1%", "volume_ratio": "1.0배"},
            {"sector": "B", "change_pct": "+2%", "volume_ratio": "1.5배"},
        ]
    )

    result = calculate_sector_internal_strength(df)

    assert "sector_spread_score" in result.columns
    assert result["sector_spread_score"].between(0, 100).all()


def test_us_candidate_csvs_keep_breadth_hardblock_schema_even_when_empty():
    files = [
        "reports/swing_candidates_us_A_top3.csv",
        "reports/swing_candidates_us_B_watch.csv",
        "reports/swing_candidates_us_C_excluded.csv",
    ]

    for file_name in files:
        path = Path(file_name)
        assert path.exists(), f"{file_name} does not exist"
        df = pd.read_csv(path)
        missing = [col for col in SECOND_UPDATE_COLUMNS if col not in df.columns]
        assert missing == []


def test_us_c_excluded_keeps_trade_allowed_false():
    path = Path("reports/swing_candidates_us_C_excluded.csv")
    assert path.exists()
    df = pd.read_csv(path, dtype=str).fillna("")

    allowed = df["strategy_trade_allowed"].astype(str).str.lower().isin(["true", "1", "1.0"])

    assert int(allowed.sum()) == 0
