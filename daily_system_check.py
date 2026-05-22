"""Lightweight daily system check helpers used by tests and admin diagnostics."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

REPORT_DIR = Path("reports")
CATALYST_VALIDATION_SUMMARY_JSON = REPORT_DIR / "catalyst_validation_summary.json"
CATALYST_VALIDATION_REPORT_CSV = REPORT_DIR / "catalyst_validation_report.csv"
COVERAGE_DIAGNOSIS_JSON = REPORT_DIR / "intraday_data_coverage_diagnosis.json"
UNSUPPORTED_SYMBOLS_CSV = REPORT_DIR / "intraday_unsupported_symbols.csv"
IMPROVEMENT_SUGGESTIONS_JSON = REPORT_DIR / "intraday_data_improvement_suggestions.json"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not Path(path).exists():
            return {}
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _row_count(path: Path) -> int:
    try:
        if not Path(path).exists():
            return 0
        return int(len(pd.read_csv(path)))
    except Exception:
        return 0


def _catalyst_validation_status() -> dict[str, Any]:
    data = _read_json(CATALYST_VALIDATION_SUMMARY_JSON)
    status = str(data.get("overall_status") or data.get("catalyst_validation_status") or "MISSING")
    return {
        "catalyst_validation_status": status,
        "overall_status": status,
        "catalyst_score_unique_count": data.get("catalyst_score_unique_count", 0),
        "top_decision_log_ratio": data.get("top_decision_log_ratio", 0),
        "warnings": data.get("warnings", []),
        "errors": data.get("errors", []),
        "report_rows": _row_count(CATALYST_VALIDATION_REPORT_CSV),
        "summary_path": str(CATALYST_VALIDATION_SUMMARY_JSON),
        "report_path": str(CATALYST_VALIDATION_REPORT_CSV),
    }


def _intraday_coverage_diagnosis_status() -> dict[str, Any]:
    data = _read_json(COVERAGE_DIAGNOSIS_JSON)
    exists = Path(COVERAGE_DIAGNOSIS_JSON).exists()
    status = str(data.get("overall_status") or data.get("intraday_coverage_diagnosis_status") or ("MISSING" if not exists else "OK"))
    return {
        "diagnosis_report_exists": bool(exists),
        "intraday_coverage_diagnosis_status": status,
        "overall_status": status,
        "total_symbol_count": data.get("total_symbol_count", 0),
        "recoverable_issue_count": data.get("recoverable_issue_count", 0),
        "unsupported_symbol_count": _row_count(UNSUPPORTED_SYMBOLS_CSV),
        "suggestion_count": len(_read_json(IMPROVEMENT_SUGGESTIONS_JSON) or []),
        "diagnosis_path": str(COVERAGE_DIAGNOSIS_JSON),
    }


def run_daily_system_check() -> dict[str, Any]:
    return {
        "catalyst_validation": _catalyst_validation_status(),
        "intraday_coverage_diagnosis": _intraday_coverage_diagnosis_status(),
    }
