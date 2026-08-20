from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "local_data_collector_safety", ROOT / "scripts" / "local_data_collector.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sp500_internal_alias_uses_valid_yfinance_ticker() -> None:
    mod = _load()
    assert mod.YFINANCE_SYMBOL_ALIASES["SP500"] == "^GSPC"


def test_us_collector_downloads_sp500_via_gspc(tmp_path, monkeypatch) -> None:
    mod = _load()
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    calls = []

    def download(symbol, **kwargs):
        calls.append((symbol, kwargs))
        return pd.DataFrame(
            {
                "Open": [1.0],
                "High": [2.0],
                "Low": [0.5],
                "Close": [1.5],
                "Volume": [100],
            },
            index=pd.to_datetime(["2026-08-19"]),
        ).rename_axis("Date")

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=download))

    result = mod.collect_ohlcv_us(["SP500"], days=5)

    assert result == {"ok": 1, "fail": 0}
    assert calls[0][0] == "^GSPC"
    assert (tmp_path / "data" / "market" / "ohlcv" / "us_SP500_daily.csv").exists()

def test_corrupt_legacy_csv_recovers_valid_rows(tmp_path) -> None:
    mod = _load()
    path = tmp_path / "us_TEST_daily.csv"
    path.write_text(
        "date,market,symbol,name,open,high,low,close,volume,source\n"
        "2026-08-17,us,TEST,,1,2,0.5,1.5,100,yahoo\n"
        "2026-08-18,us,TEST,,1,2,0.5,1.5,100,yahoo,joined-row\n"
        "2026-08-19,us,TEST,,2,3,1.5,2.5,200,yahoo\n",
        encoding="utf-8-sig",
    )

    recovered = mod._read_existing_ohlcv(path)

    assert recovered["date"].tolist() == ["2026-08-17", "2026-08-19"]


def test_atomic_write_replaces_complete_csv_without_temp_files(tmp_path) -> None:
    mod = _load()
    path = tmp_path / "us_TEST_daily.csv"
    path.write_text("old\n", encoding="utf-8")
    frame = pd.DataFrame(
        [{"date": "2026-08-20", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}]
    )

    mod._atomic_write_ohlcv(frame, path)

    loaded = pd.read_csv(path, encoding="utf-8-sig")
    assert loaded.to_dict("records") == frame.to_dict("records")
    assert not list(tmp_path.glob(".*.tmp-*"))


def test_collector_lock_blocks_overlap_and_recovers_stale_lock(tmp_path, monkeypatch) -> None:
    mod = _load()
    lock = tmp_path / ".collector.lock"
    monkeypatch.setattr(mod, "COLLECTOR_LOCK_PATH", lock)
    monkeypatch.setattr(mod, "COLLECTOR_LOCK_STALE_SECONDS", 60)

    assert mod._acquire_collector_lock() is True
    mod._collector_lock_owned = False  # simulate a second process in this module instance
    assert mod._acquire_collector_lock() is False

    old = 0
    os.utime(lock, (old, old))
    assert mod._acquire_collector_lock() is True
    mod._release_collector_lock()
    assert not lock.exists()