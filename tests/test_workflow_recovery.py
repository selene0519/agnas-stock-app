from __future__ import annotations

import gzip
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER_NAMES = (
    "virtual_operation_history",
    "virtual_operation_evaluation",
)


def _load_migration_module():
    path = ROOT / "scripts" / "migrate_virtual_operation_history.py"
    spec = importlib.util.spec_from_file_location("migrate_virtual_operation_history", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_virtual_operation_ledgers_are_compressed_and_below_git_limit():
    history = ROOT / "data" / "history"
    for name in LEDGER_NAMES:
        legacy = history / f"{name}.csv"
        compressed = history / f"{name}.csv.gz"
        assert not legacy.exists()
        assert compressed.exists()
        assert compressed.stat().st_size < 95 * 1024 * 1024
        with gzip.open(compressed, "rt", encoding="utf-8-sig", newline="") as handle:
            header = handle.readline()
            first_row = handle.readline()
        assert "," in header
        assert first_row.strip()


def test_migration_is_lossless_and_deterministic(tmp_path):
    module = _load_migration_module()
    source = tmp_path / "ledger.csv"
    payload = b"created_at,symbol\n2026-08-13,005930\n"
    source.write_bytes(payload)

    module.migrate(source, remove_source=True)
    compressed = tmp_path / "ledger.csv.gz"
    first_bytes = compressed.read_bytes()
    assert not source.exists()
    with gzip.open(compressed, "rb") as handle:
        assert handle.read() == payload

    source.write_bytes(payload)
    module.migrate(source, remove_source=True)
    assert compressed.read_bytes() == first_bytes


def test_auto_workflow_migrates_before_recording_history():
    workflow = (ROOT / ".github" / "workflows" / "mone-auto-accumulator.yml").read_text(encoding="utf-8")
    migrate = "python scripts/migrate_virtual_operation_history.py --remove-source"
    record = "python record_operation_history.py --market all"
    assert migrate in workflow
    assert workflow.index(migrate) < workflow.index(record)


def test_commit_workflows_rebase_restage_and_retry():
    app_commit = (ROOT / "scripts" / "ci_commit_app_data.sh").read_text(encoding="utf-8")
    assert 'MAX_PUSH_ATTEMPTS="${MONE_CI_PUSH_ATTEMPTS:-8}"' in app_commit
    assert "Refusing oversized Git blob" in app_commit
    reset = app_commit.index('git reset --mixed "origin/${GITHUB_REF_NAME}"')
    restage = app_commit.index("stage_app_data", reset)
    assert reset < restage

    walkforward = (ROOT / ".github" / "workflows" / "mone-walkforward.yml").read_text(encoding="utf-8")
    loop = walkforward.index('for attempt in $(seq 1 "${max_attempts}")')
    reset = walkforward.index("git reset --mixed origin/main", loop)
    stage = walkforward.index("stage_backtest_results", reset)
    commit = walkforward.index('git commit -m "chore: weekly walk-forward', stage)
    assert loop < reset < stage < commit


def _write_gzip_ledger(path: Path, rows: list[dict[str, str]]) -> None:
    import csv

    with gzip.open(path, "wt", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_operation_history_limit_is_memory_bounded_and_keeps_newest(tmp_path, monkeypatch):
    from app.services import operation_history

    ledger = tmp_path / "virtual_operation_history.csv.gz"
    rows = [
        {
            "created_at": f"2026-08-{day:02d} 16:30:00",
            "market": "kr" if day % 2 else "us",
            "mode": "balanced",
            "symbol": f"{day:06d}",
        }
        for day in range(1, 21)
    ]
    _write_gzip_ledger(ledger, rows)
    recent = tmp_path / "virtual_operation_history_recent.csv"
    index = tmp_path / "virtual_operation_history_index.json"
    from app.services.operation_history_storage import rebuild_sidecar
    rebuild_sidecar(ledger, recent, index, rows_per_cell=3)
    monkeypatch.setattr(operation_history, "VIRTUAL_HISTORY_FILE", ledger)
    monkeypatch.setattr(operation_history, "VIRTUAL_HISTORY_RECENT_FILE", recent)
    monkeypatch.setattr(operation_history, "VIRTUAL_HISTORY_INDEX_FILE", index)

    payload = operation_history.virtual_operation_history("kr", "balanced", limit=3)
    assert payload["count"] == 10
    assert [row["created_at"] for row in payload["items"]] == [
        "2026-08-19 16:30:00",
        "2026-08-17 16:30:00",
        "2026-08-15 16:30:00",
    ]


def test_virtual_summary_uses_recent_window_and_avoids_duplicate_history(tmp_path, monkeypatch):
    from app.engine import mone_v61_virtual_summary as summary

    history_dir = tmp_path / "data" / "history"
    history_dir.mkdir(parents=True)
    evaluation = history_dir / "virtual_operation_evaluation.csv.gz"
    operation = history_dir / "virtual_operation_history.csv.gz"
    rows = [
        {"evaluated_at": f"2026-08-{day:02d}", "market": "kr", "symbol": f"{day:06d}"}
        for day in range(1, 21)
    ]
    _write_gzip_ledger(evaluation, rows)
    _write_gzip_ledger(operation, rows)
    monkeypatch.setattr(summary, "_root", lambda: tmp_path)

    recent = summary._read_csv_recent(evaluation, limit=3)
    assert [row["evaluated_at"] for row in recent] == [
        "2026-08-20",
        "2026-08-19",
        "2026-08-18",
    ]
    paths = summary._virtual_paths()
    assert evaluation in paths
    assert operation not in paths

def test_ai_paper_workflow_installs_pinned_runtime_dependencies():
    workflow = (ROOT / ".github" / "workflows" / "mone-ai-paper-trader.yml").read_text(encoding="utf-8")

    install = workflow.index("Install runtime dependencies")
    execute = workflow.index("python scripts/run_ai_paper_supervisor.py")
    assert install < execute
    assert '"pandas>=2.2,<3"' in workflow
    assert '"numpy>=1.26,<3"' in workflow
    assert "requests python-dotenv" in workflow
