"""
GitHub Actions 커밋 자동 동기화 모듈.

- 백엔드 시작 시 git pull 실행 (선택적)
- /api/admin/sync 엔드포인트: 즉시 pull + lru_cache 초기화
- /api/admin/sync-status: 마지막 동기화 상태 조회
- 백그라운드 주기 동기화 (GIT_AUTO_SYNC_INTERVAL_MIN 환경변수로 설정)
"""
from __future__ import annotations

import gc
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks

_REPO_ROOT = Path(__file__).resolve().parents[4]
_STATUS_FILE = _REPO_ROOT / "reports" / "auto_sync_status.json"
_LOCK = threading.Lock()

_last_status: dict[str, Any] = {
    "status": "NOT_RUN",
    "lastSyncAt": "",
    "lastCommit": "",
    "filesChanged": 0,
    "error": "",
}


def _run_git(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd or _REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:
        return -1, "", str(exc)


def _latest_commit() -> str:
    code, out, _ = _run_git(["rev-parse", "--short", "HEAD"])
    return out if code == 0 else ""


def _git_repo_state() -> dict[str, Any]:
    code, out, err = _run_git(["rev-parse", "--is-inside-work-tree"])
    if code != 0 or out.strip().lower() != "true":
        return {
            "ok": False,
            "status": "DEPLOYMENT_NO_GIT",
            "statusLabel": "배포 환경에 git 원격 저장소가 없어 pull을 생략했습니다",
            "gitOutput": (out + "\n" + err).strip(),
        }
    code, out, err = _run_git(["remote", "get-url", "origin"])
    remote = out.strip()
    if code != 0 or not remote:
        return {
            "ok": False,
            "status": "NO_GIT_REMOTE",
            "statusLabel": "origin 원격 저장소가 없어 GitHub Actions/재배포 데이터 기준으로 동작합니다",
            "gitOutput": (out + "\n" + err).strip(),
        }
    return {"ok": True, "remote": remote}


def _files_changed(before: str, after: str) -> int:
    if not before or not after or before == after:
        return 0
    code, out, _ = _run_git(["diff", "--name-only", before, after])
    return len(out.splitlines()) if code == 0 else 0


def _clear_all_caches() -> int:
    """lru_cache 및 TTL 캐시를 사용하는 모든 모듈의 캐시 초기화."""
    cleared = 0
    targets = [
        "app.services.data_loader",
        "app.services.final_engine",
        "app.engine.mone_v65_api_stabilizer",
        "app.engine.quant_scanner",
    ]
    for mod_name in targets:
        mod = sys.modules.get(mod_name)
        if not mod:
            continue
        for attr_name in dir(mod):
            try:
                fn = getattr(mod, attr_name)
                if callable(fn) and hasattr(fn, "cache_clear"):
                    fn.cache_clear()
                    cleared += 1
            except Exception:
                pass
        # TTL cache dicts (final_engine)
        try:
            if hasattr(mod, "_RECO_CACHE"):
                mod._RECO_CACHE.clear()
                mod._RECO_CACHE_TS.clear()
                cleared += 1
        except Exception:
            pass
    gc.collect()
    return cleared


def _auto_curate_watchlist() -> dict[str, Any]:
    if os.environ.get("MONE_AUTO_CURATE_WATCHLIST", "1") == "0":
        return {"status": "DISABLED", "count": 0}
    try:
        from app.services import user_data

        limit = int(os.environ.get("MONE_AUTO_WATCHLIST_LIMIT_PER_MARKET", "12"))
        return user_data.apply_auto_watchlist("all", limit)
    except Exception as exc:
        return {"status": "ERROR", "count": 0, "error": str(exc)[:200]}


def _save_status(status: dict[str, Any]) -> None:
    global _last_status
    _last_status = status
    try:
        _STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _classify_git_error(code: int, out: str, err: str) -> str:
    """git pull 실패 원인을 분류하여 상태 코드 반환."""
    combined = (out + " " + err).lower()
    if code == 0:
        return "OK"
    if "already up to date" in combined:
        return "OK"
    if "local changes" in combined or "unstaged changes" in combined or "uncommitted changes" in combined:
        return "LOCAL_CHANGES"
    if "would be overwritten" in combined or "your local changes" in combined:
        return "LOCAL_CHANGES"
    if "conflict" in combined or "merge conflict" in combined:
        return "CONFLICT_RISK"
    if "behind" in combined and "fast-forward" in combined:
        return "BEHIND_REMOTE"
    if "cannot pull" in combined or "need to merge" in combined:
        return "BEHIND_REMOTE"
    if "network" in combined or "could not resolve" in combined or "connection" in combined or "timeout" in combined:
        return "NETWORK_ERROR"
    if (
        "not a git repository" in combined
        or "origin does not appear to be a git repository" in combined
        or "could not read from remote repository" in combined
    ):
        return "NO_GIT_REMOTE"
    return "ERROR"


def pull_and_refresh(source: str = "manual") -> dict[str, Any]:
    """git pull + lru_cache 초기화. 스레드 안전."""
    with _LOCK:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        before = _latest_commit()
        repo_state = _git_repo_state()
        if not repo_state.get("ok"):
            cleared = _clear_all_caches()
            status = {
                "status": repo_state.get("status", "NO_GIT_REMOTE"),
                "statusLabel": repo_state.get("statusLabel", ""),
                "source": source,
                "lastSyncAt": now,
                "beforeCommit": before,
                "afterCommit": before,
                "filesChanged": 0,
                "cachesCleared": cleared,
                "autoWatchlist": {"status": "SKIPPED", "count": 0},
                "gitOutput": str(repo_state.get("gitOutput") or "")[:500],
                "error": "",
            }
            _save_status(status)
            return status

        # git pull
        code, out, err = _run_git(["pull", "--rebase", "--autostash", "origin", "main"])
        after = _latest_commit()

        if code != 0 and code != -1:
            if "Already up to date" in out or "already up to date" in out.lower():
                code = 0

        sync_status = _classify_git_error(code, out, err)
        changed = _files_changed(before, after)
        cleared = _clear_all_caches() if changed > 0 or sync_status == "OK" else 0
        auto_watchlist = _auto_curate_watchlist() if sync_status == "OK" and (changed > 0 or source in {"api_sync_now", "startup"}) else {"status": "SKIPPED", "count": 0}
        if auto_watchlist.get("status") == "OK":
            cleared += _clear_all_caches()

        status_labels = {
            "LOCAL_CHANGES": "로컬 수정사항 있음 — 커밋 또는 스태시 후 재시도",
            "CONFLICT_RISK": "충돌 위험 — 원격과 로컬이 동시에 변경됨",
            "BEHIND_REMOTE": "원격보다 뒤처짐 — pull 필요",
            "NETWORK_ERROR": "네트워크 오류 — 인터넷 연결 확인",
            "NOT_GIT_REPO": "Git 저장소가 아닙니다",
            "NO_GIT_REMOTE": "origin 원격 저장소가 없어 GitHub Actions/재배포 데이터 기준으로 동작합니다",
            "DEPLOYMENT_NO_GIT": "배포 환경에 git 원격 저장소가 없어 pull을 생략했습니다",
            "ERROR": "알 수 없는 오류",
        }

        status: dict[str, Any] = {
            "status": sync_status,
            "statusLabel": status_labels.get(sync_status, ""),
            "source": source,
            "lastSyncAt": now,
            "beforeCommit": before,
            "afterCommit": after,
            "filesChanged": changed,
            "cachesCleared": cleared,
            "autoWatchlist": auto_watchlist,
            "gitOutput": (out + "\n" + err).strip()[:500],
            "error": err[:200] if sync_status not in {"OK"} else "",
        }
        _save_status(status)
        return status


def get_sync_status() -> dict[str, Any]:
    if _STATUS_FILE.exists():
        try:
            return json.loads(_STATUS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _last_status


def _background_sync_loop(interval_minutes: float) -> None:
    """백그라운드 주기 동기화 스레드."""
    interval_sec = interval_minutes * 60
    # 시작 후 2분 대기 (서버 초기화 완료 후)
    time.sleep(120)
    while True:
        try:
            result = pull_and_refresh(source="background_scheduler")
            print(f"[AutoSync] {result['lastSyncAt']} status={result['status']} changed={result['filesChanged']}")
        except Exception as exc:
            print(f"[AutoSync] error: {exc}")
        time.sleep(interval_sec)


def start_background_sync(interval_minutes: float | None = None) -> None:
    """백그라운드 동기화 스레드 시작 (CI 환경에서는 비활성)."""
    if os.environ.get("GITHUB_ACTIONS_RUN") == "true":
        return  # GitHub Actions 환경에서는 불필요
    if os.environ.get("MONE_AUTO_SYNC_DISABLE") == "1":
        return

    env_interval = os.environ.get("GIT_AUTO_SYNC_INTERVAL_MIN")
    if env_interval:
        try:
            interval_minutes = float(env_interval)
        except ValueError:
            pass

    if interval_minutes is None:
        interval_minutes = 30.0  # 기본 30분

    t = threading.Thread(target=_background_sync_loop, args=(interval_minutes,), daemon=True)
    t.start()
    print(f"[AutoSync] 백그라운드 동기화 시작 (간격: {interval_minutes}분)")


def startup_sync() -> None:
    """서버 시작 시 1회 pull (선택적)."""
    if os.environ.get("MONE_STARTUP_SYNC") != "1":
        return
    if os.environ.get("GITHUB_ACTIONS_RUN") == "true":
        return
    try:
        result = pull_and_refresh(source="startup")
        print(f"[AutoSync] 시작 동기화: {result['status']} / 변경 파일 {result['filesChanged']}개")
    except Exception as exc:
        print(f"[AutoSync] 시작 동기화 실패: {exc}")


def register_auto_sync_routes(app: Any) -> None:
    @app.post("/api/admin/sync")
    def admin_sync(background_tasks: BackgroundTasks) -> dict[str, Any]:
        """즉시 GitHub 동기화 (git pull + 캐시 초기화)."""
        background_tasks.add_task(pull_and_refresh, "api_trigger")
        return {"status": "SYNC_STARTED", "message": "동기화가 시작됐습니다. /api/admin/sync-status로 확인하세요."}

    @app.post("/api/admin/sync-now")
    def admin_sync_now() -> dict[str, Any]:
        """즉시 동기화 후 결과 반환 (동기 실행)."""
        return pull_and_refresh(source="api_sync_now")

    @app.get("/api/admin/sync-status")
    def admin_sync_status() -> dict[str, Any]:
        """마지막 동기화 상태."""
        return get_sync_status()

    @app.post("/api/admin/cache-clear")
    def admin_cache_clear() -> dict[str, Any]:
        """캐시만 초기화 (pull 없이)."""
        cleared = _clear_all_caches()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {"status": "OK", "clearedAt": now, "cachesCleared": cleared}
