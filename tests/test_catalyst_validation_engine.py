import json

import pandas as pd

import daily_system_check
from core.catalyst_validation_engine import (
    build_catalyst_validation_report,
    build_catalyst_validation_summary,
    save_catalyst_validation_reports,
    validate_catalyst_score_distribution,
    validate_decision_log_diversity,
)


def _row(symbol="AAA", score=60, log="뉴스 반영", market="미국주식"):
    return {
        "symbol": symbol,
        "market": market,
        "catalyst_score": score,
        "news_importance_score": score,
        "news_freshness_score": 55,
        "disclosure_score": 50,
        "earnings_score": 60,
        "supply_score": 65,
        "catalyst_reasons": "뉴스 확인",
        "catalyst_warnings": "",
        "decision_change_log": log,
    }


def test_missing_required_catalyst_columns_is_error():
    result = validate_catalyst_score_distribution(pd.DataFrame([{"symbol": "AAA"}]))

    assert result["score_distribution_status"] == "ERROR"
    assert result["errors"]


def test_catalyst_score_out_of_range_is_error():
    df = pd.DataFrame([_row(score=101)])

    result = validate_catalyst_score_distribution(df)

    assert result["score_distribution_status"] == "ERROR"
    assert any("outside 0~100" in err for err in result["errors"])


def test_too_few_unique_catalyst_scores_is_warning():
    df = pd.DataFrame([_row("A", 50), _row("B", 50), _row("C", 50)])

    result = validate_catalyst_score_distribution(df)

    assert result["score_distribution_status"] == "WARNING"
    assert result["catalyst_score_unique_count"] == 1


def test_decision_change_log_repeated_above_70_percent_warns():
    df = pd.DataFrame([_row("A", 50, "same"), _row("B", 55, "same"), _row("C", 70, "same"), _row("D", 80, "other")])

    result = validate_decision_log_diversity(df)

    assert result["decision_log_status"] == "WARNING"
    assert result["top_decision_log_ratio"] >= 0.7


def test_validation_report_csv_is_created(tmp_path):
    source = tmp_path / "candidates.csv"
    report = tmp_path / "reports" / "catalyst_validation_report.csv"
    summary = tmp_path / "reports" / "catalyst_validation_summary.json"
    pd.DataFrame([_row("A", 40), _row("B", 75, "다른 근거")]).to_csv(source, index=False, encoding="utf-8-sig")

    result = save_catalyst_validation_reports([source], report, summary)

    assert report.exists()
    assert result["report_path"] == str(report)
    saved = pd.read_csv(report)
    assert "catalyst_validation_status" in saved.columns


def test_validation_summary_json_is_created(tmp_path):
    source = tmp_path / "candidates.csv"
    report = tmp_path / "reports" / "catalyst_validation_report.csv"
    summary = tmp_path / "reports" / "catalyst_validation_summary.json"
    pd.DataFrame([_row("A", 40), _row("B", 75, "다른 근거")]).to_csv(source, index=False, encoding="utf-8-sig")

    save_catalyst_validation_reports([source], report, summary)

    assert summary.exists()
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert "overall_status" in data
    assert "catalyst_score_unique_count" in data


def test_build_summary_contains_expected_fields():
    report_df = build_catalyst_validation_report(pd.DataFrame([_row("A", 40), _row("B", 75, "다른 근거")]))

    summary = build_catalyst_validation_summary(report_df)

    assert summary["row_count"] == 2
    assert "top_decision_log_ratio" in summary
    assert "market_counts" in summary


def test_daily_system_check_reads_catalyst_validation_status(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    summary_path = reports / "catalyst_validation_summary.json"
    report_path = reports / "catalyst_validation_report.csv"
    summary_path.write_text(
        json.dumps(
            {
                "overall_status": "WARNING",
                "catalyst_score_unique_count": 1,
                "top_decision_log_ratio": 0.8,
                "warnings": ["narrow"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    pd.DataFrame([{"symbol": "A"}]).to_csv(report_path, index=False)
    monkeypatch.setattr(daily_system_check, "CATALYST_VALIDATION_SUMMARY_JSON", summary_path)
    monkeypatch.setattr(daily_system_check, "CATALYST_VALIDATION_REPORT_CSV", report_path)

    status = daily_system_check._catalyst_validation_status()

    assert status["catalyst_validation_status"] == "WARNING"
    assert status["catalyst_score_unique_count"] == 1
    assert status["top_decision_log_ratio"] == 0.8
