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
