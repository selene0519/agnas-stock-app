import json
import os
import time
from pathlib import Path

import pandas as pd

from core.data_quality_engine import (
    check_candidate_files_quality,
    check_csv_schema,
    check_file_freshness,
    check_market_regime_quality,
    check_predictions_quality,
)


def test_missing_csv_is_error(tmp_path):
    result = check_csv_schema(str(tmp_path / "missing.csv"), ["a"])

    assert result["file_exists"] is False
    assert result["status"] == "ERROR"


def test_missing_required_columns_is_error(tmp_path):
    path = tmp_path / "x.csv"
    pd.DataFrame([{"a": 1}]).to_csv(path, index=False)

    result = check_csv_schema(str(path), ["a", "b"])

    assert result["status"] == "ERROR"
    assert result["missing_columns"] == ["b"]


def test_predictions_quality_missing_required_columns_is_error(tmp_path):
    path = tmp_path / "predictions.csv"
    pd.DataFrame([{"ticker": "A"}]).to_csv(path, index=False)

    result = check_predictions_quality(str(path))

    assert result["status"] == "ERROR"


def test_candidate_c_trade_allowed_true_is_error(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    required = {
        "symbol": "A",
        "rr": 2.5,
        "risk_final_decision": "관망 우위",
        "strategy_mode": "박스장",
        "strategy_adjusted_grade": "C",
        "strategy_trade_allowed": False,
        "실전등급": "C/제외",
        "실전등급사유": "-",
        "실전경고": "-",
    }
    for name in [
        "swing_candidates_us_A_top3.csv",
        "swing_candidates_us_B_watch.csv",
        "swing_candidates_kr_A_top3.csv",
        "swing_candidates_kr_B_watch.csv",
        "swing_candidates_kr_C_excluded.csv",
    ]:
        pd.DataFrame([required]).to_csv(reports / name, index=False)
    pd.DataFrame([{**required, "strategy_trade_allowed": True}]).to_csv(
        reports / "swing_candidates_us_C_excluded.csv", index=False
    )

    result = check_candidate_files_quality(str(reports))

    assert result["status"] == "ERROR"
    assert any("strategy_trade_allowed=True" in e for e in result["errors"])


def test_candidate_a_rr_lt_2_is_error(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    required = {
        "symbol": "A",
        "rr": 2.5,
        "rr_pass": True,
        "market_risk_level": "보통",
        "overheat_level": "보통",
        "risk_final_decision": "관망 우위",
        "strategy_mode": "박스장",
        "strategy_adjusted_grade": "B",
        "strategy_trade_allowed": True,
        "실전등급": "B급",
        "실전등급사유": "-",
        "실전경고": "-",
    }
    for name in [
        "swing_candidates_us_B_watch.csv",
        "swing_candidates_us_C_excluded.csv",
        "swing_candidates_kr_A_top3.csv",
        "swing_candidates_kr_B_watch.csv",
        "swing_candidates_kr_C_excluded.csv",
    ]:
        pd.DataFrame([required]).to_csv(reports / name, index=False)
    pd.DataFrame([{**required, "rr": 1.9}]).to_csv(reports / "swing_candidates_us_A_top3.csv", index=False)

    result = check_candidate_files_quality(str(reports))

    assert result["status"] == "ERROR"
    assert any("rr < 2.0" in e for e in result["errors"])


def test_market_regime_summary_stale_is_warning(tmp_path):
    path = tmp_path / "market_regime_summary.json"
    path.write_text(json.dumps({"market_regime": "박스장", "market_risk_level": "보통"}), encoding="utf-8")
    old = time.time() - 60 * 60 * 30
    os.utime(path, (old, old))

    result = check_market_regime_quality(str(path))

    assert result["status"] == "WARNING"
    assert result["is_stale"] is True


def test_file_freshness_existing_file(tmp_path):
    path = tmp_path / "x.csv"
    path.write_text("a\n1\n", encoding="utf-8")

    result = check_file_freshness(str(path), max_age_hours=24)

    assert result["status"] == "OK"
    assert result["exists"] is True


def test_current_kr_candidate_csvs_keep_first_upgrade_schema():
    required = [
        "position_size_pct",
        "position_risk_level",
        "position_action",
        "position_reasons",
        "position_warnings",
        "original_grade",
        "final_grade",
        "grade_change_reason",
        "regime_downgrade_reason",
        "review_penalty_reason",
        "hard_block_reason",
    ]
    for name in [
        "reports/swing_candidates_kr_A_top3.csv",
        "reports/swing_candidates_kr_B_watch.csv",
        "reports/swing_candidates_kr_C_excluded.csv",
    ]:
        path = Path(name)
        assert path.exists()
        df = pd.read_csv(path)
        assert [c for c in required if c not in df.columns] == []


def test_current_kr_c_excluded_position_and_trade_block():
    path = Path("reports/swing_candidates_kr_C_excluded.csv")
    assert path.exists()
    df = pd.read_csv(path)

    assert "position_size_pct" in df.columns
    assert "final_grade" in df.columns
    assert "hard_block_reason" in df.columns
    assert pd.to_numeric(df["position_size_pct"], errors="coerce").fillna(-1).eq(0).all()
    assert int(df["strategy_trade_allowed"].astype(str).str.lower().isin(["true", "1", "1.0"]).sum()) == 0
