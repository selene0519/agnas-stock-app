from __future__ import annotations

import sys
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import db, main  # noqa: E402


def test_journal_api_requires_login_and_isolates_signed_users(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MONE_AUTH_SECRET", "test-only-signing-secret")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("MONE_JOURNAL_REQUIRE_DATABASE", raising=False)
    monkeypatch.setattr(db, "_sqlite_conn", None)
    monkeypatch.setattr(db, "_sqlite_db_path", lambda: tmp_path / "users.db")
    alice_token, _, alice_uid = main._create_user_token("google", "a" * 80 + "alice")
    bob_token, _, bob_uid = main._create_user_token("google", "a" * 80 + "bob")
    alice_auth = f"Bearer {alice_token}"
    bob_auth = f"Bearer {bob_token}"
    assert main.api_journal_get("all", 200, "", "").status_code == 401
    created = main.api_journal_add({"memo": "private", "returnPct": 1.5}, alice_uid, alice_auth)
    entry = created["entry"]
    assert main.api_journal_get("all", 200, alice_uid, alice_auth)["items"][0]["id"] == entry["id"]
    assert main.api_journal_get("all", 200, bob_uid, bob_auth)["items"] == []
    assert main.api_journal_delete(entry["id"], bob_uid, bob_auth)["status"] == "NOT_FOUND"
    assert main.api_journal_update(entry["id"], {"review": "done"}, alice_uid, alice_auth)["item"]["review"] == "done"
    assert main.api_journal_get("all", 200, bob_uid, alice_auth).status_code == 401

    db._sqlite_conn.close()
    db._sqlite_conn = None


def test_production_journal_fails_closed_without_database(monkeypatch) -> None:
    monkeypatch.setenv("MONE_JOURNAL_REQUIRE_DATABASE", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert main._journal_storage_unavailable() is True


def test_no_default_user_signing_key(monkeypatch) -> None:
    monkeypatch.delenv("MONE_AUTH_SECRET", raising=False)
    monkeypatch.delenv("MONE_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("MONE_ADMIN_PASSWORD_SHA256", raising=False)
    assert main._verify_user_token("anything") is None
    assert main._verify_auth_state("anything", "google") is False


def test_automation_secret_cannot_authorize_paper_orders(monkeypatch) -> None:
    monkeypatch.setenv("MONE_AUTOMATION_TOKEN", "test-machine-secret")

    async def call(path: str, secret: str = ""):
        headers = [(b"x-admin-secret", secret.encode())] if secret else []
        request = Request({"type": "http", "method": "POST", "path": path, "headers": headers})

        async def next_handler(_request):
            return JSONResponse({"status": "OK"})

        return await main.admin_auth_middleware(request, next_handler)

    def run_without_event_loop(coro):
        try:
            coro.send(None)
        except StopIteration as result:
            return result.value
        raise AssertionError("unexpected suspension")

    assert run_without_event_loop(call("/api/journal/auto-capture/run")).status_code == 401
    assert run_without_event_loop(call("/api/journal/auto-capture/run", "test-machine-secret")).status_code == 200
    assert run_without_event_loop(call("/api/paper/ai/run", "test-machine-secret")).status_code in {401, 503}


def test_only_authenticated_journal_routes_are_registered() -> None:
    for (path, method), expected in main._JOURNAL_USER_ROUTES.items():
        routes = [r for r in main.app.router.routes if getattr(r, "path", "") == path and method in (getattr(r, "methods", None) or set())]
        assert [r.endpoint for r in routes] == [expected]
