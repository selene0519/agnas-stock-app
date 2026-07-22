#!/usr/bin/env python3
"""Anti-truncation guard for committed OHLCV history.

A backfill that deepens data/market/ohlcv/*_daily.csv can be silently clobbered
when a concurrent collector run (or a stale CI checkout) rewrites the same files
with only recent rows and commits them. This guard runs right before the
workflow stages OHLCV files: for every tracked *_daily.csv whose working copy
has FEWER data rows than the committed (HEAD) version, it restores HEAD's deeper
version. History is only ever allowed to grow, never to shrink.

Usage:
  python scripts/guard_ohlcv_no_shrink.py            # guard all markets
  python scripts/guard_ohlcv_no_shrink.py --tolerance 2

Exit code is always 0 (advisory guard, never blocks the pipeline).
"""
from __future__ import annotations

import argparse
import glob
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OHLCV_GLOB = os.path.join(REPO, "data", "market", "ohlcv", "*_daily.csv")


def _data_rows(text: str) -> int:
    # Count non-empty lines minus a header line if present.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and lines[0].lower().startswith(("date", "﻿date")):
        return len(lines) - 1
    return len(lines)


def _head_text(rel_path: str) -> str | None:
    r = subprocess.run(
        ["git", "show", f"HEAD:{rel_path}"],
        cwd=REPO, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return r.stdout if r.returncode == 0 else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tolerance", type=int, default=1,
                    help="allow the working copy to be at most this many rows shorter before restoring")
    args = ap.parse_args()

    restored = []
    checked = 0
    for path in sorted(glob.glob(OHLCV_GLOB)):
        rel = os.path.relpath(path, REPO).replace("\\", "/")
        try:
            with open(path, encoding="utf-8-sig") as fh:
                work_rows = _data_rows(fh.read())
        except Exception:
            continue
        head_text = _head_text(rel)
        if head_text is None:  # new file, nothing committed to protect
            continue
        checked += 1
        head_rows = _data_rows(head_text)
        if work_rows < head_rows - args.tolerance:
            subprocess.run(["git", "checkout", "HEAD", "--", rel], cwd=REPO,
                           capture_output=True, text=True)
            restored.append((rel, work_rows, head_rows))

    if restored:
        print(f"[guard] restored {len(restored)} OHLCV file(s) that would have shrunk:")
        for rel, w, h in restored[:20]:
            print(f"  {rel}: working {w} rows < HEAD {h} rows -> restored HEAD")
        if len(restored) > 20:
            print(f"  ... and {len(restored) - 20} more")
    else:
        print(f"[guard] ok: {checked} OHLCV files checked, none would shrink")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
