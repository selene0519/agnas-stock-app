#!/usr/bin/env python3
"""Migrate oversized virtual-operation CSV ledgers to deterministic gzip files."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGERS = (
    REPO_ROOT / "data/history/virtual_operation_history.csv",
    REPO_ROOT / "data/history/virtual_operation_evaluation.csv",
)


def _sha256(path: Path, *, compressed: bool = False) -> str:
    digest = hashlib.sha256()
    opener = gzip.open if compressed else Path.open
    mode = "rb"
    with opener(path, mode) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def migrate(source: Path, *, remove_source: bool) -> str:
    target = source.with_suffix(source.suffix + ".gz")
    if not source.exists():
        if target.exists():
            with gzip.open(target, "rb") as handle:
                handle.read(1)
            return f"already migrated: {(target.relative_to(REPO_ROOT) if target.is_relative_to(REPO_ROOT) else target)}"
        return f"no ledger yet: {source.relative_to(REPO_ROOT)}"

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        with source.open("rb") as src, temporary.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=6, mtime=0) as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)

        source_hash = _sha256(source)
        compressed_hash = _sha256(temporary, compressed=True)
        if source_hash != compressed_hash:
            raise RuntimeError(f"compression verification failed for {source}")

        temporary.replace(target)
        if remove_source:
            source.unlink()

        suffix = " and removed source" if remove_source else ""
        return f"migrated: {(target.relative_to(REPO_ROOT) if target.is_relative_to(REPO_ROOT) else target)}{suffix} (sha256={source_hash[:12]})"
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--remove-source", action="store_true")
    args = parser.parse_args()
    for ledger in LEDGERS:
        print(migrate(ledger, remove_source=args.remove_source))

    backend_dir = REPO_ROOT / "mone-web-app" / "backend"
    import sys
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))
    from app.services.operation_history_storage import rebuild_sidecar

    history_source = REPO_ROOT / "data/history/virtual_operation_history.csv.gz"
    evaluation_source = REPO_ROOT / "data/history/virtual_operation_evaluation.csv.gz"
    if history_source.exists():
        metadata = rebuild_sidecar(
            history_source,
            REPO_ROOT / "data/history/virtual_operation_history_recent.csv",
            REPO_ROOT / "data/history/virtual_operation_history_index.json",
        )
        print(f"history sidecar: {metadata['recentRows']} recent / {metadata['totalRows']} total")
    if evaluation_source.exists():
        metadata = rebuild_sidecar(
            evaluation_source,
            REPO_ROOT / "data/history/virtual_operation_evaluation_recent.csv",
            REPO_ROOT / "data/history/virtual_operation_evaluation_index.json",
        )
        print(f"evaluation sidecar: {metadata['recentRows']} recent / {metadata['totalRows']} total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
