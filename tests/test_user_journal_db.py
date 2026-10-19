from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import db  # noqa: E402


def test_user_journal_is_persistent_and_isolated(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(db, "_sqlite_conn", None)
    monkeypatch.setattr(db, "_sqlite_db_path", lambda: tmp_path / "users.db")

    alice = db.add_journal("alice", {"market": "kr", "symbol": "005930", "memo": "first", "price": 70000})
    bob = db.add_journal("bob", {"market": "us", "symbol": "AAPL", "memo": "private", "returnPct": 1.2})

    assert [row["id"] for row in db.get_journal("alice")] == [alice["id"]]
    assert [row["id"] for row in db.get_journal("bob")] == [bob["id"]]
    assert db.get_journal("alice")[0]["price"] == 70000.0

    updated = db.update_journal("alice", alice["id"], {"review": "reviewed", "returnPct": 2.5})
    assert updated and updated["review"] == "reviewed"
    assert updated["returnPct"] == 2.5
    assert db.update_journal("bob", alice["id"], {"review": "intrusion"}) is None
    assert db.delete_journal("bob", alice["id"]) is False
    assert db.delete_journal("alice", alice["id"]) is True
    assert db.get_journal("alice") == []

    db._sqlite_conn.close()
    db._sqlite_conn = None
