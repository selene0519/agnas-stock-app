"""추천 예측 캡처 가드 회귀 테스트.

캡처는 자가보정 루프의 입력이라 "안 도는 것"만큼이나 "잘못된 날 도는 것"이
위험하다. 주말/노후 데이터에 캡처하면 직전 거래일 가격이 새 예측으로 다시
찍혀 표본이 중복되고, 그 오염은 정산 후에 되돌릴 수 없다.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "capture_recommendation_predictions",
        ROOT / "scripts" / "capture_recommendation_predictions.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_weekend_capture_is_refused(monkeypatch) -> None:
    cap = _load_module()
    monkeypatch.setattr(cap, "_newest_ohlcv_date", lambda: "2026-07-24")
    allowed, reason = cap._capture_precondition(datetime(2026, 7, 26))  # Sunday
    assert allowed is False
    assert "WEEKEND" in reason


def test_stale_ohlcv_capture_is_refused(monkeypatch) -> None:
    cap = _load_module()
    monkeypatch.setattr(cap, "_newest_ohlcv_date", lambda: "2026-07-10")
    allowed, reason = cap._capture_precondition(datetime(2026, 7, 23))  # Thursday
    assert allowed is False
    assert "STALE_OHLCV" in reason


def test_missing_ohlcv_capture_is_refused(monkeypatch) -> None:
    cap = _load_module()
    monkeypatch.setattr(cap, "_newest_ohlcv_date", lambda: None)
    allowed, reason = cap._capture_precondition(datetime(2026, 7, 23))
    assert allowed is False
    assert "NO_OHLCV" in reason


def test_fresh_trading_day_capture_is_allowed(monkeypatch) -> None:
    cap = _load_module()
    monkeypatch.setattr(cap, "_newest_ohlcv_date", lambda: "2026-07-23")
    allowed, reason = cap._capture_precondition(datetime(2026, 7, 23))  # Thursday
    assert allowed is True
    assert reason.startswith("OK")


def test_monday_tolerates_friday_close(monkeypatch) -> None:
    """월요일 장전에는 금요일 봉이 최신이다 — 이걸 STALE로 막으면 안 된다."""
    cap = _load_module()
    monkeypatch.setattr(cap, "_newest_ohlcv_date", lambda: "2026-07-24")  # Friday
    allowed, _ = cap._capture_precondition(datetime(2026, 7, 27))  # Monday
    assert allowed is True


def test_skipped_run_writes_status_and_captures_nothing(monkeypatch, tmp_path) -> None:
    cap = _load_module()
    status = tmp_path / "status.json"
    monkeypatch.setattr(cap, "STATUS_JSON", status)
    monkeypatch.setattr(cap, "LEDGER", tmp_path / "ledger.csv")
    monkeypatch.setattr(cap, "_capture_precondition", lambda _now: (False, "WEEKEND (Sunday)"))

    # 백엔드를 import 하기 전에 빠져나가야 한다(가드가 실제로 차단하는지 확인).
    monkeypatch.setitem(sys.modules, "app.engine.mone_v65_api_stabilizer", None)

    result = cap.run(("kr",))
    assert result["status"] == "SKIPPED"
    assert result["rowsAdded"] == 0
    assert status.exists()
