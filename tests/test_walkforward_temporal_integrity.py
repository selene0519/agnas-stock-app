import csv
import sys
from datetime import date
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.engine import walkforward_backtest as walkforward


def test_exclude_future_ohlcv_removes_future_and_invalid_rows() -> None:
    as_of = date(2026, 7, 26)
    historic = [{"date": f"2026-06-{day:02d}"} for day in range(1, 31)]
    rows = historic + [{"date": "2026-07-27"}, {"date": "not-a-date"}]

    usable, excluded = walkforward._exclude_future_ohlcv({"TEST": rows}, as_of=as_of)

    assert excluded == 2
    assert [row["date"] for row in usable["TEST"]] == [row["date"] for row in historic]


def test_exclude_future_ohlcv_normalizes_compact_dates() -> None:
    rows = [{"date": f"202605{day:02d}"} for day in range(1, 31)]

    usable, excluded = walkforward._exclude_future_ohlcv({"TEST": rows}, as_of=date(2026, 7, 30))

    assert excluded == 0
    assert usable["TEST"][0]["date"] == "2026-05-01"
    assert usable["TEST"][-1]["date"] == "2026-05-30"


def test_persisted_results_with_future_window_are_invalid(monkeypatch, tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    with (reports / "walkforward_results_us.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["window"])
        writer.writeheader()
        writer.writerows([{"window": "2026-07-26"}, {"window": "2026-07-29"}])
    monkeypatch.setattr(walkforward, "_reports_dir", lambda: reports)

    integrity = walkforward.inspect_persisted_results("us", as_of=date(2026, 7, 28))

    assert integrity["status"] == "INVALID_TEMPORAL_DATA"
    assert integrity["futureWindowCount"] == 1


def test_run_all_prepares_ohlcv_once(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(walkforward, "_reports_dir", lambda: tmp_path)
    loads = []
    received = []
    monkeypatch.setattr(walkforward, "_load_ohlcv_all", lambda market: loads.append(market) or {"TEST": []})
    monkeypatch.setattr(walkforward, "_exclude_future_ohlcv", lambda rows, as_of: (rows, 0))

    def fake_run(*args, **kwargs):
        received.append(kwargs.get("prepared_ohlcv"))
        return {"status": "DATA_INSUFFICIENT", "windows": [], "diff": {}}

    monkeypatch.setattr(walkforward, "run_walkforward", fake_run)

    result = walkforward.run_all("us", window_months=3)

    assert result["combosRun"] == 9
    assert result["results"]
    assert loads == ["us"]
    assert received == [({"TEST": []}, 0)] * 9


def test_learning_pool_purges_unresolved_and_same_day_outcomes() -> None:
    rows = [
        {"symbol": "A", "exitDate": "2026-06-29"},
        {"symbol": "B", "exitDate": "2026-07-01"},
        {"symbol": "C", "exitDate": "2026-07-02"},
        {"symbol": "D", "exitDate": None},
    ]

    usable = walkforward._resolved_before_window(rows, "2026-07-01")

    assert [row["symbol"] for row in usable] == ["A"]


def test_us_price_band_and_correction_preserve_positive_price_order() -> None:
    entry, stop, target = walkforward._price_band(
        60.0, 0.30, "balanced", "short", market="us"
    )
    corrected = walkforward._apply_wf_correction(
        {"priceAdjustments": {"entryAggressiveness": -0.5, "stopAtrMultiplier": -0.3, "targetMultiplier": 0.0}},
        entry,
        stop,
        target,
        market="us",
    )

    corrected_entry, corrected_stop, corrected_target, applied = corrected
    assert applied is True
    assert 0 < stop < entry < target
    assert 0 < corrected_stop < corrected_entry < corrected_target
    assert corrected_entry != round(corrected_entry, 0)
    assert (corrected_entry - corrected_stop) / corrected_entry < 0.20


def test_run_all_does_not_persist_duplicate_trade_records(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(walkforward, "_reports_dir", lambda: tmp_path)
    monkeypatch.setattr(walkforward, "_load_ohlcv_all", lambda market: {"TEST": []})
    monkeypatch.setattr(walkforward, "_exclude_future_ohlcv", lambda rows, as_of: (rows, 0))
    monkeypatch.setattr(walkforward, "run_walkforward", lambda *args, **kwargs: {
        "status": "OK",
        "windows": [],
        "diff": {},
        "tradeRecords": [{"symbol": "SHOULD_NOT_BE_PERSISTED"}],
    })

    walkforward.run_all("us", window_months=3)

    import json
    summary = json.loads((tmp_path / "walkforward_summary_us.json").read_text(encoding="utf-8"))
    assert all("tradeRecords" not in result for result in summary["combos"].values())
