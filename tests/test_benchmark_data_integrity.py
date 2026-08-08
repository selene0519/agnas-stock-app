from __future__ import annotations

import importlib.util
import math
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "fetch_benchmark_data_test", ROOT / "scripts" / "fetch_benchmark_data.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _bar(day: str, close: float, source: str = "test") -> dict:
    return {
        "date": day,
        "open": close - 1,
        "high": close + 2,
        "low": close - 2,
        "close": close,
        "volume": 1,
        "source": source,
    }


def test_invalid_nan_and_inconsistent_benchmark_bars_are_rejected() -> None:
    bm = _load_module()
    assert bm._valid_bar(_bar("2026-08-07", 4000)) is True
    assert bm._valid_bar({**_bar("2026-08-07", 4000), "close": math.nan}) is False
    assert bm._valid_bar({**_bar("2026-08-07", 4000), "high": 3000}) is False


def test_recent_merge_preserves_old_history_and_replaces_overlap() -> None:
    bm = _load_module()
    old_day = (datetime(2026, 8, 7) - timedelta(days=30)).strftime("%Y-%m-%d")
    existing = [_bar(old_day, 3000, "existing"), _bar("2026-08-03", 3900, "existing")]
    fetched = [_bar(old_day, 9999, "provider"), _bar("2026-08-03", 4000, "provider"), _bar("2026-08-07", 4100, "provider")]

    merged = bm._merge_recent(existing, fetched)
    by_date = {row["date"]: row for row in merged}

    assert by_date[old_day]["close"] == 3000
    assert by_date["2026-08-03"]["close"] == 4000
    assert by_date["2026-08-07"]["close"] == 4100
