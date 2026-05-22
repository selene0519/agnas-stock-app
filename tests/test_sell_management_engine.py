from pathlib import Path

import pandas as pd

from core.sell_management_engine import (
    SELL_MANAGEMENT_COLUMNS,
    apply_sell_management,
    apply_sell_management_plan,
    backfill_sell_management_candidate_files,
    calculate_sell_management_plan,
)


def test_stop_break_prioritizes_stop_loss():
    result = calculate_sell_management_plan(
        {
            "last_price": 94,
            "entry": 100,
            "stop": 95,
            "tp1": 110,
            "prob_up_5d": 60,
        }
    )

    assert result["sell_timing_label"] == "손절 우선"
    assert result["hold_or_sell_decision"] == "손절 우선"
    assert result["trailing_stop_level"] == 95


def test_near_target_and_overheat_suggests_partial_profit():
    result = calculate_sell_management_plan(
        {
            "last_price": 108,
            "entry": 100,
            "stop": 95,
            "tp1": 110,
            "tp2": 120,
            "overheat_level": "높음",
            "prob_up_5d": 58,
            "prob_stop_5d": 20,
        }
    )

    assert result["sell_timing_label"] == "일부 익절"
    assert "분할익절" in result["profit_taking_plan"]
    assert "1차 목표가 근접" in result["sell_reasons"]


def test_declining_probability_suggests_reduce_position():
    result = calculate_sell_management_plan(
        {
            "last_price": 101,
            "entry": 100,
            "stop": 95,
            "tp1": 110,
            "prob_up_5d": 38,
            "prob_tp1_5d": 20,
            "prob_stop_5d": 45,
            "expected_return_5d": -1.2,
            "strategy_mode": "하락장",
        }
    )

    assert result["sell_timing_label"] == "비중 축소"
    assert result["hold_or_sell_decision"] == "축소 또는 관망"


def test_trailing_stop_level_moves_up_after_profit():
    result = calculate_sell_management_plan(
        {
            "last_price": 116,
            "entry": 100,
            "stop": 94,
            "tp1": 110,
            "tp2": 125,
            "prob_up_5d": 60,
            "prob_stop_5d": 20,
            "expected_return_5d": 2.5,
        }
    )

    assert result["trailing_stop_level"] > 94
    assert result["trailing_stop_level"] < 116


def test_apply_sell_management_plan_keeps_existing_columns():
    df = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "last_price": 108,
                "entry": 100,
                "stop": 95,
                "tp1": 110,
                "overheat_level": "높음",
            }
        ]
    )

    out = apply_sell_management_plan(df)

    assert "symbol" in out.columns
    assert "sell_timing_label" in out.columns
    assert out.loc[0, "symbol"] == "ABC"


def test_forbidden_candidate_gets_holder_only_default_text():
    result = calculate_sell_management_plan(
        {
            "last_price": 100,
            "entry": 100,
            "stop": 95,
            "tp1": 110,
            "position_size_pct": 0,
            "strategy_trade_allowed": False,
            "strategy_adjusted_grade": "C",
        }
    )

    assert result["sell_timing_label"] == "보유자만 관리"
    assert result["hold_or_sell_decision"] == "신규매수 금지/관망"
    assert "신규매수 금지 상태" in result["sell_reasons"][0]
    assert "신규 진입 금지" in result["sell_warnings"][0]


def test_empty_ab_rows_keep_sell_management_schema():
    out = apply_sell_management(pd.DataFrame(columns=["symbol", "grade"]))

    for col in SELL_MANAGEMENT_COLUMNS:
        assert col in out.columns


def test_backfill_candidate_files_adds_schema_and_defaults(tmp_path):
    us_a = tmp_path / "reports" / "swing_candidates_us_A_top3.csv"
    kr_b = tmp_path / "reports" / "swing_candidates_kr_B_watch.csv"
    us_c = tmp_path / "reports" / "swing_candidates_us_C_excluded.csv"
    kr_c = tmp_path / "reports" / "swing_candidates_kr_C_excluded.csv"
    for empty_file in [us_a, kr_b]:
        empty_file.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=["symbol", "grade"]).to_csv(empty_file, index=False, encoding="utf-8-sig")
    c_df = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "grade": "C",
                "strategy_adjusted_grade": "C",
                "strategy_trade_allowed": False,
                "position_size_pct": 0,
                "last_price": 100,
                "entry": 100,
                "stop": 95,
                "tp1": 110,
            }
        ]
    )
    c_df.to_csv(us_c, index=False, encoding="utf-8-sig")
    c_df.to_csv(kr_c, index=False, encoding="utf-8-sig")

    backfill_sell_management_candidate_files([us_a, kr_b, us_c, kr_c])

    for path in [us_a, kr_b, us_c, kr_c]:
        df = pd.read_csv(path, dtype=str).fillna("")
        for col in SELL_MANAGEMENT_COLUMNS:
            assert col in df.columns
    for path in [us_c, kr_c]:
        df = pd.read_csv(path, dtype=str).fillna("")
        assert df["strategy_trade_allowed"].astype(str).str.lower().isin(["true", "1", "1.0"]).sum() == 0
        assert not df["sell_reasons"].astype(str).str.strip().isin(["", "nan", "None"]).any()
        assert not df["sell_warnings"].astype(str).str.strip().isin(["", "nan", "None"]).any()
