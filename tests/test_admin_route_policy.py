from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.admin_route_policy import requires_admin_auth


def test_read_only_quant_shadow_status_remains_readable() -> None:
    assert requires_admin_auth("GET", "/api/quant/shadow-status") is False


def test_all_self_learning_mutations_require_admin_auth() -> None:
    protected = (
        "/api/journal/self-learning/performance-gate",
        "/api/journal/self-learning/auto-calibrate",
        "/api/journal/self-learning/rollback",
        "/api/journal/calibration-suggestions/abc/approve",
    )
    assert all(requires_admin_auth("POST", path) for path in protected)


def test_capture_evaluation_review_and_replay_require_admin_auth() -> None:
    protected = (
        "/api/journal/virtual-trades/capture",
        "/api/journal/virtual-trades/evaluate",
        "/api/journal/virtual-trades/abc/review",
        "/api/journal/historical-replay",
        "/api/journal/historical-replay/backfill",
    )
    assert all(requires_admin_auth("POST", path) for path in protected)


def test_read_only_journal_status_is_not_accidentally_blocked() -> None:
    assert requires_admin_auth("GET", "/api/journal/self-learning/status") is False
    assert requires_admin_auth("GET", "/api/journal/virtual-trades") is False


def test_all_paper_ledger_mutations_require_admin_auth() -> None:
    protected = (
        ("POST", "/api/paper/buy"),
        ("POST", "/api/paper/sell"),
        ("DELETE", "/api/paper/reset"),
        ("PATCH", "/api/paper/stops/kr/005930"),
        ("POST", "/api/paper/ai/run"),
    )
    assert all(requires_admin_auth(method, path) for method, path in protected)
    assert requires_admin_auth("GET", "/api/paper/ai/status") is False
