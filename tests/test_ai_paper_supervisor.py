from __future__ import annotations

import importlib.util
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
