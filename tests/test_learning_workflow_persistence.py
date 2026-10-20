from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_settlement_persists_self_correction_lineage_and_fails_on_error() -> None:
    workflow = (ROOT / ".github/workflows/mone-settle-validations.yml").read_text(encoding="utf-8")
    for path in (
        "data/self_correction_candidate_registry.csv",
        "data/self_correction_shadow_predictions.csv",
        "data/self_correction_shadow_settlements.csv",
        "reports/self_correction_shadow.json",
        "reports/self_correction_promotion.json",
    ):
        assert path in workflow
    assert 'if [ -f "$path" ]; then git add -- "$path"; fi' in workflow
    assert "Self-correction settlement failed" in workflow


def test_ledger_writers_queue_and_checkout_current_branch() -> None:
    for name in ("mone-auto-accumulator.yml", "mone-settle-validations.yml", "mone-vtj-capture.yml", "mone-ai-paper-trader.yml"):
        workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "group: mone-ledger-writer-${{ github.ref }}" in workflow
        assert "cancel-in-progress: false" in workflow
        assert "queue: max" in workflow
        assert "ref: ${{ github.ref_name }}" in workflow


def test_accumulator_stages_optional_lineage_files_individually() -> None:
    script = (ROOT / "scripts/ci_commit_app_data.sh").read_text(encoding="utf-8")
    assert 'if [ -f "$path" ]; then git add -- "$path"; fi' in script


def test_accumulator_does_not_create_after_close_journals_before_close() -> None:
    workflow = (ROOT / ".github/workflows/mone-auto-accumulator.yml").read_text(encoding="utf-8")
    assert "vtj.run_auto_capture(" not in workflow


def test_accumulator_checks_backend_sync_result() -> None:
    workflow = (ROOT / ".github/workflows/mone-auto-accumulator.yml").read_text(encoding="utf-8")
    assert 'acceptable={"OK", "DEPLOYMENT_NO_GIT", "NO_GIT_REMOTE"}' in workflow
    assert 'MONE_ADMIN_SECRET is missing' in workflow
    assert 'sync_status=SKIPPED_SECRET_MISSING' in workflow
    assert 'sync-now 호출 실패 (무시)' not in workflow
