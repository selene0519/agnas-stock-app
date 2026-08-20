from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import main  # noqa: E402
from app.services import virtual_trade_journal as vtj  # noqa: E402


def test_self_learning_summary_uses_persisted_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        vtj,
        "_persisted_self_learning_status",
        lambda market: {
            "status": "OK",
            "source": "PERSISTED_RUN",
            "generatedAt": "2026-08-20T17:14:24",
            "policyFingerprint": "fingerprint",
            "quality": {"score": 73, "grade": "B"},
            "eligibleAutoCount": 0,
            "lowSampleCount": 4,
            "appliedCount": 0,
            "lastSelfLearningRun": {"generatedAt": "2026-08-20T17:14:24", "market": market},
            "performanceGate": {"status": "DEFERRED"},
        },
    )
    monkeypatch.setattr(
        vtj,
        "calibration_suggestions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("summary must not recalculate suggestions")),
    )

    payload = vtj.self_learning_summary("all")

    assert payload["status"] == "OK"
    assert payload["summaryOnly"] is True
    assert payload["quality"]["score"] == 73
    assert payload["lastSelfLearningRun"]["market"] == "all"


def test_auto_capture_summary_omits_large_evaluation_items(monkeypatch) -> None:
    monkeypatch.setattr(
        vtj,
        "auto_capture_status",
        lambda: {
            "status": "OK",
            "enabled": True,
            "source": "background_scheduler",
            "lastRunAt": "2026-08-20T20:42:17+09:00",
            "timezone": "Asia/Seoul",
            "journalSession": "AFTER_CLOSE_TRADE",
            "evaluation": {
                "status": "OK",
                "evaluated": 38,
                "outcomes": {"PENDING": 38},
                "items": [{"large": "x" * 100_000}],
            },
            "completedKeys": ["one", "two"],
            "runs": [{"market": "kr", "status": "NO_CANDIDATES", "selected": 0, "added": 0, "items": [{"large": "x" * 100_000}]}],
        },
    )

    payload = main.api_journal_auto_capture_status(summary_only=True)

    assert payload["status"] == "OK"
    assert payload["summaryOnly"] is True
    assert payload["completedKeyCount"] == 2
    assert "items" not in payload["evaluation"]
    assert "items" not in payload["runs"][0]
