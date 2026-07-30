from __future__ import annotations

import csv
import importlib.util
import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_walkforward_integrity",
    ROOT / "scripts" / "audit_walkforward_integrity.py",
)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def _write_market(reports: Path, market: str, quality: dict) -> None:
    with (reports / f"walkforward_results_{market}.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["window"])
        writer.writeheader()
        writer.writerow({"window": "2026-06-01"})
    (reports / f"walkforward_summary_{market}.json").write_text(json.dumps({
        "combos": {f"{market}_balanced_short": {"dataQuality": quality}},
    }), encoding="utf-8")


def test_promotion_grade_requires_embargo_and_point_in_time_universe(tmp_path: Path) -> None:
    quality = {
        "lookAheadControlled": True,
        "trainingOutcomesResolvedBeforeWindow": True,
        "sameDayOutcomeEmbargo": True,
        "survivorshipBias": False,
        "pointInTimeListingFilter": True,
    }
    _write_market(tmp_path, "kr", quality)

    result = audit.audit_market("kr", tmp_path, date(2026, 7, 30))

    assert result["promotionGrade"] is True
    assert result["blockingReasons"] == []


def test_old_report_and_survivorship_bias_are_research_only(tmp_path: Path) -> None:
    quality = {
        "lookAheadControlled": True,
        "survivorshipBias": True,
        "pointInTimeListingFilter": False,
    }
    _write_market(tmp_path, "us", quality)

    result = audit.audit_market("us", tmp_path, date(2026, 7, 30))

    assert result["promotionGrade"] is False
    assert "RERUN_REQUIRED_FOR_OUTCOME_EMBARGO_PROOF" in result["blockingReasons"]
    assert "SURVIVORSHIP_BIAS_RESEARCH_ONLY" in result["blockingReasons"]


def test_future_window_is_rejected(tmp_path: Path) -> None:
    quality = {
        "lookAheadControlled": True,
        "trainingOutcomesResolvedBeforeWindow": True,
        "sameDayOutcomeEmbargo": True,
        "survivorshipBias": False,
        "pointInTimeListingFilter": True,
    }
    _write_market(tmp_path, "kr", quality)
    with (tmp_path / "walkforward_results_kr.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["window"])
        writer.writeheader()
        writer.writerow({"window": "2026-08-01"})

    result = audit.audit_market("kr", tmp_path, date(2026, 7, 30))

    assert result["promotionGrade"] is False
    assert "CSV_TEMPORAL_INTEGRITY_FAILED" in result["blockingReasons"]
