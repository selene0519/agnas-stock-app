import json
from pathlib import Path

import pandas as pd

from core.historical_pattern_stats_engine import (
    apply_historical_pattern_stats_to_candidates,
    build_condition_bucket,
    generate_weight_adjustment_suggestions,
    save_historical_pattern_reports,
    summarize_historical_pattern_performance,
)


def _review_row(**overrides):
    row = {
        "prediction_result": "success",
        "score": 72,
        "rr": 2.1,
        "rr_pass": True,
        "entry_gap_pct": 1.0,
        "sector": "AI",
        "daily_setup": "pullback",
        "news_grade": "B",
        "strategy_mode": "박스장",
        "entry_position_type": "눌림 확인 완료",
        "aggressive_score": 75,
        "return_1d": 0.5,
        "return_3d": 1.0,
        "return_5d": 2.0,
        "return_10d": 3.0,
        "tp1_hit_5d": True,
        "stop_hit_5d": False,
        "tp_first": True,
        "stop_first": False,
        "market_excess_return_5d": 1.0,
        "sector_excess_return_5d": 0.5,
    }
    row.update(overrides)
    return row


def test_build_condition_bucket_has_condition_key():
    bucket = build_condition_bucket(_review_row())

    assert "condition_key" in bucket
    assert "rr_2_2.99" in bucket["condition_key"]


def test_sample_count_and_not_enough_data_exclusion():
    df = pd.DataFrame([_review_row(), _review_row(), _review_row(prediction_result="not_enough_data")])

    stats = summarize_historical_pattern_performance(df)

    assert int(stats["sample_count"].sum()) == 2


def test_tp_and_stop_rates_are_calculated():
    df = pd.DataFrame(
        [
            _review_row(tp1_hit_5d=True, stop_hit_5d=False),
            _review_row(tp1_hit_5d=False, stop_hit_5d=True, return_5d=-2),
        ]
    )

    stats = summarize_historical_pattern_performance(df)
    row = stats.iloc[0]

    assert row["tp1_hit_rate_5d"] == 50.0
    assert row["stop_hit_rate_5d"] == 50.0


def test_less_than_20_samples_does_not_make_strong_suggestion():
    stats = pd.DataFrame(
        [
            {
                "condition_key": "small",
                "sample_count": 5,
                "expected_return_5d": -5,
                "stop_hit_rate_5d": 80,
                "tp1_hit_rate_5d": 0,
            }
        ]
    )

    suggestions = generate_weight_adjustment_suggestions(stats)

    assert suggestions
    assert all(item["strength"] != "strong" for item in suggestions)
    assert suggestions[0]["suggestion_type"] == "observe_only"


def test_apply_historical_stats_keeps_existing_columns():
    candidates = pd.DataFrame([{"symbol": "ABC", "score": 72, "rr": 2.1, "sector": "AI"}])
    stats = summarize_historical_pattern_performance(pd.DataFrame([_review_row() for _ in range(3)]))

    out = apply_historical_pattern_stats_to_candidates(candidates, stats)

    assert "symbol" in out.columns
    assert "historical_condition_key" in out.columns
    assert "historical_sample_count" in out.columns


def test_apply_historical_stats_works_when_candidate_has_forecast_expected_return():
    candidates = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "score": 72,
                "rr": 2.1,
                "rr_pass": True,
                "entry_gap_pct": 1.0,
                "sector": "AI",
                "daily_setup": "pullback",
                "news_grade": "B",
                "strategy_mode": "박스장",
                "entry_position_type": "눌림 확인 완료",
                "aggressive_score": 75,
                "expected_return_5d": 9.99,
            }
        ]
    )
    stats = summarize_historical_pattern_performance(pd.DataFrame([_review_row() for _ in range(3)]))

    out = apply_historical_pattern_stats_to_candidates(candidates, stats)

    assert out.loc[0, "historical_condition_key"]
    assert pd.notna(out.loc[0, "historical_condition_key"])
    assert "expected_return_5d" in out.columns
    assert "historical_expected_return_5d" in out.columns


def test_zero_sample_note_is_never_nan():
    candidates = pd.DataFrame([{"symbol": "ABC", "score": 72, "rr": 2.1, "sector": "AI"}])

    out = apply_historical_pattern_stats_to_candidates(candidates, pd.DataFrame())

    assert out.loc[0, "historical_sample_count"] == 0
    assert out.loc[0, "historical_pattern_note"] == "표본 부족: 유사조건 통계 미적용"
    assert pd.notna(out.loc[0, "historical_pattern_note"])


def test_missing_values_build_unknown_condition_key():
    bucket = build_condition_bucket({})

    assert bucket["condition_key"] == (
        "score_unknown|rr_unknown|entry_unknown|sector=unknown|chart=unknown|"
        "news_unknown|market=unknown|entry=unknown|agg_unknown"
    )


def test_save_historical_pattern_reports_writes_files(tmp_path, monkeypatch):
    import core.historical_pattern_stats_engine as engine

    stats_path = tmp_path / "historical_pattern_stats.csv"
    suggestions_path = tmp_path / "weight_adjustment_suggestions.json"
    monkeypatch.setattr(engine, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(engine, "HISTORICAL_PATTERN_STATS_CSV", stats_path)
    monkeypatch.setattr(engine, "WEIGHT_ADJUSTMENT_SUGGESTIONS_JSON", suggestions_path)

    save_historical_pattern_reports(pd.DataFrame([_review_row() for _ in range(2)]))

    assert stats_path.exists()
    assert suggestions_path.exists()
    assert isinstance(json.loads(suggestions_path.read_text(encoding="utf-8")), list)


def test_current_candidate_csvs_have_historical_condition_key_schema():
    for file_name in [
        "reports/swing_candidates_us_A_top3.csv",
        "reports/swing_candidates_us_B_watch.csv",
        "reports/swing_candidates_us_C_excluded.csv",
        "reports/swing_candidates_kr_A_top3.csv",
        "reports/swing_candidates_kr_B_watch.csv",
        "reports/swing_candidates_kr_C_excluded.csv",
    ]:
        path = Path(file_name)
        assert path.exists(), f"{file_name} does not exist"
        df = pd.read_csv(path, dtype=str)
        assert "historical_condition_key" in df.columns


def test_current_c_excluded_zero_sample_note_is_not_nan():
    for file_name in [
        "reports/swing_candidates_us_C_excluded.csv",
        "reports/swing_candidates_kr_C_excluded.csv",
    ]:
        df = pd.read_csv(file_name, dtype=str)
        assert df["historical_condition_key"].notna().all()
        assert not df["historical_condition_key"].astype(str).str.strip().isin(["", "nan", "None"]).any()
        if "historical_sample_count" not in df.columns or df.empty:
            continue
        zero = pd.to_numeric(df["historical_sample_count"], errors="coerce").fillna(0).eq(0)
        if bool(zero.any()):
            assert df.loc[zero, "historical_pattern_note"].notna().all()
            assert not df.loc[zero, "historical_pattern_note"].astype(str).str.strip().isin(["", "nan", "None"]).any()
