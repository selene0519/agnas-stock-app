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
