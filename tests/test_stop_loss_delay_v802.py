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

from app.engine import mone_v802_holdings_clean as hc  # noqa: E402


def _write_ohlcv(tmp_path: Path, market: str, symbol: str, closes: list[float]) -> Path:
    ohlcv_dir = tmp_path / "data" / "market" / "ohlcv"
    ohlcv_dir.mkdir(parents=True, exist_ok=True)
    path = ohlcv_dir / f"{market}_{symbol}_daily.csv"
    rows = [{"date": f"2026-06-{i+1:02d}", "close": str(c)} for i, c in enumerate(closes)]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "close"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_no_delay_when_above_stop() -> None:
    out = hc._stop_loss_delay_info("000001", "kr", stop=9000, current=10000)
    assert out == {"breached": False, "daysSinceBreach": 0, "delayRisk": "정상"}


def test_breached_today_with_no_ohlcv_is_watch(monkeypatch) -> None:
    monkeypatch.setattr(hc, "_ohlcv_files_cached", lambda sym, market: ())
    out = hc._stop_loss_delay_info("000001", "kr", stop=10000, current=9000)
    assert out["breached"] is True
    assert out["delayRisk"] == "주의"


def test_breached_three_days_is_stop_loss_delay(monkeypatch, tmp_path: Path) -> None:
    path = _write_ohlcv(tmp_path, "kr", "000001", closes=[11000, 11200, 9500, 9300, 9100])
    monkeypatch.setattr(hc, "_ohlcv_files_cached", lambda sym, market: (path,))
    out = hc._stop_loss_delay_info("000001", "kr", stop=10000, current=9100)
    assert out == {"breached": True, "daysSinceBreach": 3, "delayRisk": "손절지연"}


def test_breached_one_day_is_watch_not_delay(monkeypatch, tmp_path: Path) -> None:
    path = _write_ohlcv(tmp_path, "kr", "000001", closes=[11000, 11200, 10500, 9100])
    monkeypatch.setattr(hc, "_ohlcv_files_cached", lambda sym, market: (path,))
    out = hc._stop_loss_delay_info("000001", "kr", stop=10000, current=9100)
    assert out == {"breached": True, "daysSinceBreach": 1, "delayRisk": "주의"}


def test_holdings_clean_payload_surfaces_stop_loss_delay(monkeypatch, tmp_path: Path) -> None:
    path = _write_ohlcv(tmp_path, "kr", "000001", closes=[11000, 9500, 9300, 9100])
    monkeypatch.setattr(hc, "_ohlcv_files_cached", lambda sym, market: (path,) if sym == "000001" else ())
    monkeypatch.setattr(hc, "_raw_holdings", lambda: [
        {"symbol": "000001", "market": "kr", "quantity": "10", "avgPrice": "11000",
         "stopPrice": "10000", "currentPrice": "9100"},
    ])
    monkeypatch.setattr(hc, "_price_ref", lambda symbol, market: {"current": 0.0, "entry": 0.0, "stop": 0.0, "target": 0.0, "source": ""})
    monkeypatch.setattr(hc, "_ohlcv_ref", lambda symbol, market: {"latest": 9100.0, "prev": 9300.0, "source": "test", "date": "2026-06-04"})

    payload = hc.holdings_clean_payload("kr")
    item = payload["items"][0]
    assert item["riskStatus"] == "손절지연"
    assert item["stopLossDelayDays"] == 3
    assert item["stopLossBreached"] is True
