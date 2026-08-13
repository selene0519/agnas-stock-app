from __future__ import annotations

import csv
import gzip
import heapq
import json
from pathlib import Path
from typing import Any, Iterable

DEFAULT_ROWS_PER_CELL = 1000
DATE_FIELDS = ("created_at", "evaluated_at", "snapshot_at", "date", "prediction_at")


def _iter_rows(path: Path) -> Iterable[dict[str, str]]:
    if not path.exists() or path.stat().st_size <= 0:
        return
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            opener = gzip.open if path.suffix == ".gz" else Path.open
            open_args = (path, "rt") if path.suffix == ".gz" else (path, "r")
            with opener(*open_args, encoding=encoding, newline="") as handle:
                for raw in csv.DictReader(handle):
                    yield {
                        str(key): ("" if value is None else str(value))
                        for key, value in raw.items()
                        if key is not None
                    }
            return
        except UnicodeDecodeError:
            continue


def _select_recent(
    rows: Iterable[dict[str, Any]],
    rows_per_cell: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    heaps: dict[tuple[str, str], list[tuple[str, int, dict[str, Any]]]] = {}
    market_counts: dict[str, int] = {}
    mode_counts: dict[str, int] = {}
    cell_counts: dict[str, int] = {}
    total = 0

    for index, raw in enumerate(rows):
        row = dict(raw)
        total += 1
        market = str(row.get("market", "")).strip().lower()
        mode = str(row.get("mode", "")).strip().lower()
        if market:
            market_counts[market] = market_counts.get(market, 0) + 1
        if mode:
            mode_counts[mode] = mode_counts.get(mode, 0) + 1
        cell_name = f"{market}|{mode}"
        cell_counts[cell_name] = cell_counts.get(cell_name, 0) + 1

        sort_key = next((str(row.get(field, "")) for field in DATE_FIELDS if row.get(field)), "")
        cell = (market, mode)
        heap = heaps.setdefault(cell, [])
        item = (sort_key, index, row)
        if len(heap) < rows_per_cell:
            heapq.heappush(heap, item)
        elif item[:2] > heap[0][:2]:
            heapq.heapreplace(heap, item)

    selected = [item for heap in heaps.values() for item in heap]
    selected.sort(key=lambda item: item[:2], reverse=True)
    recent = [item[2] for item in selected]
    metadata = {
        "version": 1,
        "totalRows": total,
        "recentRows": len(recent),
        "rowsPerMarketMode": rows_per_cell,
        "counts": {
            "all": total,
            "market": market_counts,
            "mode": mode_counts,
            "marketMode": cell_counts,
        },
    }
    return recent, metadata


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_sidecar_from_rows(
    source_path: Path,
    rows: Iterable[dict[str, Any]],
    recent_path: Path,
    index_path: Path | None = None,
    *,
    rows_per_cell: int = DEFAULT_ROWS_PER_CELL,
) -> dict[str, Any]:
    recent, metadata = _select_recent(rows, rows_per_cell)
    metadata["sourceFile"] = source_path.as_posix()
    _write_csv(recent_path, recent)
    if index_path is not None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def rebuild_sidecar(
    source_path: Path,
    recent_path: Path,
    index_path: Path | None = None,
    *,
    rows_per_cell: int = DEFAULT_ROWS_PER_CELL,
) -> dict[str, Any]:
    return write_sidecar_from_rows(
        source_path,
        _iter_rows(source_path),
        recent_path,
        index_path,
        rows_per_cell=rows_per_cell,
    )
