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

    result = walkforward.run_all("us")

    assert result["combosRun"] == 9
    assert loads == ["us"]
    assert received == [({"TEST": []}, 0)] * 9
