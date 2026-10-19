from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path
import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.atomic_io import atomic_write_csv, file_lock  # noqa: E402


def test_atomic_csv_replaces_complete_file_and_leaves_no_temporary_file(tmp_path: Path) -> None:
    target = tmp_path / "ledger.csv"
    atomic_write_csv(target, [{"id": "one", "value": 1}], ["id", "value"])
    atomic_write_csv(target, [{"id": "two", "value": 2}], ["id", "value"])

    with target.open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle)) == [{"id": "two", "value": "2"}]
    assert list(tmp_path.glob(".*.tmp")) == []


def test_file_lock_is_reentrant_in_same_thread(tmp_path: Path) -> None:
    lock_path = tmp_path / "ledger.lock"
    with file_lock(lock_path):
        with file_lock(lock_path):
            assert lock_path.exists()
    assert not lock_path.exists()


def test_file_lock_serializes_concurrent_mutations(tmp_path: Path) -> None:
    lock_path = tmp_path / "ledger.lock"
    counter = [0]

    def increment() -> None:
        for _ in range(100):
            with file_lock(lock_path):
                old = counter[0]
                counter[0] = old + 1

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: increment(), range(4)))
    assert counter[0] == 400


def test_existing_lock_fails_closed_instead_of_deleting_it(tmp_path: Path) -> None:
    lock_path = tmp_path / "ledger.lock"
    lock_path.write_text("another-owner", encoding="ascii")
    with pytest.raises(TimeoutError):
        with file_lock(lock_path, timeout_seconds=0.1):
            pass
    assert lock_path.read_text(encoding="ascii") == "another-owner"
