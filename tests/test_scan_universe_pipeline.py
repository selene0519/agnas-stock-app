from __future__ import annotations

import csv
import sys
from pathlib import Path

from scripts import backfill_ohlcv_history as backfill
from scripts import build_universe
from scripts import refresh_kr_close_ohlcv as refresh


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["symbol", "name", "type", "theme", "group"])
        writer.writeheader()
        writer.writerows(rows)


def test_weekly_universe_replaces_stale_automatic_rows_and_keeps_curated(monkeypatch) -> None:
    curated = {"symbol": "005930", "name": "삼성전자", "type": "core", "theme": "AI", "group": "반도체"}
    stale_auto = {"symbol": "111111", "name": "old", "type": "discovery", "theme": "자동선별", "group": "발굴 후보"}
    selected = [
        {"symbol": "005930", "name": "삼성전자", "type": "core"},
        {"symbol": "222222", "name": "new", "type": "discovery"},
    ]

    merged, retired = build_universe.merge_universe([curated, stale_auto], selected, "kr")
    by_symbol = {row["symbol"]: row for row in merged}

    assert set(by_symbol) == {"005930", "222222"}
    assert by_symbol["005930"]["theme"] == "AI"
    assert by_symbol["222222"]["theme"] == "자동선별"
    assert retired == 1

    # The automatic budget is independent of a user's curated holdings/watchlist.
    monkeypatch.setitem(build_universe.MAX_TOTAL, "kr", 1)
    merged, _ = build_universe.merge_universe([curated], selected, "kr")
    assert {row["symbol"] for row in merged} == {"005930", "222222"}


def test_kr_close_and_history_collectors_include_candidate_universe(tmp_path: Path, monkeypatch) -> None:
    _write_csv(tmp_path / "candidate_universe_kr.csv", [
        {"symbol": "222222", "name": "core", "type": "core", "theme": "자동선별", "group": "대형 핵심"},
        {"symbol": "333333", "name": "discovery", "type": "discovery", "theme": "자동선별", "group": "발굴 후보"},
    ])
    _write_csv(tmp_path / "holdings_kr.csv", [
        {"symbol": "111111", "name": "holding", "type": "", "theme": "", "group": ""},
    ])
    for module in (refresh, backfill):
        monkeypatch.setattr(module, "REPO", tmp_path)
        monkeypatch.setattr(module, "STOCKAPP", tmp_path / "data" / "stockapp")
        monkeypatch.setattr(module, "REPORTS", tmp_path / "reports")

    refreshed = refresh._target_universe(limit=10)
    historical = backfill._target_universe()

    assert [row["symbol"] for row in refreshed] == ["111111", "222222", "333333"]
    assert [row["symbol"] for row in historical] == ["111111", "222222", "333333"]


def test_kr_scan_coverage_uses_current_root_universe_before_legacy_copy(tmp_path: Path, monkeypatch) -> None:
    _write_csv(tmp_path / "candidate_universe_kr.csv", [
        {"symbol": "111111", "name": "current", "type": "core", "theme": "자동선별", "group": "대형 핵심"},
    ])
    _write_csv(tmp_path / "data" / "candidate_universe_kr.csv", [
        {"symbol": "999999", "name": "stale", "type": "discovery", "theme": "자동선별", "group": "발굴 후보"},
    ])
    original_sys_path = sys.path.copy()
    previous_app = sys.modules.get("app")
    try:
        from scripts import generate_kr_recommendations as generate_kr

        monkeypatch.setattr(generate_kr, "ROOT", tmp_path)
        coverage = generate_kr._configured_scan_coverage({"111111": [{}]})
    finally:
        sys.path[:] = original_sys_path
        if previous_app is None:
            sys.modules.pop("app", None)
        else:
            sys.modules["app"] = previous_app

    assert coverage["configuredUniverseSymbols"] == 1
    assert coverage["ohlcvEligibleSymbols"] == 1
    assert coverage["coverageRatio"] == 1.0
