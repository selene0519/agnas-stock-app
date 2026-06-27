from __future__ import annotations

import csv
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
loaded_app = sys.modules.get("app")
if loaded_app is not None and not hasattr(loaded_app, "__path__"):
    sys.modules.pop("app", None)

from app.engine import mone_v65_api_stabilizer as stabilizer  # noqa: E402


def _base_item(**overrides: object) -> dict:
    item = {
        "market": "us",
        "symbol": "MPWR",
        "name": "Monolithic Power Systems, Inc.",
        "mode": "conservative",
        "horizon": "mid",
        "entry": 100.0,
        "stop": 90.0,
        "target": 120.0,
        "expectedPrice": 110.0,
        "probability": 80.0,
    }
    item.update(overrides)
    return item


def test_record_virtual_ledger_round_trips_name_with_embedded_comma(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(stabilizer, "_repo_root", lambda: tmp_path)

    stabilizer._record_virtual_ledger([_base_item()], source="api/final/recommendations")

    ledger_path = stabilizer._ledger_path()
    with ledger_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["name"] == "Monolithic Power Systems, Inc."
    assert rows[0]["symbol"] == "MPWR"
    assert rows[0]["market"] == "us"
    assert rows[0]["source"] == "api/final/recommendations"


def test_record_virtual_ledger_round_trips_name_with_embedded_newline(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(stabilizer, "_repo_root", lambda: tmp_path)

    stabilizer._record_virtual_ledger(
        [_base_item(symbol="RKLB", name="Rocket\nLab")],
        source="api/final/recommendations",
    )

    ledger_path = stabilizer._ledger_path()
    with ledger_path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["name"] == "Rocket\nLab"
    assert rows[0]["symbol"] == "RKLB"


def test_write_csv_rows_does_not_leave_temp_files_behind(tmp_path: Path) -> None:
    target = tmp_path / "ledger.csv"
    stabilizer._write_csv_rows(target, ["a", "b"], [{"a": "1", "b": "2"}])

    assert target.exists()
    leftover = [p for p in tmp_path.iterdir() if p != target]
    assert leftover == []

    with target.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows == [{"a": "1", "b": "2"}]
