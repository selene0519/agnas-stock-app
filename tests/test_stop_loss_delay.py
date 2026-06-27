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

from app.engine import mone_v77_holdings_risk as hr  # noqa: E402


def _write_ohlcv(tmp_path: Path, market: str, symbol: str, closes: list[float]) -> None:
    path = tmp_path / "mone-web-app"  # _app_root()가 가리킬 위치 (app.parent == tmp_path)
    path.mkdir(parents=True, exist_ok=True)
    (path / "backend").mkdir(exist_ok=True)
    ohlcv_dir = tmp_path / "data" / "market" / "ohlcv"
    ohlcv_dir.mkdir(parents=True, exist_ok=True)
    rows = [{"date": f"2026-06-{i+1:02d}", "close": str(c)} for i, c in enumerate(closes)]
    with (ohlcv_dir / f"{market}_{symbol}_daily.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "close"])
        writer.writeheader()
        writer.writerows(rows)


def test_no_delay_when_current_above_stop() -> None:
    out = hr._stop_loss_delay_info("kr", "000001", stop=9000, current=10000)
    assert out == {"breached": False, "daysSinceBreach": 0, "delayRisk": "NONE"}


def test_breached_today_with_no_ohlcv_is_watch_not_high(monkeypatch, tmp_path: Path) -> None:
    """OHLCV가 없어도 '지금 손절가 밑'이라는 사실 자체는 숨기지 않는다 — 다만 며칠째인지
    모르니 HIGH(누적된 지연)까지는 못 올리고 WATCH로 그친다."""
    monkeypatch.setattr(hr, "_app_root", lambda: tmp_path / "mone-web-app")
    out = hr._stop_loss_delay_info("kr", "000001", stop=10000, current=9000)
    assert out["breached"] is True
    assert out["delayRisk"] == "WATCH"


def test_breached_three_days_is_high_risk(monkeypatch, tmp_path: Path) -> None:
    # 마지막 날(오늘)부터 거슬러 3일 연속 손절가(10000) 밑, 그 전엔 위였음
    _write_ohlcv(tmp_path, "kr", "000001", closes=[11000, 11200, 9500, 9300, 9100])
    monkeypatch.setattr(hr, "_app_root", lambda: tmp_path / "mone-web-app")
    out = hr._stop_loss_delay_info("kr", "000001", stop=10000, current=9100)
    assert out == {"breached": True, "daysSinceBreach": 3, "delayRisk": "HIGH"}


def test_breached_one_day_is_watch_not_high(monkeypatch, tmp_path: Path) -> None:
    _write_ohlcv(tmp_path, "kr", "000001", closes=[11000, 11200, 10500, 9100])
    monkeypatch.setattr(hr, "_app_root", lambda: tmp_path / "mone-web-app")
    out = hr._stop_loss_delay_info("kr", "000001", stop=10000, current=9100)
    assert out == {"breached": True, "daysSinceBreach": 1, "delayRisk": "WATCH"}


def test_holdings_payload_marks_stop_loss_delay_as_risk_status(monkeypatch, tmp_path: Path) -> None:
    _write_ohlcv(tmp_path, "kr", "000001", closes=[11000, 9500, 9300, 9100])
    monkeypatch.setattr(hr, "_app_root", lambda: tmp_path / "mone-web-app")
    monkeypatch.setattr(hr, "_holding_rows", lambda: [
        {"symbol": "000001", "market": "kr", "quantity": "10", "avgPrice": "11000", "stopPrice": "10000"},
    ])
    monkeypatch.setattr(hr, "_latest_quote_map", lambda market: {"000001": {"price": 9100, "change": "-5%"}} if market == "kr" else {})
    monkeypatch.setattr(hr, "_recommendation_map", lambda market: {})

    payload = hr.holdings_payload("kr")
    item = payload["items"][0]
    assert item["riskStatus"] == "STOP_LOSS_DELAY"
    assert item["stopLossDelayDays"] == 3
    assert payload["summary"]["stopLossDelayCount"] == 1
