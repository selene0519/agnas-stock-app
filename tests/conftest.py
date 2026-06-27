from __future__ import annotations

import sys
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "mone-web-app" / "backend"


def pytest_configure(config: pytest.Config) -> None:
    os.environ.setdefault("MONE_FORCE_TEST_WRITE_REDIRECT", "1")


@pytest.fixture(autouse=True)
def isolate_virtual_trade_journal_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    try:
        from app.services import virtual_trade_journal as vtj
    except Exception:
        return

    base = tmp_path / "virtual_trade_journal"
    data_dir = base / "data"
    reports_dir = base / "reports"
    history_dir = data_dir / "history"
    monkeypatch.setattr(vtj, "DATA_DIR", data_dir)
    monkeypatch.setattr(vtj, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(vtj, "JOURNAL_CSV", data_dir / "virtual_trade_journal.csv")
    monkeypatch.setattr(vtj, "EVALUATION_CSV", data_dir / "virtual_trade_evaluations.csv")
    monkeypatch.setattr(vtj, "AUTO_CAPTURE_STATUS_JSON", reports_dir / "virtual_trade_journal_status.json")
    monkeypatch.setattr(vtj, "CALIBRATION_APPROVALS_CSV", data_dir / "virtual_trade_calibration_approvals.csv")
    monkeypatch.setattr(vtj, "CALIBRATION_APPLICATIONS_CSV", data_dir / "virtual_trade_calibration_applications.csv")
    monkeypatch.setattr(vtj, "SELF_LEARNING_STATUS_JSON", reports_dir / "virtual_trade_self_learning_status.json")
    monkeypatch.setattr(vtj, "HISTORY_OPERATION_CSV", history_dir / "virtual_operation_history.csv")
    monkeypatch.setattr(vtj, "HISTORY_EVALUATION_CSV", history_dir / "virtual_operation_evaluation.csv")
    monkeypatch.setattr(vtj, "VIRTUAL_VALIDATION_RESULTS_CSV", reports_dir / "virtual_validation_results.csv")
    monkeypatch.setattr(vtj, "HISTORICAL_CALIBRATION_REPORT_JSON", reports_dir / "historical_strategy_calibration.json")
    if hasattr(vtj, "_FEEDBACK_JSON"):
        monkeypatch.setattr(vtj, "_FEEDBACK_JSON", data_dir / "attribution_feedback.json")
