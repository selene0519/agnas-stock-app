"""수집기 자동 동기화의 브랜치 가드 회귀 테스트.

수집기의 커밋/rebase/push는 전부 main 기준(`git push origin main`)이다.
피처 브랜치가 체크아웃돼 있으면 데이터 커밋이 그 브랜치에 쌓이고, push는
낡은 로컬 main ref를 밀다가 실패한다. 2026-07-27에 실제로 작업 브랜치에
수집 커밋 3개(273파일)가 얹히고 push가 계속 실패했다.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "local_data_collector", ROOT / "scripts" / "local_data_collector.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _fake_git(branch: str, status: str = ""):
    def run(args, timeout=30):
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return subprocess.CompletedProcess(args, 0, stdout=branch + "\n", stderr="")
        if args[0] == "status":
            return subprocess.CompletedProcess(args, 0, stdout=status, stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    return run


def test_feature_branch_blocks_auto_sync(monkeypatch, tmp_path) -> None:
    mod = _load()
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(mod, "_run_git", _fake_git("fix/some-work"))

    reason = mod._auto_sync_block_reason()
    assert reason is not None
    assert "main이 아닙니다" in reason
    assert "fix/some-work" in reason


def test_detached_head_blocks_auto_sync(monkeypatch, tmp_path) -> None:
    mod = _load()
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(mod, "_run_git", _fake_git("HEAD"))

    reason = mod._auto_sync_block_reason()
    assert reason is not None and "main이 아닙니다" in reason


def test_main_branch_with_only_data_changes_is_allowed(monkeypatch, tmp_path) -> None:
    """수집기 산출물(data/, reports/)만 바뀐 main은 정상 경로다."""
    mod = _load()
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    (tmp_path / ".git").mkdir()
    status = " M data/market/ohlcv/kr_005930_daily.csv\n M reports/strategy_win_rates.json\n"
    monkeypatch.setattr(mod, "_run_git", _fake_git("main", status))

    assert mod._auto_sync_block_reason() is None


def test_main_branch_with_source_changes_still_blocks(monkeypatch, tmp_path) -> None:
    """기존 가드(사용자 작업 보호)가 브랜치 검사 추가 후에도 살아 있어야 한다."""
    mod = _load()
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    (tmp_path / ".git").mkdir()
    status = " M scripts/local_data_collector.py\n"
    monkeypatch.setattr(mod, "_run_git", _fake_git("main", status))

    reason = mod._auto_sync_block_reason()
    assert reason is not None and "수집기 대상이 아닌 변경" in reason


def test_in_progress_rebase_on_main_still_blocks(monkeypatch, tmp_path) -> None:
    mod = _load()
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    (tmp_path / ".git" / "rebase-merge").mkdir(parents=True)
    monkeypatch.setattr(mod, "_run_git", _fake_git("main"))

    reason = mod._auto_sync_block_reason()
    assert reason is not None and "rebase-merge" in reason
