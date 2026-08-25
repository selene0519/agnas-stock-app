from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_ai_paper_supervisor.py"
SPEC = importlib.util.spec_from_file_location("ai_paper_supervisor", SCRIPT_PATH)
assert SPEC and SPEC.loader
supervisor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervisor)


def test_latest_evaluations_removes_orphans_and_keeps_latest() -> None:
    rows = [
        {"journal_id": "keep", "evaluated_at": "2026-07-20T10:00:00", "status": "PENDING"},
        {"journal_id": "keep", "evaluated_at": "2026-07-21T10:00:00", "status": "EVALUATED"},
        {"journal_id": "orphan", "evaluated_at": "2026-07-22T10:00:00", "status": "EVALUATED"},
        {"journal_id": "", "evaluated_at": "2026-07-22T10:00:00", "status": "EVALUATED"},
    ]

    canonical, dropped = supervisor._latest_evaluations(rows, {"keep"})

    assert canonical == [{"journal_id": "keep", "evaluated_at": "2026-07-21T10:00:00", "status": "EVALUATED"}]
    assert dropped == {"droppedMissingId": 1, "droppedOrphan": 1, "droppedSuperseded": 1}


def test_supervisor_preserves_status_per_market(monkeypatch, tmp_path) -> None:
    status_path = tmp_path / "supervisor.json"
    status_path.write_text(
        json.dumps({"market": "kr", "byMarket": {"kr": {"status": "OK", "market": "kr", "lastRunAt": "old-kr"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(supervisor, "SUPERVISOR_STATUS_PATH", status_path)
    monkeypatch.setattr(supervisor, "repair_evaluation_ledger", lambda: {"status": "OK"})
    monkeypatch.setattr(supervisor.vtj, "evaluate", lambda **kwargs: {"status": "OK", "evaluated": 0, "outcomes": {}})
    monkeypatch.setattr(
        supervisor.vtj,
        "ops_dashboard",
        lambda **kwargs: {"operational": {"status": "RUNNING", "recordingStatus": "OK", "evaluationStatus": "OK"}},
    )
    monkeypatch.setattr(
        supervisor.ai_paper_trader,
        "run_cycle",
        lambda **kwargs: {"status": "OK", "market": "us", "markets": {"us": {"summary": {"portfolioValue": 100}}}},
    )

    result = supervisor.run_supervisor(market="us", execute=True)
    persisted = json.loads(status_path.read_text(encoding="utf-8"))

    assert result["byMarket"]["kr"]["lastRunAt"] == "old-kr"
    assert result["byMarket"]["us"]["market"] == "us"
    assert persisted["byMarket"]["us"]["paper"]["markets"]["us"]["summary"]["portfolioValue"] == 100