from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.portfolio_risk_manager import backfill_portfolio_risk_candidate_files
from core.sell_management_engine import backfill_sell_management_candidate_files
from core.swing_candidate_grade_engine import apply_final_candidate_bucket, build_hard_block_reason
from core.swing_candidate_io import read_swing_candidate_csv, save_swing_candidate_csv


CANDIDATE_FILES = [
    Path("reports/swing_candidates_us_A_top3.csv"),
    Path("reports/swing_candidates_us_B_watch.csv"),
    Path("reports/swing_candidates_us_C_excluded.csv"),
    Path("reports/swing_candidates_kr_A_top3.csv"),
    Path("reports/swing_candidates_kr_B_watch.csv"),
    Path("reports/swing_candidates_kr_C_excluded.csv"),
]
APP_REQUIRED_COLUMNS = [
    "strategy_mode",
    "strategy_adjusted_grade",
    "strategy_trade_allowed",
    "position_size_pct",
    "position_action",
    "prob_up_5d",
    "prob_stop_5d",
    "forecast_label",
    "sell_timing_label",
    "portfolio_risk_level",
    "portfolio_warnings",
]


def test_review_update_runner_entrypoint_exists():
    runner = Path("runners/review_update_runner.py")

    assert runner.exists()
    assert "review" in runner.read_text(encoding="utf-8", errors="ignore").lower()


def test_swing_candidate_io_roundtrip_keeps_schema(tmp_path):
    target = tmp_path / "swing_candidates_us_A_top3.csv"
    df = pd.DataFrame([{"symbol": "ABC", "grade": "A", "score": 90}])

    save_swing_candidate_csv(df, target, required_columns=APP_REQUIRED_COLUMNS)
    loaded = read_swing_candidate_csv(target, required_columns=APP_REQUIRED_COLUMNS)

    assert len(loaded) == 1
    for col in APP_REQUIRED_COLUMNS:
        assert col in loaded.columns
    assert "original_grade" in loaded.columns
    assert "final_grade" in loaded.columns


def test_grade_engine_handles_hard_block_and_bucket():
    df = pd.DataFrame(
        [
            {
                "symbol": "ABC",
                "grade": "A",
                "rr_pass": False,
                "strategy_trade_allowed": True,
                "strategy_adjusted_grade": "A",
            }
        ]
    )

    out = apply_final_candidate_bucket(df)

    assert build_hard_block_reason(out.iloc[0].to_dict()) == "rr_pass=False"
    assert out.loc[0, "final_candidate_bucket"] == "FORBIDDEN"


def test_candidate_pipeline_outputs_have_app_required_columns(tmp_path):
    files = [tmp_path / path.name for path in CANDIDATE_FILES]
    for path in files:
        save_swing_candidate_csv(
            pd.DataFrame([{"symbol": "ABC", "market": "us", "grade": "A", "score": 90}]),
            path,
            required_columns=APP_REQUIRED_COLUMNS,
        )

    backfill_sell_management_candidate_files(files)
    backfill_portfolio_risk_candidate_files(files, tmp_path / "portfolio_risk_summary.json", base_dir=tmp_path)

    for path in files:
        assert path.exists()
        df = read_swing_candidate_csv(path, required_columns=APP_REQUIRED_COLUMNS)
        for col in APP_REQUIRED_COLUMNS:
            assert col in df.columns


def test_empty_ab_files_keep_required_schema():
    for path in [
        Path("reports/swing_candidates_us_A_top3.csv"),
        Path("reports/swing_candidates_us_B_watch.csv"),
        Path("reports/swing_candidates_kr_A_top3.csv"),
        Path("reports/swing_candidates_kr_B_watch.csv"),
    ]:
        df = read_swing_candidate_csv(path, required_columns=APP_REQUIRED_COLUMNS)
        for col in APP_REQUIRED_COLUMNS:
            assert col in df.columns


def test_c_excluded_trade_allowed_is_never_true():
    for path in [Path("reports/swing_candidates_us_C_excluded.csv"), Path("reports/swing_candidates_kr_C_excluded.csv")]:
        df = read_swing_candidate_csv(path, required_columns=APP_REQUIRED_COLUMNS)
        if "strategy_trade_allowed" not in df.columns:
            continue
        true_count = int(df["strategy_trade_allowed"].astype(str).str.lower().isin(["true", "1", "1.0"]).sum())
        assert true_count == 0
