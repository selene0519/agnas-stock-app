from __future__ import annotations

import csv
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar


_T = TypeVar("_T")
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()
_HELD = threading.local()


def _thread_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def file_lock(path: Path, *, timeout_seconds: float = 30.0) -> Iterator[None]:
    """Serialize a file-backed mutation across threads and worker processes.

    The lock is deliberately small and dependency-free so scheduled GitHub runs,
    local scripts and web workers all use the same protocol. A lock left by a
    crashed process must be checked and removed by an operator; age alone is not
    evidence that a slow writer has stopped. Ownership tokens prevent one
    process from deleting another process' lock.
    """

    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(lock_path.resolve())
    held: dict[str, int] = getattr(_HELD, "counts", {})
    if held.get(key, 0):
        held[key] += 1
        _HELD.counts = held
        try:
            yield
        finally:
            held[key] -= 1
        return

    token = f"{os.getpid()}:{threading.get_ident()}:{uuid.uuid4().hex}"
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    with _thread_lock(lock_path):
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, token.encode("ascii"))
                    os.fsync(fd)
                finally:
                    os.close(fd)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for data lock: {lock_path}")
                time.sleep(0.05)

        held[key] = 1
        _HELD.counts = held
        try:
            yield
        finally:
            held.pop(key, None)
            try:
                if lock_path.read_text(encoding="ascii") == token:
                    lock_path.unlink(missing_ok=True)
            except FileNotFoundError:
                pass


def serialized_file_mutation(lock_path: Path) -> Callable[[Callable[..., _T]], Callable[..., _T]]:
    def decorate(func: Callable[..., _T]) -> Callable[..., _T]:
        @wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> _T:
            with file_lock(lock_path):
                return func(*args, **kwargs)

        return wrapped

    return decorate


def _atomic_replace(path: Path, write: Callable[[Any], None], *, newline: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline=newline) as handle:
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    def write(handle: Any) -> None:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows([{key: row.get(key, "") for key in fields} for row in rows])

    _atomic_replace(path, write, newline="")


def atomic_write_json(path: Path, payload: Any) -> None:
    def write(handle: Any) -> None:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    _atomic_replace(path, write)
